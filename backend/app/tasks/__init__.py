"""Celery 任务包

导入各任务模块使 @celery_app.task 装饰器完成注册
（供 celery_app 的 include=["app.tasks"] 或 autodiscover 使用）。
"""
from app.tasks import execute_task, rollback_task, scene_task, sync_task  # noqa: F401
from app.tasks import scheduled  # noqa: F401  # CELERYBEAT_SCHEDULE 与定时清理任务
