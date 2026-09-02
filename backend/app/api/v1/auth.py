"""认证模块路由

POST /login    用户登录（含登录失败锁定）
POST /register 提交注册申请
POST /logout   主动登出（jti 加入黑名单）
GET  /me       当前用户信息及权限列表
"""

from fastapi import APIRouter, Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import bearer_scheme, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.response import ApiResponse
from app.schemas.user import (
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
)
from app.services import user_service

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    """取客户端 IP（直连地址）。"""
    return request.client.host if request.client else None


@router.post("/login", summary="用户登录（连续失败5次锁定10分钟）")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[LoginResponse]:
    data = await user_service.login(
        db,
        username=body.username,
        password=body.password,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ApiResponse(data=data)


@router.post("/register", summary="提交注册申请（用户名查重含各状态）")
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await user_service.register(
        db,
        username=body.username,
        password=body.password,
        real_name=body.real_name,
        group_type=body.group_type,
        apply_reason=body.apply_reason,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ApiResponse(message="申请已提交，请等待管理员审批")


@router.post("/logout", summary="主动登出（Token 加入黑名单）")
async def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await user_service.logout(
        db,
        current_user=current_user,
        token=credentials.credentials if credentials else "",
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ApiResponse(message="已登出")


@router.get("/me", summary="获取当前用户信息及权限列表")
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CurrentUserResponse]:
    data = await user_service.get_current_user_info(db, current_user)
    return ApiResponse(data=data)
