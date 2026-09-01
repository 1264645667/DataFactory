"""用户管理模块路由（API 清单 10.2，前缀 /api/v1/users）。

管理端（USER:APPROVE / USER:PERMISSION / USER:DISABLE）+ 个人中心（已登录）。
注意：/me/* 与 /audit-logs 等静态路径必须声明在 /{user_id} 动态路径之前。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PageParams, get_current_user, require_permission, to_local_naive
from app.db.session import get_db
from app.models.user import User
from app.schemas.response import ApiResponse, PageData
from app.schemas.user import (
    AuditLogItem,
    AvatarUpdateRequest,
    DefaultDatasourceRequest,
    PasswordChangeRequest,
    PendingUserItem,
    PermissionUpdateRequest,
    RejectRequest,
    ResetPasswordResponse,
    ApproveRequest,
    UserListItem,
)
from app.services import user_service

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ── 审批（USER:APPROVE）─────────────────────────────────────────


@router.get("/pending", summary="获取待审批用户列表")
async def list_pending(
    current_user: User = Depends(require_permission("USER:APPROVE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[PendingUserItem]]:
    items = await user_service.list_pending_users(db)
    return ApiResponse(data=items)


@router.post("/{user_id}/approve", summary="审批通过并分配权限")
async def approve(
    user_id: int,
    body: ApproveRequest,
    request: Request,
    current_user: User = Depends(require_permission("USER:APPROVE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await user_service.approve_user(
        db, operator=current_user, target_user_id=user_id,
        menu_ids=body.menu_ids, ip=_ip(request),
    )
    return ApiResponse(message="已通过审批")


@router.post("/{user_id}/reject", summary="审批拒绝（填写原因）")
async def reject(
    user_id: int,
    body: RejectRequest,
    request: Request,
    current_user: User = Depends(require_permission("USER:APPROVE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await user_service.reject_user(
        db, operator=current_user, target_user_id=user_id,
        reject_reason=body.reject_reason, ip=_ip(request),
    )
    return ApiResponse(message="已拒绝该申请")


# ── 用户列表（USER:APPROVE）──────────────────────────────────────


@router.get("", summary="获取全部用户列表（分页）")
async def list_users(
    page_params: PageParams = Depends(),
    keyword: str | None = Query(default=None, description="用户名/真实姓名模糊搜索"),
    status: int | None = Query(default=None, ge=0, le=3),
    group_type: int | None = Query(default=None),
    current_user: User = Depends(require_permission("USER:APPROVE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PageData[UserListItem]]:
    data = await user_service.list_users(
        db, page=page_params.page, page_size=page_params.page_size,
        keyword=keyword, status=status, group_type=group_type,
    )
    return ApiResponse(data=data)


# ── 权限 / 禁用 / 重置密码 ────────────────────────────────────────


@router.put("/{user_id}/permissions", summary="更新用户菜单权限")
async def update_permissions(
    user_id: int,
    body: PermissionUpdateRequest,
    request: Request,
    current_user: User = Depends(require_permission("USER:PERMISSION")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await user_service.update_user_permissions(
        db, operator=current_user, target_user_id=user_id,
        menu_codes=body.menu_codes, ip=_ip(request),
    )
    return ApiResponse(message="权限已更新，立即生效")


@router.post("/{user_id}/disable", summary="禁用用户")
async def disable(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_permission("USER:DISABLE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await user_service.disable_user(db, operator=current_user, target_user_id=user_id, ip=_ip(request))
    return ApiResponse(message="已禁用")


@router.post("/{user_id}/enable", summary="启用用户")
async def enable(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_permission("USER:DISABLE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await user_service.enable_user(db, operator=current_user, target_user_id=user_id, ip=_ip(request))
    return ApiResponse(message="已启用")


@router.post("/{user_id}/reset-password", summary="重置密码（返回临时密码）")
async def reset_password(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_permission("USER:DISABLE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ResetPasswordResponse]:
    temp_password = await user_service.reset_password(
        db, operator=current_user, target_user_id=user_id, ip=_ip(request)
    )
    return ApiResponse(data=ResetPasswordResponse(temp_password=temp_password))


# ── 个人中心（已登录）─────────────────────────────────────────────


@router.put("/me/password", summary="修改自己密码（验旧密码）")
async def change_password(
    body: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await user_service.change_my_password(
        db, current_user=current_user,
        old_password=body.old_password, new_password=body.new_password,
    )
    return ApiResponse(message="密码已修改")


@router.put("/me/avatar", summary="更新头像序号")
async def update_avatar(
    body: AvatarUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await user_service.update_my_avatar(db, current_user=current_user, avatar_index=body.avatar_index)
    return ApiResponse(message="头像已更新")


@router.put("/me/default-datasource", summary="设置默认数据源")
async def set_default_datasource(
    body: DefaultDatasourceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await user_service.set_my_default_datasource(
        db, current_user=current_user, datasource_id=body.datasource_id
    )
    return ApiResponse(message="默认数据源已更新")


# ── 操作日志（PRD 2.7）───────────────────────────────────────────


@router.get("/audit-logs", summary="查询操作日志（普通用户看本组/管理员看全量）")
async def audit_logs(
    username: str | None = Query(default=None, description="按操作人账号筛选"),
    action: str | None = Query(default=None, description="按操作类型筛选"),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    group_type: int | None = Query(default=None, description="按分组筛选（仅管理员生效）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[AuditLogItem]]:
    items = await user_service.list_audit_logs(
        db, current_user=current_user, username=username, action=action,
        start_time=to_local_naive(start_time), end_time=to_local_naive(end_time), group_type=group_type,
    )
    return ApiResponse(data=items)
