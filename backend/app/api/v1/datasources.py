"""数据源模块路由

GET    /                数据源列表（含连接状态心跳）
POST   /                新增数据源（AES 加密 + 异步初始化）
PUT    /{datasource_id} 编辑数据源（密码不填保持原值 + 重同步）
DELETE /{datasource_id} 删除数据源（硬校验 + 级联清理）
POST   /test            测试连接（不保存）
POST   /{datasource_id}/sync   手动触发表结构同步
GET    /{datasource_id}/status 获取连接状态（心跳）
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.models.user import User
from app.schemas.datasource import (
    DatasourceCreateRequest,
    DatasourceItem,
    DatasourceStatusResponse,
    DatasourceSyncResponse,
    DatasourceTestRequest,
    DatasourceTestResponse,
    DatasourceUpdateRequest,
)
from app.schemas.response import ApiResponse
from app.services import datasource_service

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", summary="数据源列表（含连接状态）")
async def list_datasources(
    keyword: str | None = Query(default=None, description="按数据源名称过滤"),
    current_user: User = Depends(require_permission("DATASOURCE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[DatasourceItem]]:
    items = await datasource_service.list_datasources(db, current_user=current_user, keyword=keyword)
    return ApiResponse(data=items)


@router.post("", summary="新增数据源")
async def create_datasource(
    body: DatasourceCreateRequest,
    request: Request,
    current_user: User = Depends(require_permission("DATASOURCE:ADD")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[DatasourceItem]:
    data = await datasource_service.create_datasource(
        db, current_user=current_user, req=body, ip=_ip(request)
    )
    return ApiResponse(data=data, message="数据源已保存，正在后台初始化表结构")


@router.put("/{datasource_id}", summary="编辑数据源")
async def update_datasource(
    datasource_id: int,
    body: DatasourceUpdateRequest,
    request: Request,
    current_user: User = Depends(require_permission("DATASOURCE:EDIT")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await datasource_service.update_datasource(
        db, current_user=current_user, datasource_id=datasource_id, req=body, ip=_ip(request)
    )
    return ApiResponse(message="数据源已更新，正在后台重新同步表结构")


@router.delete("/{datasource_id}", summary="删除数据源（硬校验 + 级联清理）")
async def delete_datasource(
    datasource_id: int,
    request: Request,
    current_user: User = Depends(require_permission("DATASOURCE:DELETE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await datasource_service.delete_datasource(
        db, current_user=current_user, datasource_id=datasource_id, ip=_ip(request)
    )
    return ApiResponse(message="数据源已删除")


@router.post("/test", summary="测试连接（表单页按钮，不保存）")
async def test_connection(
    body: DatasourceTestRequest,
    current_user: User = Depends(require_permission("DATASOURCE:ADD")),
) -> ApiResponse[DatasourceTestResponse]:
    data = await datasource_service.test_connection(body)
    return ApiResponse(data=data)


@router.post("/{datasource_id}/sync", summary="手动触发表结构同步")
async def trigger_sync(
    datasource_id: int,
    request: Request,
    current_user: User = Depends(require_permission("DATASOURCE:EDIT")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[DatasourceSyncResponse]:
    data = await datasource_service.trigger_sync(
        db, current_user=current_user, datasource_id=datasource_id, ip=_ip(request)
    )
    return ApiResponse(data=data)


@router.get("/{datasource_id}/status", summary="获取数据源连接状态（心跳）")
async def get_status(
    datasource_id: int,
    current_user: User = Depends(require_permission("DATASOURCE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[DatasourceStatusResponse]:
    data = await datasource_service.get_datasource_status(
        db, current_user=current_user, datasource_id=datasource_id
    )
    return ApiResponse(data=data)
