"""Celery 应用实例。

- broker / backend 均使用 Redis（减少中间件）
- 任务路由：造数执行/场景调度→high，数据源同步→normal，心跳/定时→low
- 时区 Asia/Shanghai
- Beat 使用默认调度器（不使用 django_celery_beat，依赖中不含该包）
"""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "dataforge",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)

celery_app.conf.update(
    # 时区
    timezone=settings.TZ,
    enable_utc=False,
    # 任务队列路由
    task_routes={
        "tasks.execute_data_gen": {"queue": "high"},  # 造数执行，高优先
        "tasks.execute_scene": {"queue": "high"},  # 场景调度，高优先
        "tasks.sync_datasource": {"queue": "normal"},  # 数据源同步
        "tasks.rollback_exec_task": {"queue": "normal"},  # 执行回滚
        "tasks.heartbeat_check": {"queue": "low"},  # 心跳检测
    },
    task_default_queue="normal",
    # 可靠性消费后再 ack，防止 Worker 崩溃丢任务
    task_acks_late=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    # 任务结果保留 24h
    result_expires=86400,
    broker_connection_retry_on_startup=True,
)

# Celery Beat 定时任务
celery_app.conf.beat_schedule = {
    # 每天凌晨 02:00 同步所有数据源表结构
    "sync-all-datasources": {
        "task": "tasks.scheduled_sync_all",
        "schedule": crontab(hour=2, minute=0),
    },
    # 每 30 秒心跳检测所有数据源连接状态
    "heartbeat-check": {
        "task": "tasks.heartbeat_check",
        "schedule": 30.0,
    },
    # 每天凌晨 03:00 清理过期消息
    "cleanup-notifications": {
        "task": "tasks.clean_notifications",
        "schedule": crontab(hour=3, minute=0),
    },
    # 每天凌晨 03:30 清理操作日志（每人仅保留最近 200 条）
    "clean-audit-logs": {
        "task": "tasks.clean_audit_logs",
        "schedule": crontab(hour=3, minute=30),
    },
}
