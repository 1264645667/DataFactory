"""造数执行 Celery 任务（单 Case）

- 队列：high（CELERY_TASK_ROUTES: tasks.execute_data_gen）
- 任务级不重试（max_retries=0），重试在引擎内部批次级完成
- acks_late=True：消费后再 ack，防止 Worker 崩溃丢任务
- 场景节点任务（带 scene_exec_no/node_id）完成后回写场景进度，不发 EXEC_* 通知
  （场景整体通知由 tasks.scene_task 统一发送）
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import structlog

from app.celery_app import celery_app
from app.core.redis_client import sync_redis_client
from app.db.session import SyncSessionLocal
from app.engine import executor
from app.models import ExecTask, SceneExec, SceneNodeExec
from app.tasks.notify_helper import create_notification

logger = structlog.get_logger(__name__)

# df_scene_node_exec.status
_NODE_STATUS_SUCCESS = 2
_NODE_STATUS_FAILED = 3


def _decode(value: Any) -> Any:
    """Redis 返回值兼容 bytes/str"""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


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
    max_retries=0,        # 任务级不重试，内部批次级重试
    acks_late=True,       # 消费后再 ack，防止 Worker 崩溃丢任务
    track_started=True,
    name="tasks.execute_data_gen",
)
def execute_data_gen(self, task_id: int, scene_exec_no: str | None = None,
                     node_id: str | None = None) -> dict:
    """单 Case 造数执行任务

    :param task_id: df_exec_task.id
    :param scene_exec_no: 场景执行编号（场景节点任务时传入）
    :param node_id: 场景节点 ID（场景节点任务时传入）
    """
    logger.info(
        "execute_data_gen_start",
        task_id=task_id, celery_task_id=self.request.id,
        scene_exec_no=scene_exec_no, node_id=node_id,
    )
    # 回写 celery_task_id（供「强制停止」发送 revoke 信号）
    session = SyncSessionLocal()
    try:
        task = session.get(ExecTask, task_id)
        if task is not None:
            task.celery_task_id = self.request.id
            session.commit()
    finally:
        session.close()

    # 调用造数引擎执行核心
    result = executor.execute_case_task(task_id)

    if scene_exec_no and node_id:
        # 场景节点任务：回写场景节点进度（场景调度器轮询依据）
        _writeback_scene_node(result, scene_exec_no, node_id)
    else:
        # 独立任务：生成 EXEC_* 消息通知
        _notify_exec_result(result, task_id)
    return result


def _writeback_scene_node(result: dict, scene_exec_no: str, node_id: str) -> None:
    """节点任务完成后回写 df_scene_node_exec 与 df:scene:node_progress

    状态映射：任务成功→节点成功(2)；任务部分成功/失败/中止→节点失败(3)（保留成功条数）。
    注意顺序：先写 MySQL 再写 Redis 终态，保证调度器读到 Redis 终态时 DB 已可见。
    """
    status_str = result.get("status") or "failed"
    node_status = _NODE_STATUS_SUCCESS if status_str == "success" else _NODE_STATUS_FAILED

    session = SyncSessionLocal()
    try:
        scene_exec = (
            session.query(SceneExec)
            .filter(SceneExec.scene_exec_no == scene_exec_no)
            .first()
        )
        if scene_exec is not None:
            node_exec = (
                session.query(SceneNodeExec)
                .filter(
                    SceneNodeExec.scene_exec_id == scene_exec.id,
                    SceneNodeExec.node_id == node_id,
                )
                .first()
            )
            if node_exec is not None:
                node_exec.status = node_status
                node_exec.success_count = int(result.get("success_count") or 0)
                node_exec.fail_count = int(result.get("fail_count") or 0)
                node_exec.duration_ms = result.get("duration_ms")
                node_exec.finish_at = datetime.now()
                if node_status == _NODE_STATUS_FAILED:
                    if status_str == "partial_success":
                        node_exec.error_msg = (
                            f"任务部分成功：成功 {result.get('success_count') or 0} 条，"
                            f"失败 {result.get('fail_count') or 0} 条。"
                            f"{result.get('error') or ''}"
                        )[:2000]
                    else:
                        node_exec.error_msg = (result.get("error") or "执行失败")[:2000]
                else:
                    node_exec.error_msg = None
                session.commit()

        # Redis 节点进度（保留 target/layer 等既有字段）
        node_key = f"df:scene:node_progress:{scene_exec_no}"
        raw = sync_redis_client.hget(node_key, node_id)
        data = json.loads(_decode(raw)) if raw else {}
        data.update({
            "status": status_str if status_str in ("success", "partial_success", "failed") else "failed",
            "success": int(result.get("success_count") or 0),
            "task_no": result.get("task_no"),
        })
        sync_redis_client.hset(node_key, node_id, json.dumps(data))
        logger.info(
            "scene_node_writeback",
            scene_exec_no=scene_exec_no, node_id=node_id, status=status_str,
        )
    finally:
        session.close()


def _notify_exec_result(result: dict, task_id: int) -> None:
    """独立造数任务完成后生成消息通知（EXEC_SUCCESS/EXEC_FAILED/EXEC_PARTIAL）"""
    status_str = result.get("status")
    if status_str in (None, "skipped"):
        return

    session = SyncSessionLocal()
    try:
        task = session.get(ExecTask, task_id)
        if task is None:
            return
        success = int(result.get("success_count") or 0)
        fail = int(result.get("fail_count") or 0)
        target = int(task.target_count or 0)
        duration = _format_duration(result.get("duration_ms"))

        if status_str == "success":
            msg_type, priority, title = "EXEC_SUCCESS", 3, "造数任务执行完成"
            content = f"Case「{task.case_name}」已成功插入 {success:,} 条数据，耗时 {duration}。"
        elif status_str == "partial_success":
            msg_type, priority, title = "EXEC_PARTIAL", 2, "造数任务部分成功"
            content = (
                f"Case「{task.case_name}」部分成功，共插入 {success:,} 条"
                f"（目标 {target:,} 条），失败 {fail:,} 条，可在执行详情页重试失败批次。"
            )
        else:
            msg_type, priority, title = "EXEC_FAILED", 1, "造数任务执行失败"
            total = success + fail
            fail_rate = round(fail / total * 100, 1) if total else 100.0
            error_msg = (result.get("error") or task.error_msg or "")[:200]
            content = (
                f"Case「{task.case_name}」执行失败，失败率 {fail_rate}%，"
                f"共插入 {success:,} 条（目标 {target:,} 条）。错误摘要：{error_msg}"
            )

        create_notification(
            session,
            user_id=task.created_by,
            msg_type=msg_type,
            title=title,
            content=content,
            link_url=f"/tasks/{task.task_no}",
            priority=priority,
            group_type=task.group_type,
        )
        session.commit()
        logger.info("exec_notification_sent", task_no=task.task_no, msg_type=msg_type)
    finally:
        session.close()
