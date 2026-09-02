"""消息通知服务 + 操作审计辅助。

- audit()：统一封装 df_audit_log 写入（登录/登出/注册/审批/Case/场景/数据源/权限等敏感操作）。
- notify()：异步侧 df_notification 写入 + Redis 未读计数累加（df:notify:unread:{user_id}），
  与 tasks.notify_helper（Celery 同步侧）逻辑保持一致。
- 未读数查询/已读操作均实时校准 Redis 计数，保证铃铛角标准确。
"""

from datetime import datetime

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import redis_client
from app.models.notification import Notification
from app.models.task import AuditLog
from app.models.user import User
from app.schemas.errors import DATA_NOT_FOUND, BizException
from app.schemas.response import PageData

logger = structlog.get_logger(__name__)

UNREAD_COUNT_KEY = "df:notify:unread:{user_id}"


# ── 操作审计（敏感操作写 df_audit_log，不可删除）────────


async def audit(
    db: AsyncSession,
    *,
    user_id: int,
    username: str,
    action: str,
    resource: str | None = None,
    resource_id: str | int | None = None,
    detail: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """写入操作审计日志（仅 add，事务由调用方统一 commit）。

    :param action: 操作类型（LOGIN/LOGOUT/REGISTER/APPROVE_USER/REJECT_USER/
        CREATE_CASE/UPDATE_CASE/DELETE_CASE/EXEC_CASE/COPY_CASE/
        CREATE_SCENE/UPDATE_SCENE/DELETE_SCENE/EXEC_SCENE/
        ADD_DS/EDIT_DS/DEL_DS/SYNC_DS/PERMISSION_CHANGED/DISABLE_USER/
        ENABLE_USER/RESET_PASSWORD/AI_EXEC_TASK 等）
    """
    db.add(
        AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            resource=resource,
            resource_id=None if resource_id is None else str(resource_id),
            detail=detail,
            ip=ip,
            user_agent=(user_agent[:500] if user_agent else None),
        )
    )
    logger.info(
        "audit_log",
        user_id=user_id, username=username, action=action,
        resource=resource, resource_id=resource_id, ip=ip,
    )


# ── 消息通知 ────────────────────────────────────────────────────


async def notify(
    db: AsyncSession,
    *,
    user_id: int,
    msg_type: str,
    title: str,
    content: str,
    link_url: str | None = None,
    priority: int = 2,
    group_type: int = 99,
) -> Notification:
    """创建一条系统消息（仅 add + 未读计数，事务由调用方统一 commit）。

    :param priority: 1=高(红) 2=中(黄) 3=普通(绿)
    """
    notification = Notification(
        user_id=user_id,
        msg_type=msg_type,
        title=title[:200],
        content=content[:1000],
        link_url=(link_url[:500] if link_url else None),
        priority=priority,
        is_read=0,
        is_deleted=0,
        group_type=group_type,
        created_at=datetime.now(),
    )
    db.add(notification)
    try:
        await redis_client.incr(UNREAD_COUNT_KEY.format(user_id=user_id))
    except Exception:  # Redis 异常不阻断通知落库
        logger.warning("notify_unread_incr_failed", user_id=user_id)
    return notification


async def _refresh_unread_cache(db: AsyncSession, user_id: int) -> int:
    """以 DB 为准重算未读数并回写 Redis（校准计数，容忍任务侧漏增/重复增）。"""
    result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.is_read == 0,
            Notification.is_deleted == 0,
        )
    )
    count = int(result.scalar_one())
    try:
        await redis_client.set(UNREAD_COUNT_KEY.format(user_id=user_id), count)
    except Exception:
        logger.warning("unread_cache_refresh_failed", user_id=user_id)
    return count


async def get_unread_count(db: AsyncSession, current_user: User) -> int:
    """获取当前用户未读消息数（DB 实时统计并校准 Redis 缓存）。"""
    return await _refresh_unread_cache(db, current_user.id)


async def list_notifications(
    db: AsyncSession,
    current_user: User,
    *,
    page: int,
    page_size: int,
    is_read: int | None = None,
    priority: int | None = None,
) -> PageData:
    """消息列表（分页 + 已读/未读/优先级筛选），只能查看自己的消息。

    返回未参数化的 PageData（items 为 Notification ORM 对象，由路由层转换为 NotificationItem）。
    """
    conditions = [
        Notification.user_id == current_user.id,
        Notification.is_deleted == 0,
    ]
    if is_read is not None:
        conditions.append(Notification.is_read == is_read)
    if priority is not None:
        conditions.append(Notification.priority == priority)

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(Notification).where(*conditions)
            )
        ).scalar_one()
    )
    result = await db.execute(
        select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(result.scalars().all())
    return PageData(items=items, total=total, page=page, page_size=page_size)


async def mark_read(db: AsyncSession, current_user: User, notification_id: int) -> None:
    """标记单条消息为已读（只能操作自己的消息）。"""
    notification = await db.get(Notification, notification_id)
    if (
        notification is None
        or notification.is_deleted == 1
        or notification.user_id != current_user.id
    ):
        raise BizException(DATA_NOT_FOUND, "消息不存在或已被删除")
    if notification.is_read == 0:
        notification.is_read = 1
        notification.read_at = datetime.now()
        await db.commit()
        await _refresh_unread_cache(db, current_user.id)


async def mark_all_read(db: AsyncSession, current_user: User) -> int:
    """全部标为已读，返回本次标记条数。"""
    now = datetime.now()
    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read == 0,
            Notification.is_deleted == 0,
        )
        .values(is_read=1, read_at=now)
    )
    await db.commit()
    updated = int(result.rowcount or 0)
    try:
        await redis_client.set(UNREAD_COUNT_KEY.format(user_id=current_user.id), 0)
    except Exception:
        logger.warning("unread_cache_reset_failed", user_id=current_user.id)
    logger.info("notifications_read_all", user_id=current_user.id, updated=updated)
    return updated
