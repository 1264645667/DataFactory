"""Case 管理业务服务。

覆盖：列表（分组过滤 + 筛选 + 分页，禁 SELECT config_json）、详情、覆盖式修改（含表结构变更检测）、
逻辑删除、执行、复制（默认 xxx_copy）、执行历史（含统计）、批量执行（串行提交独立任务）。
"""

import json
from datetime import datetime

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_group_visible, group_filter_value
from app.models.case import Case, CaseFolder
from app.models.task import ExecTask
from app.models.user import User
from app.schemas.case import (
    CaseBatchExecuteRequest,
    CaseDetail,
    CaseHistoryItem,
    CaseListItem,
    CaseUpdateRequest,
    FolderItem,
)
from app.schemas.engine import CaseConfig
from app.schemas.errors import (
    CASE_NOT_FOUND,
    FOLDER_NAME_TAKEN,
    FOLDER_NOT_FOUND,
    TARGET_COUNT_TOO_LARGE,
    BizException,
)
from app.schemas.response import PageData
from app.services.engine_service import (
    MAX_TARGET_COUNT,
    _apply_redis_case_display,
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
    folder_id: int | None = None,
    unfiled: bool = False,
) -> PageData[CaseListItem]:
    """Case 列表（分组过滤 + 筛选 + 分页 + 文件夹过滤）。

    列表查询显式指定列（禁 SELECT config_json 大字段，避免列表页性能问题）。
    """
    conditions = [Case.is_deleted == 0]
    group_type = group_filter_value(current_user)
    if group_type is not None:
        conditions.append(Case.group_type == group_type)
    if datasource_id is not None:
        conditions.append(Case.datasource_id == datasource_id)
    if folder_id is not None:
        conditions.append(Case.folder_id == folder_id)
    if unfiled:
        conditions.append(Case.folder_id.is_(None))
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
    """Case 详情（含 config_json）。"""
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
    """表结构变更检测返回已失效（缓存中不存在）的字段名列表。

    检测范围：主表配置字段 + 关联目标字段。跨数据源按 table_datasources 解析表所属数据源。
    """
    from app.services.engine_service import _get_column_type_map

    table_ds = dict(new_config.table_datasources or {})

    def _ds_of(table: str) -> int:
        return table_ds.get(table, case.datasource_id)

    outdated: list[str] = []
    main_columns = await _get_column_type_map(db, _ds_of(new_config.main_table), new_config.main_table)
    if main_columns:
        for fc in new_config.field_configs:
            if fc.column_name not in main_columns:
                outdated.append(f"{new_config.main_table}.{fc.column_name}")
    for assoc in new_config.associations or []:
        target_columns = await _get_column_type_map(db, _ds_of(assoc.target_table), assoc.target_table)
        if target_columns and assoc.target_column not in target_columns:
            outdated.append(f"{assoc.target_table}.{assoc.target_column}")
    # 关联表字段策略覆盖中的字段同样做失效检测
    for table, related_configs in (new_config.related_field_configs or {}).items():
        related_columns = await _get_column_type_map(db, _ds_of(table), table)
        if related_columns:
            for fc in related_configs:
                if fc.column_name not in related_columns:
                    outdated.append(f"{table}.{fc.column_name}")
    return outdated


async def update_case(
    db: AsyncSession,
    *,
    current_user: User,
    case_id: int,
    req: CaseUpdateRequest,
    ip: str | None,
) -> dict:
    """修改 Case。

    返回 {"case_id", "schema_outdated", "outdated_fields"}：
    检测到表结构变更时 outdated_fields 非空（提示「以下字段配置可能失效」），保存仍生效。
    """
    case = await get_case_checked(db, current_user, case_id)
    await validate_case_config(db, case.datasource_id, req.config, current_user)
    await _check_case_name_unique(db, case.datasource_id, req.case_name, exclude_id=case.id)

    outdated_fields: list[str] = []
    if (req.config.case_type or "mysql") != "redis":
        outdated_fields = await _detect_schema_outdated(db, case, req.config)
    _apply_redis_case_display(req.config)

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
    """逻辑删除 Case（is_deleted=1，历史执行记录保留）。"""
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
    """复制 Case默认名「原Case名_copy」，默认名冲突时自动追加序号。"""
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
        folder_id=source.folder_id,  # 复制保留原文件夹归属
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
    """执行 Case创建 ExecTask（当前配置快照）→ 下发 Celery → 返回 task_no。"""
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
    """批量执行先统一校验，再逐个串行提交独立任务。"""
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
    """Case 执行历史记录列表 + 底部统计（总次数/成功次数/累计造数条数）。"""
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


# ── Case 文件夹 ──────────────────────────────────────────────────


async def list_folders(db: AsyncSession, *, current_user: User) -> dict:
    """文件夹列表（分组隔离）：含各文件夹收纳数 + 全部/未分类计数。"""
    group_type = group_filter_value(current_user)
    folder_conditions = [] if group_type is None else [CaseFolder.group_type == group_type]
    folders = list(
        (await db.execute(
            select(CaseFolder).where(*folder_conditions).order_by(CaseFolder.id)
        )).scalars().all()
    )
    case_conditions = [Case.is_deleted == 0]
    if group_type is not None:
        case_conditions.append(Case.group_type == group_type)
    count_rows = (
        await db.execute(
            select(Case.folder_id, func.count())
            .where(*case_conditions)
            .group_by(Case.folder_id)
        )
    ).all()
    by_folder = {fid: int(cnt) for fid, cnt in count_rows}
    items = [
        FolderItem(id=f.id, name=f.name, case_count=by_folder.get(f.id, 0), created_at=f.created_at)
        for f in folders
    ]
    return {
        "folders": items,
        "total_count": sum(by_folder.values()),
        "unfiled_count": by_folder.get(None, 0),
    }


async def _check_folder_name_unique(
    db: AsyncSession, group_type: int, name: str, exclude_id: int | None = None
) -> None:
    """同分组内文件夹名称唯一（1405）。"""
    stmt = select(CaseFolder.id).where(CaseFolder.group_type == group_type, CaseFolder.name == name)
    if exclude_id is not None:
        stmt = stmt.where(CaseFolder.id != exclude_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise BizException(FOLDER_NAME_TAKEN)


async def create_folder(
    db: AsyncSession, *, current_user: User, name: str, ip: str | None
) -> FolderItem:
    """新建文件夹（归属创建人所在分组）。"""
    group_type = current_user.group_type
    await _check_folder_name_unique(db, group_type, name)
    folder = CaseFolder(name=name, group_type=group_type, created_by=current_user.id)
    db.add(folder)
    await db.flush()
    await db.refresh(folder)
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="CREATE_FOLDER",
        resource="case_folder", resource_id=folder.id, detail=f"新建文件夹「{name}」", ip=ip,
    )
    await db.commit()
    return FolderItem(id=folder.id, name=folder.name, case_count=0, created_at=folder.created_at)


async def _get_folder_checked(db: AsyncSession, current_user: User, folder_id: int) -> CaseFolder:
    """获取文件夹并校验分组数据权限。"""
    folder = await db.get(CaseFolder, folder_id)
    if folder is None:
        raise BizException(FOLDER_NOT_FOUND)
    ensure_group_visible(current_user, folder.group_type, FOLDER_NOT_FOUND)
    return folder


async def rename_folder(
    db: AsyncSession, *, current_user: User, folder_id: int, name: str, ip: str | None
) -> None:
    """重命名文件夹。"""
    folder = await _get_folder_checked(db, current_user, folder_id)
    await _check_folder_name_unique(db, folder.group_type, name, exclude_id=folder_id)
    folder.name = name
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="RENAME_FOLDER",
        resource="case_folder", resource_id=folder_id, detail=f"重命名为「{name}」", ip=ip,
    )
    await db.commit()


async def delete_folder(
    db: AsyncSession, *, current_user: User, folder_id: int, ip: str | None
) -> None:
    """删除文件夹：其中 Case 自动移到未分类（不删 Case）。"""
    folder = await _get_folder_checked(db, current_user, folder_id)
    await db.execute(
        update(Case).where(Case.folder_id == folder_id).values(folder_id=None)
    )
    await db.delete(folder)
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="DELETE_FOLDER",
        resource="case_folder", resource_id=folder_id,
        detail=f"删除文件夹「{folder.name}」，其中 Case 移到未分类", ip=ip,
    )
    await db.commit()


async def move_cases(
    db: AsyncSession, *, current_user: User, case_ids: list[int], folder_id: int | None, ip: str | None
) -> None:
    """批量移动 Case 到文件夹（folder_id=None 移到未分类）。"""
    target_name = "未分类"
    if folder_id is not None:
        folder = await _get_folder_checked(db, current_user, folder_id)
        target_name = folder.name
    # 逐个校验 Case 归属（跨组拒绝）
    for case_id in case_ids:
        await get_case_checked(db, current_user, case_id)
    await db.execute(
        update(Case).where(Case.id.in_(case_ids)).values(folder_id=folder_id)
    )
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="MOVE_CASE",
        resource="case", resource_id=None,
        detail=f"移动 {len(case_ids)} 个 Case 到「{target_name}」", ip=ip,
    )
    await db.commit()
