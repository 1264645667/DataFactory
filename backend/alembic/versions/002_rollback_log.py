"""执行回滚支持 + Redis 造数配套变更

- 新增表 df_exec_rollback_log（一键回滚的批次级定位数据）
- df_exec_task 新增列 rollback_status / rolled_back_at / rolled_back_by

实现方式：新表走 Base.metadata.create_all（仅创建缺失表）；
已有表新增列用 op.add_column（先 inspect 判存在，保证幂等可重复执行）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import TINYINT

from app.db.base import Base
from app import models  # noqa: F401  # 确保全部模型注册到 metadata

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # 仅创建缺失的新表（df_exec_rollback_log），已有表不受影响
    Base.metadata.create_all(bind=bind)

    # df_exec_task 新增回滚状态列（幂等：已存在则跳过）
    insp = sa.inspect(bind)
    existing = {col["name"] for col in insp.get_columns("df_exec_task")}
    if "rollback_status" not in existing:
        op.add_column(
            "df_exec_task",
            sa.Column(
                "rollback_status", TINYINT, nullable=False, server_default="0",
                comment="0=未回滚 1=回滚中 2=已回滚 3=回滚失败",
            ),
        )
    if "rolled_back_at" not in existing:
        op.add_column(
            "df_exec_task",
            sa.Column("rolled_back_at", sa.DateTime, nullable=True, comment="回滚完成时间"),
        )
    if "rolled_back_by" not in existing:
        op.add_column(
            "df_exec_task",
            sa.Column("rolled_back_by", sa.BigInteger, nullable=True, comment="回滚操作人"),
        )


def downgrade() -> None:
    op.drop_column("df_exec_task", "rolled_back_by")
    op.drop_column("df_exec_task", "rolled_back_at")
    op.drop_column("df_exec_task", "rollback_status")
    op.drop_table("df_exec_rollback_log")
