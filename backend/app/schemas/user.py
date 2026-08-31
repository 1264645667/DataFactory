"""用户与认证模块请求/响应 Schema（API 清单 10.1/10.2 + PRD 第 2 章）。"""

from datetime import datetime

from pydantic import BaseModel, Field


# ── 认证 ────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class UserBrief(BaseModel):
    """用户简要信息。"""

    id: int
    username: str
    real_name: str | None = None
    group_type: int  # 1=销项组 2=申报组 99=管理员
    avatar_index: int | None = 1


class LoginResponse(BaseModel):
    """登录响应：JWT Token + 用户信息。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="有效期（秒）")
    user: UserBrief


class RegisterRequest(BaseModel):
    """注册申请（PRD 2.6 字段校验规则）。"""

    username: str = Field(
        min_length=4, max_length=20, pattern=r"^\w+$", description="4~20位字母/数字/下划线"
    )
    password: str = Field(min_length=8, max_length=128, description="≥8位且含数字和字母")
    real_name: str = Field(min_length=2, max_length=20)
    group_type: int = Field(description="申请分组：1=销项组 2=申报组")
    apply_reason: str | None = Field(default=None, max_length=200)


class CurrentUserResponse(BaseModel):
    """GET /auth/me 响应：当前用户信息及权限列表。"""

    id: int
    username: str
    real_name: str | None = None
    group_type: int
    status: int
    avatar_index: int | None = 1
    default_datasource_id: int | None = None
    permissions: list[str] = []
    last_login_at: datetime | None = None


# ── 用户管理（管理员）─────────────────────────────────────────


class PendingUserItem(BaseModel):
    """待审批用户列表项。"""

    id: int
    username: str
    real_name: str | None = None
    group_type: int
    apply_reason: str | None = None
    created_at: datetime


class UserListItem(BaseModel):
    """全部用户列表项。"""

    id: int
    username: str
    real_name: str | None = None
    group_type: int
    status: int  # 0=待审批 1=正常 2=禁用 3=已拒绝
    default_datasource_id: int | None = None
    permissions: list[str] = []
    last_login_at: datetime | None = None
    created_at: datetime


class ApproveRequest(BaseModel):
    """审批通过并分配菜单权限。"""

    menu_ids: list[int] = Field(default_factory=list, description="授权的 df_menu.id 列表")


class RejectRequest(BaseModel):
    """审批拒绝（必填拒绝原因）。"""

    reject_reason: str = Field(min_length=1, max_length=500)


class PermissionUpdateRequest(BaseModel):
    """更新用户菜单权限。"""

    menu_ids: list[int] = Field(default_factory=list)


class ResetPasswordResponse(BaseModel):
    """重置密码响应（返回临时密码）。"""

    temp_password: str


# ── 个人中心 ──────────────────────────────────────────────────


class PasswordChangeRequest(BaseModel):
    """修改自己密码（需验证旧密码）。"""

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128, description="≥8位且含数字和字母")


class AvatarUpdateRequest(BaseModel):
    """更新头像序号（预设 10 款猫咪头像）。"""

    avatar_index: int = Field(ge=1, le=10)


class DefaultDatasourceRequest(BaseModel):
    """设置默认数据源。"""

    datasource_id: int | None = None


# ── 操作日志 ──────────────────────────────────────────────────


class AuditLogItem(BaseModel):
    """操作日志列表项。"""

    id: int
    user_id: int
    username: str
    real_name: str | None = None
    group_type: int | None = None
    action: str
    resource: str | None = None
    resource_id: str | None = None
    detail: str | None = None
    ip: str | None = None
    created_at: datetime
