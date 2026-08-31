"""消息通知模型（架构文档 4.1 DDL）。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notification(Base):
    """系统消息通知表。"""

    __tablename__ = "df_notification"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="接收用户ID")
    msg_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment=(
            "消息类型：USER_APPLY/APPLY_APPROVED/APPLY_REJECTED/EXEC_SUCCESS/EXEC_FAILED/"
            "EXEC_PARTIAL/SCENE_SUCCESS/SCENE_FAILED/SCENE_PARTIAL/DS_SYNC_DONE/"
            "DS_SYNC_FAILED/DS_OFFLINE/PERMISSION_CHANGED"
        ),
    )
    priority: Mapped[int] = mapped_column(
        TINYINT,
        nullable=False,
        default=2,
        comment="优先级：1=高(红) 2=中(黄) 3=普通(绿)",
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="消息标题")
    content: Mapped[str] = mapped_column(String(1000), nullable=False, comment="消息正文")
    link_url: Mapped[str | None] = mapped_column(
        String(500), comment="关联跳转路径（相对路径）"
    )
    is_read: Mapped[int] = mapped_column(
        TINYINT, nullable=False, default=0, comment="0=未读 1=已读"
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime, comment="阅读时间")
    is_deleted: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0)
    group_type: Mapped[int] = mapped_column(
        TINYINT, nullable=False, comment="接收人所属分组，管理员填99"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_user_read", "user_id", "is_read", "is_deleted"),
        Index("idx_user_created", "user_id", "created_at"),
        Index("idx_group_type", "group_type", "msg_type"),
        {"comment": "系统消息通知表", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )
