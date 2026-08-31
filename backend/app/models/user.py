"""用户与权限体系模型（架构文档 4.1 DDL）。"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """用户表。"""

    __tablename__ = "df_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment="登录账号"
    )
    password: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="bcrypt哈希"
    )
    real_name: Mapped[str | None] = mapped_column(String(50), comment="真实姓名")
    group_type: Mapped[int] = mapped_column(
        TINYINT, nullable=False, comment="1=销项组 2=申报组 99=管理员"
    )
    status: Mapped[int] = mapped_column(
        TINYINT,
        nullable=False,
        default=0,
        comment="0=待审批 1=正常 2=禁用 3=已拒绝",
    )
    apply_reason: Mapped[str | None] = mapped_column(String(500), comment="申请理由")
    reject_reason: Mapped[str | None] = mapped_column(String(500), comment="拒绝原因")
    default_datasource_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="默认数据源ID"
    )
    avatar_index: Mapped[int | None] = mapped_column(
        TINYINT, default=1, comment="猫咪头像序号1-10"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="最后登录时间"
    )
    last_login_ip: Mapped[str | None] = mapped_column(String(50), comment="最后登录IP")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), server_onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_group_status", "group_type", "status"),
        {"comment": "用户表", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class Menu(Base):
    """菜单权限表。"""

    __tablename__ = "df_menu"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    menu_code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment="权限编码，如ENGINE:EXECUTE"
    )
    menu_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="菜单名称")
    parent_code: Mapped[str | None] = mapped_column(String(50), comment="父菜单编码")
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="排序"
    )
    icon: Mapped[str | None] = mapped_column(String(100), comment="图标名称")

    __table_args__ = (
        {"comment": "菜单权限表", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class UserMenu(Base):
    """用户菜单关联表。"""

    __tablename__ = "df_user_menu"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    menu_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    __table_args__ = (
        Index("idx_user", "user_id"),
        {"comment": "用户菜单关联表", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class AiApiKey(Base):
    """AI接口API Key表（二期预留）。"""

    __tablename__ = "df_ai_api_key"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="Key名称")
    api_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="df_ai_前缀+32位hex"
    )
    permissions: Mapped[list | None] = mapped_column(JSON, comment="允许的接口权限范围")
    rate_limit: Mapped[int | None] = mapped_column(
        Integer, default=100, comment="每分钟请求限制"
    )
    expire_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="过期时间，NULL=永不过期"
    )
    status: Mapped[int | None] = mapped_column(
        TINYINT, default=1, comment="1=启用 0=禁用"
    )
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_api_key", "api_key"),
        {"comment": "AI接口API Key表", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )
