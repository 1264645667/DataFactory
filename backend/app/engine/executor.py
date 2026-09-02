"""单 Case 造数执行核心（同步实现，Celery Worker 内调用，禁止 asyncio）

职责
- 解析 df_exec_task + case_snapshot，参数校验，拓扑排序确定插入顺序
- 初始化 Redis 自增计数器（df:incr:{task_id}:{table}:{column}）
- calc_batch_size 动态批次+ ThreadPoolExecutor 多线程并发
- 原生 SQL VALUES 批量拼接插入，批次失败原地重试 3 次（指数退避 1s/2s/4s）
- 失败率超过阈值（默认 50%）任务失败停止；否则部分成功
- ITERATE_LIST 遍历驱动模式逐轮执行，单轮失败继续下轮
- Redis 实时进度：progress 24h TTL、rate 10s TTL
- 断点续传 retry_failed_batches：仅重跑 status=失败 的批次

并发模型说明：
- 工作线程只做「数据生成 + 目标库 INSERT」（Engine 与 Redis 客户端均线程安全）
- 批次日志写库 / Redis 进度更新统一由主线程在 future 完成后处理，
  避免 SQLAlchemy Session 跨线程使用与分表进度 JSON 读-改-写竞争
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text

from app.config import settings
from app.core.redis_client import sync_redis_client
from app.db.session import SyncSessionLocal
from app.engine.data_generator import generate_rows
from app.engine.db_pool import get_sync_engine
from app.engine.dep_analyzer import build_insert_order
from app.engine.strategies.number_strategies import init_incr_counter
from app.engine.strategies.registry import get_strategy
from app.models import Case, ExecBatchLog, ExecTask

logger = structlog.get_logger(__name__)

# ---------------- 状态枚举 ----------------
# df_exec_task.status
TASK_STATUS_PENDING = 0      # 待执行
TASK_STATUS_RUNNING = 1      # 执行中
TASK_STATUS_SUCCESS = 2      # 成功
TASK_STATUS_FAILED = 3       # 失败
TASK_STATUS_RETRYING = 4     # 重试中
TASK_STATUS_PARTIAL = 5      # 部分成功
TASK_STATUS_ABORTED = 6      # 已中止

# df_exec_batch_log.status
BATCH_STATUS_SUCCESS = 1
BATCH_STATUS_FAILED = 2

# Redis 进度状态字符串
REDIS_STATUS_MAP = {
    TASK_STATUS_SUCCESS: "success",
    TASK_STATUS_FAILED: "failed",
    TASK_STATUS_PARTIAL: "partial_success",
    TASK_STATUS_ABORTED: "aborted",
}

# ---------------- Redis Key 模板 ----------------
PROGRESS_KEY = "df:task:progress:{task_no}"
TABLE_PROGRESS_KEY = "df:task:table_progress:{task_no}"
RATE_KEY = "df:task:rate:{task_no}:{table}"
PROGRESS_TTL = 24 * 3600        # 进度 Key 24h
RATE_TTL = 10                   # 速率滑动窗口 10s
INCR_COUNTER_TTL = 24 * 3600    # 自增计数器任务结束后保留 24h 自动过期（支撑断点重试取值连续）

# 表名/字段名合法字符（防 SQL 注入，元数据标识符无法参数化，只能白名单校验）
_IDENT_RE = re.compile(r"^[A-Za-z0-9_$]+$")


def _safe_ident(name: str) -> str:
    """标识符白名单校验（表名/字段名）"""
    if not _IDENT_RE.match(name or ""):
        raise ValueError(f"非法表名或字段名: {name!r}")
    return name


def _decode(value: Any) -> Any:
    """Redis 返回值兼容 bytes/str"""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def calc_batch_size(target_count: int) -> int:
    """动态批次大小；settings.BATCH_SIZE_OVERRIDE 可强制覆盖"""
    override = getattr(settings, "BATCH_SIZE_OVERRIDE", None)
    if override:
        return int(override)
    if target_count <= 10_000:
        return 500
    if target_count <= 100_000:
        return 1_000
    if target_count <= 1_000_000:
        return 3_000
    return 5_000


def detect_iterate_driver(config: dict) -> dict | None:
    """识别 Case 中是否存在 ITERATE_LIST 驱动字段

    全 Case 最多允许一个 ITERATE_LIST 字段。
    """
    driver: dict | None = None
    for field_config in config.get("field_configs") or []:
        if (field_config.get("strategy") or "").upper() != "ITERATE_LIST":
            continue
        if driver is not None:
            raise ValueError("一个 Case 只允许一个字段使用按序遍历插入策略")
        params = field_config.get("strategy_params") or {}
        values = params.get("values")
        if isinstance(values, str):
            values = [line.strip() for line in values.splitlines() if line.strip()]
        values = list(values or [])
        if not values:
            raise ValueError("列表不能为空")
        rows_per_value = params.get("rows_per_value")
        if not isinstance(rows_per_value, int) or isinstance(rows_per_value, bool) or rows_per_value < 1:
            raise ValueError("每值条数必须 ≥ 1")
        driver = {
            "table": config["main_table"],
            "column": field_config["column_name"],
            "drive_values": values,
            "rows_per_value": rows_per_value,
        }
    return driver


class _CaseContext:
    """解析后的任务执行上下文"""

    def __init__(self, task: ExecTask, config: dict, engine) -> None:
        self.task = task
        self.task_id = task.id
        self.task_no = task.task_no
        self.config = config
        self.main_table = config["main_table"]
        self.associations: list[dict] = config.get("associations") or []
        self.engine = engine
        # 每张表的字段配置 {table_name: [field_config, ...]}
        self.table_field_configs: dict[str, list[dict]] = {}
        # 拓扑排序后的插入顺序
        self.insert_order: list[str] = []
        # ITERATE_LIST 驱动信息（普通模式为 None）
        self.iterate_driver: dict | None = None
        # 执行参数（settings 提供，含默认值兜底）
        self.max_workers = int(getattr(settings, "MAX_WORKERS", 8) or 8)
        self.max_retry = int(getattr(settings, "BATCH_MAX_RETRY", 3) or 3)
        self.fail_rate_threshold = float(getattr(settings, "FAIL_RATE_THRESHOLD", 0.5) or 0.5)
        self.batch_size = calc_batch_size(int(task.target_count or 0))
        self.start_monotonic = time.time()


def _new_stats() -> dict:
    """批次统计累加器"""
    return {"success_rows": 0, "fail_rows": 0, "errors": [], "stopped": False}


# 配置解析与校验

def _validate_config(config: dict) -> None:
    """快照配置基础校验"""
    if not isinstance(config, dict):
        raise ValueError("Case 配置快照格式非法")
    if not config.get("main_table"):
        raise ValueError("Case 配置缺少主表(main_table)")
    field_configs = config.get("field_configs")
    if not isinstance(field_configs, list) or not field_configs:
        raise ValueError("Case 配置缺少字段配置(field_configs)")
    for field_config in field_configs:
        if not field_config.get("column_name"):
            raise ValueError("字段配置缺少字段名(column_name)")
    associations = config.get("associations") or []
    if not isinstance(associations, list):
        raise ValueError("关联配置(associations)格式非法")
    for assoc in associations:
        if not assoc.get("target_table") or not assoc.get("target_column") or not assoc.get("source_column"):
            raise ValueError("关联配置缺少必要字段(source_column/target_table/target_column)")


def _infer_strategy(col) -> tuple[str, dict]:
    """关联表字段策略自动推断"""
    extra = (col.extra or "").lower()
    name = (col.column_name or "").lower()
    data_type = (col.data_type or "").lower()

    if "auto_increment" in extra:
        return "SKIP", {}
    if col.is_primary_key and data_type in ("bigint", "int"):
        return "SNOWFLAKE", {}
    if col.is_primary_key and data_type in ("varchar", "char"):
        return "UUID", {}
    if col.is_unique and data_type in ("int", "bigint"):
        return "INCR_FROM", {"start": 1}
    if col.is_unique and data_type in ("varchar", "char"):
        return "UUID", {}
    if name in ("created_at", "create_time", "created_time", "updated_at", "update_time", "updated_time"):
        return "NOW", {}
    if name in ("deleted_at", "delete_time"):
        return "CUSTOM_VALUE", {"value": None}
    if name in ("is_deleted", "is_del", "del_flag"):
        return "CUSTOM_VALUE", {"value": 0}
    if col.column_default is not None:
        default_value = str(col.column_default)
        # 表达式默认值（如 CURRENT_TIMESTAMP / (uuid())）不做字面量注入
        if "(" in default_value or ")" in default_value:
            if data_type in ("datetime", "timestamp", "date"):
                return "NOW", {}
            return "DEFAULT", {}
        return "CUSTOM_VALUE", {"value": default_value}
    return "DEFAULT", {}


def _infer_field_configs_from_cache(session, datasource_id: int, table_name: str) -> list[dict]:
    """从 df_column_cache 读取关联表字段元数据并推断策略"""
    from app.models import ColumnCache  # 延迟导入，便于单测替换

    columns = (
        session.query(ColumnCache)
        .filter(ColumnCache.datasource_id == datasource_id, ColumnCache.table_name == table_name)
        .order_by(ColumnCache.ordinal_position)
        .all()
    )
    if not columns:
        raise ValueError(
            f"关联表 {table_name} 无字段元数据缓存，请先同步数据源表结构"
        )
    field_configs = []
    for col in columns:
        strategy, params = _infer_strategy(col)
        field_configs.append({
            "column_name": col.column_name,
            "data_type": col.data_type,
            "column_type": col.column_type,
            "is_nullable": bool(col.is_nullable),
            "is_primary_key": bool(col.is_primary_key),
            "char_max_length": col.char_max_length,
            "numeric_precision": col.numeric_precision,
            "numeric_scale": col.numeric_scale,
            "strategy": strategy,
            "strategy_params": params,
        })
    return field_configs


def _build_table_field_configs(session, ctx: _CaseContext) -> None:
    """构建每张表的字段配置：主表用快照；关联表优先快照 related_field_configs，否则从缓存推断"""
    ctx.table_field_configs[ctx.main_table] = ctx.config.get("field_configs") or []

    related_overrides: dict = ctx.config.get("related_field_configs") or {}
    target_tables: list[str] = []
    for assoc in ctx.associations:
        target = assoc["target_table"]
        if target not in target_tables:
            target_tables.append(target)
    for table in target_tables:
        if table in related_overrides:
            ctx.table_field_configs[table] = related_overrides[table]
        else:
            ctx.table_field_configs[table] = _infer_field_configs_from_cache(
                session, ctx.task.datasource_id, table
            )


def _validate_associations(ctx: _CaseContext) -> None:
    """关联配置校验：源字段存在且非 SKIP；同一目标列不被多个源字段重复关联"""
    seen_targets: dict[tuple[str, str], tuple[str, str]] = {}
    for assoc in ctx.associations:
        source_table = assoc.get("source_table") or ctx.main_table
        source_column = assoc["source_column"]
        target_key = (assoc["target_table"], assoc["target_column"])
        source_key = (source_table, source_column)
        if target_key in seen_targets and seen_targets[target_key] != source_key:
            raise ValueError(
                f"关联目标 {target_key[0]}.{target_key[1]} 被多个源字段关联，配置冲突"
            )
        seen_targets[target_key] = source_key
        source_configs = ctx.table_field_configs.get(source_table) or []
        matched = next(
            (fc for fc in source_configs if fc["column_name"] == source_column), None
        )
        if matched is None:
            raise ValueError(f"关联源字段不存在: {source_table}.{source_column}")
        if (matched.get("strategy") or "").upper() == "SKIP":
            raise ValueError(f"自增主键字段不能作为关联源: {source_table}.{source_column}")


def _validate_all_strategies(ctx: _CaseContext) -> None:
    """执行前统一校验所有字段策略参数（非法配置快速失败，避免插入部分数据后才报错）"""
    for table, field_configs in ctx.table_field_configs.items():
        for field_config in field_configs:
            strategy_code = (field_config.get("strategy") or "DEFAULT").upper()
            if strategy_code == "SKIP":
                continue
            strategy = get_strategy(strategy_code)  # 未知策略在此抛 ValueError
            strategy.validate(field_config, dict(field_config.get("strategy_params") or {}))


def _init_incr_counters(ctx: _CaseContext) -> None:
    """扫描所有表 INCR_FROM 字段，初始化 Redis 自增计数器（NX，重试时不覆盖已有进度）"""
    for table, field_configs in ctx.table_field_configs.items():
        for field_config in field_configs:
            if (field_config.get("strategy") or "").upper() == "INCR_FROM":
                start = (field_config.get("strategy_params") or {}).get("start", 1)
                init_incr_counter(
                    sync_redis_client, ctx.task_id, table, field_config["column_name"], int(start)
                )


# Redis 进度

def _init_progress(ctx: _CaseContext, per_table_target: int, total_rounds: int | None = None) -> None:
    """初始化任务进度 Key（progress / table_progress，TTL 24h）"""
    now = str(int(time.time()))
    tables = ctx.insert_order
    pipe = sync_redis_client.pipeline()
    progress_key = PROGRESS_KEY.format(task_no=ctx.task_no)
    mapping = {
        "status": "running",
        "target_total": str(per_table_target * len(tables)),
        "success_total": "0",
        "fail_total": "0",
        "table_count": str(len(tables)),
        "batch_size": str(ctx.batch_size),
        "concurrency": str(ctx.max_workers),
        "start_at": now,
        "updated_at": now,
    }
    if total_rounds is not None:
        # 遍历模式附加轮次信息
        mapping.update({"current_round": "0", "total_rounds": str(total_rounds), "current_drive_value": ""})
    pipe.hset(progress_key, mapping=mapping)
    pipe.expire(progress_key, PROGRESS_TTL)

    table_key = TABLE_PROGRESS_KEY.format(task_no=ctx.task_no)
    for table in tables:
        pipe.hset(table_key, table, json.dumps(
            {"target": per_table_target, "success": 0, "failed": 0, "status": "pending"}
        ))
    pipe.expire(table_key, PROGRESS_TTL)
    pipe.execute()


def _update_table_progress(ctx: _CaseContext, table: str, success_delta: int = 0, fail_delta: int = 0) -> None:
    """分表进度读-改-写（仅主线程调用，无并发竞争）"""
    key = TABLE_PROGRESS_KEY.format(task_no=ctx.task_no)
    raw = sync_redis_client.hget(key, table)
    data = json.loads(_decode(raw)) if raw else {"target": 0, "success": 0, "failed": 0, "status": "pending"}
    data["success"] = int(data.get("success", 0)) + success_delta
    data["failed"] = int(data.get("failed", 0)) + fail_delta
    target = int(data.get("target", 0))
    if target > 0 and data["success"] >= target:
        data["status"] = "success"
    elif data["failed"] > 0 and data["success"] + data["failed"] >= target:
        data["status"] = "failed"
    else:
        data["status"] = "running"
    sync_redis_client.hset(key, table, json.dumps(data))


def _progress_success(ctx: _CaseContext, table: str, count: int) -> None:
    """批次成功进度更新：整体进度 + 分表进度 + 速率滑动窗口"""
    now = str(int(time.time()))
    progress_key = PROGRESS_KEY.format(task_no=ctx.task_no)
    rate_key = RATE_KEY.format(task_no=ctx.task_no, table=table)
    pipe = sync_redis_client.pipeline()
    pipe.hincrby(progress_key, "success_total", count)
    pipe.hset(progress_key, "updated_at", now)
    # 速率滑动窗口：RPUSH "{timestamp}:{count}"，TTL 10s 自动清理
    pipe.rpush(rate_key, f"{time.time()}:{count}")
    pipe.expire(rate_key, RATE_TTL)
    pipe.execute()
    _update_table_progress(ctx, table, success_delta=count)


def _progress_fail(ctx: _CaseContext, table: str, count: int) -> None:
    """批次失败进度更新"""
    now = str(int(time.time()))
    progress_key = PROGRESS_KEY.format(task_no=ctx.task_no)
    pipe = sync_redis_client.pipeline()
    pipe.hincrby(progress_key, "fail_total", count)
    pipe.hset(progress_key, "updated_at", now)
    pipe.execute()
    _update_table_progress(ctx, table, fail_delta=count)


def _write_final_progress(ctx: _CaseContext, final_status: int) -> None:
    """写入进度终态并刷新 TTL"""
    final_str = REDIS_STATUS_MAP.get(final_status, "failed")
    now = str(int(time.time()))
    progress_key = PROGRESS_KEY.format(task_no=ctx.task_no)
    table_key = TABLE_PROGRESS_KEY.format(task_no=ctx.task_no)
    pipe = sync_redis_client.pipeline()
    pipe.hset(progress_key, mapping={"status": final_str, "updated_at": now})
    pipe.expire(progress_key, PROGRESS_TTL)
    pipe.expire(table_key, PROGRESS_TTL)
    pipe.execute()


def _expire_incr_counters(ctx: _CaseContext) -> None:
    """清理自增计数器：设置 24h TTL 自动过期

    不立即删除的原因：断点重试需要在保留窗口内沿用计数器，保证自增值连续不重复。
    """
    try:
        for key in sync_redis_client.scan_iter(f"df:incr:{ctx.task_id}:*"):
            sync_redis_client.expire(key, INCR_COUNTER_TTL)
    except Exception:  # 清理失败不影响主流程
        logger.warning("incr_counter_expire_failed", task_no=ctx.task_no)


# 批量插入（工作线程内执行）

def _bulk_insert(engine, table: str, rows: list[dict]) -> None:
    """原生批量 VALUES 插入"""
    if not rows:
        return
    columns = [_safe_ident(column) for column in rows[0].keys()]
    col_names = ", ".join(f"`{column}`" for column in columns)
    placeholders = ", ".join(f":{column}" for column in columns)
    sql = text(f"INSERT INTO `{_safe_ident(table)}` ({col_names}) VALUES ({placeholders})")
    disable_fk = bool(getattr(settings, "DISABLE_FK_CHECKS", False))
    disable_unique = bool(getattr(settings, "DISABLE_UNIQUE_CHECKS", False))
    with engine.begin() as conn:
        # 可选：临时关闭外键/唯一检查加速批量插入（会话级，插入后恢复）
        if disable_fk:
            conn.exec_driver_sql("SET SESSION foreign_key_checks=0")
        if disable_unique:
            conn.exec_driver_sql("SET SESSION unique_checks=0")
        try:
            conn.execute(sql, rows)
        finally:
            if disable_fk:
                conn.exec_driver_sql("SET SESSION foreign_key_checks=1")
            if disable_unique:
                conn.exec_driver_sql("SET SESSION unique_checks=1")


def _table_result(table: str, status: int, size: int, retry_times: int,
                  error: str | None, start_at: datetime, start_ts: float) -> dict:
    """组装单表单批次执行结果"""
    return {
        "table": table,
        "status": status,
        "size": size,
        "retry_times": retry_times,
        "error": error,
        "start_at": start_at,
        "finish_at": datetime.now(),
        "duration_ms": int((time.time() - start_ts) * 1000),
    }


def _insert_with_retry(ctx: _CaseContext, table: str, rows: list[dict], batch_no: int) -> dict:
    """单表批量 INSERT，失败原地重试 max_retry 次（指数退避 1s/2s/4s）"""
    start_ts = time.time()
    start_at = datetime.now()
    retry_times = 0
    last_error: str | None = None
    while retry_times <= ctx.max_retry:
        try:
            _bulk_insert(ctx.engine, table, rows)
            return _table_result(table, BATCH_STATUS_SUCCESS, len(rows), retry_times, None, start_at, start_ts)
        except Exception as exc:  # noqa: BLE001 — 目标库异常需兜底重试
            last_error = str(exc)[:500]
            retry_times += 1
            if retry_times > ctx.max_retry:
                break
            backoff = 2 ** (retry_times - 1)  # 1s → 2s → 4s
            logger.warning(
                "batch_insert_retry",
                task_no=ctx.task_no, table=table, batch_no=batch_no,
                retry_times=retry_times, backoff=backoff, error=last_error,
            )
            time.sleep(backoff)
    logger.error(
        "batch_insert_failed",
        task_no=ctx.task_no, table=table, batch_no=batch_no, error=last_error,
    )
    return _table_result(table, BATCH_STATUS_FAILED, len(rows), ctx.max_retry, last_error, start_at, start_ts)


def _sample_source_values(ctx: _CaseContext, source_table: str, source_column: str, size: int) -> list:
    """断点重试场景：从源表采样真实值用于关联注入，保证外键一致"""
    sql = text(
        f"SELECT `{_safe_ident(source_column)}` FROM `{_safe_ident(source_table)}` LIMIT :limit_size"
    )
    with ctx.engine.connect() as conn:
        rows = conn.execute(sql, {"limit_size": size}).fetchall()
    values = [row[0] for row in rows]
    if not values:
        raise ValueError(f"源表 {source_table} 无可用数据，无法重试关联批次")
    # 不足 size 时循环填充
    while len(values) < size:
        values.extend(values[: size - len(values)])
    return values[:size]


def _execute_batch(ctx: _CaseContext, batch_no: int, size: int,
                   round_no: int | None = None, drive_value: Any = None,
                   only_tables: list[str] | None = None) -> dict:
    """单个批次执行（工作线程）：生成数据 → 按依赖顺序插入各表

    :param only_tables: 仅插入指定表（断点重试用）；None 表示按完整插入顺序
    线程安全说明：仅访问目标库 Engine（线程安全）与 Redis 客户端（线程安全），
    不触碰 SQLAlchemy Session。
    """
    if only_tables is not None:
        only_set = set(only_tables)
        insert_tables = [table for table in ctx.insert_order if table in only_set]
    else:
        insert_tables = list(ctx.insert_order)

    batch_result = {"batch_no": batch_no, "size": size, "round_no": round_no,
                    "drive_value": drive_value, "tables": []}
    # 本批已生成的行数据（关联注入的取值来源）
    generated: dict[str, list[dict]] = {}

    def _source_values(source_table: str, source_column: str) -> list:
        """取关联源值：遍历模式驱动列取当前轮固定值；优先本批生成行；否则源表采样"""
        if (
            drive_value is not None
            and ctx.iterate_driver
            and source_table == ctx.main_table
            and source_column == ctx.iterate_driver["column"]
        ):
            return [drive_value] * size
        if source_table in generated:
            return [row.get(source_column) for row in generated[source_table]]
        return _sample_source_values(ctx, source_table, source_column, size)

    for index, table in enumerate(insert_tables):
        # 1) 构建本表关联注入 {目标列: [每行的值]}
        injected: dict[str, list] = {}
        for assoc in ctx.associations:
            if assoc["target_table"] != table:
                continue
            source_table = assoc.get("source_table") or ctx.main_table
            injected[assoc["target_column"]] = _source_values(source_table, assoc["source_column"])

        # 2) 遍历模式：主表驱动列固定为当前轮 drive_value
        overrides: dict[str, Any] = {}
        if drive_value is not None and ctx.iterate_driver and table == ctx.main_table:
            overrides[ctx.iterate_driver["column"]] = drive_value

        # 3) 生成数据（参数错误直接判定本表失败，不做无意义重试）
        try:
            rows, _ = generate_rows(
                table_name=table,
                field_configs=ctx.table_field_configs[table],
                count=size,
                task_id=ctx.task_id,
                redis_client=sync_redis_client,
                injected_columns=injected,
                value_overrides=overrides,
            )
        except ValueError as exc:
            start_ts = time.time()
            batch_result["tables"].append(
                _table_result(table, BATCH_STATUS_FAILED, size, 0, str(exc)[:500], datetime.now(), start_ts)
            )
            if table == ctx.main_table:
                # 主表失败：关联表无外键来源，整批跳过
                for rest in insert_tables[index + 1:]:
                    batch_result["tables"].append(
                        _table_result(rest, BATCH_STATUS_FAILED, size, 0,
                                      "主表批次失败，关联表跳过", datetime.now(), start_ts)
                    )
                break
            continue

        generated[table] = rows

        # 4) 批量插入（含原地重试）
        table_result = _insert_with_retry(ctx, table, rows, batch_no)
        batch_result["tables"].append(table_result)

        if table == ctx.main_table and table_result["status"] == BATCH_STATUS_FAILED:
            # 主表插入失败：关联表跳过（避免插入无对应主表行的孤儿数据）
            start_ts = time.time()
            for rest in insert_tables[index + 1:]:
                batch_result["tables"].append(
                    _table_result(rest, BATCH_STATUS_FAILED, size, 0,
                                  "主表批次失败，关联表跳过", datetime.now(), start_ts)
                )
            break

    return batch_result


# 批次结果记录（主线程）

def _record_batch_result(ctx: _CaseContext, session, batch_result: dict, stats: dict) -> None:
    """主线程统一写批次日志 + 更新 Redis 进度 + 累计统计"""
    for table_result in batch_result["tables"]:
        batch_log = ExecBatchLog(
            task_id=ctx.task_id,
            table_name=table_result["table"],
            batch_no=batch_result["batch_no"],
            batch_size=table_result["size"],
            status=table_result["status"],
            retry_times=table_result["retry_times"],
            error_msg=table_result["error"],
            start_at=table_result["start_at"],
            finish_at=table_result["finish_at"],
            duration_ms=table_result["duration_ms"],
            # 遍历模式轮次信息
            round_no=batch_result["round_no"],
            drive_value=(str(batch_result["drive_value"]) if batch_result["drive_value"] is not None else None),
            created_at=datetime.now(),
        )
        session.add(batch_log)
        if table_result["status"] == BATCH_STATUS_SUCCESS:
            stats["success_rows"] += table_result["size"]
            _progress_success(ctx, table_result["table"], table_result["size"])
        else:
            stats["fail_rows"] += table_result["size"]
            stats["errors"].append(
                f"{table_result['table']} 批次{batch_result['batch_no']}: {table_result['error']}"
            )
            _progress_fail(ctx, table_result["table"], table_result["size"])
    session.commit()


def _fail_rate_exceeded(ctx: _CaseContext, stats: dict) -> bool:
    """失败率是否超过阈值（失败率 > 50% 任务失败停止）"""
    total = stats["success_rows"] + stats["fail_rows"]
    return total > 0 and stats["fail_rows"] / total > ctx.fail_rate_threshold


def _run_offsets(ctx: _CaseContext, session, offset_list: list[int], batch_no_start: int,
                 row_count: int, round_no: int | None, drive_value: Any, stats: dict) -> bool:
    """对给定 offset 列表并发执行批次（波次提交，控制内存与在途任务数）

    每波最多 max_workers*4 个在途批次；批次完成即检查失败率，
    超阈值则取消未开始的批次、等待运行中批次收尾后停止。

    :return: 是否因失败率超阈值而提前停止
    """
    pending = set()
    stop_submit = False
    index = 0
    max_inflight = max(ctx.max_workers * 4, ctx.max_workers)

    with ThreadPoolExecutor(max_workers=ctx.max_workers, thread_name_prefix=f"df-{ctx.task_no}") as pool:
        while True:
            # 补充提交新批次（波次控制）
            while not stop_submit and len(pending) < max_inflight and index < len(offset_list):
                offset = offset_list[index]
                size = min(ctx.batch_size, row_count - offset)
                future = pool.submit(
                    _execute_batch, ctx, batch_no_start + index, size, round_no, drive_value
                )
                pending.add(future)
                index += 1
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                if future.cancelled():
                    continue  # 被取消的批次不记录日志（未执行）
                batch_result = future.result()
                _record_batch_result(ctx, session, batch_result, stats)
            if not stop_submit and _fail_rate_exceeded(ctx, stats):
                stop_submit = True
                stats["stopped"] = True
                logger.warning(
                    "task_fail_rate_exceeded",
                    task_no=ctx.task_no,
                    success_rows=stats["success_rows"],
                    fail_rows=stats["fail_rows"],
                    threshold=ctx.fail_rate_threshold,
                )
                # 取消尚未开始的批次；运行中的批次等待完成后自然收尾
                for future in pending:
                    future.cancel()
                index = len(offset_list)  # 不再提交新批次
    return stop_submit


def _run_all(ctx: _CaseContext, session, row_count: int, round_no: int | None,
             drive_value: Any, batch_no_start: int, stats: dict) -> bool:
    """执行全部批次（超过 AUTO_SPLIT_THRESHOLD 自动分片，片间输出检查点日志）

    :return: 是否因失败率超阈值而提前停止
    """
    offsets = list(range(0, row_count, ctx.batch_size))
    shard_rows = int(getattr(settings, "AUTO_SPLIT_THRESHOLD", 10_000_000) or 10_000_000)
    batches_per_shard = max(1, shard_rows // ctx.batch_size)

    stopped = False
    for shard_index, shard_start in enumerate(range(0, len(offsets), batches_per_shard)):
        shard_offsets = offsets[shard_start:shard_start + batches_per_shard]
        if len(offsets) > batches_per_shard:
            # 单表超阈值自动分片：每片一个检查点日志，便于大任务追踪
            logger.info(
                "auto_split_shard_start",
                task_no=ctx.task_no, shard_no=shard_index,
                shard_batches=len(shard_offsets), round_no=round_no,
            )
        stopped = _run_offsets(
            ctx, session, shard_offsets, batch_no_start + shard_start,
            row_count, round_no, drive_value, stats,
        )
        if stopped:
            break

    if stopped:
        # 未执行的行按失败计入（失败率超阈值任务失败停止）
        accounted = stats["success_rows"] + stats["fail_rows"]
        remaining = row_count * len(ctx.insert_order) - accounted
        if remaining > 0:
            stats["fail_rows"] += remaining
            stats["errors"].append(
                f"失败率超过阈值 {ctx.fail_rate_threshold:.0%}，剩余 {remaining} 行未执行"
            )
    return stopped


# 执行模式

def _execute_normal_mode(ctx: _CaseContext, session) -> list[dict]:
    """普通模式：按 target_count 一次性执行"""
    row_count = int(ctx.task.target_count or 0)
    if row_count <= 0:
        raise ValueError("造数条数必须为正整数")
    _init_progress(ctx, per_table_target=row_count)
    logger.info(
        "exec_task_start",
        task_no=ctx.task_no, main_table=ctx.main_table, tables=ctx.insert_order,
        target_count=row_count, batch_size=ctx.batch_size, max_workers=ctx.max_workers,
    )
    stats = _new_stats()
    _run_all(ctx, session, row_count, None, None, 0, stats)
    return [stats]


def execute_iterate_mode(ctx: _CaseContext, session) -> list[dict]:
    """ITERATE_LIST 遍历驱动模式

    逐轮串行执行：每轮将驱动字段注入为固定值，主表与各关联表各插入 rows_per_value 行；
    单轮整体失败记录后继续下一轮，不中止整体任务。
    """
    driver = ctx.iterate_driver
    drive_values = driver["drive_values"]
    rows_per_value = driver["rows_per_value"]
    total_rounds = len(drive_values)
    per_table_target = rows_per_value * total_rounds

    # 遍历模式总条数由策略参数决定，校准任务目标条数
    if int(ctx.task.target_count or 0) != per_table_target:
        ctx.task.target_count = per_table_target
        session.commit()

    # 遍历模式按「每值条数」计算批次大小
    ctx.batch_size = calc_batch_size(rows_per_value)
    _init_progress(ctx, per_table_target=per_table_target, total_rounds=total_rounds)
    logger.info(
        "exec_iterate_start",
        task_no=ctx.task_no, drive_column=driver["column"],
        total_rounds=total_rounds, rows_per_value=rows_per_value,
    )

    progress_key = PROGRESS_KEY.format(task_no=ctx.task_no)
    stats_list: list[dict] = []
    batch_no_cursor = 0
    batches_per_round = (rows_per_value + ctx.batch_size - 1) // ctx.batch_size

    for round_index, drive_value in enumerate(drive_values):
        # 更新 Redis：当前轮次信息（进度面板展示「已完成轮次/总轮次 + 当前值」）
        sync_redis_client.hset(progress_key, mapping={
            "current_round": str(round_index + 1),
            "current_drive_value": str(drive_value),
            "updated_at": str(int(time.time())),
        })
        logger.info(
            "iterate_round_start",
            task_no=ctx.task_no, round_no=round_index, drive_value=str(drive_value),
        )
        stats = _new_stats()
        _run_all(ctx, session, rows_per_value, round_index, drive_value, batch_no_cursor, stats)
        batch_no_cursor += batches_per_round
        stats_list.append(stats)
        if stats["stopped"]:
            # 单轮整体失败：记录后继续后续轮次
            logger.warning(
                "iterate_round_failed_continue",
                task_no=ctx.task_no, round_no=round_index, drive_value=str(drive_value),
            )
            continue
    return stats_list


# 任务终态汇总

def _finalize_task(ctx: _CaseContext, session, stats_list: list[dict], iterate_mode: bool) -> int:
    """汇总任务终态：更新 df_exec_task / df_case / Redis 进度，清理自增计数器"""
    task = ctx.task
    success_rows = sum(s["success_rows"] for s in stats_list)
    fail_rows = sum(s["fail_rows"] for s in stats_list)
    errors = [error for s in stats_list for error in s["errors"]]
    total = success_rows + fail_rows

    if iterate_mode:
        # 遍历模式按轮次判定全轮成功=成功 / 部分轮失败=部分成功 / 全轮失败=失败
        total_rounds = len(ctx.iterate_driver["drive_values"])
        failed_rounds = sum(1 for s in stats_list if s["fail_rows"] > 0)
        if failed_rounds == 0:
            final = TASK_STATUS_SUCCESS
        elif failed_rounds >= total_rounds:
            final = TASK_STATUS_FAILED
        else:
            final = TASK_STATUS_PARTIAL
    else:
        # 普通模式按行失败率判定
        if total == 0:
            final = TASK_STATUS_FAILED
            errors = errors or ["未执行任何批次"]
        elif fail_rows == 0:
            final = TASK_STATUS_SUCCESS
        elif any(s["stopped"] for s in stats_list) or fail_rows / total > ctx.fail_rate_threshold:
            final = TASK_STATUS_FAILED
        else:
            final = TASK_STATUS_PARTIAL

    now = datetime.now()
    task.status = final
    task.success_count = success_rows
    task.fail_count = fail_rows
    task.finish_at = now
    task.duration_ms = int((time.time() - ctx.start_monotonic) * 1000)
    if final != TASK_STATUS_SUCCESS and errors:
        task.error_msg = errors[0][:2000]
    session.commit()

    # 更新 Case 最后执行信息（last_exec_status：1=成功 2=失败 3=部分成功）
    case = session.get(Case, task.case_id)
    if case is not None:
        case.last_exec_at = now
        case.last_exec_status = {
            TASK_STATUS_SUCCESS: 1, TASK_STATUS_FAILED: 2, TASK_STATUS_PARTIAL: 3,
        }.get(final, 2)
        case.exec_count = (case.exec_count or 0) + 1
        session.commit()

    _write_final_progress(ctx, final)
    _expire_incr_counters(ctx)
    logger.info(
        "exec_task_finish",
        task_no=ctx.task_no, status=final,
        success_rows=success_rows, fail_rows=fail_rows, duration_ms=task.duration_ms,
    )
    return final


def _mark_task_failed(session, task: ExecTask, message: str) -> None:
    """初始化/异常阶段的快速失败标记"""
    task.status = TASK_STATUS_FAILED
    task.error_msg = message[:2000]
    task.finish_at = datetime.now()
    session.commit()
    try:
        progress_key = PROGRESS_KEY.format(task_no=task.task_no)
        if sync_redis_client.exists(progress_key):
            sync_redis_client.hset(progress_key, mapping={
                "status": "failed", "updated_at": str(int(time.time())),
            })
            sync_redis_client.expire(progress_key, PROGRESS_TTL)
    except Exception:
        pass


def _build_result(ctx: _CaseContext, final: int) -> dict:
    """组装返回给 Celery 任务的结果"""
    return {
        "task_id": ctx.task_id,
        "task_no": ctx.task_no,
        "status": REDIS_STATUS_MAP.get(final, "failed"),
        "status_code": final,
        "success_count": int(ctx.task.success_count or 0),
        "fail_count": int(ctx.task.fail_count or 0),
        "duration_ms": int(ctx.task.duration_ms or 0),
        "error": ctx.task.error_msg,
    }


# 对外入口

def _prepare_context(session, task: ExecTask) -> _CaseContext:
    """解析配置并构建执行上下文（含全部静态校验）"""
    config = json.loads(task.case_snapshot)
    _validate_config(config)
    engine = get_sync_engine(task.datasource_id)
    ctx = _CaseContext(task, config, engine)
    _build_table_field_configs(session, ctx)
    ctx.insert_order = build_insert_order(ctx.main_table, ctx.associations)
    _validate_associations(ctx)
    ctx.iterate_driver = detect_iterate_driver(config)
    _validate_all_strategies(ctx)
    _init_incr_counters(ctx)
    return ctx


def execute_case_task(task_id: int) -> dict:
    """单 Case 执行入口（Celery 任务内同步调用）

    流程参数校验 → 插入顺序 → Redis 计数器 → 动态批次 →
    多线程并发批次 → 批次日志/进度 → 终态汇总。
    """
    session = SyncSessionLocal()
    try:
        task = session.get(ExecTask, task_id)
        if task is None:
            logger.error("exec_task_not_found", task_id=task_id)
            return {"task_id": task_id, "status": "failed", "error": "执行任务不存在"}
        # 幂等保护：仅「待执行/重试中」状态可进入执行
        if task.status not in (TASK_STATUS_PENDING, TASK_STATUS_RETRYING):
            logger.warning("exec_task_status_skip", task_no=task.task_no, status=task.status)
            return {"task_id": task_id, "task_no": task.task_no, "status": "skipped",
                    "error": f"任务状态为 {task.status}，不可重复执行"}

        try:
            ctx = _prepare_context(session, task)
        except Exception as exc:
            logger.exception("exec_task_prepare_failed", task_no=task.task_no)
            _mark_task_failed(session, task, f"任务初始化失败: {exc}")
            return {"task_id": task_id, "task_no": task.task_no, "status": "failed",
                    "status_code": TASK_STATUS_FAILED, "success_count": 0, "fail_count": 0,
                    "duration_ms": 0, "error": str(exc)[:500]}

        # 标记执行中
        task.status = TASK_STATUS_RUNNING
        task.start_at = datetime.now()
        task.error_msg = None
        session.commit()

        try:
            iterate_mode = ctx.iterate_driver is not None
            if iterate_mode:
                stats_list = execute_iterate_mode(ctx, session)
            else:
                stats_list = _execute_normal_mode(ctx, session)
            final = _finalize_task(ctx, session, stats_list, iterate_mode)
            return _build_result(ctx, final)
        except Exception as exc:
            logger.exception("exec_task_error", task_no=task.task_no)
            session.rollback()
            _mark_task_failed(session, task, f"执行异常: {exc}")
            _expire_incr_counters(ctx)
            return {"task_id": task_id, "task_no": task.task_no, "status": "failed",
                    "status_code": TASK_STATUS_FAILED,
                    "success_count": int(task.success_count or 0),
                    "fail_count": int(task.fail_count or 0),
                    "duration_ms": 0, "error": str(exc)[:500]}
    finally:
        session.close()


def _latest_batch_logs(session, task_id: int) -> dict[tuple, ExecBatchLog]:
    """取每个 (round_no, batch_no, table_name) 最新一条批次日志（重试后新旧日志并存）"""
    logs = (
        session.query(ExecBatchLog)
        .filter(ExecBatchLog.task_id == task_id)
        .order_by(ExecBatchLog.id)
        .all()
    )
    latest: dict[tuple, ExecBatchLog] = {}
    for log in logs:
        latest[(log.round_no, log.batch_no, log.table_name)] = log
    return latest


def _reset_progress_for_retry(ctx: _CaseContext, session, per_table_target: int) -> None:
    """断点重试前重建 Redis 进度基线：保留已成功行数，失败清零待重跑"""
    latest = _latest_batch_logs(session, ctx.task_id)
    table_success: dict[str, int] = {}
    for log in latest.values():
        if log.status == BATCH_STATUS_SUCCESS:
            table_success[log.table_name] = table_success.get(log.table_name, 0) + int(log.batch_size)

    now = str(int(time.time()))
    total_success = sum(table_success.values())
    pipe = sync_redis_client.pipeline()
    progress_key = PROGRESS_KEY.format(task_no=ctx.task_no)
    pipe.hset(progress_key, mapping={
        "status": "running",
        # 全量重写关键字段，兼容进度 Key 已过期的场景
        "target_total": str(per_table_target * len(ctx.insert_order)),
        "success_total": str(total_success),
        "fail_total": "0",
        "table_count": str(len(ctx.insert_order)),
        "batch_size": str(ctx.batch_size),
        "concurrency": str(ctx.max_workers),
        "updated_at": now,
    })
    pipe.expire(progress_key, PROGRESS_TTL)
    table_key = TABLE_PROGRESS_KEY.format(task_no=ctx.task_no)
    for table in ctx.insert_order:
        success = table_success.get(table, 0)
        status = "success" if success >= per_table_target else "running"
        pipe.hset(table_key, table, json.dumps(
            {"target": per_table_target, "success": success, "failed": 0, "status": status}
        ))
    pipe.expire(table_key, PROGRESS_TTL)
    pipe.execute()


def retry_failed_batches(task_id: int) -> dict:
    """断点续传：仅重跑 status=失败 的批次

    - 计数器采用 NX 初始化，自增值从上次断点继续，不会重复
    - 关联表批次重试时若主表批次已成功，则从源表采样真实值注入，保证外键一致
    - 重试结果以新批次日志追加，终态按「每批次最新一条日志」重新汇总
    """
    session = SyncSessionLocal()
    try:
        task = session.get(ExecTask, task_id)
        if task is None:
            return {"task_id": task_id, "status": "failed", "error": "执行任务不存在"}
        if task.status not in (TASK_STATUS_FAILED, TASK_STATUS_PARTIAL):
            return {"task_id": task_id, "task_no": task.task_no, "status": "skipped",
                    "error": f"任务状态为 {task.status}，仅失败/部分成功任务可重试"}

        try:
            ctx = _prepare_context(session, task)
        except Exception as exc:
            logger.exception("retry_prepare_failed", task_no=task.task_no)
            _mark_task_failed(session, task, f"重试初始化失败: {exc}")
            return {"task_id": task_id, "task_no": task.task_no, "status": "failed",
                    "status_code": TASK_STATUS_FAILED, "error": str(exc)[:500]}

        # 按 (round_no, batch_no) 分组收集失败批次及失败表
        failed_logs = (
            session.query(ExecBatchLog)
            .filter(ExecBatchLog.task_id == task_id, ExecBatchLog.status == BATCH_STATUS_FAILED)
            .order_by(ExecBatchLog.round_no, ExecBatchLog.batch_no)
            .all()
        )
        if not failed_logs:
            # 无失败批次：直接按现有日志重算终态
            task.status = TASK_STATUS_RUNNING
            session.commit()
            final = _recount_finalize(ctx, session)
            return _build_result(ctx, final)

        task.status = TASK_STATUS_RETRYING
        task.error_msg = None
        session.commit()

        per_table_target = int(task.target_count or 0)
        _reset_progress_for_retry(ctx, session, per_table_target)
        logger.info(
            "retry_failed_batches_start",
            task_no=task.task_no, failed_batch_logs=len(failed_logs),
        )

        groups: dict[tuple, dict] = {}
        for log in failed_logs:
            group_key = (log.round_no, log.batch_no)
            group = groups.setdefault(group_key, {
                "round_no": log.round_no,
                "batch_no": log.batch_no,
                "size": int(log.batch_size),
                "drive_value": log.drive_value,
                "tables": [],
            })
            group["tables"].append(log.table_name)
            group["size"] = max(group["size"], int(log.batch_size))
        group_list = sorted(
            groups.values(),
            key=lambda item: (item["round_no"] if item["round_no"] is not None else -1, item["batch_no"]),
        )

        stats = _new_stats()
        with ThreadPoolExecutor(max_workers=ctx.max_workers,
                                thread_name_prefix=f"df-retry-{ctx.task_no}") as pool:
            futures = {
                pool.submit(
                    _execute_batch, ctx, group["batch_no"], group["size"],
                    group["round_no"], group["drive_value"], group["tables"],
                ): group
                for group in group_list
            }
            for future in as_completed(futures):
                _record_batch_result(ctx, session, future.result(), stats)

        final = _recount_finalize(ctx, session)
        return _build_result(ctx, final)
    finally:
        session.close()


def _recount_finalize(ctx: _CaseContext, session) -> int:
    """按「每批次最新一条日志」重新汇总任务终态（断点重试后调用）"""
    latest = _latest_batch_logs(session, ctx.task_id)
    success_rows = sum(int(log.batch_size) for log in latest.values() if log.status == BATCH_STATUS_SUCCESS)
    fail_rows = sum(int(log.batch_size) for log in latest.values() if log.status == BATCH_STATUS_FAILED)
    total = success_rows + fail_rows

    if fail_rows == 0 and success_rows > 0:
        final = TASK_STATUS_SUCCESS
    elif success_rows == 0 or (total > 0 and fail_rows / total > ctx.fail_rate_threshold):
        final = TASK_STATUS_FAILED
    else:
        final = TASK_STATUS_PARTIAL

    task = ctx.task
    now = datetime.now()
    task.status = final
    task.success_count = success_rows
    task.fail_count = fail_rows
    task.finish_at = now
    task.duration_ms = int((time.time() - ctx.start_monotonic) * 1000)
    if final == TASK_STATUS_SUCCESS:
        task.error_msg = None
    else:
        failed_log = next((log for log in latest.values() if log.status == BATCH_STATUS_FAILED), None)
        if failed_log is not None:
            task.error_msg = (failed_log.error_msg or "")[:2000]
    session.commit()

    # 同步 Redis 终态（分表进度同步为最终值）
    table_success: dict[str, int] = {}
    table_fail: dict[str, int] = {}
    for log in latest.values():
        if log.status == BATCH_STATUS_SUCCESS:
            table_success[log.table_name] = table_success.get(log.table_name, 0) + int(log.batch_size)
        else:
            table_fail[log.table_name] = table_fail.get(log.table_name, 0) + int(log.batch_size)
    per_table_target = int(task.target_count or 0)
    table_key = TABLE_PROGRESS_KEY.format(task_no=ctx.task_no)
    for table in ctx.insert_order:
        success = table_success.get(table, 0)
        failed = table_fail.get(table, 0)
        if success >= per_table_target:
            status = "success"
        elif failed > 0:
            status = "failed"
        else:
            status = "running"
        sync_redis_client.hset(table_key, table, json.dumps(
            {"target": per_table_target, "success": success, "failed": failed, "status": status}
        ))
    progress_key = PROGRESS_KEY.format(task_no=ctx.task_no)
    sync_redis_client.hset(progress_key, mapping={
        "success_total": str(success_rows), "fail_total": str(fail_rows),
    })
    _write_final_progress(ctx, final)
    _expire_incr_counters(ctx)
    logger.info(
        "retry_finalize",
        task_no=ctx.task_no, status=final, success_rows=success_rows, fail_rows=fail_rows,
    )
    return final
