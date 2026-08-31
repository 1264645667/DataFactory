"""消息通知模块路由（API 清单 10.10，前缀 /api/v1/notifications）。

GET  /unread-count   未读消息数量（前端每 60s 轮询）
GET  /               消息列表（分页 + 已读/未读/优先级筛选）
POST /{notification_id}/read  标记单条已读
POST /read-all       全部标为已读（静态路径先于 /{id} 声明）
所有接口只能操作当前登录用户自己的消息。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PageParams, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.notification import (
    NotificationItem,
    ReadAllResponse,
    UnreadCountResponse,
)
from app.schemas.response import ApiResponse, PageData
from app.services import notification_service

router = APIRouter()


@router.get("/unread-count", summary="获取未读消息数量")
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UnreadCountResponse]:
    count = await notification_service.get_unread_count(db, current_user)
    return ApiResponse(data=UnreadCountResponse(unread_count=count))


@router.get("", summary="消息列表（分页 + 筛选）")
async def list_notifications(
    page_params: PageParams = Depends(),
    is_read: int | None = Query(default=None, ge=0, le=1, description="0=未读 1=已读"),
    priority: int | None = Query(default=None, ge=1, le=3, description="1=高 2=中 3=普通"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PageData[NotificationItem]]:
    page_data = await notification_service.list_notifications(
        db, current_user,
        page=page_params.page, page_size=page_params.page_size,
        is_read=is_read, priority=priority,
    )
    items = [
        NotificationItem(
            id=n.id,
            msg_type=n.msg_type,
            priority=n.priority,
            title=n.title,
            content=n.content,
            link_url=n.link_url,
            is_read=n.is_read,
            read_at=n.read_at,
            created_at=n.created_at,
        )
        for n in page_data.items
    ]
    return ApiResponse(data=PageData(
        items=items, total=page_data.total, page=page_data.page, page_size=page_data.page_size
    ))


@router.post("/read-all", summary="全部标为已读")
async def read_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReadAllResponse]:
    updated = await notification_service.mark_all_read(db, current_user)
    return ApiResponse(data=ReadAllResponse(updated_count=updated))


@router.post("/{notification_id}/read", summary="标记单条消息为已读")
async def read_one(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await notification_service.mark_read(db, current_user, notification_id)
    return ApiResponse(message="已标记为已读")
