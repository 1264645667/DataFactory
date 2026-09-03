"""执行回滚 Celery 任务（tasks.rollback_exec_task）

按 df_exec_rollback_log 逐批删除任务已写入的数据：
- MySQL values 模式：DELETE WHERE pk IN (...)（分批 1000）
- MySQL range 模式：DELETE WHERE pk BETWEEN start AND end（自增连续区间，精确）
- Redis keys 模式：DEL 逐 Key（分批 500）
- Redis del_key 模式：DEL 聚合 Key（多批次写同一 Key 时自动去重，只删一次）

处理顺序：回滚日志 id 倒序（关联表/后写批次先删，规避外键约束残留）。
单条日志失败不中断整体回滚，失败项回滚后可重新发起（rolled_back 仍为 0）。
"""
from __future__ import annotations

import json
from datetime import datetime

import structlog
from sqlalchemy import bindparam, text

from app.celery_app import celery_app
from app.db.session import SyncSessionLocal
from app.engine.db_pool import get_sync_engine
from app.engine.executor import _safe_ident
from app.engine.redis_pool import get_sync_redis
from app.models import ExecRollbackLog, ExecTask
from app.tasks.notify_helper import create_notification

logger = structlog.get_logger(__name__)

_DELETE_CHUNK = 1000   # MySQL IN 分批大小
_DEL_CHUNK = 500       # Redis DEL 分批大小


def _rollback_mysql_log(log: ExecRollbackLog, payload: dict) -> int:
    """回滚单条 MySQL 日志，返回删除行数"""
    engine = get_sync_engine(log.datasource_id)
    table = _safe_ident(log.table_name)
    pk = _safe_ident(payload["pk"])
    deleted = 0
    if payload["mode"] == "range":
        sql = text(f"DELETE FROM `{table}` WHERE `{pk}` BETWEEN :start AND :end")
        with engine.begin() as conn:
            result = conn.execute(sql, {"start": payload["start"], "end": payload["end"]})
        deleted = int(result.rowcount or 0)
    else:
        values = list(payload.get("values") or [])
        sql = text(f"DELETE FROM `{table}` WHERE `{pk}` IN :values").bindparams(
            bindparam("values", expanding=True)
        )
        for i in range(0, len(values), _DELETE_CHUNK):
            chunk = values[i:i + _DELETE_CHUNK]
            with engine.begin() as conn:
                result = conn.execute(sql, {"values": chunk})
            deleted += int(result.rowcount or 0)
    return deleted


def _rollback_redis_log(log: ExecRollbackLog, payload: dict, deleted_keys: set[str]) -> int:
    """回滚单条 Redis 日志，返回删除 Key 数（del_key 模式跨批次去重）"""
    client = get_sync_redis(log.datasource_id)
    keys = [k for k in (payload.get("keys") or []) if k not in deleted_keys]
    deleted_keys.update(keys)
    deleted = 0
    for i in range(0, len(keys), _DEL_CHUNK):
        chunk = keys[i:i + _DEL_CHUNK]
        if chunk:
            deleted += int(client.delete(*chunk))
    return deleted


@celery_app.task(bind=True, max_retries=0, acks_late=True, name="tasks.rollback_exec_task")
def rollback_exec_task(self, task_id: int, operator_id: int) -> dict:
    """任务回滚执行体（API 层已将 df_exec_task.rollback_status 置 1）"""
    logger.info("rollback_task_start", task_id=task_id, celery_task_id=self.request.id)
    session = SyncSessionLocal()
    deleted_keys: set[str] = set()  # del_key 模式去重
    total_deleted = 0
    failed_logs: list[str] = []
    try:
        task = session.get(ExecTask, task_id)
        if task is None:
            return {"task_id": task_id, "status": "failed", "error": "执行任务不存在"}

        logs = (
            session.query(ExecRollbackLog)
            .filter(ExecRollbackLog.task_id == task_id, ExecRollbackLog.rolled_back == 0)
            .order_by(ExecRollbackLog.id.desc())  # 逆序：关联表/后写批次先删
            .all()
        )
        for log in logs:
            try:
                payload = json.loads(log.pk_payload)
                if log.target_type == "redis":
                    deleted = _rollback_redis_log(log, payload, deleted_keys)
                else:
                    deleted = _rollback_mysql_log(log, payload)
                log.rolled_back = 1
                total_deleted += deleted
                session.commit()
            except Exception as exc:  # noqa: BLE001 — 单条失败不中断，整体收尾时汇总
                session.rollback()
                failed_logs.append(f"{log.target_type}:{log.table_name} 批次{log.batch_no}: {str(exc)[:200]}")
                logger.warning(
                    "rollback_log_failed", task_no=task.task_no,
                    target=f"{log.target_type}:{log.table_name}", batch_no=log.batch_no,
                    error=str(exc)[:300],
                )

        # 汇总终态：有失败项 → 3 回滚失败（可再次发起，剩余项 rolled_back 仍为 0）
        task = session.get(ExecTask, task_id)
        final_status = 3 if failed_logs else 2
        task.rollback_status = final_status
        task.rolled_back_at = datetime.now()
        task.rolled_back_by = operator_id
        if failed_logs:
            task.error_msg = f"回滚部分失败（{len(failed_logs)} 项）：{failed_logs[0]}"[:2000]
        session.commit()

        # 通知操作人
        try:
            if failed_logs:
                create_notification(
                    session, user_id=operator_id, msg_type="ROLLBACK_FAILED",
                    title="任务回滚部分失败",
                    content=f"Case「{task.case_name}」任务 {task.task_no} 回滚部分失败，"
                            f"已删除 {total_deleted:,} 条，{len(failed_logs)} 项失败，可重新发起回滚。",
                    link_url=f"/tasks/{task.task_no}", priority=1, group_type=task.group_type,
                )
            else:
                create_notification(
                    session, user_id=operator_id, msg_type="ROLLBACK_DONE",
                    title="任务回滚完成",
                    content=f"Case「{task.case_name}」任务 {task.task_no} 已回滚，"
                            f"共删除 {total_deleted:,} 条数据。",
                    link_url=f"/tasks/{task.task_no}", priority=3, group_type=task.group_type,
                )
            session.commit()
        except Exception:  # noqa: BLE001
            logger.warning("rollback_notify_failed", task_no=task.task_no)

        logger.info(
            "rollback_task_done", task_no=task.task_no,
            total_deleted=total_deleted, failed=len(failed_logs),
        )
        return {
            "task_id": task_id, "task_no": task.task_no,
            "status": "failed" if failed_logs else "success",
            "deleted": total_deleted, "failed_items": len(failed_logs),
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.exception("rollback_task_error", task_id=task_id)
        task = session.get(ExecTask, task_id)
        if task is not None:
            task.rollback_status = 3
            task.error_msg = f"回滚异常: {str(exc)[:500]}"[:2000]
            session.commit()
        return {"task_id": task_id, "status": "failed", "error": str(exc)[:500]}
    finally:
        session.close()
