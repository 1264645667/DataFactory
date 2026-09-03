"""Redis 造数引擎：纯 Redis Case 执行 + MySQL Case Redis 联动同步

模板占位符（key_template / value_template 通用）：
- {incr} / {incr:起始值}：全局递增序号（Redis 计数器按批次预取连续区间，跨批次不重不漏）
- {i}：行在批次内序号（0 起）
- {uuid} / {uuid:N}：随机 UUID（可指定截断长度）
- {rand:N}：N 位随机数字
- {ts} / {ts_ms}：当前时间戳（秒/毫秒）
- {task_no}：执行任务编号
- {字段名}：纯 Redis Case 引用 field_configs 生成的字段值
- {表名.字段名}：MySQL Case 联动引用本批生成行的字段值

写入语义：
- write_mode=per_row：每行一个 Key（10 行 → 10 个 Key）
- write_mode=single_key：全量行聚合到一个 Key（10 行 → 1 个 Key 的 10 个成员）
- 批次写入使用 pipeline(transaction=True)，单批原子；失败整批不落
- 批次日志 table_name 以 "redis:" 前缀标识（断点重试跳过 Redis 项，由回滚兜底）
"""
from __future__ import annotations

import json
import random
import re
import time
import uuid as uuid_mod
from datetime import datetime
from typing import Any

import structlog

from app.core.redis_client import sync_redis_client
from app.engine.data_generator import generate_rows
from app.engine.redis_pool import get_sync_redis
from app.models import ExecBatchLog

logger = structlog.get_logger(__name__)

BATCH_STATUS_SUCCESS = 1
BATCH_STATUS_FAILED = 2

# Redis 写入目标的批次日志表名前缀（断点重试据此跳过 Redis 项）
REDIS_LOG_PREFIX = "redis:"

_TOKEN_RE = re.compile(r"\{([^{}]+)\}")

# 模板 {incr} 计数器 Key（系统 Redis，按任务隔离，24h 过期）
_INCR_KEY = "df:tplincr:{task_id}:{seq}"
_INCR_TTL = 24 * 3600


def is_redis_log_table(table_name: str) -> bool:
    """批次日志表名是否为 Redis 写入目标"""
    return table_name.startswith(REDIS_LOG_PREFIX)


# ── 模板渲染 ──────────────────────────────────────────────────


def _template_has_incr(template: str) -> bool:
    return any(t.strip().startswith("incr") for t in _TOKEN_RE.findall(template or ""))


def _reserve_incr_base(task_id: int, template: str, count: int) -> int:
    """为模板中的 {incr} 占位符预取本批连续区间，返回区间首值（跨批次递增不重不漏）。

    {incr} 默认从 1 开始；{incr:起始值} 指定起始。计数器存系统 Redis（NX 初始化，
    重试同任务时延续进度），任务结束由 24h TTL 自动清理。
    """
    start = 1
    for token in _TOKEN_RE.findall(template):
        token = token.strip()
        if token.startswith("incr"):
            _, _, arg = token.partition(":")
            if arg:
                try:
                    start = int(arg)
                except ValueError as exc:
                    raise ValueError(f"模板占位符 {{incr:{arg}}} 起始值必须为整数") from exc
            break
    key = _INCR_KEY.format(task_id=task_id, seq=abs(hash(template)) % 10_000_000)
    sync_redis_client.set(key, str(start - 1), nx=True, ex=_INCR_TTL)
    end = int(sync_redis_client.incrby(key, count))
    return end - count + 1


def render_template(
    template: str,
    *,
    row_fields: dict[str, Any],
    row_index: int,
    incr_base: int | None = None,
    task_no: str | None = None,
) -> str:
    """渲染模板：字段引用 + 内置占位符。

    :param row_fields: 可引用的字段值字典（Redis Case 为 {字段名: 值}，联动为 {表.字段: 值}）
    :param row_index: 行在批次内序号（{i}）
    :param incr_base: {incr} 本批预取区间首值（模板无 incr 时传 None）
    :param task_no: 任务编号（{task_no}）
    """

    def _sub(match: re.Match) -> str:
        token = match.group(1).strip()
        if token.startswith("incr"):
            if incr_base is None:
                raise ValueError("模板使用了 {incr} 但未预取递增区间")
            return str(incr_base + row_index)
        if token == "i":
            return str(row_index)
        if token == "task_no":
            return task_no or ""
        if token == "ts":
            return str(int(time.time()))
        if token == "ts_ms":
            return str(int(time.time() * 1000))
        if token.startswith("uuid"):
            _, _, arg = token.partition(":")
            value = uuid_mod.uuid4().hex
            if arg:
                try:
                    value = value[: int(arg)]
                except ValueError as exc:
                    raise ValueError(f"模板占位符 {{uuid:{arg}}} 长度必须为整数") from exc
            return value
        if token.startswith("rand:"):
            _, _, arg = token.partition(":")
            try:
                length = int(arg)
            except ValueError as exc:
                raise ValueError(f"模板占位符 {{rand:{arg}}} 位数必须为整数") from exc
            if not 1 <= length <= 18:
                raise ValueError("模板占位符 {rand:N} 位数须在 1~18 之间")
            return "".join(random.choices("0123456789", k=length))
        if token in row_fields:
            value = row_fields[token]
            return "" if value is None else str(value)
        raise ValueError(f"模板占位符 {{{token}}} 无法解析（不存在对应字段）")

    return _TOKEN_RE.sub(_sub, template)


def validate_template(template: str, allowed_fields: set[str], *, allow_row_fields: bool) -> None:
    """保存前静态校验模板占位符（字段引用必须在可选字段范围内）。"""
    builtin_prefixes = ("incr", "uuid", "rand:")
    builtin_exact = {"i", "task_no", "ts", "ts_ms"}
    for token in _TOKEN_RE.findall(template or ""):
        token = token.strip()
        if token in builtin_exact or any(token.startswith(p) for p in builtin_prefixes):
            continue
        if allow_row_fields and token in allowed_fields:
            continue
        raise ValueError(f"模板占位符 {{{token}}} 非法：字段不存在或不被支持")


def validate_single_key_template(template: str) -> None:
    """聚合单 Key 模式的 Key 模板校验：仅允许字面量与 {task_no}。

    聚合 Key 必须在任务内跨批次保持稳定——{incr}/{uuid}/{ts}/{字段} 等行级占位符
    每个批次渲染结果不同，会把同一聚合 Key 打散成多个，故禁止。
    """
    for token in _TOKEN_RE.findall(template or ""):
        if token.strip() != "task_no":
            raise ValueError(
                f"聚合单 Key 模式的 Key 模板仅支持 {{task_no}} 占位符，不支持 {{{token.strip()}}}"
            )


# ── Value 组装与写入 ──────────────────────────────────────────


def _json_default(value: Any) -> str:
    """datetime/Decimal 等非 JSON 原生类型序列化为字符串"""
    return str(value)


def _build_value(
    data_type: str,
    fields: dict[str, Any],
    *,
    short_names: bool,
    value_template: str | None,
    row_index: int,
    incr_base: int | None,
    task_no: str | None,
) -> str:
    """按数据类型组装单行 value（string/json/hash 字段值/list-member 通用）。"""
    if value_template:
        return render_template(
            value_template, row_fields=fields, row_index=row_index,
            incr_base=incr_base, task_no=task_no,
        )
    named = fields
    if short_names:
        # {表.字段} → {字段}（联动场景 value 内不暴露表名前缀）
        named = {k.rsplit(".", 1)[-1]: v for k, v in fields.items()}
    if data_type in ("json", "hash"):
        return json.dumps(named, ensure_ascii=False, default=_json_default)
    # string/list/set/zset 成员：单字段直接取值，多字段拼 JSON
    if len(named) == 1:
        value = next(iter(named.values()))
        return "" if value is None else str(value)
    return json.dumps(named, ensure_ascii=False, default=_json_default)


class _RedisBatchWriter:
    """单批次 Redis 写入器：收集命令 → pipeline(transaction=True) 原子执行。

    返回 (写入条数, 回滚 payload)。回滚 payload：
    - per_row：{"mode": "keys", "keys": [...]}（逐 Key DEL）
    - single_key：{"mode": "del_key", "keys": [聚合Key]}（回滚时整体 DEL，去重由回滚方处理）
    """

    def __init__(self, client, *, write_mode: str, data_type: str,
                 ttl_seconds: int, score_field: str | None,
                 key_template: str = "") -> None:
        if write_mode not in ("per_row", "single_key"):
            raise ValueError(f"非法写入模式: {write_mode}（仅支持 per_row/single_key）")
        if data_type not in ("string", "json", "hash", "list", "set", "zset"):
            raise ValueError(f"非法 Redis 数据类型: {data_type}")
        if write_mode == "per_row" and data_type in ("list", "set", "zset"):
            raise ValueError("per_row 模式仅支持 string/json/hash（list/set/zset 请用 single_key 聚合）")
        if write_mode == "single_key":
            validate_single_key_template(key_template)
        self.client = client
        self.write_mode = write_mode
        self.data_type = data_type
        self.ttl_seconds = int(ttl_seconds or 0)
        self.score_field = score_field

    def write_rows(
        self,
        *,
        key_template: str,
        rows_fields: list[dict[str, Any]],
        task_id: int,
        task_no: str | None,
        value_template: str | None = None,
        short_names: bool = True,
    ) -> tuple[int, dict]:
        if not rows_fields:
            return 0, {"mode": "keys", "keys": []}
        incr_base = None
        if _template_has_incr(key_template) or (value_template and _template_has_incr(value_template)):
            incr_base = _reserve_incr_base(task_id, f"{key_template}‖{value_template or ''}", len(rows_fields))

        pipe = self.client.pipeline(transaction=True)
        written_keys: list[str] = []
        written = 0

        if self.write_mode == "single_key":
            # 聚合 Key 跨批次稳定：仅以 {task_no} 渲染（校验期已禁止其他占位符）
            key = render_template(
                key_template, row_fields={}, row_index=0,
                incr_base=None, task_no=task_no,
            )
            members: list[str] = []
            scores: dict[str, float] = {}
            for i, fields in enumerate(rows_fields):
                member = _build_value(
                    self.data_type, fields, short_names=short_names,
                    value_template=value_template, row_index=i,
                    incr_base=incr_base, task_no=task_no,
                )
                members.append(member)
                if self.data_type == "zset":
                    scores[member] = self._score_of(fields, i)
            if self.data_type == "list":
                pipe.rpush(key, *members)
            elif self.data_type == "set":
                pipe.sadd(key, *members)
            elif self.data_type == "zset":
                pipe.zadd(key, scores)
            else:
                # string/json 聚合：整体 JSON 数组覆盖写入
                pipe.set(key, json.dumps(members, ensure_ascii=False))
            if self.ttl_seconds > 0:
                pipe.expire(key, self.ttl_seconds)
            written = len(members)
            pipe.execute()
            return written, {"mode": "del_key", "keys": [key]}

        # per_row：每行一个 Key
        for i, fields in enumerate(rows_fields):
            key = render_template(
                key_template, row_fields=fields, row_index=i,
                incr_base=incr_base, task_no=task_no,
            )
            if self.data_type == "hash" and not value_template:
                mapping = {
                    k.rsplit(".", 1)[-1] if short_names else k: ("" if v is None else str(v))
                    for k, v in fields.items()
                }
                pipe.hset(key, mapping=mapping)
                if self.ttl_seconds > 0:
                    pipe.expire(key, self.ttl_seconds)
            else:
                value = _build_value(
                    self.data_type, fields, short_names=short_names,
                    value_template=value_template, row_index=i,
                    incr_base=incr_base, task_no=task_no,
                )
                if self.ttl_seconds > 0:
                    pipe.set(key, value, ex=self.ttl_seconds)
                else:
                    pipe.set(key, value)
            written_keys.append(key)
            written += 1
        pipe.execute()
        return written, {"mode": "keys", "keys": written_keys}

    def _score_of(self, fields: dict[str, Any], row_index: int) -> float:
        """zset 分数：优先 score_field 字段值，否则行序号"""
        if self.score_field:
            raw = fields.get(self.score_field)
            if raw is None:
                raise ValueError(f"zset 分数字段 {self.score_field} 无值")
            try:
                return float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"zset 分数字段 {self.score_field} 的值不是数字: {raw!r}") from exc
        return float(row_index)


# ── MySQL Case Redis 联动（executor 每批成功后调用）────────────


def _row_fields_for_sync(
    sync_cfg: dict, generated: dict[str, list[dict]], row_index: int, main_table: str
) -> dict[str, Any]:
    """按 fields 配置收集单行字段值；fields 为空时取主表全部已生成字段（键为 表.字段）。"""
    spec = sync_cfg.get("fields") or []
    if not spec:
        main_rows = generated.get(main_table) or []
        if row_index >= len(main_rows):
            raise ValueError("主表生成行数不足，无法执行 Redis 联动")
        return {f"{main_table}.{k}": v for k, v in main_rows[row_index].items()}
    out: dict[str, Any] = {}
    for ref in spec:
        if "." not in ref:
            raise ValueError(f"联动字段须为 表.字段 格式: {ref}")
        table, _, column = ref.partition(".")
        rows = generated.get(table)
        if rows is None or row_index >= len(rows):
            raise ValueError(f"联动字段 {ref} 所在表本批未生成数据")
        out[ref] = rows[row_index].get(column)
    return out


def execute_redis_syncs(
    ctx, generated: dict[str, list[dict]], batch_no: int, batch_size: int
) -> list[dict]:
    """执行 MySQL Case 的 Redis 联动同步（工作线程内调用，Redis 客户端线程安全）。

    :param generated: 本批各表已生成行 {表名: [row, ...]}
    :return: 批次日志条目列表（含回滚 payload，由主线程统一落库）
    """
    results: list[dict] = []
    for index, sync_cfg in enumerate(ctx.redis_syncs):
        label = sync_cfg.get("name") or sync_cfg.get("key_template") or f"sync{index}"
        log_table = f"{REDIS_LOG_PREFIX}{label}"[:200]
        start_ts = time.time()
        start_at = datetime.now()
        try:
            client = get_sync_redis(int(sync_cfg["datasource_id"]))
            writer = _RedisBatchWriter(
                client,
                write_mode=sync_cfg.get("write_mode") or "per_row",
                data_type=sync_cfg.get("data_type") or "string",
                ttl_seconds=int(sync_cfg.get("ttl_seconds") or 0),
                score_field=sync_cfg.get("score_field"),
                key_template=sync_cfg.get("key_template") or "",
            )
            rows_fields = [
                _row_fields_for_sync(sync_cfg, generated, i, ctx.main_table)
                for i in range(batch_size)
            ]
            written, payload = writer.write_rows(
                key_template=sync_cfg["key_template"],
                rows_fields=rows_fields,
                task_id=ctx.task_id,
                task_no=ctx.task_no,
                value_template=sync_cfg.get("value_template"),
                short_names=True,
            )
            results.append({
                "table": log_table,
                "status": BATCH_STATUS_SUCCESS,
                "size": written,
                "retry_times": 0,
                "error": None,
                "start_at": start_at,
                "finish_at": datetime.now(),
                "duration_ms": int((time.time() - start_ts) * 1000),
                "rollback": {
                    "target_type": "redis",
                    "datasource_id": int(sync_cfg["datasource_id"]),
                    "payload": payload,
                    "row_count": written,
                },
            })
        except Exception as exc:  # noqa: BLE001 — 联动失败不阻断 MySQL 已落库数据
            logger.warning(
                "redis_sync_failed", task_no=ctx.task_no, batch_no=batch_no,
                sync=label, error=str(exc)[:300],
            )
            results.append({
                "table": log_table,
                "status": BATCH_STATUS_FAILED,
                "size": batch_size,
                "retry_times": 0,
                "error": f"Redis 联动失败: {str(exc)[:400]}",
                "start_at": start_at,
                "finish_at": datetime.now(),
                "duration_ms": int((time.time() - start_ts) * 1000),
                "rollback": None,
            })
    return results


# ── 纯 Redis Case 执行 ────────────────────────────────────────


def execute_redis_case(ctx, session) -> dict:
    """纯 Redis 造数执行（顺序批次 + pipeline 原子写入）。

    复用 executor 的进度/统计体系：ctx.main_table 为 redis:{key模板} 展示名。
    返回 stats 累加器（与 executor._new_stats 结构一致）。
    """
    # 延迟导入避免循环依赖（executor 在调用本函数时已完成模块加载）
    from app.engine.executor import _new_stats, _progress_fail, _progress_success, _record_batch_result

    redis_cfg: dict = ctx.config.get("redis_config") or {}
    row_count = int(ctx.task.target_count or 0)
    if row_count <= 0:
        raise ValueError("造数条数必须为正整数")

    client = get_sync_redis(ctx.task.datasource_id)
    writer = _RedisBatchWriter(
        client,
        write_mode=redis_cfg.get("write_mode") or "per_row",
        data_type=redis_cfg.get("data_type") or "json",
        ttl_seconds=int(redis_cfg.get("ttl_seconds") or 0),
        score_field=redis_cfg.get("score_field"),
        key_template=redis_cfg["key_template"],
    )
    field_configs = redis_cfg.get("field_configs") or []
    key_template = redis_cfg["key_template"]
    value_template = redis_cfg.get("value_template")
    log_table = ctx.main_table  # redis:{key模板}（任务创建时已生成展示名）

    logger.info(
        "redis_case_start", task_no=ctx.task_no, key_template=key_template,
        target_count=row_count, batch_size=ctx.batch_size,
        write_mode=writer.write_mode, data_type=writer.data_type,
    )
    stats = _new_stats()
    offsets = list(range(0, row_count, ctx.batch_size))
    for batch_index, offset in enumerate(offsets):
        size = min(ctx.batch_size, row_count - offset)
        start_ts = time.time()
        start_at = datetime.now()
        try:
            rows, _ = generate_rows(
                table_name=log_table,
                field_configs=field_configs,
                count=size,
                task_id=ctx.task_id,
                redis_client=sync_redis_client,
            )
            rows_fields = [dict(row) for row in rows]
            written, payload = writer.write_rows(
                key_template=key_template,
                rows_fields=rows_fields,
                task_id=ctx.task_id,
                task_no=ctx.task_no,
                value_template=value_template,
                short_names=False,
            )
            table_result = {
                "table": log_table,
                "status": BATCH_STATUS_SUCCESS,
                "size": written,
                "retry_times": 0,
                "error": None,
                "start_at": start_at,
                "finish_at": datetime.now(),
                "duration_ms": int((time.time() - start_ts) * 1000),
            }
            batch_result = {
                "batch_no": batch_index, "size": size, "round_no": None, "drive_value": None,
                "tables": [table_result],
                "rollbacks": [{
                    "target_type": "redis",
                    "datasource_id": ctx.task.datasource_id,
                    "table_name": log_table,
                    "payload": payload,
                    "row_count": written,
                }] if ctx.capture_rollback else [],
            }
        except Exception as exc:  # noqa: BLE001 — 单批失败记录后继续后续批次
            logger.warning("redis_batch_failed", task_no=ctx.task_no, batch_no=batch_index, error=str(exc)[:300])
            batch_result = {
                "batch_no": batch_index, "size": size, "round_no": None, "drive_value": None,
                "tables": [{
                    "table": log_table,
                    "status": BATCH_STATUS_FAILED,
                    "size": size,
                    "retry_times": 0,
                    "error": str(exc)[:500],
                    "start_at": start_at,
                    "finish_at": datetime.now(),
                    "duration_ms": int((time.time() - start_ts) * 1000),
                }],
                "rollbacks": [],
            }
        _record_batch_result(ctx, session, batch_result, stats)
        # 失败率超阈值提前停止（与 MySQL 路径一致）
        total = stats["success_rows"] + stats["fail_rows"]
        if total > 0 and stats["fail_rows"] / total > ctx.fail_rate_threshold:
            stats["stopped"] = True
            remaining = row_count - (stats["success_rows"] + stats["fail_rows"])
            if remaining > 0:
                stats["fail_rows"] += remaining
                stats["errors"].append(
                    f"失败率超过阈值 {ctx.fail_rate_threshold:.0%}，剩余 {remaining} 行未执行"
                )
            break
    return stats


def cleanup_incr_counters(task_id: int) -> None:
    """任务结束清理模板 {incr} 计数器（设 24h TTL，支撑窗口期内幂等查询）"""
    try:
        for key in sync_redis_client.scan_iter(f"df:tplincr:{task_id}:*"):
            sync_redis_client.expire(key, _INCR_TTL)
    except Exception:  # noqa: BLE001
        logger.warning("tpl_incr_expire_failed", task_id=task_id)
