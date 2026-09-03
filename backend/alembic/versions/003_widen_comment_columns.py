"""放宽缓存表长文本字段为 TEXT（修复超长 column_comment 同步失败 1406）

- df_column_cache.column_comment: VARCHAR(500) → TEXT
- df_column_cache.column_default: VARCHAR(500) → TEXT
- df_table_cache.table_comment: VARCHAR(500) → TEXT
- df_index_cache.column_names: VARCHAR(500) → TEXT
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALTERS = [
    ("df_column_cache", "column_comment", "字段备注", True),
    ("df_column_cache", "column_default", "默认值", True),
    ("df_table_cache", "table_comment", "表备注", True),
    ("df_index_cache", "column_names", "JSON数组，字段名列表", False),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, column, comment, nullable in _ALTERS:
        cols = {c["name"]: c for c in insp.get_columns(table)}
        current = cols.get(column)
        # 已是 TEXT 则跳过（幂等可重复执行）
        if current is not None and isinstance(current["type"], sa.Text):
            continue
        op.alter_column(
            table, column,
            existing_type=sa.String(500),
            type_=sa.Text(),
            existing_nullable=nullable,
            comment=comment,
        )


def downgrade() -> None:
    for table, column, comment, nullable in _ALTERS:
        op.alter_column(
            table, column,
            existing_type=sa.Text(),
            type_=sa.String(500),
            existing_nullable=nullable,
            comment=comment,
        )
