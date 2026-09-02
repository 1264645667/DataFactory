"""初始建表（所有 DDL）

全部 16 张表（df_ 前缀）：
  用户与权限：df_user / df_menu / df_user_menu / df_ai_api_key
  数据源与缓存：df_datasource / df_table_cache / df_column_cache / df_index_cache
  造数 Case：df_case
  执行任务与日志：df_exec_task / df_exec_batch_log / df_audit_log
  场景管理：df_scene / df_scene_exec / df_scene_node_exec
  消息通知：df_notification

 补充索引：df_case.idx_group_created_at、df_audit_log.idx_user_created、
  df_exec_batch_log.idx_task_round

实现方式说明：直接基于 ORM metadata 建表，保证迁移结果与 app/models 完全一致，
避免 DDL 与模型双写漂移；后续变更使用 alembic revision --autogenerate 生成增量迁移。
"""

from typing import Sequence, Union

from alembic import op

from app.db.base import Base
from app import models  # noqa: F401  # 确保全部模型注册到 metadata

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
