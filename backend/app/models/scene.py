"""场景管理模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Scene(Base):
    """场景表。"""

    __tablename__ = "df_scene"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scene_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="场景名称"
    )
    description: Mapped[str | None] = mapped_column(String(500), comment="场景描述")
    # nodes_json 存储节点列表，exec_mode 由后端计算后冗余存储
    nodes_json: Mapped[str] = mapped_column(
        MEDIUMTEXT, nullable=False, comment="节点配置JSON数组"
    )
    edges_json: Mapped[str] = mapped_column(
        MEDIUMTEXT, nullable=False, default="[]", comment="连线关系JSON数组"
    )
    node_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="节点总数"
    )
    exec_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="serial",
        comment="serial=纯串行 parallel=纯并行 mixed=混合",
    )
    group_type: Mapped[int] = mapped_column(
        TINYINT, nullable=False, comment="1=销项组 2=申报组"
    )
    is_deleted: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0)
    last_exec_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="最后执行时间"
    )
    last_exec_status: Mapped[int | None] = mapped_column(
        TINYINT, comment="0=未执行 1=成功 2=失败 3=部分成功 4=已中止"
    )
    exec_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), server_onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_group", "group_type", "is_deleted"),
        Index("idx_creator", "created_by"),
        {"comment": "场景表", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class SceneExec(Base):
    """场景执行记录表。"""

    __tablename__ = "df_scene_exec"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scene_exec_no: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        comment="场景执行编号（雪花ID，SC前缀）",
    )
    scene_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scene_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="冗余场景名"
    )
    scene_snapshot: Mapped[str] = mapped_column(
        MEDIUMTEXT, nullable=False, comment="执行时场景配置快照（nodes+edges）"
    )
    node_count: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="本次执行节点总数"
    )
    success_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="成功节点数"
    )
    fail_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="失败/已取消节点数"
    )
    total_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="所有节点成功插入条数之和"
    )
    status: Mapped[int] = mapped_column(
        TINYINT,
        nullable=False,
        default=0,
        comment="0=待执行 1=执行中 2=成功 3=失败 4=部分成功 5=已中止",
    )
    error_msg: Mapped[str | None] = mapped_column(Text, comment="失败摘要")
    start_at: Mapped[datetime | None] = mapped_column(DateTime)
    finish_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, comment="总耗时毫秒")
    group_type: Mapped[int] = mapped_column(TINYINT, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_scene", "scene_id"),
        Index("idx_scene_exec_no", "scene_exec_no"),
        Index("idx_group_created", "group_type", "created_at"),
        {"comment": "场景执行记录表", "mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class SceneNodeExec(Base):
    """场景节点执行明细表。"""

    __tablename__ = "df_scene_node_exec"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scene_exec_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="关联 df_scene_exec.id"
    )
    node_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="节点唯一ID（前端生成UUID，用于关联edges）"
    )
    case_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    case_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="冗余Case名"
    )
    layer_no: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="拓扑分层序号（0=第一批）"
    )
    target_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="本节点造数目标条数"
    )
    success_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    exec_task_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="关联 df_exec_task.id（节点实际执行的任务）"
    )
    exec_task_no: Mapped[str | None] = mapped_column(
        String(64), comment="冗余 task_no，方便查询"
    )
    fail_strategy: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="continue",
        comment="continue=继续执行 abort=终止场景",
    )
    status: Mapped[int] = mapped_column(
        TINYINT,
        nullable=False,
        default=0,
        comment="0=待执行 1=执行中 2=成功 3=失败 4=已取消（前置终止）",
    )
    error_msg: Mapped[str | None] = mapped_column(Text)
    start_at: Mapped[datetime | None] = mapped_column(DateTime)
    finish_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_scene_exec", "scene_exec_id"),
        Index("idx_case", "case_id"),
        Index("idx_exec_task", "exec_task_id"),
        {
            "comment": "场景节点执行明细表",
            "mysql_charset": "utf8mb4",
            "mysql_engine": "InnoDB",
        },
    )
