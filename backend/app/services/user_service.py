"""用户与认证业务服务。

覆盖：登录（含失败锁定）、注册申请、审批/拒绝、用户列表、权限分配、
禁用/启用、重置密码、修改密码、头像、默认数据源、操作日志查询。
"""

import re
import secrets
import string
from datetime import datetime

import structlog
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_user_permissions
from app.config import settings
from app.core.redis_client import redis_client
from app.core.security import (
    create_access_token,
    get_password_hash,
    invalidate_token,
    verify_password,
    verify_token,
)
from app.models.datasource import Datasource
from app.models.task import AuditLog
from app.models.user import Menu, User, UserMenu
from app.schemas.errors import (
    DS_NOT_FOUND,
    DS_PERMISSION_DENIED,
    FORBIDDEN,
    OLD_PASSWORD_WRONG,
    PARAM_INVALID,
    PASSWORD_TOO_WEAK,
    PASSWORD_WRONG,
    USER_DISABLED,
    USER_NOT_FOUND,
    USER_PENDING,
    USER_REJECTED,
    USERNAME_TAKEN,
    BizException,
)
from app.schemas.response import PageData
from app.schemas.user import (
    AuditLogItem,
    CurrentUserResponse,
    LoginResponse,
    PendingUserItem,
    UserBrief,
    UserListItem,
)
from app.services.notification_service import audit, notify

logger = structlog.get_logger(__name__)

# 登录失败计数 Redis Key
LOGIN_FAIL_KEY = "df:login:fail:{username}"

# 分组名称映射（通知文案用）
GROUP_NAMES = {1: "销项组", 2: "申报组", 99: "管理员"}

# 密码强度：至少 8 位且同时包含数字和字母
_PASSWORD_RULE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


def check_password_strength(password: str) -> None:
    """校验密码强度，不通过抛 1107。"""
    if not _PASSWORD_RULE.match(password or ""):
        raise BizException(PASSWORD_TOO_WEAK)


def _generate_temp_password(length: int = 10) -> str:
    """生成临时密码（保证含字母+数字，符合强度规则）。"""
    alphabet = string.ascii_letters + string.digits
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if _PASSWORD_RULE.match(password):
            return password


# ── 认证 ────────────────────────────────────────────────────────


async def login(
    db: AsyncSession, *, username: str, password: str, ip: str | None, user_agent: str | None
) -> LoginResponse:
    """用户登录（连续失败 ≥5 次锁定 10 分钟）。

    - 锁定判定：df:login:fail:{username} 计数 ≥ LOGIN_FAIL_MAX_TIMES → 1005 并提示剩余分钟
    - 密码错误：INCR 计数（首次设置 TTL=600s），按剩余次数提示
    - 登录成功：删除计数 Key，更新最后登录时间/IP，签发 JWT
    """
    max_times = settings.LOGIN_FAIL_MAX_TIMES
    lock_seconds = settings.LOGIN_FAIL_LOCK_SECONDS
    fail_key = LOGIN_FAIL_KEY.format(username=username)

    # 1. 锁定检查（不查 DB）
    try:
        fail_count_raw = await redis_client.get(fail_key)
        fail_count = int(fail_count_raw or 0)
        if fail_count >= max_times:
            ttl = await redis_client.ttl(fail_key)
            remaining_minutes = max(1, (int(ttl) + 59) // 60) if ttl and ttl > 0 else 10
            raise BizException(
                1005, f"操作过于频繁，账号已锁定，请 {remaining_minutes} 分钟后重试"
            )
    except BizException:
        raise
    except Exception:
        fail_count = 0  # Redis 异常时降级，不阻断登录

    # 2. 用户与状态校验
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is not None:
        # 账号状态优先于密码校验（状态类错误不计入失败次数）
        if user.status == 2:
            raise BizException(USER_DISABLED)
        if user.status == 0:
            raise BizException(USER_PENDING)
        if user.status == 3:
            reason = f"：{user.reject_reason}" if user.reject_reason else ""
            raise BizException(USER_REJECTED, f"注册申请已被拒绝{reason}")

    # 3. 密码校验（用户不存在同样按密码错误处理，避免暴露账号是否存在）
    password_ok = user is not None and verify_password(password, user.password)
    if not password_ok:
        new_count = fail_count
        try:
            new_count = await redis_client.incr(fail_key)
            if new_count == 1:
                await redis_client.expire(fail_key, lock_seconds)
        except Exception:
            logger.warning("login_fail_incr_failed", username=username)
        if new_count >= max_times:
            raise BizException(1005, "密码错误次数过多，账号已被锁定 10 分钟")
        raise BizException(PASSWORD_WRONG, f"密码错误，还剩 {max_times - new_count} 次尝试机会")

    # 4. 登录成功：清零失败计数，更新登录信息，签发 Token
    try:
        await redis_client.delete(fail_key)
    except Exception:
        pass
    user.last_login_at = datetime.now()
    user.last_login_ip = ip
    permissions = await get_user_permissions(db, user.id)
    token = create_access_token(user.id, permissions)
    await audit(
        db, user_id=user.id, username=user.username, action="LOGIN",
        resource="user", resource_id=user.id, ip=ip, user_agent=user_agent,
    )
    await db.commit()
    logger.info("user_login", user_id=user.id, username=username, ip=ip)
    return LoginResponse(
        access_token=token,
        expires_in=settings.JWT_EXPIRE_DAYS * 86400,
        user=UserBrief(
            id=user.id,
            username=user.username,
            real_name=user.real_name,
            group_type=user.group_type,
            avatar_index=user.avatar_index,
        ),
    )


async def register(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    real_name: str,
    group_type: int,
    apply_reason: str | None,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """提交注册申请用户名查重（含各状态）→ 创建 status=0 账号 → 通知管理员。"""
    if group_type not in (1, 2):
        raise BizException(PARAM_INVALID, "申请分组不合法")
    check_password_strength(password)

    # 用户名唯一性（含待审批/已拒绝等所有状态）
    result = await db.execute(select(User.id).where(User.username == username))
    if result.scalar_one_or_none() is not None:
        raise BizException(USERNAME_TAKEN)

    user = User(
        username=username,
        password=get_password_hash(password),
        real_name=real_name,
        group_type=group_type,
        status=0,  # 待审批
        apply_reason=apply_reason,
        avatar_index=1,
    )
    db.add(user)
    await db.flush()  # 取 user.id

    await audit(
        db, user_id=user.id, username=username, action="REGISTER",
        resource="user", resource_id=user.id,
        detail=f"申请分组：{GROUP_NAMES.get(group_type, group_type)}",
        ip=ip, user_agent=user_agent,
    )

    # 通知全部管理员（USER_APPLY，高优先级）
    admin_result = await db.execute(
        select(User).where(User.group_type == 99, User.status == 1)
    )
    for admin in admin_result.scalars().all():
        await notify(
            db,
            user_id=admin.id,
            msg_type="USER_APPLY",
            title="新用户注册申请",
            content=(
                f"用户「{username}」（{real_name}）申请加入"
                f"{GROUP_NAMES.get(group_type, group_type)}，请及时审批。"
            ),
            link_url="/admin/users?tab=pending",
            priority=1,
            group_type=99,
        )
    await db.commit()
    logger.info("user_registered", user_id=user.id, username=username, group_type=group_type)


async def logout(
    db: AsyncSession, *, current_user: User, token: str, ip: str | None, user_agent: str | None
) -> None:
    """主动登出：jti 加入 Redis 黑名单（TTL 为 Token 剩余有效期）。"""
    payload = await verify_token(token)
    jti = payload.get("jti")
    exp = payload.get("exp")
    ttl = int(exp) - int(datetime.now().timestamp()) if exp else 0
    if jti:
        await invalidate_token(jti, max(ttl, 0))
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="LOGOUT",
        resource="user", resource_id=current_user.id, ip=ip, user_agent=user_agent,
    )
    await db.commit()
    logger.info("user_logout", user_id=current_user.id)


async def get_current_user_info(db: AsyncSession, current_user: User) -> CurrentUserResponse:
    """获取当前用户信息及权限列表（管理员返回全量权限编码）。"""
    if current_user.group_type == 99:
        result = await db.execute(select(Menu.menu_code).order_by(Menu.sort_order))
        permissions = list(result.scalars().all())
    else:
        permissions = await get_user_permissions(db, current_user.id)
    return CurrentUserResponse(
        id=current_user.id,
        username=current_user.username,
        real_name=current_user.real_name,
        group_type=current_user.group_type,
        status=current_user.status,
        avatar_index=current_user.avatar_index,
        default_datasource_id=current_user.default_datasource_id,
        permissions=permissions,
        last_login_at=current_user.last_login_at,
    )


# ── 用户管理（管理员）────────────────────────────────────────────


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise BizException(USER_NOT_FOUND)
    return user


async def _replace_user_menus(db: AsyncSession, user_id: int, menu_codes: list[str]) -> list[str]:
    """按权限编码重建用户菜单关联，返回规范化的权限编码列表。非法编码抛 1000。"""
    menu_ids: list[int] = []
    if menu_codes:
        result = await db.execute(select(Menu).where(Menu.menu_code.in_(menu_codes)))
        menus = list(result.scalars().all())
        if len(menus) != len(set(menu_codes)):
            raise BizException(PARAM_INVALID, "存在无效的菜单权限编码")
        # 按 sort_order 稳定排序，保持返回编码顺序一致
        menus.sort(key=lambda m: m.sort_order)
        menu_ids = [menu.id for menu in menus]
        menu_codes = [menu.menu_code for menu in menus]
    # 先删后插（覆盖式）
    await db.execute(sql_delete(UserMenu).where(UserMenu.user_id == user_id))
    for menu_id in dict.fromkeys(menu_ids):
        db.add(UserMenu(user_id=user_id, menu_id=menu_id))
    return menu_codes


async def list_pending_users(db: AsyncSession) -> list[PendingUserItem]:
    """待审批用户列表（申请时间正序）。"""
    result = await db.execute(
        select(User).where(User.status == 0).order_by(User.created_at.asc())
    )
    return [
        PendingUserItem(
            id=u.id,
            username=u.username,
            real_name=u.real_name,
            group_type=u.group_type,
            apply_reason=u.apply_reason,
            created_at=u.created_at,
        )
        for u in result.scalars().all()
    ]


async def approve_user(
    db: AsyncSession,
    *,
    operator: User,
    target_user_id: int,
    menu_codes: list[str],
    ip: str | None,
) -> None:
    """审批通过：分配权限 + APPLY_APPROVED 通知 + 审计。"""
    target = await _get_user_or_404(db, target_user_id)
    if target.status != 0:
        raise BizException(PARAM_INVALID, "该用户不处于待审批状态")
    menu_codes = await _replace_user_menus(db, target_user_id, menu_codes)
    target.status = 1  # 正常
    target.reject_reason = None
    await notify(
        db,
        user_id=target.id,
        msg_type="APPLY_APPROVED",
        title="注册申请已通过",
        content=(
            f"你的账号「{target.username}」已通过审批，已分配 {len(menu_codes)} 项权限，"
            "现在可以登录系统了。"
        ),
        link_url="/login",
        priority=3,
        group_type=target.group_type,
    )
    await audit(
        db, user_id=operator.id, username=operator.username, action="APPROVE_USER",
        resource="user", resource_id=target.id,
        detail=f"分配权限：{','.join(menu_codes) if menu_codes else '（无）'}",
        ip=ip,
    )
    await db.commit()
    logger.info("user_approved", operator=operator.username, target=target.username)


async def reject_user(
    db: AsyncSession,
    *,
    operator: User,
    target_user_id: int,
    reject_reason: str,
    ip: str | None,
) -> None:
    """审批拒绝：填写原因 + APPLY_REJECTED 通知 + 审计。"""
    target = await _get_user_or_404(db, target_user_id)
    if target.status != 0:
        raise BizException(PARAM_INVALID, "该用户不处于待审批状态")
    target.status = 3  # 已拒绝
    target.reject_reason = reject_reason
    await notify(
        db,
        user_id=target.id,
        msg_type="APPLY_REJECTED",
        title="注册申请被拒绝",
        content=f"你的账号「{target.username}」注册申请已被拒绝。原因：{reject_reason}",
        link_url="/login",
        priority=1,
        group_type=target.group_type,
    )
    await audit(
        db, user_id=operator.id, username=operator.username, action="REJECT_USER",
        resource="user", resource_id=target.id, detail=reject_reason, ip=ip,
    )
    await db.commit()
    logger.info("user_rejected", operator=operator.username, target=target.username)


async def list_users(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    keyword: str | None = None,
    status: int | None = None,
    group_type: int | None = None,
) -> PageData[UserListItem]:
    """全部用户列表（分页，含权限列表）。"""
    conditions = []
    if keyword:
        like = f"%{keyword}%"
        conditions.append((User.username.like(like)) | (User.real_name.like(like)))
    if status is not None:
        conditions.append(User.status == status)
    if group_type is not None:
        conditions.append(User.group_type == group_type)

    total = int(
        (await db.execute(select(func.count()).select_from(User).where(*conditions))).scalar_one()
    )
    result = await db.execute(
        select(User)
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    users = list(result.scalars().all())

    # 批量查询本页用户的权限编码（避免 N+1）
    perm_map: dict[int, list[str]] = {u.id: [] for u in users}
    if users:
        perm_result = await db.execute(
            select(UserMenu.user_id, Menu.menu_code)
            .join(Menu, UserMenu.menu_id == Menu.id)
            .where(UserMenu.user_id.in_([u.id for u in users]))
        )
        for user_id, menu_code in perm_result.all():
            perm_map.setdefault(user_id, []).append(menu_code)

    items = [
        UserListItem(
            id=u.id,
            username=u.username,
            real_name=u.real_name,
            group_type=u.group_type,
            status=u.status,
            default_datasource_id=u.default_datasource_id,
            permissions=perm_map.get(u.id, []),
            last_login_at=u.last_login_at,
            created_at=u.created_at,
        )
        for u in users
    ]
    return PageData(items=items, total=total, page=page, page_size=page_size)


async def update_user_permissions(
    db: AsyncSession,
    *,
    operator: User,
    target_user_id: int,
    menu_codes: list[str],
    ip: str | None,
) -> None:
    """更新用户菜单权限（保存后立即生效）+ PERMISSION_CHANGED 通知 + 审计。"""
    target = await _get_user_or_404(db, target_user_id)
    menu_codes = await _replace_user_menus(db, target_user_id, menu_codes)
    await notify(
        db,
        user_id=target.id,
        msg_type="PERMISSION_CHANGED",
        title="权限已变更",
        content=(
            f"管理员已调整你的菜单权限，当前共 {len(menu_codes)} 项权限，立即生效。"
        ),
        link_url=None,
        priority=2,
        group_type=target.group_type,
    )
    await audit(
        db, user_id=operator.id, username=operator.username, action="PERMISSION_CHANGED",
        resource="user", resource_id=target.id,
        detail=f"新权限：{','.join(menu_codes) if menu_codes else '（清空）'}",
        ip=ip,
    )
    await db.commit()
    logger.info("user_permissions_updated", operator=operator.username, target=target.username)


async def disable_user(
    db: AsyncSession, *, operator: User, target_user_id: int, ip: str | None
) -> None:
    """禁用用户（不能禁用管理员账号与自己）。"""
    target = await _get_user_or_404(db, target_user_id)
    if target.group_type == 99:
        raise BizException(FORBIDDEN, "不能禁用管理员账号")
    if target.id == operator.id:
        raise BizException(FORBIDDEN, "不能禁用自己的账号")
    if target.status == 2:
        raise BizException(PARAM_INVALID, "该用户已处于禁用状态")
    target.status = 2
    await audit(
        db, user_id=operator.id, username=operator.username, action="DISABLE_USER",
        resource="user", resource_id=target.id, ip=ip,
    )
    await db.commit()
    logger.info("user_disabled", operator=operator.username, target=target.username)


async def enable_user(
    db: AsyncSession, *, operator: User, target_user_id: int, ip: str | None
) -> None:
    """启用用户。"""
    target = await _get_user_or_404(db, target_user_id)
    if target.status != 2:
        raise BizException(PARAM_INVALID, "该用户不处于禁用状态")
    target.status = 1
    await audit(
        db, user_id=operator.id, username=operator.username, action="ENABLE_USER",
        resource="user", resource_id=target.id, ip=ip,
    )
    await db.commit()
    logger.info("user_enabled", operator=operator.username, target=target.username)


async def reset_password(
    db: AsyncSession, *, operator: User, target_user_id: int, ip: str | None
) -> str:
    """重置密码：生成临时密码返回（仅此一次明文返回）。"""
    target = await _get_user_or_404(db, target_user_id)
    temp_password = _generate_temp_password()
    target.password = get_password_hash(temp_password)
    await audit(
        db, user_id=operator.id, username=operator.username, action="RESET_PASSWORD",
        resource="user", resource_id=target.id, ip=ip,
    )
    await db.commit()
    logger.info("user_password_reset", operator=operator.username, target=target.username)
    return temp_password


# ── 个人中心 ────────────────────────────────────────────────────


async def change_my_password(
    db: AsyncSession, *, current_user: User, old_password: str, new_password: str
) -> None:
    """修改自己密码（需验证旧密码）。"""
    # 重新查库取最新密码哈希
    user = await db.get(User, current_user.id)
    if user is None or not verify_password(old_password, user.password):
        raise BizException(OLD_PASSWORD_WRONG)
    check_password_strength(new_password)
    user.password = get_password_hash(new_password)
    await db.commit()
    logger.info("user_password_changed", user_id=current_user.id)


async def update_my_avatar(db: AsyncSession, *, current_user: User, avatar_index: int) -> None:
    """更新头像序号（预设 10 款猫咪头像）。"""
    user = await db.get(User, current_user.id)
    user.avatar_index = avatar_index
    await db.commit()


async def set_my_default_datasource(
    db: AsyncSession, *, current_user: User, datasource_id: int | None
) -> None:
    """设置默认数据源（None 表示清除；只能选择本组可用数据源）。"""
    if datasource_id is not None:
        ds = await db.get(Datasource, datasource_id)
        if ds is None:
            raise BizException(DS_NOT_FOUND)
        if current_user.group_type != 99 and ds.group_type != current_user.group_type:
            raise BizException(DS_PERMISSION_DENIED)
    user = await db.get(User, current_user.id)
    user.default_datasource_id = datasource_id
    await db.commit()
    logger.info("user_default_datasource_set", user_id=current_user.id, datasource_id=datasource_id)


# ── 操作日志───────────────────────────────────────────


async def list_audit_logs(
    db: AsyncSession,
    *,
    current_user: User,
    username: str | None = None,
    action: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    group_type: int | None = None,
) -> list[AuditLogItem]:
    """操作日志查询。

    普通用户：本组内所有成员的操作日志，最近 500 条；
    管理员：全量日志，最近 1000 条，额外支持按分组筛选。
    """
    conditions = []
    if username:
        conditions.append(AuditLog.username.like(f"%{username}%"))
    if action:
        conditions.append(AuditLog.action == action)
    if start_time is not None:
        conditions.append(AuditLog.created_at >= start_time)
    if end_time is not None:
        conditions.append(AuditLog.created_at <= end_time)

    if current_user.group_type == 99:
        limit = 1000
        if group_type is not None:
            # 按操作人所属分组过滤（子查询同组用户 ID）
            sub = select(User.id).where(User.group_type == group_type)
            conditions.append(AuditLog.user_id.in_(sub))
    else:
        limit = 500
        sub = select(User.id).where(User.group_type == current_user.group_type)
        conditions.append(AuditLog.user_id.in_(sub))

    result = await db.execute(
        select(AuditLog, User.real_name, User.group_type)
        .join(User, AuditLog.user_id == User.id, isouter=True)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    items = [
        AuditLogItem(
            id=log.id,
            user_id=log.user_id,
            username=log.username,
            real_name=real_name,
            group_type=u_group_type,
            action=log.action,
            resource=log.resource,
            resource_id=log.resource_id,
            detail=log.detail,
            ip=log.ip,
            created_at=log.created_at,
        )
        for log, real_name, u_group_type in result.all()
    ]
    return items
