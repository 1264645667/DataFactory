"""场景执行 Celery 任务（DAG 调度）

- 队列：high（CELERY_TASK_ROUTES: tasks.execute_scene）
- 场景调度任务本身消耗资源极少（轮询等待 + 触发子任务），与造数执行同队列避免调度延迟
- 任务结束写 SCENE_SUCCESS / SCENE_FAILED / SCENE_PARTIAL 消息通知
"""
from __future__ import annotations

import structlog

from app.celery_app import celery_app
from app.db.session import SyncSessionLocal
from app.engine import scene_executor
from app.models import SceneExec
from app.tasks.notify_helper import create_notification

logger = structlog.get_logger(__name__)


def _format_duration(duration_ms: int | None) -> str:
    """耗时格式化：1h 2m 3s / 2m 34s / 45s"""
    if not duration_ms:
        return "0s"
    seconds = max(0, int(duration_ms) // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


@celery_app.task(
    bind=True,
    max_retries=0,
    acks_late=True,
    track_started=True,
    name="tasks.execute_scene",
)
def execute_scene(self, scene_exec_id: int) -> dict:
    """场景执行主任务：负责 DAG 调度，不直接插入数据"""
    logger.info("execute_scene_start", scene_exec_id=scene_exec_id, celery_task_id=self.request.id)
    result = scene_executor.execute_scene_task(scene_exec_id)
    _notify_scene_result(result, scene_exec_id)
    return result


@celery_app.task(
    bind=True,
    max_retries=0,
    acks_late=True,
    track_started=True,
    name="tasks.retry_scene_nodes",
)
def retry_scene_nodes(self, scene_exec_id: int, node_ids: list[str]) -> dict:
    """重试失败节点入口仅重跑选中节点，结果追加到本次场景执行记录"""
    logger.info(
        "retry_scene_nodes_start",
        scene_exec_id=scene_exec_id, node_ids=node_ids, celery_task_id=self.request.id,
    )
    result = scene_executor.retry_failed_nodes(scene_exec_id, node_ids)
    _notify_scene_result(result, scene_exec_id)
    return result


def _notify_scene_result(result: dict, scene_exec_id: int) -> None:
    """场景执行结束生成消息通知（SCENE_SUCCESS/SCENE_FAILED/SCENE_PARTIAL）"""
    status_str = result.get("status")
    if status_str in (None, "skipped"):
        return

    session = SyncSessionLocal()
    try:
        scene_exec = session.get(SceneExec, scene_exec_id)
        if scene_exec is None:
            return
        node_count = int(scene_exec.node_count or 0)
        success_nodes = int(scene_exec.success_count or 0)
        fail_nodes = int(scene_exec.fail_count or 0)
        total_rows = int(scene_exec.total_rows or 0)
        duration = _format_duration(scene_exec.duration_ms)

        if status_str == "success":
            msg_type, priority, title = "SCENE_SUCCESS", 3, "场景执行成功"
            content = (
                f"场景「{scene_exec.scene_name}」执行成功，共 {node_count} 个节点，"
                f"成功插入 {total_rows:,} 条数据，耗时 {duration}。"
            )
        elif status_str == "partial_success":
            msg_type, priority, title = "SCENE_PARTIAL", 2, "场景执行部分成功"
            content = (
                f"场景「{scene_exec.scene_name}」部分成功：成功节点 {success_nodes}/{node_count}，"
                f"失败 {fail_nodes} 个，成功插入 {total_rows:,} 条数据，耗时 {duration}。"
                f"可在执行详情页重试失败节点。"
            )
        else:
            msg_type, priority, title = "SCENE_FAILED", 1, "场景执行失败"
            error_msg = (result.get("error") or scene_exec.error_msg or "")[:200]
            content = (
                f"场景「{scene_exec.scene_name}」执行失败：成功节点 {success_nodes}/{node_count}，"
                f"成功插入 {total_rows:,} 条数据。错误摘要：{error_msg}"
            )

        create_notification(
            session,
            user_id=scene_exec.created_by,
            msg_type=msg_type,
            title=title,
            content=content,
            link_url=f"/scenes/exec/{scene_exec.scene_exec_no}",
            priority=priority,
            group_type=scene_exec.group_type,
        )
        session.commit()
        logger.info("scene_notification_sent", scene_exec_no=scene_exec.scene_exec_no, msg_type=msg_type)
    finally:
        session.close()
