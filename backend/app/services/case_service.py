"""Case 管理业务服务（PRD 第 5 章）。

覆盖：列表（分组过滤 + 筛选 + 分页，禁 SELECT config_json）、详情、覆盖式修改（含表结构变更检测）、
逻辑删除、执行、复制（默认 xxx_copy）、执行历史（含统计）、批量执行（串行提交独立任务）。
"""

import json
from datetime import datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_group_visible, group_filter_value
from app.models.case import Case
from app.models.task import ExecTask
from app.models.user import User
from app.schemas.case import (
    CaseBatchExecuteRequest,
    CaseDetail,
    CaseHistoryItem,
    CaseListItem,
    CaseUpdateRequest,
)
from app.schemas.engine import CaseConfig
from app.schemas.errors import (
    CASE_NOT_FOUND,
    TARGET_COUNT_TOO_LARGE,
    BizException,
)
from app.schemas.response import PageData
from app.services.engine_service import (
    MAX_TARGET_COUNT,
    _check_case_name_unique,
    create_exec_task,
    submit_exec_task,
    validate_case_config,
)
from app.services.notification_service import audit

logger = structlog.get_logger(__name__)


async def get_case_checked(db: AsyncSession, current_user: User, case_id: int) -> Case:
    """获取 Case 并校验分组数据权限（不存在/已删除/跨组统一抛 1400，不泄露存在性）。"""
    case = await db.get(Case, case_id)
    if case is None or case.is_deleted == 1:
        raise BizException(CASE_NOT_FOUND)
    ensure_group_visible(current_user, case.group_type, CASE_NOT_FOUND)
    return case


# ── 列表 / 详情 ──────────────────────────────────────────────────


async def list_cases(
    db: AsyncSession,
    *,
    current_user: User,
    page: int,
    page_size: int,
    datasource_id: int | None = None,
    name: str | None = None,
    created_by: int | None = None,
    last_exec_status: list[int] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    main_table: str | None = None,
) -> PageData[CaseListItem]:
    """Case 列表（PRD 5.2：分组过滤 + 筛选 + 分页）。

    列表查询显式指定列（禁 SELECT config_json 大字段，避免列表页性能问题）。
    """
    conditions = [Case.is_deleted == 0]
    group_type = group_filter_value(current_user)
    if group_type is not None:
        conditions.append(Case.group_type == group_type)
    if datasource_id is not None:
        conditions.append(Case.datasource_id == datasource_id)
    if name:
        conditions.append(Case.case_name.like(f"%{name}%"))
    if created_by is not None:
        conditions.append(Case.created_by == created_by)
    if last_exec_status:
        conditions.append(Case.last_exec_status.in_(last_exec_status))
    if start_time is not None:
        conditions.append(Case.created_at >= start_time)
    if end_time is not None:
        conditions.append(Case.created_at <= end_time)
    if main_table:
        conditions.append(Case.main_table.like(f"%{main_table}%"))

    total = int(
        (await db.execute(select(func.count()).select_from(Case).where(*conditions))).scalar_one()
    )
    # 显式列清单：不取 config_json（MEDIUMTEXT 大字段）
    result = await db.execute(
        select(
            Case.id, Case.case_name, Case.datasource_id, Case.datasource_name,
            Case.main_table, Case.related_count, Case.created_by,
            Case.created_at, Case.last_exec_at, Case.last_exec_status, Case.exec_count,
            User.real_name.label("creator_name"),
        )
        .join(User, Case.created_by == User.id, isouter=True)
        .where(*conditions)
        .order_by(Case.created_at.desc(), Case.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        CaseListItem(
            id=row.id,
            case_name=row.case_name,
            datasource_id=row.datasource_id,
            datasource_name=row.datasource_name,
            main_table=row.main_table,
            related_count=row.related_count,
            created_by=row.created_by,
            creator_name=row.creator_name,
            created_at=row.created_at,
            last_exec_at=row.last_exec_at,
            last_exec_status=row.last_exec_status,
            exec_count=row.exec_count,
        )
        for row in result.all()
    ]
    return PageData(items=items, total=total, page=page, page_size=page_size)


async def get_case_detail(db: AsyncSession, *, current_user: User, case_id: int) -> CaseDetail:
    """Case 详情（含 config_json，PRD 5.4）。"""
    case = await get_case_checked(db, current_user, case_id)
    creator = await db.get(User, case.created_by)
    return CaseDetail(
        id=case.id,
        case_name=case.case_name,
        datasource_id=case.datasource_id,
        datasource_name=case.datasource_name,
        main_table=case.main_table,
        related_tables=json.loads(case.related_tables or "[]"),
        related_count=case.related_count,
        config=CaseConfig.model_validate_json(case.config_json),
        group_type=case.group_type,
        created_by=case.created_by,
        creator_name=creator.real_name if creator else None,
        created_at=case.created_at,
        updated_at=case.updated_at,
        last_exec_at=case.last_exec_at,
        last_exec_status=case.last_exec_status,
        exec_count=case.exec_count,
    )


# ── 修改 / 删除 / 复制 ────────────────────────────────────────────


async def _detect_schema_outdated(
    db: AsyncSession, case: Case, new_config: CaseConfig
) -> list[str]:
    """表结构变更检测（PRD 5.3.2）：返回已失效（缓存中不存在）的字段名列表。

    检测范围：主表配置字段 + 关联目标字段。
    """
    from app.services.engine_service import _get_column_type_map

    outdated: list[str] = []
    main_columns = await _get_column_type_map(db, case.datasource_id, new_config.main_table)
    if main_columns:
        for fc in new_config.field_configs:
            if fc.column_name not in main_columns:
                outdated.append(f"{new_config.main_table}.{fc.column_name}")
    for assoc in new_config.associations or []:
        target_columns = await _get_column_type_map(db, case.datasource_id, assoc.target_table)
        if target_columns and assoc.target_column not in target_columns:
            outdated.append(f"{assoc.target_table}.{assoc.target_column}")
    return outdated


async def update_case(
    db: AsyncSession,
    *,
    current_user: User,
    case_id: int,
    req: CaseUpdateRequest,
    ip: str | None,
) -> dict:
    """修改 Case（覆盖式更新，PRD 5.5 不做版本管理）。

    返回 {"case_id", "schema_outdated", "outdated_fields"}：
    检测到表结构变更时 outdated_fields 非空（提示「以下字段配置可能失效」），保存仍生效。
    """
    case = await get_case_checked(db, current_user, case_id)
    await validate_case_config(db, case.datasource_id, req.config)
    await _check_case_name_unique(db, case.datasource_id, req.case_name, exclude_id=case.id)

    outdated_fields = await _detect_schema_outdated(db, case, req.config)

    related_tables, related_count = [], 0
    for assoc in req.config.associations or []:
        if assoc.target_table not in related_tables:
            related_tables.append(assoc.target_table)
    related_count = len(related_tables)

    case.case_name = req.case_name
    case.main_table = req.config.main_table
    case.related_tables = json.dumps(related_tables, ensure_ascii=False)
    case.related_count = related_count
    case.config_json = req.config.model_dump_json()

    await audit(
        db, user_id=current_user.id, username=current_user.username, action="UPDATE_CASE",
        resource="case", resource_id=case.id,
        detail=f"Case「{req.case_name}」覆盖式更新", ip=ip,
    )
    await db.commit()
    logger.info("case_updated", case_id=case.id, operator=current_user.username)
    return {
        "case_id": case.id,
        "schema_outdated": bool(outdated_fields),
        "outdated_fields": outdated_fields,
    }


async def delete_case(
    db: AsyncSession, *, current_user: User, case_id: int, ip: str | None
) -> None:
    """逻辑删除 Case（is_deleted=1，历史执行记录保留，PRD 5.3.5）。"""
    case = await get_case_checked(db, current_user, case_id)
    case.is_deleted = 1
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="DELETE_CASE",
        resource="case", resource_id=case.id, detail=f"删除 Case「{case.case_name}」", ip=ip,
    )
    await db.commit()
    logger.info("case_deleted", case_id=case.id, operator=current_user.username)


async def copy_case(
    db: AsyncSession,
    *,
    current_user: User,
    case_id: int,
    case_name: str | None,
    ip: str | None,
) -> Case:
    """复制 Case（PRD 5.3.3）：默认名「原Case名_copy」，默认名冲突时自动追加序号。"""
    source = await get_case_checked(db, current_user, case_id)

    if case_name:
        await _check_case_name_unique(db, source.datasource_id, case_name)
        new_name = case_name
    else:
        # 自动生成不冲突的复制名：xxx_copy → xxx_copy2 → xxx_copy3 ...
        base = f"{source.case_name}_copy"
        new_name = base
        suffix = 2
        while True:
            result = await db.execute(
                select(Case.id).where(
                    Case.datasource_id == source.datasource_id,
                    Case.case_name == new_name,
                    Case.is_deleted == 0,
                )
            )
            if result.scalar_one_or_none() is None:
                break
            new_name = f"{base}{suffix}"
            suffix += 1

    new_case = Case(
        case_name=new_name,
        datasource_id=source.datasource_id,
        datasource_name=source.datasource_name,
        main_table=source.main_table,
        related_tables=source.related_tables,
        related_count=source.related_count,
        config_json=source.config_json,
        group_type=source.group_type,
        is_deleted=0,
        exec_count=0,
        created_by=current_user.id,
    )
    db.add(new_case)
    await db.flush()
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="COPY_CASE",
        resource="case", resource_id=new_case.id,
        detail=f"复制自 Case「{source.case_name}」(id={source.id})", ip=ip,
    )
    await db.commit()
    logger.info("case_copied", source_id=source.id, new_case_id=new_case.id, operator=current_user.username)
    return new_case


# ── 执行 ────────────────────────────────────────────────────────


async def execute_case(
    db: AsyncSession,
    *,
    current_user: User,
    case_id: int,
    target_count: int,
    batch_size: int | None = None,
    max_workers: int | None = None,
    disable_unique_checks: bool = False,
    disable_fk_checks: bool = False,
    ip: str | None = None,
) -> str:
    """执行 Case（PRD 5.3.1）：创建 ExecTask（当前配置快照）→ 下发 Celery → 返回 task_no。"""
    if target_count > MAX_TARGET_COUNT:
        raise BizException(
            TARGET_COUNT_TOO_LARGE, f"目标造数量超过单次限制（最大 {MAX_TARGET_COUNT} 条）"
        )
    case = await get_case_checked(db, current_user, case_id)

    # 执行参数覆盖写入快照（引擎当前版本读取 settings，预留字段供后续版本生效）
    snapshot = case.config_json
    exec_params = {
        "batch_size": batch_size,
        "max_workers": max_workers,
        "disable_unique_checks": disable_unique_checks,
        "disable_fk_checks": disable_fk_checks,
    }
    if any(v is not None and v is not False for v in exec_params.values()):
        snapshot_dict = json.loads(case.config_json)
        snapshot_dict["exec_params"] = {k: v for k, v in exec_params.items() if v is not None}
        snapshot = json.dumps(snapshot_dict, ensure_ascii=False)

    exec_task = create_exec_task(
        db, case=case, target_count=target_count, current_user=current_user, snapshot=snapshot
    )
    await db.flush()
    submit_exec_task(exec_task)
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="EXEC_CASE",
        resource="case", resource_id=case.id,
        detail=f"Case「{case.case_name}」执行 {target_count} 条，任务 {exec_task.task_no}", ip=ip,
    )
    await db.commit()
    logger.info(
        "case_execute_submitted", case_id=case.id, task_no=exec_task.task_no,
        target_count=target_count, operator=current_user.username,
    )
    return exec_task.task_no


async def batch_execute_cases(
    db: AsyncSession, *, current_user: User, req: CaseBatchExecuteRequest, ip: str | None
) -> list[str]:
    """批量执行（PRD 5.3.6）：先统一校验，再逐个串行提交独立任务。"""
    # 1. 统一校验（任何一个不合法则整体不提交，避免部分执行）
    cases: list[tuple[Case, int]] = []
    for item in req.items:
        if item.target_count > MAX_TARGET_COUNT:
            raise BizException(
                TARGET_COUNT_TOO_LARGE, f"目标造数量超过单次限制（最大 {MAX_TARGET_COUNT} 条）"
            )
        case = await get_case_checked(db, current_user, item.case_id)
        cases.append((case, item.target_count))

    # 2. 逐个串行创建独立任务并下发
    task_nos: list[str] = []
    for case, target_count in cases:
        exec_task = create_exec_task(
            db, case=case, target_count=target_count, current_user=current_user
        )
        await db.flush()
        submit_exec_task(exec_task)
        task_nos.append(exec_task.task_no)
        await audit(
            db, user_id=current_user.id, username=current_user.username, action="EXEC_CASE",
            resource="case", resource_id=case.id,
            detail=f"批量执行：Case「{case.case_name}」{target_count} 条，任务 {exec_task.task_no}",
            ip=ip,
        )
    await db.commit()
    logger.info("case_batch_executed", count=len(task_nos), operator=current_user.username)
    return task_nos


# ── 执行历史 ─────────────────────────────────────────────────────


async def get_case_history(
    db: AsyncSession, *, current_user: User, case_id: int, limit: int = 100
) -> dict:
    """Case 执行历史（PRD 5.3.4）：记录列表 + 底部统计（总次数/成功次数/累计造数条数）。"""
    await get_case_checked(db, current_user, case_id)

    result = await db.execute(
        select(ExecTask)
        .where(ExecTask.case_id == case_id)
        .order_by(ExecTask.created_at.desc(), ExecTask.id.desc())
        .limit(limit)
    )
    tasks = list(result.scalars().all())
    items = [
        CaseHistoryItem(
            task_no=t.task_no,
            target_count=t.target_count,
            success_count=t.success_count,
            fail_count=t.fail_count,
            status=t.status,
            duration_ms=t.duration_ms,
            start_at=t.start_at,
            finish_at=t.finish_at,
            created_at=t.created_at,
        )
        for t in tasks
    ]

    # 统计（全量，不受 limit 影响）
    stat_result = await db.execute(
        select(
            func.count(),
            func.sum(ExecTask.status == 2),
            func.sum(ExecTask.success_count),
        ).where(ExecTask.case_id == case_id)
    )
    total_count, success_count, total_rows = stat_result.one()
    return {
        "items": items,
        "total_count": int(total_count or 0),
        "success_count": int(success_count or 0),
        "total_rows": int(total_rows or 0),
    }
