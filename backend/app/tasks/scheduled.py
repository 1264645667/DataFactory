"""Celery Beat 定时任务配置（架构文档 2.3.3）与定时清理任务

- 每天 02:00：全量数据源表结构同步
- 每 30 秒：数据源连接状态心跳检测
- 每天 03:00：消息通知清理（PRD 11.6）

celery_app 侧引入方式：from app.tasks.scheduled import CELERYBEAT_SCHEDULE
并设置 celery_app.conf.beat_schedule = CELERYBEAT_SCHEDULE。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from celery.schedules import crontab
from sqlalchemy import text

from app.celery_app import celery_app
from app.db.session import SyncSessionLocal

logger = structlog.get_logger(__name__)

# 定时任务调度表
CELERYBEAT_SCHEDULE = {
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
    # 每天凌晨 03:00 清理过期消息通知
    "clean-notifications": {
        "task": "tasks.clean_notifications",
        "schedule": crontab(hour=3, minute=0),
    },
}

# 消息保留策略（PRD 11.6）：优先级 -> 保留天数
NOTIFICATION_RETENTION_DAYS = {
    1: 90,   # 高优先级（红）90 天
    2: 30,   # 中优先级（黄）30 天
    3: 14,   # 普通（绿）14 天
}
# 每用户最多保留消息条数（超出按时间倒序保留最新）
NOTIFICATION_MAX_PER_USER = 500


@celery_app.task(bind=True, max_retries=0, name="tasks.clean_notifications")
def clean_notifications(self) -> dict:
    """消息通知清理（PRD 11.6，软删除）

    1. 按优先级分级保留：高 90 天 / 中 30 天 / 普通 14 天，过期软删除
    2. 每用户最多保留 500 条未删除消息，超出部分按时间倒序软删除最旧的
    """
    session = SyncSessionLocal()
    try:
        now = datetime.now()
        expired_total = 0
        for priority, days in NOTIFICATION_RETENTION_DAYS.items():
            cutoff = now - timedelta(days=days)
            result = session.execute(
                text(
                    "UPDATE df_notification SET is_deleted = 1 "
                    "WHERE is_deleted = 0 AND priority = :priority AND created_at < :cutoff"
                ),
                {"priority": priority, "cutoff": cutoff},
            )
            expired_total += result.rowcount or 0
        session.commit()

        # 每用户超量清理：找出未删除消息超 500 条的用户
        over_limit_users = session.execute(
            text(
                "SELECT user_id, COUNT(*) AS cnt FROM df_notification "
                "WHERE is_deleted = 0 GROUP BY user_id HAVING cnt > :max_count"
            ),
            {"max_count": NOTIFICATION_MAX_PER_USER},
        ).fetchall()

        trimmed_total = 0
        for user_id, _count in over_limit_users:
            # 取第 500 名之后的所有消息 ID（按时间倒序，最旧的在前）
            rows = session.execute(
                text(
                    "SELECT id FROM df_notification WHERE user_id = :user_id AND is_deleted = 0 "
                    "ORDER BY created_at DESC, id DESC LIMIT :skip, 100000"
                ),
                {"user_id": user_id, "skip": NOTIFICATION_MAX_PER_USER},
            ).fetchall()
            ids = [row[0] for row in rows]
            # 分块软删除（参数化 IN，避免超长 SQL）
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ", ".join(f":id{j}" for j in range(len(chunk)))
                params = {f"id{j}": value for j, value in enumerate(chunk)}
                session.execute(
                    text(f"UPDATE df_notification SET is_deleted = 1 WHERE id IN ({marks})"),
                    params,
                )
                trimmed_total += len(chunk)
        session.commit()

        logger.info(
            "clean_notifications_done",
            expired=expired_total, trimmed=trimmed_total, over_limit_users=len(over_limit_users),
        )
        return {"expired": expired_total, "trimmed": trimmed_total}
    finally:
        session.close()
