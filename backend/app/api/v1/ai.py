"""AI 预留接口路由（PRD 第 10 章，前缀 /api/v1/ai）。

与用户 JWT 体系完全独立：X-DataForge-AI-Key 头认证（ai_key_auth 依赖，含状态/过期/限流校验）。
GET  /datasources                                  数据源列表
GET  /datasources/{datasource_id}/tables           表列表
GET  /datasources/{datasource_id}/tables/{table_name}/columns  表字段详情
POST /tasks/execute                                创建并执行造数任务（复用引擎链路）
GET  /tasks/{task_no}/progress                     任务执行进度
GET  /strategies                                   造数策略枚举（含 params_schema 供 AI 理解）
"""

import json
import time

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ai_key_auth
from app.core.redis_client import redis_client
from app.db.session import get_db
from app.models.cache import ColumnCache, IndexCache, TableCache
from app.models.datasource import Datasource
from app.models.task import ExecTask
from app.models.user import AiApiKey
from app.schemas.errors import TABLE_NOT_FOUND, TASK_NOT_FOUND, BizException
from app.schemas.response import ApiResponse
from app.services import engine_service
from app.services.datasource_service import DS_STATUS_KEY, get_datasource_or_404

logger = structlog.get_logger(__name__)

router = APIRouter()

# Redis Key（与 executor 保持一致）
_TASK_PROGRESS_KEY = "df:task:progress:{task_no}"
_TASK_TABLE_PROGRESS_KEY = "df:task:table_progress:{task_no}"

_TASK_STATUS_STR = {
    0: "submitted", 1: "running", 2: "success", 3: "failed",
    4: "running", 5: "partial_success", 6: "aborted",
}


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


# ── 请求/响应模型（AI 接口专用，PRD 10.3）─────────────────────────


class AiFieldConfig(BaseModel):
    """AI 字段策略配置（只需提供关心的字段，其余自动补全）。"""

    column_name: str
    strategy: str = Field(default="DEFAULT", description="策略编码，见 /strategies")
    strategy_params: dict = Field(default_factory=dict)


class AiAssociation(BaseModel):
    """AI 字段关联配置。"""

    source_column: str
    target_table: str
    target_column: str


class AiExecuteRequest(BaseModel):
    """AI 创建并执行造数任务请求（PRD 10.3.4）。"""

    case_name: str = Field(min_length=1, max_length=200)
    datasource_id: int
    target_count: int = Field(gt=0)
    main_table: str = Field(min_length=1, max_length=200)
    field_configs: list[AiFieldConfig] = Field(default_factory=list)
    associations: list[AiAssociation] = Field(default_factory=list)
    save_as_case: bool = Field(default=False, description="是否同时保存为 Case 供复用")


# ── 数据源 / 表结构 ──────────────────────────────────────────────


@router.get("/datasources", summary="获取数据源列表（AI）")
async def list_datasources(
    api_key: AiApiKey = Depends(ai_key_auth),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    result = await db.execute(select(Datasource).order_by(Datasource.id))
    datasources = list(result.scalars().all())
    try:
        status_values = await redis_client.mget(
            [DS_STATUS_KEY.format(ds_id=ds.id) for ds in datasources]
        )
    except Exception:
        status_values = [None] * len(datasources)
    items = [
        {
            "id": ds.id,
            "name": ds.name,
            "group_type": ds.group_type,
            "status": "online" if value == "online" else "offline",
            "table_count": int(ds.table_count or 0),
        }
        for ds, value in zip(datasources, status_values)
    ]
    return ApiResponse(data={"datasources": items})


@router.get("/datasources/{datasource_id}/tables", summary="获取数据源表列表（AI）")
async def list_tables(
    datasource_id: int,
    keyword: str | None = Query(default=None, description="模糊搜索表名/备注"),
    api_key: AiApiKey = Depends(ai_key_auth),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    await get_datasource_or_404(db, datasource_id)
    result = await db.execute(
        select(TableCache).where(TableCache.datasource_id == datasource_id).order_by(TableCache.table_name)
    )
    items = []
    for row in result.scalars().all():
        if keyword and keyword.lower() not in row.table_name.lower() \
                and keyword.lower() not in (row.table_comment or "").lower():
            continue
        items.append({
            "table_name": row.table_name,
            "table_comment": row.table_comment or "",
            "column_count": int(row.column_count or 0),
            "row_count": int(row.table_rows or 0),
            "primary_key_type": row.pk_type or "none",
        })
    return ApiResponse(data={"tables": items})


@router.get(
    "/datasources/{datasource_id}/tables/{table_name}/columns",
    summary="获取表字段详情（AI）",
)
async def get_columns(
    datasource_id: int,
    table_name: str,
    api_key: AiApiKey = Depends(ai_key_auth),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    await get_datasource_or_404(db, datasource_id)
    col_result = await db.execute(
        select(ColumnCache)
        .where(ColumnCache.datasource_id == datasource_id, ColumnCache.table_name == table_name)
        .order_by(ColumnCache.ordinal_position)
    )
    columns = list(col_result.scalars().all())
    if not columns:
        raise BizException(TABLE_NOT_FOUND, f"表 {table_name} 不存在或尚未同步")

    table_result = await db.execute(
        select(TableCache).where(
            TableCache.datasource_id == datasource_id, TableCache.table_name == table_name
        )
    )
    table_row = table_result.scalar_one_or_none()
    idx_result = await db.execute(
        select(IndexCache).where(
            IndexCache.datasource_id == datasource_id, IndexCache.table_name == table_name
        )
    )
    indexes = [
        {
            "index_name": row.index_name,
            "is_unique": bool(row.is_unique),
            "is_primary": bool(row.is_primary),
            "column_names": json.loads(row.column_names or "[]"),
        }
        for row in idx_result.scalars().all()
    ]
    return ApiResponse(data={
        "table_name": table_name,
        "table_comment": (table_row.table_comment or "") if table_row else "",
        "columns": [
            {
                "column_name": col.column_name,
                "column_comment": col.column_comment or "",
                "data_type": col.data_type,
                "column_type": col.column_type,
                "is_nullable": bool(col.is_nullable),
                "is_primary_key": bool(col.is_primary_key),
                "is_unique": bool(col.is_unique),
                "char_max_length": col.char_max_length,
                "column_default": col.column_default,
            }
            for col in columns
        ],
        "indexes": indexes,
    })


# ── 任务执行 / 进度 ──────────────────────────────────────────────


@router.post("/tasks/execute", summary="创建并执行造数任务（AI 核心接口）")
async def execute_task(
    body: AiExecuteRequest,
    request: Request,
    api_key: AiApiKey = Depends(ai_key_auth),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    result = await engine_service.ai_execute_task(
        db,
        case_name=body.case_name,
        datasource_id=body.datasource_id,
        target_count=body.target_count,
        main_table=body.main_table,
        field_configs=[fc.model_dump() for fc in body.field_configs],
        associations=[a.model_dump() for a in body.associations],
        save_as_case=body.save_as_case,
        operator_user_id=api_key.created_by,
        operator_name=f"AI:{api_key.key_name}",
        ip=request.client.host if request.client else None,
    )
    return ApiResponse(data={
        "task_no": result["task_no"],
        "status": "submitted",
        "message": "任务已提交，可通过 task_no 查询进度",
    })


@router.get("/tasks/{task_no}/progress", summary="查询任务执行进度（AI）")
async def get_task_progress(
    task_no: str,
    api_key: AiApiKey = Depends(ai_key_auth),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    result = await db.execute(select(ExecTask).where(ExecTask.task_no == task_no))
    task = result.scalar_one_or_none()
    if task is None:
        raise BizException(TASK_NOT_FOUND)

    # 优先读 Redis 实时进度，miss 回退 df_exec_task 历史数据
    progress: dict = {}
    table_raw: dict = {}
    try:
        progress = {k: _decode(v) for k, v in (await redis_client.hgetall(_TASK_PROGRESS_KEY.format(task_no=task_no))).items()}
        table_raw = {k: _decode(v) for k, v in (await redis_client.hgetall(_TASK_TABLE_PROGRESS_KEY.format(task_no=task_no))).items()}
    except Exception:
        logger.warning("ai_task_progress_redis_failed", task_no=task_no)

    if progress:
        target_total = int(progress.get("target_total") or 0)
        success_total = int(progress.get("success_total") or 0)
        fail_total = int(progress.get("fail_total") or 0)
        status = progress.get("status") or "running"
        start_at = progress.get("start_at")
        elapsed_ms = (int(time.time()) - int(start_at)) * 1000 if start_at else None
        table_details = [
            {
                "table_name": _decode(name),
                "target_count": int(data.get("target") or 0),
                "success_count": int(data.get("success") or 0),
                "status": data.get("status") or "pending",
            }
            for name, raw in table_raw.items()
            for data in [json.loads(_decode(raw))]
        ]
    else:
        target_total = int(task.target_count or 0)
        success_total = int(task.success_count or 0)
        fail_total = int(task.fail_count or 0)
        status = _TASK_STATUS_STR.get(task.status, "failed")
        elapsed_ms = task.duration_ms
        table_details = [{
            "table_name": task.main_table,
            "target_count": int(task.target_count or 0),
            "success_count": success_total,
            "status": "success" if status == "success" else status,
        }]

    remaining = target_total - success_total
    estimated_remaining_ms = None
    if elapsed_ms and success_total > 0 and remaining > 0:
        estimated_remaining_ms = int(remaining / (success_total / elapsed_ms))
    return ApiResponse(data={
        "task_no": task_no,
        "status": status,
        "target_count": target_total,
        "success_count": success_total,
        "fail_count": fail_total,
        "progress_percent": round(success_total / target_total * 100, 1) if target_total > 0 else 0.0,
        "elapsed_ms": elapsed_ms,
        "estimated_remaining_ms": estimated_remaining_ms,
        "table_details": table_details,
    })


# ── 策略枚举（AI 理解用，PRD 10.3.6）──────────────────────────────

# 策略元数据：编码 / 名称 / 适用类型 / 参数 Schema
_STRATEGY_META: list[dict] = [
    {
        "strategy_code": "DEFAULT",
        "name": "默认随机",
        "applicable_types": ["varchar", "char", "text", "int", "bigint", "decimal", "datetime", "date", "tinyint"],
        "params_schema": {},
    },
    {
        "strategy_code": "SKIP",
        "name": "跳过（数据库自动填充）",
        "applicable_types": ["int", "bigint"],
        "params_schema": {},
        "remark": "仅用于 AUTO_INCREMENT 主键，执行时该列不出现在 INSERT 语句中",
    },
    {
        "strategy_code": "RANDOM_FIXED_LEN",
        "name": "随机X位生成",
        "applicable_types": ["varchar", "char", "int", "bigint"],
        "params_schema": {
            "length": {"type": "integer", "min": 1, "description": "生成位数，不超过字段最大长度"},
        },
    },
    {
        "strategy_code": "RANDOM_RANGE_LEN",
        "name": "随机X~Y位生成",
        "applicable_types": ["varchar", "char", "int", "bigint"],
        "params_schema": {
            "min_length": {"type": "integer", "min": 1, "description": "最小位数"},
            "max_length": {"type": "integer", "min": 1, "description": "最大位数，须大于最小位数"},
        },
    },
    {
        "strategy_code": "CUSTOM_VALUE",
        "name": "自定义固定值",
        "applicable_types": ["varchar", "char", "int", "bigint", "decimal", "datetime", "date", "text"],
        "params_schema": {
            "value": {"type": "any", "description": "固定值，须与字段类型兼容；null 表示插入 NULL"},
        },
    },
    {
        "strategy_code": "PICK_FROM_LIST",
        "name": "从列表随机选取",
        "applicable_types": ["varchar", "char", "int", "bigint", "tinyint", "text"],
        "params_schema": {
            "values": {"type": "array", "description": "候选值列表（非空，也支持换行分隔字符串）"},
        },
    },
    {
        "strategy_code": "ITERATE_LIST",
        "name": "按序遍历插入（驱动型）",
        "applicable_types": ["varchar", "char", "int", "bigint"],
        "params_schema": {
            "values": {"type": "array", "description": "遍历值列表（非空）"},
            "rows_per_value": {"type": "integer", "min": 1, "description": "每个值插入条数"},
        },
        "remark": "一个 Case 最多一个字段使用；总条数=列表长度×每值条数",
    },
    {
        "strategy_code": "UUID",
        "name": "随机 UUID",
        "applicable_types": ["varchar", "char"],
        "params_schema": {
            "with_dash": {"type": "boolean", "description": "是否保留连字符，默认 false（32位无连字符）"},
        },
    },
    {
        "strategy_code": "SNOWFLAKE",
        "name": "雪花 ID",
        "applicable_types": ["bigint", "int", "varchar", "char"],
        "params_schema": {},
        "remark": "适合 bigint 主键，全局唯一递增",
    },
    {
        "strategy_code": "INCR_FROM",
        "name": "指定值自增",
        "applicable_types": ["int", "bigint"],
        "params_schema": {
            "start": {"type": "integer", "min": 1, "description": "起始值（正整数）"},
        },
        "remark": "多线程通过 Redis 原子计数器保证唯一",
    },
    {
        "strategy_code": "NOW",
        "name": "当前时间",
        "applicable_types": ["datetime", "timestamp", "date"],
        "params_schema": {},
    },
    {
        "strategy_code": "RANDOM_TIME_RANGE",
        "name": "随机时间段",
        "applicable_types": ["datetime", "timestamp", "date"],
        "params_schema": {
            "start_time": {"type": "string", "description": "起始时间 yyyy-MM-dd HH:mm:ss（date 用 yyyy-MM-dd）"},
            "end_time": {"type": "string", "description": "结束时间，须晚于起始时间"},
        },
    },
    {
        "strategy_code": "FIXED_TIME",
        "name": "固定时间",
        "applicable_types": ["datetime", "timestamp", "date"],
        "params_schema": {
            "time": {"type": "string", "description": "固定时间 yyyy-MM-dd HH:mm:ss（date 用 yyyy-MM-dd）"},
        },
    },
]


@router.get("/strategies", summary="获取造数策略枚举（AI 理解用）")
async def get_strategies(
    api_key: AiApiKey = Depends(ai_key_auth),
) -> ApiResponse[dict]:
    return ApiResponse(data={"strategies": _STRATEGY_META})
