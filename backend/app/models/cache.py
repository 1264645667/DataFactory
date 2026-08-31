"""数据源表结构本地缓存模型（架构文档 4.1 DDL）。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TableCache(Base):
    """数据源表信息缓存。"""

    __tablename__ = "df_table_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    table_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="表名")
    table_comment: Mapped[str | None] = mapped_column(String(500), comment="表备注")
    table_rows: Mapped[int | None] = mapped_column(
        BigInteger, default=0, comment="估算行数(information_schema)"
    )
    data_length: Mapped[int | None] = mapped_column(
        BigInteger, default=0, comment="数据大小(bytes)"
    )
    engine: Mapped[str | None] = mapped_column(String(50), comment="存储引擎")
    charset: Mapped[str | None] = mapped_column(String(50), comment="字符集")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="表创建时间")
    column_count: Mapped[int | None] = mapped_column(
        Integer, default=0, comment="字段数量"
    )
    pk_type: Mapped[str | None] = mapped_column(
        String(20), default="none", comment="none/single/composite"
    )
    unique_index_count: Mapped[int | None] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="缓存同步时间"
    )

    __table_args__ = (
        UniqueConstraint("datasource_id", "table_name", name="uk_ds_table"),
        Index("idx_datasource", "datasource_id"),
        {"comment": "数据源表信息缓存", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class ColumnCache(Base):
    """数据源字段信息缓存。"""

    __tablename__ = "df_column_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    table_name: Mapped[str] = mapped_column(String(200), nullable=False)
    column_name: Mapped[str] = mapped_column(String(200), nullable=False)
    column_comment: Mapped[str | None] = mapped_column(String(500), comment="字段备注")
    data_type: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="基础类型: varchar/int/datetime等"
    )
    column_type: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="完整类型: varchar(255)/int(11)等"
    )
    is_nullable: Mapped[int] = mapped_column(
        TINYINT, nullable=False, default=1, comment="0=NOT NULL 1=NULL"
    )
    is_primary_key: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0)
    is_unique: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0)
    column_default: Mapped[str | None] = mapped_column(String(500), comment="默认值")
    char_max_length: Mapped[int | None] = mapped_column(
        Integer, comment="varchar最大长度"
    )
    numeric_precision: Mapped[int | None] = mapped_column(Integer, comment="数字精度")
    numeric_scale: Mapped[int | None] = mapped_column(Integer, comment="小数位数")
    ordinal_position: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="字段顺序"
    )
    extra: Mapped[str | None] = mapped_column(String(100), comment="auto_increment等")
    synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "datasource_id", "table_name", "column_name", name="uk_ds_table_col"
        ),
        Index("idx_ds_table", "datasource_id", "table_name"),
        {"comment": "数据源字段信息缓存", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class IndexCache(Base):
    """数据源索引信息缓存。"""

    __tablename__ = "df_index_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    table_name: Mapped[str] = mapped_column(String(200), nullable=False)
    index_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_unique: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0)
    is_primary: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0)
    column_names: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="JSON数组，字段名列表"
    )
    seq_in_index: Mapped[int | None] = mapped_column(Integer, comment="联合索引中的位置")
    synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_ds_table", "datasource_id", "table_name"),
        {"comment": "数据源索引信息缓存", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )
