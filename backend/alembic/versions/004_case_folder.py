"""Case 文件夹收纳

- 新增表 df_case_folder（按分组隔离，组内名称唯一）
- df_case 新增列 folder_id（NULL=未分类）+ idx_group_folder 索引
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.base import Base
from app import models  # noqa: F401  # 确保全部模型注册到 metadata

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # 仅创建缺失的新表（df_case_folder）
    Base.metadata.create_all(bind=bind)

    insp = sa.inspect(bind)
    existing_cols = {c["name"] for c in insp.get_columns("df_case")}
    if "folder_id" not in existing_cols:
        op.add_column(
            "df_case",
            sa.Column("folder_id", sa.BigInteger, nullable=True, comment="所属文件夹（NULL=未分类）"),
        )
    existing_indexes = {idx["name"] for idx in insp.get_indexes("df_case")}
    if "idx_group_folder" not in existing_indexes:
        op.create_index("idx_group_folder", "df_case", ["group_type", "folder_id"])


def downgrade() -> None:
    op.drop_index("idx_group_folder", "df_case")
    op.drop_column("df_case", "folder_id")
    op.drop_table("df_case_folder")
