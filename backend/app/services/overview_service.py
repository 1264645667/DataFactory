"""造数总览业务服务。

覆盖：核心指标卡（7 指标，Redis 缓存 df:stats:{group}:daily 5min）、执行趋势（近 7/30/90 天）、
执行状态分布、表操作量 Top10、成员贡献排行、执行记录明细（分页 + 筛选）。
管理员看全量，普通用户看 本组 + 管理员 的数据（数据权限）。
"""

import json
from datetime import datetime, timedelta

import structlog
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import group_scope_values
from app.core.redis_client import redis_client
from app.models.case import Case
from app.models.scene import Scene, SceneExec
from app.models.task import ExecBatchLog, ExecTask
from app.models.user import User
from app.schemas.overview import (
    ExecRecordItem,
    MemberRankItem,
    OverviewMetrics,
    StatusDistItem,
    StatusDistResponse,
    TableTopItem,
    TrendPoint,
    TrendResponse,
)
from app.schemas.response import PageData

logger = structlog.get_logger(__name__)

# 总览指标缓存（df:stats:{group_type}:daily，5min）
STATS_CACHE_KEY = "df:stats:{group_type}:daily"
STATS_CACHE_TTL = 5 * 60

# 执行状态码 → 分布名称（成功/失败/执行中/重试中/部分成功）
_STATUS_NAME_MAP = {
    0: "running",          # 待执行归入执行中
    1: "running",
    2: "success",
    3: "failed",
    4: "retrying",
    5: "partial_success",
    6: "failed",           # 已中止归入失败
}


def _today_start() -> datetime:
    """今日 00:00。"""
    now = datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _group_conditions(model, scope: list[int] | None) -> list:
    """分组数据可见范围过滤条件（None=管理员全量；否则 本组+管理员 in_ 过滤）。"""
    return [model.group_type.in_(scope)] if scope is not None else []


# ── 核心指标卡 ───────────────────────────────────────────────────


async def get_metrics(db: AsyncSession, *, current_user: User) -> OverviewMetrics:
    """核心指标卡片数据，Redis 缓存 5 分钟。"""
    scope = group_scope_values(current_user)
    cache_key = STATS_CACHE_KEY.format(group_type=current_user.group_type)

    # 缓存命中直接返回
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return OverviewMetrics(**json.loads(cached))
    except Exception:
        logger.warning("overview_metrics_cache_read_failed")

    today = _today_start()
    yesterday = today - timedelta(days=1)
    thirty_days_ago = today - timedelta(days=30)
    seven_days_ago = today - timedelta(days=7)

    case_cond = _group_conditions(Case, scope)
    scene_cond = _group_conditions(Scene, scope)
    task_cond = _group_conditions(ExecTask, scope)
    scene_exec_cond = _group_conditions(SceneExec, scope)

    # 1. 总 Case 数 / 总场景数（未删除）
    total_case_count = int((await db.execute(
        select(func.count()).select_from(Case).where(Case.is_deleted == 0, *case_cond)
    )).scalar_one())
    total_scene_count = int((await db.execute(
        select(func.count()).select_from(Scene).where(Scene.is_deleted == 0, *scene_cond)
    )).scalar_one())

    # 2. 今日执行次数（Case 执行 + 场景执行）
    today_case_exec = int((await db.execute(
        select(func.count()).select_from(ExecTask).where(ExecTask.created_at >= today, *task_cond)
    )).scalar_one())
    today_scene_exec = int((await db.execute(
        select(func.count()).select_from(SceneExec).where(SceneExec.created_at >= today, *scene_exec_cond)
    )).scalar_one())
    today_exec_count = today_case_exec + today_scene_exec

    # 3. 累计造数条数（历史成功插入总条数）
    total_row_count = int((await db.execute(
        select(func.coalesce(func.sum(ExecTask.success_count), 0)).where(*task_cond)
    )).scalar_one())

    # 4. 近 30 天执行成功率（成功次数 / 已结束总次数）
    success_30d = int((await db.execute(
        select(func.count()).select_from(ExecTask).where(
            ExecTask.created_at >= thirty_days_ago, ExecTask.status == 2, *task_cond
        )
    )).scalar_one())
    finished_30d = int((await db.execute(
        select(func.count()).select_from(ExecTask).where(
            ExecTask.created_at >= thirty_days_ago,
            ExecTask.status.in_([2, 3, 5, 6]),
            *task_cond,
        )
    )).scalar_one())
    exec_success_rate = round(success_30d / finished_30d * 100, 1) if finished_30d > 0 else 0.0

    # 5. 近 7 天活跃数据源数（有执行操作的数据源去重）
    active_datasource_count = int((await db.execute(
        select(func.count(distinct(ExecTask.datasource_id))).where(
            ExecTask.created_at >= seven_days_ago, *task_cond
        )
    )).scalar_one())

    # 6. 本组成员数（管理员=全系统正常用户数；成员数始终按本组统计，不含管理员组）
    member_cond = [User.status == 1]
    if scope is not None:
        member_cond.append(User.group_type == current_user.group_type)
    group_member_count = int((await db.execute(
        select(func.count()).select_from(User).where(*member_cond)
    )).scalar_one())

    # 7. 较昨日环比增量
    yesterday_case_exec = int((await db.execute(
        select(func.count()).select_from(ExecTask).where(
            ExecTask.created_at >= yesterday, ExecTask.created_at < today, *task_cond
        )
    )).scalar_one())
    yesterday_scene_exec = int((await db.execute(
        select(func.count()).select_from(SceneExec).where(
            SceneExec.created_at >= yesterday, SceneExec.created_at < today, *scene_exec_cond
        )
    )).scalar_one())
    today_new_cases = int((await db.execute(
        select(func.count()).select_from(Case).where(
            Case.is_deleted == 0, Case.created_at >= today, *case_cond
        )
    )).scalar_one())
    today_new_scenes = int((await db.execute(
        select(func.count()).select_from(Scene).where(
            Scene.is_deleted == 0, Scene.created_at >= today, *scene_cond
        )
    )).scalar_one())
    today_rows = int((await db.execute(
        select(func.coalesce(func.sum(ExecTask.success_count), 0)).where(
            ExecTask.created_at >= today, *task_cond
        )
    )).scalar_one())
    compare_yesterday = {
        "total_case_count": float(today_new_cases),
        "total_scene_count": float(today_new_scenes),
        "today_exec_count": float(today_exec_count - (yesterday_case_exec + yesterday_scene_exec)),
        "total_row_count": float(today_rows),
    }

    metrics = OverviewMetrics(
        total_case_count=total_case_count,
        total_scene_count=total_scene_count,
        today_exec_count=today_exec_count,
        total_row_count=total_row_count,
        exec_success_rate=exec_success_rate,
        active_datasource_count=active_datasource_count,
        group_member_count=group_member_count,
        compare_yesterday=compare_yesterday,
    )

    # 写缓存（5min，失败不影响返回）
    try:
        await redis_client.set(cache_key, metrics.model_dump_json(), ex=STATS_CACHE_TTL)
    except Exception:
        logger.warning("overview_metrics_cache_write_failed")
    return metrics


# ── 图表数据 ─────────────────────────────────────────────────────


async def get_trend(db: AsyncSession, *, current_user: User, days: int) -> TrendResponse:
    """执行趋势折线图近 N 天每日执行次数/造数条数/成功率。"""
    scope = group_scope_values(current_user)
    task_cond = _group_conditions(ExecTask, scope)
    today = _today_start()
    start = today - timedelta(days=days - 1)

    day_expr = func.date(ExecTask.created_at)
    result = await db.execute(
        select(
            day_expr.label("day"),
            func.count().label("exec_count"),
            func.coalesce(func.sum(ExecTask.success_count), 0).label("row_count"),
            func.sum(ExecTask.status == 2).label("success_count"),
            func.sum(ExecTask.status.in_([2, 3, 5, 6])).label("finished_count"),
        )
        .where(ExecTask.created_at >= start, *task_cond)
        .group_by(day_expr)
    )
    day_map = {
        str(row.day): row for row in result.all()
    }

    points: list[TrendPoint] = []
    for i in range(days):
        day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        row = day_map.get(day)
        if row is None:
            points.append(TrendPoint(date=day, exec_count=0, row_count=0, success_rate=0.0))
        else:
            finished = int(row.finished_count or 0)
            success = int(row.success_count or 0)
            points.append(TrendPoint(
                date=day,
                exec_count=int(row.exec_count or 0),
                row_count=int(row.row_count or 0),
                success_rate=round(success / finished * 100, 1) if finished > 0 else 0.0,
            ))
    return TrendResponse(range_days=days, points=points)


async def get_status_dist(db: AsyncSession, *, current_user: User, days: int) -> StatusDistResponse:
    """执行状态分布饼图范围与趋势图同步（近 N 天）。"""
    scope = group_scope_values(current_user)
    task_cond = _group_conditions(ExecTask, scope)
    start = _today_start() - timedelta(days=days - 1)

    result = await db.execute(
        select(ExecTask.status, func.count())
        .where(ExecTask.created_at >= start, *task_cond)
        .group_by(ExecTask.status)
    )
    name_counts: dict[str, int] = {}
    for status, count in result.all():
        name = _STATUS_NAME_MAP.get(int(status), "failed")
        name_counts[name] = name_counts.get(name, 0) + int(count)

    total = sum(name_counts.values())
    items = [
        StatusDistItem(
            status=name,
            count=count,
            percent=round(count / total * 100, 1) if total > 0 else 0.0,
        )
        for name, count in sorted(name_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return StatusDistResponse(total=total, items=items)


async def get_table_top10(db: AsyncSession, *, current_user: User, days: int) -> list[TableTopItem]:
    """表操作量 Top10 柱状图按实际插入表聚合成功行数。

    统计口径：df_exec_batch_log 中成功批次（status=1）的 batch_size 之和，
    关联表与主表各自独立成项（ExecTask.success_count 为全表合计，无法按表拆分）。
    """
    scope = group_scope_values(current_user)
    task_cond = _group_conditions(ExecTask, scope)
    start = _today_start() - timedelta(days=days - 1)

    result = await db.execute(
        select(
            ExecBatchLog.table_name,
            ExecTask.datasource_name,
            func.coalesce(func.sum(ExecBatchLog.batch_size), 0).label("row_count"),
            func.count(distinct(ExecTask.case_id)).label("case_count"),
        )
        .join(ExecTask, ExecBatchLog.task_id == ExecTask.id)
        .where(
            ExecTask.created_at >= start,
            ExecBatchLog.status == 1,  # 1=成功批次（BATCH_STATUS_SUCCESS）
            *task_cond,
        )
        .group_by(ExecBatchLog.table_name, ExecTask.datasource_name)
        .order_by(func.sum(ExecBatchLog.batch_size).desc())
        .limit(10)
    )
    return [
        TableTopItem(
            table_name=row.table_name,
            datasource_name=row.datasource_name,
            row_count=int(row.row_count or 0),
            case_count=int(row.case_count or 0),
        )
        for row in result.all()
    ]


async def get_member_rank(db: AsyncSession, *, current_user: User, days: int) -> list[MemberRankItem]:
    """成员贡献排行本组成员按造数条数降序，最多 10 人。"""
    scope = group_scope_values(current_user)
    task_cond = _group_conditions(ExecTask, scope)
    start = _today_start() - timedelta(days=days - 1)

    result = await db.execute(
        select(
            ExecTask.created_by,
            User.username,
            User.real_name,
            func.coalesce(func.sum(ExecTask.success_count), 0).label("row_count"),
            func.count().label("exec_count"),
        )
        .join(User, ExecTask.created_by == User.id, isouter=True)
        .where(ExecTask.created_at >= start, *task_cond)
        .group_by(ExecTask.created_by, User.username, User.real_name)
        .order_by(func.sum(ExecTask.success_count).desc())
        .limit(10)
    )
    return [
        MemberRankItem(
            user_id=row.created_by,
            username=row.username or str(row.created_by),
            real_name=row.real_name,
            row_count=int(row.row_count or 0),
            exec_count=int(row.exec_count or 0),
        )
        for row in result.all()
    ]


# ── 执行记录明细 ──────────────────────────────────────────────────


async def get_exec_records(
    db: AsyncSession,
    *,
    current_user: User,
    page: int,
    page_size: int,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    status: list[int] | None = None,
    datasource_id: int | None = None,
    created_by: int | None = None,
    case_name: str | None = None,
    table_name: str | None = None,
) -> PageData[ExecRecordItem]:
    """执行记录明细表（分页 + 筛选）。"""
    scope = group_scope_values(current_user)
    conditions = _group_conditions(ExecTask, scope)
    if start_time is not None:
        conditions.append(ExecTask.created_at >= start_time)
    if end_time is not None:
        conditions.append(ExecTask.created_at <= end_time)
    if status:
        conditions.append(ExecTask.status.in_(status))
    if datasource_id is not None:
        conditions.append(ExecTask.datasource_id == datasource_id)
    if created_by is not None:
        conditions.append(ExecTask.created_by == created_by)
    if case_name:
        conditions.append(ExecTask.case_name.like(f"%{case_name}%"))
    if table_name:
        conditions.append(ExecTask.main_table.like(f"%{table_name}%"))

    total = int(
        (await db.execute(select(func.count()).select_from(ExecTask).where(*conditions))).scalar_one()
    )
    result = await db.execute(
        select(ExecTask, User.real_name.label("creator_name"))
        .join(User, ExecTask.created_by == User.id, isouter=True)
        .where(*conditions)
        .order_by(ExecTask.created_at.desc(), ExecTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    for task, creator_name in result.all():
        related = json.loads(task.related_tables or "[]")
        items.append(ExecRecordItem(
            task_no=task.task_no,
            case_name=task.case_name,
            datasource_name=task.datasource_name,
            main_table=task.main_table,
            related_count=len(related) + 1,  # 主表 + 关联表
            target_count=task.target_count,
            success_count=task.success_count,
            status=task.status,
            duration_ms=task.duration_ms,
            creator_name=creator_name,
            start_at=task.start_at,
            created_at=task.created_at,
        ))
    return PageData(items=items, total=total, page=page, page_size=page_size)
