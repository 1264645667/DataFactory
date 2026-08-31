"""消息通知写入助手（PRD 11，供各 Celery 任务复用）

统一封装 df_notification 写入 + Redis 未读计数累加（df:notify:unread:{user_id}）。
注意：本助手只 add + 计数，事务由调用方统一 commit。
"""
from __future__ import annotations

from datetime import datetime

import structlog

from app.core.redis_client import sync_redis_client
from app.models import Notification

logger = structlog.get_logger(__name__)


def create_notification(
    sync_session,
    user_id: int,
    msg_type: str,
    title: str,
    content: str,
    link_url: str | None = None,
    priority: int = 2,
    group_type: int = 99,
) -> Notification:
    """创建一条系统消息通知

    :param sync_session: 同步 SQLAlchemy Session（由调用方统一 commit）
    :param user_id: 接收用户 ID
    :param msg_type: 消息类型（EXEC_SUCCESS/EXEC_FAILED/SCENE_*/DS_* 等，PRD 11.3）
    :param title: 消息标题（≤200 字符）
    :param content: 消息正文（≤1000 字符）
    :param link_url: 关联跳转路径（相对路径，≤500 字符）
    :param priority: 优先级 1=高(红) 2=中(黄) 3=普通(绿)
    :param group_type: 接收人所属分组（管理员填 99）
    """
    notification = Notification(
        user_id=user_id,
        msg_type=msg_type,
        title=(title or "")[:200],
        content=(content or "")[:1000],
        link_url=(link_url[:500] if link_url else None),
        priority=priority,
        is_read=0,
        is_deleted=0,
        group_type=group_type,
        created_at=datetime.now(),
    )
    sync_session.add(notification)
    try:
        # 未读计数 +1（Redis 异常不阻断通知落库）
        sync_redis_client.incr(f"df:notify:unread:{user_id}")
    except Exception:  # noqa: BLE001
        logger.warning("notify_unread_incr_failed", user_id=user_id)
    return notification
