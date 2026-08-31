"""造数总览模块路由（API 清单 10.8，前缀 /api/v1/overview）。

GET /metrics       核心指标卡片数据（Redis 缓存 5min）
GET /trend         执行趋势折线图（近 7/30/90 天）
GET /status-dist   执行状态分布饼图
GET /table-top10   表操作量 Top10 柱状图
GET /member-rank   成员贡献排行
GET /exec-records  执行记录明细表（分页 + 筛选）
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PageParams, require_permission
from app.db.session import get_db
from app.models.user import User
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
    days: Literal[7, 30, 90] = Query(default=30, description="查看范围：近 7/30/90 天"),
    current_user: User = Depends(require_permission("OVERVIEW:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TrendResponse]:
    data = await overview_service.get_trend(db, current_user=current_user, days=days)
    return ApiResponse(data=data)


@router.get("/status-dist", summary="执行状态分布饼图数据")
async def get_status_dist(
    days: Literal[7, 30, 90] = Query(default=30),
    current_user: User = Depends(require_permission("OVERVIEW:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StatusDistResponse]:
    data = await overview_service.get_status_dist(db, current_user=current_user, days=days)
    return ApiResponse(data=data)


@router.get("/table-top10", summary="表操作量 Top10 柱状图数据")
async def get_table_top10(
    days: Literal[7, 30, 90] = Query(default=30),
    current_user: User = Depends(require_permission("OVERVIEW:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[TableTopItem]]:
    items = await overview_service.get_table_top10(db, current_user=current_user, days=days)
    return ApiResponse(data=items)


@router.get("/member-rank", summary="成员贡献排行数据")
async def get_member_rank(
    days: Literal[7, 30, 90] = Query(default=30),
    current_user: User = Depends(require_permission("OVERVIEW:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[MemberRankItem]]:
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
        start_time=start_time, end_time=end_time, status=status,
        datasource_id=datasource_id, created_by=created_by,
        case_name=case_name, table_name=table_name,
    )
    return ApiResponse(data=data)
