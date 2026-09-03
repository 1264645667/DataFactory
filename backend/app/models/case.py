"""造数 Case 模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CaseFolder(Base):
    """Case 文件夹（收纳分类，按分组隔离，平铺不嵌套）。"""

    __tablename__ = "df_case_folder"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="文件夹名称")
    group_type: Mapped[int] = mapped_column(TINYINT, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("group_type", "name", name="uk_group_name"),
        {"comment": "Case 文件夹", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class Case(Base):
    """造数Case表。"""

    __tablename__ = "df_case"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="Case名称"
    )
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    datasource_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="冗余，防数据源改名后显示异常"
    )
    folder_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="所属文件夹（NULL=未分类）"
    )
    main_table: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="主操作表"
    )
    related_tables: Mapped[str | None] = mapped_column(
        String(1000), comment="关联表名JSON数组"
    )
    related_count: Mapped[int | None] = mapped_column(
        Integer, default=0, comment="关联表数量"
    )
    config_json: Mapped[str] = mapped_column(
        MEDIUMTEXT, nullable=False, comment="完整配置JSON（字段策略+关联关系）"
    )
    group_type: Mapped[int] = mapped_column(TINYINT, nullable=False)
    is_deleted: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0)
    last_exec_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="最后执行时间"
    )
    last_exec_status: Mapped[int | None] = mapped_column(
        TINYINT, comment="0=未执行 1=成功 2=失败 3=部分成功"
    )
    exec_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="历史执行次数"
    )
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), server_onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_group_ds", "group_type", "datasource_id"),
        Index("idx_creator", "created_by"),
        Index("idx_main_table", "datasource_id", "main_table"),
        # 补充索引：列表页按创建时间倒序 + 分组过滤
        Index("idx_group_created_at", "group_type", "is_deleted", "created_at"),
        # 文件夹过滤
        Index("idx_group_folder", "group_type", "folder_id"),
        {"comment": "造数Case表", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )
