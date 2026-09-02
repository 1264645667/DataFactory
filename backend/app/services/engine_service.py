"""造数引擎业务服务（PRD 第 4 章）。

覆盖：表列表（Redis 优先 + 缓存表回源 + 回写）、表字段详情（含 PRD 4.4.3-A 策略自动推断预填）、
表索引信息、Case 配置校验（1300~1304/1403）、仅保存 Case、创建并执行（ExecTask + Celery 下发）。
"""

import json
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.core.redis_client import redis_client
from app.engine.dep_analyzer import build_insert_order
from app.engine.strategies.pk_strategies import next_snowflake_id
from app.engine.strategies.registry import get_strategy
from app.models.cache import ColumnCache, IndexCache, TableCache
from app.models.case import Case
from app.models.task import ExecTask
from app.models.user import User
from app.schemas.engine import (
    CaseConfig,
    ColumnInfo,
    EngineExecuteRequest,
    EngineExecuteResponse,
    EngineSaveRequest,
    EngineSaveResponse,
    IndexInfo,
    TableItem,
)
from app.schemas.errors import (
    ASSOCIATION_CYCLE,
    CASE_CONFIG_INVALID,
    CASE_NAME_TAKEN,
    CELERY_SUBMIT_FAILED,
    COLUMN_TYPE_INCOMPATIBLE,
    DS_NOT_FOUND,
    DS_NOT_INITIALIZED,
    ITERATE_LIST_DUPLICATE,
    STRATEGY_PARAM_INVALID,
    TABLE_NOT_FOUND,
    TARGET_COUNT_TOO_LARGE,
    BizException,
)
from app.services.datasource_service import get_datasource_checked, get_datasource_or_404
from app.services.notification_service import audit

logger = structlog.get_logger(__name__)

# Redis Key 与 TTL（文档 5.1/5.2）
TABLES_CACHE_KEY = "df:tables:{ds_id}"
COLUMNS_CACHE_KEY = "df:columns:{ds_id}:{table}"
INDEXES_CACHE_KEY = "df:indexes:{ds_id}:{table}"
SCHEMA_CACHE_TTL = 12 * 3600  # 表结构缓存 12h

# 单次造数条数上限（1307，PRD 12.3）
MAX_TARGET_COUNT = 100_000_000

# 类型兼容分组（1301：varchar↔varchar、int↔bigint 等同组兼容）
_INT_TYPES = {"tinyint", "smallint", "mediumint", "int", "integer", "bigint"}
_DECIMAL_TYPES = {"decimal", "numeric", "float", "double", "real"}
_CHAR_TYPES = {"char", "varchar", "tinytext", "text", "mediumtext", "longtext"}
_TIME_TYPES = {"datetime", "timestamp", "date", "time", "year"}


def _type_group(data_type: str) -> str:
    """基础类型 → 兼容分组。"""
    dt = (data_type or "").lower()
    if dt in _INT_TYPES:
        return "int"
    if dt in _DECIMAL_TYPES:
        return "decimal"
    if dt in _CHAR_TYPES:
        return "char"
    if dt in _TIME_TYPES:
        return "time"
    return dt or "unknown"


# ── 策略自动推断（PRD 4.4.3-A，优先级 1~16 依次匹配）────────────────


def infer_strategy(col) -> tuple[str, dict]:
    """根据字段元数据自动推断最合理的造数策略（字段配置页预填）。

    :param col: df_column_cache 行（ORM 对象或具有同名属性的对象）
    :return: (策略编码, 策略参数)
    """
    extra = (col.extra or "").lower()
    name = (col.column_name or "").lower()
    data_type = (col.data_type or "").lower()
    char_len = col.char_max_length

    # 1. 自增主键 → SKIP（DB 自动填充）
    if "auto_increment" in extra:
        return "SKIP", {}
    # 2. 整型主键（非自增）→ 雪花 ID
    if col.is_primary_key and data_type in ("bigint", "int"):
        return "SNOWFLAKE", {}
    # 3. 字符主键 → UUID
    if col.is_primary_key and data_type in ("varchar", "char"):
        return "UUID", {}
    # 4. 数字唯一索引 → 自增
    if col.is_unique and data_type in ("int", "bigint"):
        return "INCR_FROM", {"start": 1}
    # 5. 字符唯一索引 → UUID
    if col.is_unique and data_type in ("varchar", "char"):
        return "UUID", {}
    # 6/7. 创建/更新时间字段 → NOW
    if name in ("created_at", "create_time", "created_time", "updated_at", "update_time", "updated_time"):
        return "NOW", {}
    # 8. 逻辑删除时间 → NULL
    if name in ("deleted_at", "delete_time"):
        return "CUSTOM_VALUE", {"value": None}
    # 9. 逻辑删除标记 → 0
    if name in ("is_deleted", "is_del", "del_flag"):
        return "CUSTOM_VALUE", {"value": 0}
    # 10. 手机号字段 → 随机 11 位
    if any(k in name for k in ("phone", "mobile", "tel")) and char_len in (11, 13):
        return "RANDOM_FIXED_LEN", {"length": 11}
    # 11. 身份证字段 → 随机 18 位
    if any(k in name for k in ("id_card", "identity", "id_no")) and char_len == 18:
        return "RANDOM_FIXED_LEN", {"length": 18}
    # 12. 枚举状态字段 → 从列表选取（预填 0/1）
    if any(k in name for k in ("status", "state", "type", "flag")) and data_type == "tinyint":
        return "PICK_FROM_LIST", {"values": [0, 1]}
    # 13/14. 时间/日期字段 → NOW
    if data_type in ("datetime", "timestamp", "date"):
        return "NOW", {}
    # 15. 有默认值 → 使用默认值（表达式默认值不字面注入）
    if col.column_default is not None:
        default_value = str(col.column_default)
        if "(" in default_value or ")" in default_value:
            if data_type in ("datetime", "timestamp", "date"):
                return "NOW", {}
            return "DEFAULT", {}
        return "CUSTOM_VALUE", {"value": default_value}
    # 16. 兜底 → DEFAULT 随机
    return "DEFAULT", {}


# ── 表结构查询（Redis 优先 → 缓存表回源 → 回写 Redis）─────────────────


async def _get_table_cache_rows(db: AsyncSession, datasource_id: int) -> list[TableCache]:
    result = await db.execute(
        select(TableCache).where(TableCache.datasource_id == datasource_id).order_by(TableCache.table_name)
    )
    return list(result.scalars().all())


async def list_tables(
    db: AsyncSession,
    *,
    current_user: User,
    datasource_id: int,
    keyword: str | None = None,
    sort: str | None = None,
) -> list[TableItem]:
    """表列表（PRD 4.3.1）：先查 Redis df:tables:{ds} → miss 查 df_table_cache → 回写。

    :param keyword: 模糊匹配表名/备注
    :param sort: name=字母序 rows=数据量 columns=字段数
    """
    ds = await get_datasource_checked(db, current_user, datasource_id)

    payload: list[dict] | None = None
    try:
        raw = await redis_client.get(TABLES_CACHE_KEY.format(ds_id=datasource_id))
        if raw:
            payload = json.loads(raw)
    except Exception:
        logger.warning("tables_cache_read_failed", datasource_id=datasource_id)

    if payload is None:
        # Redis miss：回源 df_table_cache
        rows = await _get_table_cache_rows(db, datasource_id)
        if not rows:
            if ds.status in (0, 3):
                # 未初始化 / 同步中
                raise BizException(DS_NOT_INITIALIZED)
            return []
        payload = [
            {
                "table_name": row.table_name,
                "table_comment": row.table_comment or "",
                "table_rows": int(row.table_rows or 0),
                "column_count": int(row.column_count or 0),
                "pk_type": row.pk_type or "none",
                "unique_index_count": int(row.unique_index_count or 0),
                "synced_at": row.synced_at.strftime("%Y-%m-%d %H:%M:%S") if row.synced_at else None,
            }
            for row in rows
        ]
        # 回写 Redis（失败不影响返回）
        try:
            await redis_client.set(
                TABLES_CACHE_KEY.format(ds_id=datasource_id),
                json.dumps(payload, ensure_ascii=False),
                ex=SCHEMA_CACHE_TTL,
            )
        except Exception:
            logger.warning("tables_cache_write_failed", datasource_id=datasource_id)

    items = [
        TableItem(
            table_name=item["table_name"],
            table_comment=item.get("table_comment") or None,
            table_rows=item.get("table_rows") or 0,
            column_count=item.get("column_count") or 0,
            pk_type=item.get("pk_type") or "none",
            unique_index_count=item.get("unique_index_count") or 0,
            synced_at=(
                datetime.strptime(item["synced_at"], "%Y-%m-%d %H:%M:%S")
                if item.get("synced_at")
                else None
            ),
        )
        for item in payload
    ]

    # 关键字过滤（表名/备注）
    if keyword:
        kw = keyword.lower()
        items = [
            item for item in items
            if kw in item.table_name.lower() or kw in (item.table_comment or "").lower()
        ]
    # 排序（默认字母序）
    if sort == "rows":
        items.sort(key=lambda x: (x.table_rows or 0), reverse=True)
    elif sort == "columns":
        items.sort(key=lambda x: (x.column_count or 0), reverse=True)
    else:
        items.sort(key=lambda x: x.table_name)
    return items


async def get_table_columns(
    db: AsyncSession, *, current_user: User, datasource_id: int, table_name: str
) -> list[ColumnInfo]:
    """表字段详情（PRD 4.4）：Redis 优先，附加 PRD 4.4.3-A 自动推断策略预填。"""
    ds = await get_datasource_checked(db, current_user, datasource_id)

    payload: list[dict] | None = None
    try:
        raw = await redis_client.get(COLUMNS_CACHE_KEY.format(ds_id=datasource_id, table=table_name))
        if raw:
            payload = json.loads(raw)
    except Exception:
        logger.warning("columns_cache_read_failed", datasource_id=datasource_id, table=table_name)

    if payload is None:
        result = await db.execute(
            select(ColumnCache)
            .where(ColumnCache.datasource_id == datasource_id, ColumnCache.table_name == table_name)
            .order_by(ColumnCache.ordinal_position)
        )
        rows = list(result.scalars().all())
        if not rows:
            if ds.status in (0, 3):
                raise BizException(DS_NOT_INITIALIZED)
            raise BizException(TABLE_NOT_FOUND)
        payload = [
            {
                "column_name": row.column_name,
                "column_comment": row.column_comment or "",
                "data_type": row.data_type,
                "column_type": row.column_type,
                "is_nullable": int(row.is_nullable),
                "is_primary_key": int(row.is_primary_key),
                "is_unique": int(row.is_unique),
                "column_default": row.column_default,
                "char_max_length": row.char_max_length,
                "numeric_precision": row.numeric_precision,
                "numeric_scale": row.numeric_scale,
                "ordinal_position": row.ordinal_position,
                "extra": row.extra or "",
            }
            for row in rows
        ]
        try:
            await redis_client.set(
                COLUMNS_CACHE_KEY.format(ds_id=datasource_id, table=table_name),
                json.dumps(payload, ensure_ascii=False),
                ex=SCHEMA_CACHE_TTL,
            )
        except Exception:
            logger.warning("columns_cache_write_failed", datasource_id=datasource_id)

    class _Col:
        """轻量字段元数据对象（供 infer_strategy 使用）。"""

        def __init__(self, data: dict) -> None:
            self.column_name = data["column_name"]
            self.data_type = data["data_type"]
            self.column_type = data["column_type"]
            self.is_primary_key = data["is_primary_key"]
            self.is_unique = data["is_unique"]
            self.column_default = data["column_default"]
            self.char_max_length = data["char_max_length"]
            self.extra = data.get("extra") or ""

    items: list[ColumnInfo] = []
    for data in payload:
        strategy, params = infer_strategy(_Col(data))
        items.append(
            ColumnInfo(
                column_name=data["column_name"],
                column_comment=data.get("column_comment") or None,
                data_type=data["data_type"],
                column_type=data["column_type"],
                is_nullable=data["is_nullable"],
                is_primary_key=data["is_primary_key"],
                is_unique=data["is_unique"],
                column_default=data.get("column_default"),
                char_max_length=data.get("char_max_length"),
                numeric_precision=data.get("numeric_precision"),
                numeric_scale=data.get("numeric_scale"),
                ordinal_position=data["ordinal_position"],
                extra=data.get("extra") or None,
                suggested_strategy=strategy,
                suggested_params=params,
            )
        )
    return items


async def get_table_indexes(
    db: AsyncSession, *, current_user: User, datasource_id: int, table_name: str
) -> list[IndexInfo]:
    """表索引信息（PRD 4.4.1 索引展示区）。"""
    await get_datasource_checked(db, current_user, datasource_id)

    payload: list[dict] | None = None
    try:
        raw = await redis_client.get(INDEXES_CACHE_KEY.format(ds_id=datasource_id, table=table_name))
        if raw:
            payload = json.loads(raw)
    except Exception:
        logger.warning("indexes_cache_read_failed", datasource_id=datasource_id, table=table_name)

    if payload is None:
        result = await db.execute(
            select(IndexCache)
            .where(IndexCache.datasource_id == datasource_id, IndexCache.table_name == table_name)
        )
        rows = list(result.scalars().all())
        if not rows:
            raise BizException(TABLE_NOT_FOUND)
        payload = [
            {
                "index_name": row.index_name,
                "is_unique": int(row.is_unique),
                "is_primary": int(row.is_primary),
                "column_names": json.loads(row.column_names or "[]"),
            }
            for row in rows
        ]
        try:
            await redis_client.set(
                INDEXES_CACHE_KEY.format(ds_id=datasource_id, table=table_name),
                json.dumps(payload, ensure_ascii=False),
                ex=SCHEMA_CACHE_TTL,
            )
        except Exception:
            logger.warning("indexes_cache_write_failed", datasource_id=datasource_id)

    return [
        IndexInfo(
            index_name=item["index_name"],
            is_unique=item["is_unique"],
            is_primary=item["is_primary"],
            column_names=item.get("column_names") or [],
        )
        for item in payload
    ]


# ── Case 配置校验（PRD 4.4.5 / 4.4.6）────────────────────────────


async def _get_column_type_map(db: AsyncSession, datasource_id: int, table_name: str) -> dict[str, str]:
    """取表字段名 → 基础类型映射（不存在返回空 dict）。"""
    result = await db.execute(
        select(ColumnCache.column_name, ColumnCache.data_type).where(
            ColumnCache.datasource_id == datasource_id, ColumnCache.table_name == table_name
        )
    )
    return {name: (dt or "") for name, dt in result.all()}


async def validate_case_config(db: AsyncSession, datasource_id: int, config: CaseConfig) -> None:
    """Case 配置完整校验（保存/执行前调用）。

    校验项：主表存在（1300）→ ITERATE_LIST 全校唯一（1303）→ 策略参数（1304）→
    关联目标表存在（1300）→ 类型兼容（1301）→ 循环关联（1302）→ 关联源字段合法（1403）。
    """
    # 1. 主表必须已同步
    main_columns = await _get_column_type_map(db, datasource_id, config.main_table)
    if not main_columns:
        raise BizException(TABLE_NOT_FOUND, f"目标表 {config.main_table} 不存在或尚未同步")

    field_configs = config.field_configs or []
    if not field_configs:
        raise BizException(CASE_CONFIG_INVALID, "字段配置不能为空")

    # 2. ITERATE_LIST 全校唯一校验（1303）+ 参数校验（1304）
    iterate_fields = [
        fc for fc in field_configs if (fc.strategy or "").upper() == "ITERATE_LIST"
    ]
    if len(iterate_fields) > 1:
        raise BizException(ITERATE_LIST_DUPLICATE)

    # 3. 策略合法性 + 策略参数校验（SKIP 不注册策略，执行期由引擎处理）
    def _validate_field_strategy(fc, table: str) -> None:
        strategy_code = (fc.strategy or "DEFAULT").upper()
        if strategy_code == "SKIP":
            return
        try:
            strategy = get_strategy(strategy_code)
        except ValueError as e:
            raise BizException(STRATEGY_PARAM_INVALID, f"字段 {table}.{fc.column_name}：{e}") from e
        try:
            strategy.validate(fc.model_dump(), dict(fc.strategy_params or {}))
        except ValueError as e:
            raise BizException(STRATEGY_PARAM_INVALID, f"字段 {table}.{fc.column_name}：{e}") from e

    for fc in field_configs:
        _validate_field_strategy(fc, config.main_table)

    # 4. 关联配置校验（支持多级：源表可以是主表或任一已关联的表，形成 A→B→C 链式）
    associations = config.associations or []
    # 表字段类型缓存（source/target 共用）
    column_type_cache: dict[str, dict[str, str]] = {}
    configured_columns = {fc.column_name for fc in field_configs}
    skip_columns = {
        fc.column_name for fc in field_configs if (fc.strategy or "").upper() == "SKIP"
    }
    # 造数范围内的表：主表 + 所有关联目标表（多级关联的源表必须在此范围内，否则其数据不会生成）
    scope_tables = {config.main_table}
    for assoc in associations:
        scope_tables.add(assoc.target_table)

    async def _columns_of(table: str) -> dict[str, str]:
        if table not in column_type_cache:
            column_type_cache[table] = await _get_column_type_map(db, datasource_id, table)
        return column_type_cache[table]

    for assoc in associations:
        target_table = assoc.target_table
        source_table = assoc.source_table or config.main_table  # 源表缺省为主表（兼容一级关联）

        # 表内自关联禁止
        if source_table == target_table:
            raise BizException(CASE_CONFIG_INVALID, f"不允许表内自关联：{source_table}")
        # 源表必须已纳入造数范围（主表或某个关联目标表），否则没有数据可供关联
        if source_table not in scope_tables:
            raise BizException(
                CASE_CONFIG_INVALID,
                f"关联源表 {source_table} 未纳入本 Case 造数范围（须为主表或某个关联目标表）",
            )

        # 目标表/目标字段存在性
        target_columns = await _columns_of(target_table)
        if not target_columns:
            raise BizException(TABLE_NOT_FOUND, f"关联目标表 {target_table} 不存在或尚未同步")
        if assoc.target_column not in target_columns:
            raise BizException(
                CASE_CONFIG_INVALID, f"关联目标字段不存在：{target_table}.{assoc.target_column}"
            )

        # 源字段存在性 + 自增/SKIP 校验
        if source_table == config.main_table:
            # 主表：必须已配置策略且非 SKIP（自增主键不可作为关联源）
            source_type = main_columns.get(assoc.source_column)
            if assoc.source_column not in configured_columns and source_type is None:
                raise BizException(
                    CASE_CONFIG_INVALID, f"关联源字段不存在：{source_table}.{assoc.source_column}"
                )
            if assoc.source_column in skip_columns:
                raise BizException(
                    CASE_CONFIG_INVALID, f"自增主键字段不能作为关联源：{source_table}.{assoc.source_column}"
                )
        else:
            # 关联表作为源（多级）：字段须存在于该表（自增/SKIP 由执行器按推断策略兜底校验）
            source_columns = await _columns_of(source_table)
            source_type = source_columns.get(assoc.source_column)
            if source_type is None:
                raise BizException(
                    CASE_CONFIG_INVALID, f"关联源字段不存在：{source_table}.{assoc.source_column}"
                )

        # 类型兼容校验（1301）
        if source_type is not None:
            if _type_group(source_type) != _type_group(target_columns[assoc.target_column]):
                raise BizException(
                    COLUMN_TYPE_INCOMPATIBLE,
                    f"字段类型不兼容，无法关联：{source_table}.{assoc.source_column}({source_type})"
                    f" → {target_table}.{assoc.target_column}({target_columns[assoc.target_column]})",
                )

    # 5. 循环关联校验（1302，Kahn 拓扑排序）
    try:
        build_insert_order(config.main_table, [a.model_dump() for a in associations])
    except ValueError as e:
        raise BizException(ASSOCIATION_CYCLE, str(e)) from e

    # 6. 关联表字段策略覆盖（related_field_configs）校验
    related_overrides = config.related_field_configs or {}
    for table, related_configs in related_overrides.items():
        # 覆盖的表必须已纳入造数范围（关联目标表），否则配置无意义
        if table not in scope_tables or table == config.main_table:
            raise BizException(
                CASE_CONFIG_INVALID,
                f"关联表字段配置的表 {table} 未纳入本 Case 造数范围（须为某个关联目标表）",
            )
        for fc in related_configs:
            # 遍历驱动只能是主表字段（驱动全 Case 行数），关联表禁止 ITERATE_LIST
            if (fc.strategy or "").upper() == "ITERATE_LIST":
                raise BizException(
                    CASE_CONFIG_INVALID,
                    f"关联表字段不支持按序遍历插入策略：{table}.{fc.column_name}",
                )
            _validate_field_strategy(fc, table)


# ── Case 保存与执行 ──────────────────────────────────────────────


def _build_case_related(config: CaseConfig) -> tuple[str, int]:
    """从关联配置提取关联表 JSON 数组与数量（保持声明顺序去重）。"""
    tables: list[str] = []
    for assoc in config.associations or []:
        if assoc.target_table not in tables:
            tables.append(assoc.target_table)
    return json.dumps(tables, ensure_ascii=False), len(tables)


async def _check_case_name_unique(
    db: AsyncSession, datasource_id: int, case_name: str, exclude_id: int | None = None
) -> None:
    """同一数据源下 Case 名称唯一（1401）。"""
    stmt = select(Case.id).where(
        Case.datasource_id == datasource_id, Case.case_name == case_name, Case.is_deleted == 0
    )
    if exclude_id is not None:
        stmt = stmt.where(Case.id != exclude_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise BizException(CASE_NAME_TAKEN)


async def save_case(
    db: AsyncSession, *, current_user: User, req: EngineSaveRequest, ip: str | None
) -> EngineSaveResponse:
    """仅保存 Case，不执行（POST /engine/save）。"""
    ds = await get_datasource_checked(db, current_user, req.datasource_id)
    await validate_case_config(db, req.datasource_id, req.config)
    await _check_case_name_unique(db, req.datasource_id, req.case_name)

    related_tables, related_count = _build_case_related(req.config)
    case = Case(
        case_name=req.case_name,
        datasource_id=ds.id,
        datasource_name=ds.name,
        main_table=req.config.main_table,
        related_tables=related_tables,
        related_count=related_count,
        config_json=req.config.model_dump_json(),
        group_type=current_user.group_type,
        is_deleted=0,
        exec_count=0,
        created_by=current_user.id,
    )
    db.add(case)
    await db.flush()
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="CREATE_CASE",
        resource="case", resource_id=case.id,
        detail=f"Case「{req.case_name}」主表 {req.config.main_table}", ip=ip,
    )
    await db.commit()
    logger.info("case_saved", case_id=case.id, case_name=req.case_name, operator=current_user.username)
    return EngineSaveResponse(case_id=case.id, case_name=case.case_name)


def create_exec_task(
    db: AsyncSession, *, case: Case, target_count: int, current_user: User,
    snapshot: str | None = None,
) -> ExecTask:
    """创建造数执行任务（仅 add + flush，事务与 Celery 提交由调用方处理）。

    :param snapshot: 执行快照（默认取 Case 当前 config_json）
    """
    exec_task = ExecTask(
        task_no=f"TK{next_snowflake_id()}",  # TK + 雪花 ID（时间戳+机器位+序列，全局唯一）
        case_id=case.id,
        case_name=case.case_name,
        case_snapshot=snapshot if snapshot is not None else case.config_json,
        datasource_id=case.datasource_id,
        datasource_name=case.datasource_name,
        main_table=case.main_table,
        related_tables=case.related_tables,
        target_count=target_count,
        success_count=0,
        fail_count=0,
        retry_count=0,
        status=0,  # 待执行
        group_type=case.group_type,
        created_by=current_user.id,
        created_at=datetime.now(),
    )
    db.add(exec_task)
    return exec_task


def submit_exec_task(exec_task: ExecTask) -> None:
    """下发 Celery 任务 tasks.execute_data_gen（失败抛 9003）。"""
    try:
        celery_app.send_task("tasks.execute_data_gen", args=[exec_task.id])
    except Exception as e:
        logger.error("celery_submit_failed", task="tasks.execute_data_gen", task_no=exec_task.task_no)
        raise BizException(CELERY_SUBMIT_FAILED) from e


async def execute_case_config(
    db: AsyncSession, *, current_user: User, req: EngineExecuteRequest, ip: str | None
) -> EngineExecuteResponse:
    """创建 Case 并立即执行（POST /engine/execute）。

    流程：条数上限（1307）→ 配置校验 → 保存 Case → 创建 ExecTask → 下发 Celery → 审计。
    执行参数覆盖（batch_size/max_workers 等）写入快照 exec_params 供执行器后续版本使用。
    """
    if req.target_count > MAX_TARGET_COUNT:
        raise BizException(
            TARGET_COUNT_TOO_LARGE, f"目标造数量超过单次限制（最大 {MAX_TARGET_COUNT} 条）"
        )
    ds = await get_datasource_checked(db, current_user, req.datasource_id)
    await validate_case_config(db, req.datasource_id, req.config)
    await _check_case_name_unique(db, req.datasource_id, req.case_name)

    related_tables, related_count = _build_case_related(req.config)
    case = Case(
        case_name=req.case_name,
        datasource_id=ds.id,
        datasource_name=ds.name,
        main_table=req.config.main_table,
        related_tables=related_tables,
        related_count=related_count,
        config_json=req.config.model_dump_json(),
        group_type=current_user.group_type,
        is_deleted=0,
        exec_count=0,
        created_by=current_user.id,
    )
    db.add(case)
    await db.flush()

    # 执行参数覆盖写入快照（引擎当前版本读取 settings，预留字段供后续版本生效）
    snapshot_dict = req.config.model_dump()
    exec_params = {
        "batch_size": req.batch_size,
        "max_workers": req.max_workers,
        "disable_unique_checks": req.disable_unique_checks,
        "disable_fk_checks": req.disable_fk_checks,
    }
    if any(v is not None and v is not False for v in exec_params.values()):
        snapshot_dict["exec_params"] = {k: v for k, v in exec_params.items() if v is not None}

    exec_task = create_exec_task(
        db, case=case, target_count=req.target_count, current_user=current_user,
        snapshot=json.dumps(snapshot_dict, ensure_ascii=False),
    )
    await db.flush()
    submit_exec_task(exec_task)

    await audit(
        db, user_id=current_user.id, username=current_user.username, action="EXEC_CASE",
        resource="case", resource_id=case.id,
        detail=f"Case「{case.case_name}」执行 {req.target_count} 条，任务 {exec_task.task_no}",
        ip=ip,
    )
    await db.commit()
    logger.info(
        "engine_execute_submitted",
        case_id=case.id, task_no=exec_task.task_no,
        target_count=req.target_count, operator=current_user.username,
    )
    return EngineExecuteResponse(case_id=case.id, task_no=exec_task.task_no)


# ── AI 接口复用链路（PRD 10.3.4）──────────────────────────────────


async def ai_execute_task(
    db: AsyncSession,
    *,
    case_name: str,
    datasource_id: int,
    target_count: int,
    main_table: str,
    field_configs: list[dict],
    associations: list[dict],
    save_as_case: bool,
    operator_user_id: int,
    operator_name: str,
    ip: str | None = None,
) -> dict:
    """AI 创建并执行造数任务（复用引擎执行链路）。

    字段配置自动补全：AI 只需提供关心的字段策略，未提供的字段按
    PRD 4.4.3-A 推断策略自动补全（元数据取自 df_column_cache）。
    save_as_case=False 时不落 Case 记录（df_exec_task.case_id 记 0）。

    :return: {"task_no": ..., "case_id": ...}
    """
    if target_count > MAX_TARGET_COUNT:
        raise BizException(
            TARGET_COUNT_TOO_LARGE, f"目标造数量超过单次限制（最大 {MAX_TARGET_COUNT} 条）"
        )
    ds = await get_datasource_or_404(db, datasource_id)

    # 1. 主表元数据
    result = await db.execute(
        select(ColumnCache)
        .where(ColumnCache.datasource_id == datasource_id, ColumnCache.table_name == main_table)
        .order_by(ColumnCache.ordinal_position)
    )
    columns = list(result.scalars().all())
    if not columns:
        raise BizException(TABLE_NOT_FOUND, f"目标表 {main_table} 不存在或尚未同步")
    column_map = {col.column_name: col for col in columns}

    # 2. 合并 AI 字段配置 + 自动补全其余字段（推断策略）
    provided: dict[str, dict] = {fc["column_name"]: fc for fc in field_configs or []}
    merged_field_configs: list[dict] = []
    for col in columns:
        if col.column_name in provided:
            fc = provided[col.column_name]
            merged_field_configs.append({
                "column_name": col.column_name,
                "data_type": col.data_type,
                "column_type": col.column_type,
                "is_nullable": bool(col.is_nullable),
                "is_primary_key": bool(col.is_primary_key),
                "strategy": (fc.get("strategy") or "DEFAULT").upper(),
                "strategy_params": dict(fc.get("strategy_params") or {}),
            })
        else:
            strategy, params = infer_strategy(col)
            merged_field_configs.append({
                "column_name": col.column_name,
                "data_type": col.data_type,
                "column_type": col.column_type,
                "is_nullable": bool(col.is_nullable),
                "is_primary_key": bool(col.is_primary_key),
                "strategy": strategy,
                "strategy_params": params,
            })
    # AI 提供了主表不存在的字段 → 配置不合法
    unknown = [name for name in provided if name not in column_map]
    if unknown:
        raise BizException(
            CASE_CONFIG_INVALID, f"字段在主表 {main_table} 中不存在：{','.join(unknown)}"
        )

    config = CaseConfig(
        main_table=main_table,
        field_configs=merged_field_configs,
        associations=[dict(a) for a in associations or []],
    )
    await validate_case_config(db, datasource_id, config)
    config_json = config.model_dump_json()

    # 3. 按需保存 Case
    if save_as_case:
        await _check_case_name_unique(db, datasource_id, case_name)
        related_tables, related_count = _build_case_related(config)
        case = Case(
            case_name=case_name,
            datasource_id=ds.id,
            datasource_name=ds.name,
            main_table=main_table,
            related_tables=related_tables,
            related_count=related_count,
            config_json=config_json,
            group_type=ds.group_type,
            is_deleted=0,
            exec_count=0,
            created_by=operator_user_id,
        )
        db.add(case)
        await db.flush()
        case_id = case.id
        case_group = case.group_type
    else:
        case_id = 0  # 不落 Case 记录（执行器对 case_id 无对应记录时自动跳过 Case 回写）
        case_group = ds.group_type

    # 4. 创建执行任务并下发
    related_tables_json, _ = _build_case_related(config)
    exec_task = ExecTask(
        task_no=f"TK{next_snowflake_id()}",
        case_id=case_id,
        case_name=case_name,
        case_snapshot=config_json,
        datasource_id=ds.id,
        datasource_name=ds.name,
        main_table=main_table,
        related_tables=related_tables_json,
        target_count=target_count,
        success_count=0,
        fail_count=0,
        retry_count=0,
        status=0,
        group_type=case_group,
        created_by=operator_user_id,
        created_at=datetime.now(),
    )
    db.add(exec_task)
    await db.flush()
    submit_exec_task(exec_task)

    await audit(
        db, user_id=operator_user_id, username=operator_name, action="AI_EXEC_TASK",
        resource="datasource", resource_id=ds.id,
        detail=f"AI 创建任务 {exec_task.task_no}：{main_table} {target_count} 条"
        f"（save_as_case={save_as_case}）",
        ip=ip,
    )
    await db.commit()
    logger.info(
        "ai_task_submitted", task_no=exec_task.task_no, datasource_id=datasource_id,
        main_table=main_table, target_count=target_count, operator=operator_name,
    )
    return {"task_no": exec_task.task_no, "case_id": case_id}
