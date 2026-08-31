"""造数引擎模块路由（API 清单 10.4，前缀 /api/v1/engine）。

GET  /tables                          指定数据源的表列表
GET  /tables/{table_name}/columns     表字段详情（含自动推断策略预填）
GET  /tables/{table_name}/indexes     表索引信息
POST /execute                         创建 Case 并立即执行（返回 task_no）
POST /save                            仅保存 Case，不执行
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.models.user import User
from app.schemas.engine import (
    ColumnInfo,
    EngineExecuteRequest,
    EngineExecuteResponse,
    EngineSaveRequest,
    EngineSaveResponse,
    IndexInfo,
    TableItem,
)
from app.schemas.response import ApiResponse
from app.services import engine_service

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/tables", summary="获取指定数据源的表列表")
async def list_tables(
    datasource_id: int = Query(description="数据源 ID"),
    keyword: str | None = Query(default=None, description="模糊匹配表名/备注"),
    sort: str | None = Query(default=None, description="name=字母序 rows=数据量 columns=字段数"),
    current_user: User = Depends(require_permission("ENGINE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[TableItem]]:
    items = await engine_service.list_tables(
        db, current_user=current_user, datasource_id=datasource_id,
        keyword=keyword, sort=sort,
    )
    return ApiResponse(data=items)


@router.get("/tables/{table_name}/columns", summary="获取表字段详情（含自动推断策略）")
async def get_columns(
    table_name: str,
    datasource_id: int = Query(description="数据源 ID"),
    current_user: User = Depends(require_permission("ENGINE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ColumnInfo]]:
    items = await engine_service.get_table_columns(
        db, current_user=current_user, datasource_id=datasource_id, table_name=table_name
    )
    return ApiResponse(data=items)


@router.get("/tables/{table_name}/indexes", summary="获取表索引信息")
async def get_indexes(
    table_name: str,
    datasource_id: int = Query(description="数据源 ID"),
    current_user: User = Depends(require_permission("ENGINE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[IndexInfo]]:
    items = await engine_service.get_table_indexes(
        db, current_user=current_user, datasource_id=datasource_id, table_name=table_name
    )
    return ApiResponse(data=items)


@router.post("/execute", summary="创建 Case 并立即执行")
async def execute(
    body: EngineExecuteRequest,
    request: Request,
    current_user: User = Depends(require_permission("ENGINE:EXECUTE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EngineExecuteResponse]:
    data = await engine_service.execute_case_config(
        db, current_user=current_user, req=body, ip=_ip(request)
    )
    return ApiResponse(data=data, message="任务已提交")


@router.post("/save", summary="仅保存 Case，不执行")
async def save(
    body: EngineSaveRequest,
    request: Request,
    current_user: User = Depends(require_permission("ENGINE:CREATE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EngineSaveResponse]:
    data = await engine_service.save_case(
        db, current_user=current_user, req=body, ip=_ip(request)
    )
    return ApiResponse(data=data, message="Case 已保存")
