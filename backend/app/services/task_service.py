"""任务进度业务服务（架构文档 6.6/6.7）。

覆盖：任务实时进度（Redis 聚合，miss 回退 MySQL）、强制停止（celery revoke）、
重试失败批次（断点续传，调 engine.executor.retry_failed_batches）、任务详情（含分批日志）。
"""

import asyncio
import json
import time
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_group_visible
from app.celery_app import celery_app
from app.core.redis_client import redis_client
from app.models.task import ExecBatchLog, ExecTask
from app.models.user import User
from app.schemas.errors import (
    FORBIDDEN,
    TASK_ALREADY_FINISHED,
    TASK_NOT_FOUND,
    BizException,
)
from app.schemas.task import (
    BatchLogItem,
    TaskDetailResponse,
    TaskOverallProgress,
    TaskProgressResponse,
    TaskTableProgress,
)

logger = structlog.get_logger(__name__)

# Redis Key（文档 5.1/5.2）
PROGRESS_KEY = "df:task:progress:{task_no}"
TABLE_PROGRESS_KEY = "df:task:table_progress:{task_no}"
RATE_KEY = "df:task:rate:{task_no}:{table}"
PROGRESS_TTL = 24 * 3600

# df_exec_task.status → 进度字符串（文档 6.6.2）
_TASK_STATUS_STR = {
    0: "submitted",
    1: "running",
    2: "success",
    3: "failed",
    4: "running",   # 重试中按 running 展示
    5: "partial_success",
    6: "aborted",
}

# 执行中状态（可中止）
_RUNNING_STATUS = (0, 1, 4)
# 可重试状态（3=失败 5=部分成功）
_RETRYABLE_STATUS = (3, 5)


def _decode(value) -> str:
    """Redis 返回值兼容 bytes/str。"""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


async def get_task_checked(db: AsyncSession, current_user: User, task_no: str) -> ExecTask:
    """按 task_no 获取任务并校验分组数据权限（不存在/跨组统一抛 1305）。"""
    result = await db.execute(select(ExecTask).where(ExecTask.task_no == task_no))
    task = result.scalar_one_or_none()
    if task is None:
        raise BizException(TASK_NOT_FOUND)
    ensure_group_visible(current_user, task.group_type, TASK_NOT_FOUND)
    return task


async def _get_insert_rate(task_no: str, table: str) -> float:
    """最近 3 秒滑动窗口插入速率（条/秒，文档 5.2）。"""
    try:
        records = await redis_client.lrange(RATE_KEY.format(task_no=task_no, table=table), 0, -1)
    except Exception:
        return 0.0
    now = time.time()
    window_start = now - 3.0
    recent_count = 0
    for record in records:
        try:
            ts_str, count_str = _decode(record).split(":", 1)
            if float(ts_str) >= window_start:
                recent_count += int(count_str)
        except (ValueError, TypeError):
            continue
    return recent_count / 3.0


async def get_task_progress(
    db: AsyncSession, *, current_user: User, task_no: str
) -> TaskProgressResponse:
    """任务实时进度（GET /tasks/{task_no}/progress，文档 6.6.2 响应结构）。

    读 Redis df:task:progress + table_progress + rate 滑动窗口聚合；
    Redis miss（已过期）回退查 MySQL 历史数据。
    """
    task = await get_task_checked(db, current_user, task_no)

    progress_raw: dict = {}
    table_raw: dict = {}
    try:
        progress_raw = await redis_client.hgetall(PROGRESS_KEY.format(task_no=task_no))
        table_raw = await redis_client.hgetall(TABLE_PROGRESS_KEY.format(task_no=task_no))
    except Exception:
        logger.warning("task_progress_redis_failed", task_no=task_no)

    if progress_raw:
        progress = {k: _decode(v) for k, v in progress_raw.items()}

        # 分表进度 + 各表速率
        tables: list[TaskTableProgress] = []
        total_rate = 0.0
        for table_name, raw in table_raw.items():
            table_name = _decode(table_name)
            data = json.loads(_decode(raw))
            rate = await _get_insert_rate(task_no, table_name)
            total_rate += rate
            target = int(data.get("target") or 0)
            success = int(data.get("success") or 0)
            tables.append(
                TaskTableProgress(
                    table_name=table_name,
                    role="main" if table_name == task.main_table else "related",
                    target=target,
                    success=success,
                    failed=int(data.get("failed") or 0),
                    progress_percent=round(success / target * 100, 1) if target > 0 else 0.0,
                    insert_rate=round(rate, 1),
                    status=data.get("status") or "pending",
                )
            )
        tables.sort(key=lambda x: (x.role != "main", x.table_name))  # 主表在前

        target_total = int(progress.get("target_total") or 0)
        success_total = int(progress.get("success_total") or 0)
        fail_total = int(progress.get("fail_total") or 0)
        remaining = target_total - success_total
        estimated = round(remaining / total_rate) if total_rate > 0 and remaining > 0 else None
        start_at_ts = progress.get("start_at")
        elapsed = int(time.time()) - int(start_at_ts) if start_at_ts else None
        return TaskProgressResponse(
            task_no=task_no,
            status=progress.get("status") or "running",
            start_at=task.start_at,
            elapsed_seconds=elapsed,
            batch_size=int(progress.get("batch_size") or 0),
            concurrency=int(progress.get("concurrency") or 0),
            current_round=(
                int(progress["current_round"]) if progress.get("current_round") else None
            ),
            total_rounds=int(progress["total_rounds"]) if progress.get("total_rounds") else None,
            current_drive_value=progress.get("current_drive_value") or None,
            overall=TaskOverallProgress(
                target_total=target_total,
                success_total=success_total,
                fail_total=fail_total,
                progress_percent=round(success_total / target_total * 100, 1) if target_total > 0 else 0.0,
                insert_rate=round(total_rate, 1),
                estimated_remaining_seconds=estimated,
            ),
            tables=tables,
        )

    # ── Redis miss：回退 MySQL 历史数据（任务已结束） ──
    result = await db.execute(
        select(ExecBatchLog)
        .where(ExecBatchLog.task_id == task.id)
        .order_by(ExecBatchLog.id)
    )
    batch_logs = list(result.scalars().all())
    # 按表聚合（每表最新状态：取最新一条日志的状态）
    table_stats: dict[str, dict] = {}
    for log in batch_logs:
        stats = table_stats.setdefault(log.table_name, {"success": 0, "failed": 0, "status": "pending"})
        if log.status == 1:
            stats["success"] += int(log.batch_size)
        elif log.status == 2:
            stats["failed"] += int(log.batch_size)
            stats["status"] = "failed"
    related = json.loads(task.related_tables or "[]")
    table_names = [task.main_table] + [t for t in related if t != task.main_table]
    tables = []
    for name in table_names:
        stats = table_stats.get(name, {"success": 0, "failed": 0, "status": "pending"})
        target = int(task.target_count or 0)
        status = stats["status"]
        if status == "pending" and stats["success"] >= target > 0:
            status = "success"
        elif status == "pending" and stats["success"] > 0:
            status = "running"
        tables.append(
            TaskTableProgress(
                table_name=name,
                role="main" if name == task.main_table else "related",
                target=target,
                success=stats["success"],
                failed=stats["failed"],
                progress_percent=round(stats["success"] / target * 100, 1) if target > 0 else 0.0,
                insert_rate=0.0,
                status=status,
            )
        )

    elapsed = None
    if task.start_at:
        end = task.finish_at or datetime.now()
        elapsed = int((end - task.start_at).total_seconds())
    target_total = int(task.target_count or 0) * max(len(table_names), 1)
    return TaskProgressResponse(
        task_no=task_no,
        status=_TASK_STATUS_STR.get(task.status, "failed"),
        start_at=task.start_at,
        elapsed_seconds=elapsed,
        batch_size=None,
        concurrency=None,
        overall=TaskOverallProgress(
            target_total=target_total,
            success_total=int(task.success_count or 0),
            fail_total=int(task.fail_count or 0),
            progress_percent=(
                round(int(task.success_count or 0) / target_total * 100, 1) if target_total > 0 else 0.0
            ),
            insert_rate=0.0,
            estimated_remaining_seconds=None,
        ),
        tables=tables,
    )


async def abort_task(
    db: AsyncSession, *, current_user: User, task_no: str, ip: str | None
) -> None:
    """强制停止任务（文档 6.6.5）：celery revoke terminate=True + 状态置已中止。

    仅本人或管理员可操作；已结束任务返回 1306。
    """
    task = await get_task_checked(db, current_user, task_no)
    if task.created_by != current_user.id and current_user.group_type != 99:
        raise BizException(FORBIDDEN, "无权停止该任务")
    if task.status not in _RUNNING_STATUS:
        raise BizException(TASK_ALREADY_FINISHED)

    # 发送 revoke 信号（terminate=True 强制停止工作线程）
    if task.celery_task_id:
        try:
            celery_app.control.revoke(task.celery_task_id, terminate=True)
        except Exception:
            logger.warning("celery_revoke_failed", task_no=task_no)

    # 更新任务状态为已中止
    task.status = 6
    task.finish_at = datetime.now()
    if task.start_at:
        task.duration_ms = int((task.finish_at - task.start_at).total_seconds() * 1000)
    await db.commit()

    # Redis 进度同步终态
    try:
        progress_key = PROGRESS_KEY.format(task_no=task_no)
        await redis_client.hset(progress_key, mapping={
            "status": "aborted", "updated_at": str(int(time.time())),
        })
        await redis_client.expire(progress_key, PROGRESS_TTL)
    except Exception:
        logger.warning("task_abort_redis_failed", task_no=task_no)
    logger.info("task_aborted", task_no=task_no, operator=current_user.username, ip=ip)


async def retry_failed_batches(
    db: AsyncSession, *, current_user: User, task_no: str, ip: str | None
) -> None:
    """重试失败批次（断点续传，PRD 4.5.2 手动重试入口）。

    调 engine.executor.retry_failed_batches 重新提交执行（同步重活，放线程池异步执行，
    进度通过 /tasks/{task_no}/progress 轮询观察）。
    注意：现有引擎入口按 task_id 全量重跑失败批次，暂不支持按 batch_nos/round_no 过滤。
    """
    task = await get_task_checked(db, current_user, task_no)
    if task.created_by != current_user.id and current_user.group_type != 99:
        raise BizException(FORBIDDEN, "无权操作该任务")
    if task.status not in _RETRYABLE_STATUS:
        raise BizException(
            TASK_ALREADY_FINISHED, f"任务状态为 {task.status}，仅失败/部分成功任务可重试"
        )

    # 线程池 fire-and-forget：executor.retry_failed_batches 为同步长任务，
    # 内部自行维护 Redis 进度与终态，前端轮询进度接口即可
    # 说明：app.engine.executor 经 app.engine.db_pool 间接依赖 aes_decrypt（现有代码
    # 命名问题，实际为 decrypt_aes），此处延迟导入，待其修复后自动生效
    from app.engine import executor

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, executor.retry_failed_batches, task.id)
    logger.info("task_retry_batches_submitted", task_no=task_no, operator=current_user.username, ip=ip)


async def get_task_detail(
    db: AsyncSession, *, current_user: User, task_no: str
) -> TaskDetailResponse:
    """任务详情（含 df_exec_batch_log 分批日志，PRD 3.5 执行详情抽屉）。"""
    task = await get_task_checked(db, current_user, task_no)
    result = await db.execute(
        select(ExecBatchLog)
        .where(ExecBatchLog.task_id == task.id)
        .order_by(ExecBatchLog.round_no, ExecBatchLog.batch_no, ExecBatchLog.table_name, ExecBatchLog.id)
    )
    batch_logs = [
        BatchLogItem(
            id=log.id,
            table_name=log.table_name,
            batch_no=log.batch_no,
            batch_size=log.batch_size,
            status=log.status,
            retry_times=log.retry_times,
            error_msg=log.error_msg,
            start_at=log.start_at,
            finish_at=log.finish_at,
            duration_ms=log.duration_ms,
            round_no=log.round_no,
            drive_value=log.drive_value,
        )
        for log in result.scalars().all()
    ]
    return TaskDetailResponse(
        task_no=task.task_no,
        case_id=task.case_id,
        case_name=task.case_name,
        datasource_id=task.datasource_id,
        datasource_name=task.datasource_name,
        main_table=task.main_table,
        related_tables=json.loads(task.related_tables or "[]"),
        target_count=task.target_count,
        success_count=task.success_count,
        fail_count=task.fail_count,
        retry_count=task.retry_count,
        status=task.status,
        error_msg=task.error_msg,
        start_at=task.start_at,
        finish_at=task.finish_at,
        duration_ms=task.duration_ms,
        created_by=task.created_by,
        created_at=task.created_at,
        batch_logs=batch_logs,
    )
