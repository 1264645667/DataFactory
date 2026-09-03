"""API 公共依赖

- get_current_user：解析 JWT → 查库 → 校验账号状态/Token 黑名单，返回 User ORM 对象；
  权限列表每次请求实时从 df_user_menu/df_menu 读取（权限变更保存后立即生效，无需重新登录）。
- require_permission(code)：权限校验工厂，管理员（group_type=99）隐式拥有全部权限。
- PageParams：分页参数依赖（page/page_size，page_size 上限 100）。
- group_scope_values / ensure_group_visible：分组数据权限辅助，
  普通用户可见/可操作 本组 + 管理员（99）数据，管理员全量。
- ai_key_auth：AI 接口独立 API Key 认证（X-DataForge-AI-Key 头 + 状态/过期/限流校验）。
"""

from datetime import datetime

import structlog
from fastapi import Depends, Header, Query, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import redis_client
from app.core.security import verify_token
from app.db.session import get_db
from app.models.user import AiApiKey, Menu, User, UserMenu
from app.schemas.errors import (
    FORBIDDEN,
    OPERATION_TOO_FREQUENT,
    UNAUTHORIZED,
    USER_DISABLED,
    USER_PENDING,
    USER_REJECTED,
    BizException,
)

logger = structlog.get_logger(__name__)

# Bearer Token 解析器（auto_error=False 以便统一抛 1001）
bearer_scheme = HTTPBearer(auto_error=False)

# 管理员分组标识
ADMIN_GROUP_TYPE = 99


def to_local_naive(dt: datetime | None) -> datetime | None:
    """将带时区的 datetime 转为本地时区的 naive datetime。

    前端可能传 ISO 8601 带时区格式（如 new Date().toISOString() 的 UTC 时间），
    而 MySQL DATETIME 存储的是本地时间（Asia/Shanghai）的 naive 值。
    直接比较会产生 8 小时偏差导致查不到数据，此处统一转换。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    from zoneinfo import ZoneInfo

    from app.config import settings

    return dt.astimezone(ZoneInfo(settings.TZ)).replace(tzinfo=None)


async def get_user_permissions(db: AsyncSession, user_id: int) -> list[str]:
    """实时查询用户权限编码列表（df_user_menu JOIN df_menu）。"""
    result = await db.execute(
        select(Menu.menu_code)
        .join(UserMenu, UserMenu.menu_id == Menu.id)
        .where(UserMenu.user_id == user_id)
    )
    return list(result.scalars().all())


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """解析 JWT → 查库 → 校验状态/黑名单，返回当前登录用户。

    Raises:
        BizException: 1001 未登录/Token 无效；1006 Token 已失效（verify_token 抛出）；
                      1102 已禁用；1103 待审批；1104 已拒绝。
    """
    if credentials is None or not credentials.credentials:
        raise BizException(UNAUTHORIZED)
    payload = await verify_token(credentials.credentials)  # 内部已处理黑名单
    try:
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError) as e:
        raise BizException(UNAUTHORIZED) from e
    user = await db.get(User, user_id)
    if user is None:
        raise BizException(UNAUTHORIZED)
    # 账号状态实时校验（禁用/审批状态变化立即生效）
    if user.status == 2:
        raise BizException(USER_DISABLED)
    if user.status == 0:
        raise BizException(USER_PENDING)
    if user.status == 3:
        raise BizException(USER_REJECTED)
    return user


def require_permission(permission_code: str):
    """权限校验依赖工厂

    管理员（group_type=99）隐式拥有全部权限；普通用户实时查库校验，
    保证管理员调整权限后立即生效
    """

    async def _checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if current_user.group_type == ADMIN_GROUP_TYPE:
            return current_user
        permissions = await get_user_permissions(db, current_user.id)
        if permission_code not in permissions:
            logger.warning(
                "permission_denied",
                user_id=current_user.id,
                username=current_user.username,
                required=permission_code,
            )
            raise BizException(FORBIDDEN)
        return current_user

    return _checker


class PageParams:
    """分页参数依赖（page 从 1 开始，page_size 上限 100）。"""

    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
        page_size: int = Query(default=20, ge=1, le=100, description="每页条数，最大 100"),
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        """SQL OFFSET 偏移量。"""
        return (self.page - 1) * self.page_size


def group_scope_values(current_user: User) -> list[int] | None:
    """数据可见范围（普通用户 = 本组 + 管理员数据；管理员 = None 全量不过滤）。

    用法::

        scope = group_scope_values(current_user)
        if scope is not None:
            stmt = stmt.where(Model.group_type.in_(scope))
    """
    if current_user.group_type == ADMIN_GROUP_TYPE:
        return None
    return [current_user.group_type, ADMIN_GROUP_TYPE]


def ensure_group_visible(current_user: User, target_group_type: int, error_code: int) -> None:
    """校验目标数据分组对当前用户可见，否则抛业务异常（按不存在处理，不泄露数据）。

    普通用户：可操作 本组 或 管理员（99） 的数据；管理员：可操作全部。
    """
    if current_user.group_type == ADMIN_GROUP_TYPE:
        return
    if target_group_type not in (current_user.group_type, ADMIN_GROUP_TYPE):
        raise BizException(error_code)


# ── AI 接口 API Key 认证 ────────────────────────────

# AI 限流 Redis Key（每分钟窗口计数）
AI_RATE_KEY = "df:ai:rate:{key_id}"
AI_RATE_WINDOW_SECONDS = 60


async def ai_key_auth(
    x_dataforge_ai_key: str | None = Header(default=None, alias="X-DataForge-AI-Key"),
    db: AsyncSession = Depends(get_db),
) -> AiApiKey:
    """AI 接口 API Key 认证依赖

    校验链：Key 存在 → 状态启用 → 未过期 → Redis 每分钟限流（rate_limit 次/分钟）。
    """
    if not x_dataforge_ai_key:
        raise BizException(UNAUTHORIZED, "缺少 X-DataForge-AI-Key 请求头")
    result = await db.execute(
        select(AiApiKey).where(AiApiKey.api_key == x_dataforge_ai_key)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise BizException(UNAUTHORIZED, "API Key 无效")
    if api_key.status != 1:
        raise BizException(FORBIDDEN, "API Key 已被禁用")
    if api_key.expire_at is not None and api_key.expire_at < datetime.now():
        raise BizException(UNAUTHORIZED, "API Key 已过期")

    # 限流：每分钟窗口计数（默认 100 次/分钟）；Redis 异常时降级放行，不阻断 AI 调用
    rate_limit = api_key.rate_limit or 100
    rate_key = AI_RATE_KEY.format(key_id=api_key.id)
    try:
        count = await redis_client.incr(rate_key)
        if count == 1:
            await redis_client.expire(rate_key, AI_RATE_WINDOW_SECONDS)
        if count > rate_limit:
            raise BizException(
                OPERATION_TOO_FREQUENT,
                f"API Key 调用超限（{rate_limit} 次/分钟），请稍后再试",
            )
    except BizException:
        raise
    except Exception:
        logger.warning("ai_rate_limit_check_failed", key_id=api_key.id)
    return api_key
