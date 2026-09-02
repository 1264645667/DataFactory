"""造数总览模块路由

GET /metrics       核心指标卡片数据（Redis 缓存 5min）
GET /trend         执行趋势折线图（近 7/30/90 天）
GET /status-dist   执行状态分布饼图
GET /table-top10   表操作量 Top10 柱状图
GET /member-rank   成员贡献排行
GET /exec-records  执行记录明细表（分页 + 筛选）
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PageParams, require_permission, to_local_naive
from app.db.session import get_db
from app.models.user import User
from app.schemas.errors import PARAM_INVALID, BizException
from app.schemas.overview import (
    ExecRecordItem,
    MemberRankItem,
    OverviewMetrics,
    StatusDistResponse,
    TableTopItem,
    TrendResponse,
)
from app.schemas.response import ApiResponse, PageData
from app.services import overview_service

_VALID_DAYS = {7, 30, 90}


def _parse_days(days: int) -> int:
    """校验 days 参数，仅允许 7/30/90。"""
    if days not in _VALID_DAYS:
        raise BizException(PARAM_INVALID, f"days 必须是 {', '.join(map(str, sorted(_VALID_DAYS)))} 之一")
    return days

router = APIRouter()


@router.get("/metrics", summary="核心指标卡片数据")
async def get_metrics(
    current_user: User = Depends(require_permission("OVERVIEW:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[OverviewMetrics]:
    data = await overview_service.get_metrics(db, current_user=current_user)
    return ApiResponse(data=data)


@router.get("/trend", summary="执行趋势折线图数据")
async def get_trend(
    days: int = Query(default=30, description="查看范围：近 7/30/90 天"),
    current_user: User = Depends(require_permission("OVERVIEW:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TrendResponse]:
    days = _parse_days(days)
    data = await overview_service.get_trend(db, current_user=current_user, days=days)
    return ApiResponse(data=data)


@router.get("/status-dist", summary="执行状态分布饼图数据")
async def get_status_dist(
    days: int = Query(default=30),
    current_user: User = Depends(require_permission("OVERVIEW:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StatusDistResponse]:
    days = _parse_days(days)
    data = await overview_service.get_status_dist(db, current_user=current_user, days=days)
    return ApiResponse(data=data)


@router.get("/table-top10", summary="表操作量 Top10 柱状图数据")
async def get_table_top10(
    days: int = Query(default=30),
    current_user: User = Depends(require_permission("OVERVIEW:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[TableTopItem]]:
    days = _parse_days(days)
    items = await overview_service.get_table_top10(db, current_user=current_user, days=days)
    return ApiResponse(data=items)


@router.get("/member-rank", summary="成员贡献排行数据")
async def get_member_rank(
    days: int = Query(default=30),
    current_user: User = Depends(require_permission("OVERVIEW:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[MemberRankItem]]:
    days = _parse_days(days)
    items = await overview_service.get_member_rank(db, current_user=current_user, days=days)
    return ApiResponse(data=items)


@router.get("/exec-records", summary="执行记录明细表（分页 + 筛选）")
async def get_exec_records(
    page_params: PageParams = Depends(),
    start_time: datetime | None = Query(default=None, description="默认近 7 天（前端控制）"),
    end_time: datetime | None = Query(default=None),
    status: list[int] | None = Query(default=None, description="执行状态多选"),
    datasource_id: int | None = Query(default=None),
    created_by: int | None = Query(default=None),
    case_name: str | None = Query(default=None, description="Case 名称模糊搜索"),
    table_name: str | None = Query(default=None, description="主表名模糊搜索"),
    current_user: User = Depends(require_permission("OVERVIEW:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PageData[ExecRecordItem]]:
    data = await overview_service.get_exec_records(
        db, current_user=current_user,
        page=page_params.page, page_size=page_params.page_size,
        start_time=to_local_naive(start_time), end_time=to_local_naive(end_time), status=status,
        datasource_id=datasource_id, created_by=created_by,
        case_name=case_name, table_name=table_name,
    )
    return ApiResponse(data=data)
