"""消息通知模块请求/响应 Schema。"""

from datetime import datetime

from pydantic import BaseModel, Field


class UnreadCountResponse(BaseModel):
    """未读消息数量（前端每 60s 轮询）。"""

    unread_count: int = Field(ge=0)


class NotificationItem(BaseModel):
    """消息列表项。"""

    id: int
    msg_type: str = Field(
        description=(
            "USER_APPLY/APPLY_APPROVED/APPLY_REJECTED/EXEC_SUCCESS/EXEC_FAILED/EXEC_PARTIAL/"
            "SCENE_SUCCESS/SCENE_FAILED/SCENE_PARTIAL/DS_SYNC_DONE/DS_SYNC_FAILED/"
            "DS_OFFLINE/PERMISSION_CHANGED"
        )
    )
    priority: int = Field(description="1=高(红) 2=中(黄) 3=普通(绿)")
    title: str
    content: str
    link_url: str | None = None
    is_read: int = Field(description="0=未读 1=已读")
    read_at: datetime | None = None
    created_at: datetime


class ReadAllResponse(BaseModel):
    """全部标为已读响应。"""

    updated_count: int = Field(description="本次标记为已读的消息条数")
