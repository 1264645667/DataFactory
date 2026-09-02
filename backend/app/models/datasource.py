"""数据源配置模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Datasource(Base):
    """数据源配置表。"""

    __tablename__ = "df_datasource"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, comment="数据源名称"
    )
    db_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="MySQL", comment="数据库类型"
    )
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=3306)
    database_name: Mapped[str] = mapped_column(String(100), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    password: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="AES-256加密"
    )
    group_type: Mapped[int] = mapped_column(
        TINYINT, nullable=False, comment="1=销项组 2=申报组"
    )
    status: Mapped[int] = mapped_column(
        TINYINT,
        nullable=False,
        default=0,
        comment="0=未初始化 1=正常 2=异常 3=同步中",
    )
    remark: Mapped[str | None] = mapped_column(String(500))
    table_count: Mapped[int | None] = mapped_column(
        Integer, default=0, comment="已缓存表数量"
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="最后表结构同步时间"
    )
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), server_onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_group", "group_type", "status"),
        {"comment": "数据源配置表", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )
