"""执行任务与日志模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExecTask(Base):
    """造数执行任务表。"""

    __tablename__ = "df_exec_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_no: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="任务编号（雪花ID）"
    )
    case_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    case_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="冗余Case名"
    )
    case_snapshot: Mapped[str] = mapped_column(
        MEDIUMTEXT, nullable=False, comment="执行时Case配置快照"
    )
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    datasource_name: Mapped[str] = mapped_column(String(100), nullable=False)
    main_table: Mapped[str] = mapped_column(String(200), nullable=False)
    related_tables: Mapped[str | None] = mapped_column(String(1000), comment="JSON数组")
    target_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="目标造数条数"
    )
    success_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0)
    celery_task_id: Mapped[str | None] = mapped_column(
        String(100), comment="Celery任务ID，用于发送revoke强制停止"
    )
    status: Mapped[int] = mapped_column(
        TINYINT,
        nullable=False,
        default=0,
        comment="0=待执行 1=执行中 2=成功 3=失败 4=重试中 5=部分成功 6=已中止",
    )
    error_msg: Mapped[str | None] = mapped_column(Text, comment="失败时的错误摘要")
    start_at: Mapped[datetime | None] = mapped_column(DateTime)
    finish_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, comment="总耗时毫秒")
    group_type: Mapped[int] = mapped_column(TINYINT, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_case", "case_id"),
        Index("idx_task_no", "task_no"),
        Index("idx_group_status", "group_type", "status"),
        Index("idx_group_created", "group_type", "created_at"),
        {"comment": "造数执行任务表", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class ExecBatchLog(Base):
    """执行批次日志（断点续传依据）。

    含遍历模式扩展列 round_no / drive_value。
    """

    __tablename__ = "df_exec_batch_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    table_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="插入的目标表"
    )
    batch_no: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="批次序号（从0开始）"
    )
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="本批条数")
    status: Mapped[int] = mapped_column(
        TINYINT, nullable=False, default=0, comment="0=待执行 1=成功 2=失败"
    )
    retry_times: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0)
    error_msg: Mapped[str | None] = mapped_column(Text)
    start_at: Mapped[datetime | None] = mapped_column(DateTime)
    finish_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # ── ITERATE_LIST 遍历模式扩展列 ──
    round_no: Mapped[int | None] = mapped_column(
        SmallInteger, comment="遍历模式轮次序号（从0开始）"
    )
    drive_value: Mapped[str | None] = mapped_column(
        String(500), comment="遍历模式当前驱动值"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_task", "task_id"),
        Index("idx_task_table", "task_id", "table_name"),
        # 补充索引：遍历模式按 round_no 重试查询
        Index("idx_task_round", "task_id", "round_no", "status"),
        {
            "comment": "执行批次日志（断点续传依据）",
            "mysql_charset": "utf8mb4",
            "mysql_engine": "InnoDB",
        },
    )


class AuditLog(Base):
    """操作审计日志（不可删除）。"""

    __tablename__ = "df_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="LOGIN/LOGOUT/CREATE_CASE/EXEC_TASK/DELETE_CASE/ADD_DS/DEL_DS/APPROVE_USER等",
    )
    resource: Mapped[str | None] = mapped_column(String(100), comment="操作对象类型")
    resource_id: Mapped[str | None] = mapped_column(String(50), comment="操作对象ID")
    detail: Mapped[str | None] = mapped_column(Text, comment="操作详情JSON")
    ip: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_user", "user_id"),
        Index("idx_action", "action"),
        Index("idx_created", "created_at"),
        # 补充索引：按用户+时间（个人日志）
        Index("idx_user_created", "user_id", "created_at"),
        {
            "comment": "操作审计日志（不可删除）",
            "mysql_charset": "utf8mb4",
            "mysql_engine": "InnoDB",
        },
    )
