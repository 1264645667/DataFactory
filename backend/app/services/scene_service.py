"""场景管理业务服务。

覆盖：列表/详情/新建/编辑/逻辑删除/执行/复制/执行历史/执行进度/
强制停止/重试失败节点。保存校验：名称唯一(1501)/≥2节点(1502)/循环依赖(1503)/
Case 有效性(1504)/节点条数(1505)；exec_mode 由 DAG 结构自动识别。
"""

import json
import time
from datetime import datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_group_visible, group_filter_value
from app.celery_app import celery_app
from app.core.redis_client import redis_client
from app.engine.dep_analyzer import build_layers
from app.engine.strategies.pk_strategies import next_snowflake_id
from app.models.case import Case
from app.models.scene import Scene, SceneExec, SceneNodeExec
from app.models.user import User
from app.schemas.errors import (
    CELERY_SUBMIT_FAILED,
    FORBIDDEN,
    PARAM_INVALID,
    SCENE_CYCLE_DETECTED,
    SCENE_EXEC_NOT_FOUND,
    SCENE_NAME_TAKEN,
    SCENE_NODE_CASE_DELETED,
    SCENE_NODE_TOO_FEW,
    SCENE_NOT_FOUND,
    SCENE_TARGET_COUNT_MISSING,
    TASK_ALREADY_FINISHED,
    BizException,
)
from app.schemas.response import PageData
from app.schemas.scene import (
    SceneCreateRequest,
    SceneExecHistoryItem,
    SceneLayerProgress,
    SceneListItem,
    SceneNodeProgress,
    SceneProgressOverall,
    SceneProgressResponse,
    SceneUpdateRequest,
)
from app.services.notification_service import audit

logger = structlog.get_logger(__name__)

# Redis Key
SCENE_PROGRESS_KEY = "df:scene:progress:{scene_exec_no}"
SCENE_NODE_PROGRESS_KEY = "df:scene:node_progress:{scene_exec_no}"
SCENE_PROGRESS_TTL = 24 * 3600

# df_scene_exec.status
_SCENE_STATUS_PENDING = 0
_SCENE_STATUS_RUNNING = 1
_SCENE_STATUS_ABORTED = 5

# df_scene_node_exec.status
_NODE_STATUS_PENDING = 0
_NODE_STATUS_RUNNING = 1
_NODE_STATUS_SUCCESS = 2
_NODE_STATUS_FAILED = 3
_NODE_STATUS_CANCELLED = 4

# 场景执行终态 → 进度字符串
_SCENE_STATUS_STR = {
    0: "submitted",
    1: "running",
    2: "success",
    3: "failed",
    4: "partial_success",
    5: "aborted",
}
_NODE_STATUS_STR = {
    0: "pending",
    1: "running",
    2: "success",
    3: "failed",
    4: "cancelled",
}


def _decode(value) -> str:
    """Redis 返回值兼容 bytes/str。"""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


async def get_scene_checked(db: AsyncSession, current_user: User, scene_id: int) -> Scene:
    """获取场景并校验分组数据权限（不存在/已删除/跨组统一抛 1500）。"""
    scene = await db.get(Scene, scene_id)
    if scene is None or scene.is_deleted == 1:
        raise BizException(SCENE_NOT_FOUND)
    ensure_group_visible(current_user, scene.group_type, SCENE_NOT_FOUND)
    return scene


async def get_scene_exec_checked(
    db: AsyncSession, current_user: User, scene_exec_no: str
) -> SceneExec:
    """按执行编号获取场景执行记录并校验分组权限（1506）。"""
    result = await db.execute(
        select(SceneExec).where(SceneExec.scene_exec_no == scene_exec_no)
    )
    scene_exec = result.scalar_one_or_none()
    if scene_exec is None:
        raise BizException(SCENE_EXEC_NOT_FOUND)
    ensure_group_visible(current_user, scene_exec.group_type, SCENE_EXEC_NOT_FOUND)
    return scene_exec


# ── 校验与 exec_mode 识别 ────────────────────────────────────────


def _detect_exec_mode(nodes: list, edges: list) -> str:
    """执行模式自动识别

    - 无任何连线 → parallel（纯并行）
    - 拓扑分层后每层恰好 1 个节点（所有节点串成一条链）→ serial（纯串行）
    - 其余 → mixed（混合）
    """
    if not edges:
        return "parallel"
    node_dicts = [{"node_id": n.node_id} for n in nodes]
    edge_dicts = [{"source": e.source, "target": e.target} for e in edges]
    layers = build_layers(node_dicts, edge_dicts)
    if all(len(layer) == 1 for layer in layers):
        return "serial"
    return "mixed"


async def _validate_scene_payload(
    db: AsyncSession,
    *,
    current_user: User,
    scene_name: str,
    nodes: list,
    edges: list,
    exclude_id: int | None = None,
) -> None:
    """场景保存统一校验。

    名称本组唯一(1501) / 至少2节点(1502) / 节点条数(1505) / 循环依赖(1503) / Case有效性(1504)。
    """
    # 1. 场景名称本组内唯一（1501）
    stmt = select(Scene.id).where(
        Scene.scene_name == scene_name,
        Scene.group_type == current_user.group_type,
        Scene.is_deleted == 0,
    )
    if exclude_id is not None:
        stmt = stmt.where(Scene.id != exclude_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise BizException(SCENE_NAME_TAKEN)

    # 2. 节点数量（1502）
    if len(nodes) < 2:
        raise BizException(SCENE_NODE_TOO_FEW)

    # 3. node_id 唯一性 + 节点条数（1505）
    node_ids = [n.node_id for n in nodes]
    if len(set(node_ids)) != len(node_ids):
        raise BizException(PARAM_INVALID, "节点 node_id 重复")
    for node in nodes:
        if not node.target_count or node.target_count < 1:
            raise BizException(
                SCENE_TARGET_COUNT_MISSING, f"节点「{node.case_name}」的造数条数未填写"
            )

    # 4. 连线端点合法性 + 循环依赖（1503，Kahn 拓扑分层）
    node_id_set = set(node_ids)
    for edge in edges or []:
        if edge.source not in node_id_set or edge.target not in node_id_set:
            raise BizException(PARAM_INVALID, "连线引用了不存在的节点")
        if edge.source == edge.target:
            raise BizException(SCENE_CYCLE_DETECTED, "不允许节点自连线")
    try:
        build_layers(
            [{"node_id": n.node_id} for n in nodes],
            [{"source": e.source, "target": e.target} for e in edges or []],
        )
    except ValueError as e:
        raise BizException(SCENE_CYCLE_DETECTED, "检测到循环依赖，请检查连线") from e

    # 5. Case 有效性（1504）：存在、未删除、且属于本组
    case_ids = list({n.case_id for n in nodes})
    result = await db.execute(select(Case).where(Case.id.in_(case_ids)))
    case_map = {c.id: c for c in result.scalars().all()}
    group_type = group_filter_value(current_user)
    for node in nodes:
        case = case_map.get(node.case_id)
        if case is None or case.is_deleted == 1:
            raise BizException(
                SCENE_NODE_CASE_DELETED, f"节点「{node.case_name}」引用的 Case 已删除，请替换"
            )
        if group_type is not None and case.group_type != group_type:
            raise BizException(
                SCENE_NODE_CASE_DELETED, f"节点「{node.case_name}」引用的 Case 不属于本组"
            )


# ── 列表 / 详情 ──────────────────────────────────────────────────


async def list_scenes(
    db: AsyncSession,
    *,
    current_user: User,
    page: int,
    page_size: int,
    name: str | None = None,
    created_by: int | None = None,
    last_exec_status: list[int] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> PageData[SceneListItem]:
    """场景列表（分组过滤 + 筛选 + 分页）。"""
    conditions = [Scene.is_deleted == 0]
    group_type = group_filter_value(current_user)
    if group_type is not None:
        conditions.append(Scene.group_type == group_type)
    if name:
        conditions.append(Scene.scene_name.like(f"%{name}%"))
    if created_by is not None:
        conditions.append(Scene.created_by == created_by)
    if last_exec_status:
        conditions.append(Scene.last_exec_status.in_(last_exec_status))
    if start_time is not None:
        conditions.append(Scene.created_at >= start_time)
    if end_time is not None:
        conditions.append(Scene.created_at <= end_time)

    total = int(
        (await db.execute(select(func.count()).select_from(Scene).where(*conditions))).scalar_one()
    )
    result = await db.execute(
        select(Scene, User.real_name.label("creator_name"))
        .join(User, Scene.created_by == User.id, isouter=True)
        .where(*conditions)
        .order_by(Scene.created_at.desc(), Scene.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        SceneListItem(
            id=scene.id,
            scene_name=scene.scene_name,
            description=scene.description,
            node_count=scene.node_count,
            exec_mode=scene.exec_mode,
            created_by=scene.created_by,
            creator_name=creator_name,
            created_at=scene.created_at,
            last_exec_at=scene.last_exec_at,
            last_exec_status=scene.last_exec_status,
            exec_count=scene.exec_count,
        )
        for scene, creator_name in result.all()
    ]
    return PageData(items=items, total=total, page=page, page_size=page_size)


async def get_scene_detail(db: AsyncSession, *, current_user: User, scene_id: int):
    """场景详情（含 nodes_json + edges_json）。"""
    from app.schemas.scene import SceneDetail, SceneEdge, SceneNode

    scene = await get_scene_checked(db, current_user, scene_id)
    creator = await db.get(User, scene.created_by)
    return SceneDetail(
        id=scene.id,
        scene_name=scene.scene_name,
        description=scene.description,
        nodes=[SceneNode(**n) for n in json.loads(scene.nodes_json)],
        edges=[SceneEdge(**e) for e in json.loads(scene.edges_json or "[]")],
        node_count=scene.node_count,
        exec_mode=scene.exec_mode,
        group_type=scene.group_type,
        created_by=scene.created_by,
        creator_name=creator.real_name if creator else None,
        created_at=scene.created_at,
        updated_at=scene.updated_at,
        last_exec_at=scene.last_exec_at,
        last_exec_status=scene.last_exec_status,
        exec_count=scene.exec_count,
    )


# ── 新建 / 编辑 / 删除 / 复制 ──────────────────────────────────────


async def create_scene(
    db: AsyncSession, *, current_user: User, req: SceneCreateRequest, ip: str | None
) -> Scene:
    """新建场景（校验通过后 exec_mode 自动识别）。"""
    await _validate_scene_payload(
        db, current_user=current_user, scene_name=req.scene_name,
        nodes=req.nodes, edges=req.edges,
    )
    exec_mode = _detect_exec_mode(req.nodes, req.edges)
    scene = Scene(
        scene_name=req.scene_name,
        description=req.description,
        nodes_json=json.dumps([n.model_dump() for n in req.nodes], ensure_ascii=False),
        edges_json=json.dumps([e.model_dump() for e in req.edges], ensure_ascii=False),
        node_count=len(req.nodes),
        exec_mode=exec_mode,
        group_type=current_user.group_type,
        is_deleted=0,
        exec_count=0,
        created_by=current_user.id,
    )
    db.add(scene)
    await db.flush()
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="CREATE_SCENE",
        resource="scene", resource_id=scene.id,
        detail=f"场景「{req.scene_name}」{len(req.nodes)} 节点，模式 {exec_mode}", ip=ip,
    )
    await db.commit()
    logger.info("scene_created", scene_id=scene.id, scene_name=req.scene_name, exec_mode=exec_mode)
    return scene


async def update_scene(
    db: AsyncSession,
    *,
    current_user: User,
    scene_id: int,
    req: SceneUpdateRequest,
    ip: str | None,
) -> Scene:
    """编辑场景（覆盖式更新）。"""
    scene = await get_scene_checked(db, current_user, scene_id)
    await _validate_scene_payload(
        db, current_user=current_user, scene_name=req.scene_name,
        nodes=req.nodes, edges=req.edges, exclude_id=scene.id,
    )
    exec_mode = _detect_exec_mode(req.nodes, req.edges)
    scene.scene_name = req.scene_name
    scene.description = req.description
    scene.nodes_json = json.dumps([n.model_dump() for n in req.nodes], ensure_ascii=False)
    scene.edges_json = json.dumps([e.model_dump() for e in req.edges], ensure_ascii=False)
    scene.node_count = len(req.nodes)
    scene.exec_mode = exec_mode
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="UPDATE_SCENE",
        resource="scene", resource_id=scene.id,
        detail=f"场景「{req.scene_name}」覆盖式更新，模式 {exec_mode}", ip=ip,
    )
    await db.commit()
    logger.info("scene_updated", scene_id=scene.id, operator=current_user.username)
    return scene


async def delete_scene(
    db: AsyncSession, *, current_user: User, scene_id: int, ip: str | None
) -> None:
    """逻辑删除场景（is_deleted=1，历史执行记录保留）。"""
    scene = await get_scene_checked(db, current_user, scene_id)
    scene.is_deleted = 1
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="DELETE_SCENE",
        resource="scene", resource_id=scene.id, detail=f"删除场景「{scene.scene_name}」", ip=ip,
    )
    await db.commit()
    logger.info("scene_deleted", scene_id=scene.id, operator=current_user.username)


async def copy_scene(
    db: AsyncSession,
    *,
    current_user: User,
    scene_id: int,
    scene_name: str | None,
    ip: str | None,
) -> Scene:
    """复制场景默认名「原场景名_copy」，复制全部节点与连线。"""
    source = await get_scene_checked(db, current_user, scene_id)

    if scene_name:
        # 显式命名：本组查重
        result = await db.execute(
            select(Scene.id).where(
                Scene.scene_name == scene_name,
                Scene.group_type == current_user.group_type,
                Scene.is_deleted == 0,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise BizException(SCENE_NAME_TAKEN)
        new_name = scene_name
    else:
        base = f"{source.scene_name}_copy"
        new_name = base
        suffix = 2
        while True:
            result = await db.execute(
                select(Scene.id).where(
                    Scene.scene_name == new_name,
                    Scene.group_type == current_user.group_type,
                    Scene.is_deleted == 0,
                )
            )
            if result.scalar_one_or_none() is None:
                break
            new_name = f"{base}{suffix}"
            suffix += 1

    new_scene = Scene(
        scene_name=new_name,
        description=source.description,
        nodes_json=source.nodes_json,
        edges_json=source.edges_json,
        node_count=source.node_count,
        exec_mode=source.exec_mode,
        group_type=source.group_type,
        is_deleted=0,
        exec_count=0,
        created_by=current_user.id,
    )
    db.add(new_scene)
    await db.flush()
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="CREATE_SCENE",
        resource="scene", resource_id=new_scene.id,
        detail=f"复制自场景「{source.scene_name}」(id={source.id})", ip=ip,
    )
    await db.commit()
    logger.info("scene_copied", source_id=source.id, new_scene_id=new_scene.id)
    return new_scene


# ── 执行 / 历史 ───────────────────────────────────────────────────


async def execute_scene(
    db: AsyncSession, *, current_user: User, scene_id: int, ip: str | None
) -> str:
    """执行场景创建 SceneExec（SC 前缀雪花编号 + 快照）→ 下发 Celery。"""
    scene = await get_scene_checked(db, current_user, scene_id)

    snapshot = json.dumps(
        {"nodes": json.loads(scene.nodes_json), "edges": json.loads(scene.edges_json or "[]")},
        ensure_ascii=False,
    )
    scene_exec = SceneExec(
        scene_exec_no=f"SC{next_snowflake_id()}",  # SC + 雪花 ID，全局唯一
        scene_id=scene.id,
        scene_name=scene.scene_name,
        scene_snapshot=snapshot,
        node_count=scene.node_count,
        success_count=0,
        fail_count=0,
        total_rows=0,
        status=0,  # 待执行
        group_type=scene.group_type,
        created_by=current_user.id,
        created_at=datetime.now(),
    )
    db.add(scene_exec)
    await db.flush()
    try:
        celery_app.send_task("tasks.execute_scene", args=[scene_exec.id])
    except Exception as e:
        logger.error("celery_submit_failed", task="tasks.execute_scene", scene_exec_no=scene_exec.scene_exec_no)
        raise BizException(CELERY_SUBMIT_FAILED) from e

    await audit(
        db, user_id=current_user.id, username=current_user.username, action="EXEC_SCENE",
        resource="scene", resource_id=scene.id,
        detail=f"场景「{scene.scene_name}」执行，编号 {scene_exec.scene_exec_no}", ip=ip,
    )
    await db.commit()
    logger.info(
        "scene_execute_submitted", scene_id=scene.id,
        scene_exec_no=scene_exec.scene_exec_no, operator=current_user.username,
    )
    return scene_exec.scene_exec_no


async def get_scene_history(
    db: AsyncSession, *, current_user: User, scene_id: int, limit: int = 100
) -> list[SceneExecHistoryItem]:
    """场景执行历史。"""
    await get_scene_checked(db, current_user, scene_id)
    result = await db.execute(
        select(SceneExec)
        .where(SceneExec.scene_id == scene_id)
        .order_by(SceneExec.created_at.desc(), SceneExec.id.desc())
        .limit(limit)
    )
    return [
        SceneExecHistoryItem(
            scene_exec_no=row.scene_exec_no,
            node_count=row.node_count,
            success_count=row.success_count,
            fail_count=row.fail_count,
            total_rows=row.total_rows,
            status=row.status,
            error_msg=row.error_msg,
            duration_ms=row.duration_ms,
            start_at=row.start_at,
            finish_at=row.finish_at,
            created_at=row.created_at,
        )
        for row in result.scalars().all()
    ]


# ── 执行进度────────────────────────────────────────


def _layer_status(statuses: list[str]) -> str:
    """由层内节点状态聚合层状态。"""
    if statuses and all(s == "success" for s in statuses):
        return "success"
    if any(s in ("failed", "cancelled") for s in statuses):
        return "failed"
    if any(s == "running" for s in statuses):
        return "running"
    return "pending"


async def get_scene_progress(
    db: AsyncSession, *, current_user: User, scene_exec_no: str
) -> SceneProgressResponse:
    """场景执行实时进度：读 df:scene:progress + df:scene:node_progress 聚合。

    Redis miss（已过期）时回退 MySQL（df_scene_exec + df_scene_node_exec）聚合历史数据。
    """
    scene_exec = await get_scene_exec_checked(db, current_user, scene_exec_no)

    progress_raw: dict = {}
    node_raw: dict = {}
    try:
        progress_raw = await redis_client.hgetall(SCENE_PROGRESS_KEY.format(scene_exec_no=scene_exec_no))
        node_raw = await redis_client.hgetall(SCENE_NODE_PROGRESS_KEY.format(scene_exec_no=scene_exec_no))
    except Exception:
        logger.warning("scene_progress_redis_failed", scene_exec_no=scene_exec_no)

    if progress_raw:
        # ── Redis 聚合（执行中/近 24h 内） ──
        progress = {k: _decode(v) for k, v in progress_raw.items()}
        nodes_data: list[dict] = []
        for node_id, raw in node_raw.items():
            data = json.loads(_decode(raw))
            data["node_id"] = _decode(node_id)
            nodes_data.append(data)

        # 节点 case_name 从快照补齐（Redis 节点进度不含名称）
        snapshot = json.loads(scene_exec.scene_snapshot)
        name_map = {n["node_id"]: n.get("case_name") or "" for n in snapshot.get("nodes") or []}

        layers_map: dict[int, list[SceneNodeProgress]] = {}
        pending_count = running_count = 0
        for data in nodes_data:
            status = data.get("status") or "pending"
            if status == "pending":
                pending_count += 1
            elif status == "running":
                running_count += 1
            layer_no = int(data.get("layer") or 0)
            layers_map.setdefault(layer_no, []).append(
                SceneNodeProgress(
                    node_id=data["node_id"],
                    case_name=name_map.get(data["node_id"], ""),
                    status=status,
                    target=int(data.get("target") or 0),
                    success=int(data.get("success") or 0),
                    task_no=data.get("task_no"),
                    layer=layer_no,
                )
            )
        layers = [
            SceneLayerProgress(
                layer_no=layer_no,
                status=_layer_status([n.status for n in layer_nodes]),
                nodes=sorted(layer_nodes, key=lambda n: n.node_id),
            )
            for layer_no, layer_nodes in sorted(layers_map.items())
        ]
        start_at = progress.get("start_at")
        elapsed = int(time.time()) - int(start_at) if start_at else None
        return SceneProgressResponse(
            scene_exec_no=scene_exec_no,
            status=progress.get("status") or "running",
            total_layers=int(progress.get("total_layers") or len(layers)),
            current_layer=int(progress.get("current_layer") or 0),
            elapsed_seconds=elapsed,
            overall=SceneProgressOverall(
                node_count=int(progress.get("node_count") or len(nodes_data)),
                success_count=int(progress.get("success_count") or 0),
                fail_count=int(progress.get("fail_count") or 0),
                pending_count=pending_count,
                running_count=running_count,
                target_rows=int(progress.get("target_rows") or 0),
                success_rows=int(progress.get("success_rows") or 0),
            ),
            layers=layers,
        )

    # ── Redis miss：回退 MySQL 历史数据聚合 ──
    result = await db.execute(
        select(SceneNodeExec)
        .where(SceneNodeExec.scene_exec_id == scene_exec.id)
        .order_by(SceneNodeExec.layer_no, SceneNodeExec.id)
    )
    node_execs = list(result.scalars().all())
    layers_map2: dict[int, list[SceneNodeProgress]] = {}
    pending_count = running_count = 0
    for ne in node_execs:
        status = _NODE_STATUS_STR.get(ne.status, "pending")
        if status == "pending":
            pending_count += 1
        elif status == "running":
            running_count += 1
        layers_map2.setdefault(ne.layer_no, []).append(
            SceneNodeProgress(
                node_id=ne.node_id,
                case_name=ne.case_name,
                status=status,
                target=int(ne.target_count or 0),
                success=int(ne.success_count or 0),
                task_no=ne.exec_task_no,
                layer=ne.layer_no,
            )
        )
    layers = [
        SceneLayerProgress(
            layer_no=layer_no,
            status=_layer_status([n.status for n in layer_nodes]),
            nodes=layer_nodes,
        )
        for layer_no, layer_nodes in sorted(layers_map2.items())
    ]
    elapsed = None
    if scene_exec.start_at:
        end = scene_exec.finish_at or datetime.now()
        elapsed = int((end - scene_exec.start_at).total_seconds())
    return SceneProgressResponse(
        scene_exec_no=scene_exec_no,
        status=_SCENE_STATUS_STR.get(scene_exec.status, "failed"),
        total_layers=len(layers),
        current_layer=max(len(layers) - 1, 0),
        elapsed_seconds=elapsed,
        overall=SceneProgressOverall(
            node_count=scene_exec.node_count,
            success_count=scene_exec.success_count,
            fail_count=scene_exec.fail_count,
            pending_count=pending_count,
            running_count=running_count,
            target_rows=sum(int(ne.target_count or 0) for ne in node_execs),
            success_rows=int(scene_exec.total_rows or 0),
        ),
        layers=layers,
    )


# ── 强制停止 / 重试节点 ───────────────────────────────────────────


async def abort_scene(
    db: AsyncSession, *, current_user: User, scene_exec_no: str, ip: str | None
) -> None:
    """强制停止场景。

    - revoke 所有「执行中」节点的 Celery 任务（terminate=True）
    - 所有「等待中」节点置为「已取消」
    - 场景状态置为「已中止」，Redis 进度同步终态
    仅本人或管理员可操作。
    """
    scene_exec = await get_scene_exec_checked(db, current_user, scene_exec_no)
    if scene_exec.created_by != current_user.id and current_user.group_type != 99:
        raise BizException(FORBIDDEN, "无权停止该场景")
    if scene_exec.status not in (_SCENE_STATUS_PENDING, _SCENE_STATUS_RUNNING):
        raise BizException(TASK_ALREADY_FINISHED, "场景已结束，无法停止")

    # 1. revoke 执行中节点的底层 Celery 任务
    result = await db.execute(
        select(SceneNodeExec).where(
            SceneNodeExec.scene_exec_id == scene_exec.id,
            SceneNodeExec.status.in_([_NODE_STATUS_PENDING, _NODE_STATUS_RUNNING]),
        )
    )
    active_nodes = list(result.scalars().all())
    from app.models.task import ExecTask

    for node_exec in active_nodes:
        if node_exec.status == _NODE_STATUS_RUNNING and node_exec.exec_task_id:
            task = await db.get(ExecTask, node_exec.exec_task_id)
            if task is not None and task.celery_task_id:
                try:
                    celery_app.control.revoke(task.celery_task_id, terminate=True)
                except Exception:
                    logger.warning("celery_revoke_failed", task_no=task.task_no)
            if task is not None and task.status in (0, 1, 4):
                task.status = 6  # 已中止
                task.finish_at = datetime.now()
        # 2. 等待中/执行中节点统一置为「已取消」
        node_exec.status = _NODE_STATUS_CANCELLED
        node_exec.error_msg = "用户强制停止场景"
        node_exec.finish_at = datetime.now()

    # 3. 场景置为「已中止」
    now = datetime.now()
    scene_exec.status = _SCENE_STATUS_ABORTED
    scene_exec.finish_at = now
    if scene_exec.start_at:
        scene_exec.duration_ms = int((now - scene_exec.start_at).total_seconds() * 1000)
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="EXEC_SCENE",
        resource="scene_exec", resource_id=scene_exec.scene_exec_no,
        detail=f"强制停止场景「{scene_exec.scene_name}」", ip=ip,
    )
    await db.commit()

    # 4. Redis 进度同步（节点置 cancelled，场景置 aborted）
    try:
        progress_key = SCENE_PROGRESS_KEY.format(scene_exec_no=scene_exec_no)
        node_key = SCENE_NODE_PROGRESS_KEY.format(scene_exec_no=scene_exec_no)
        node_raw = await redis_client.hgetall(node_key)
        pipe = redis_client.pipeline()
        for node_id, raw in node_raw.items():
            data = json.loads(_decode(raw))
            if data.get("status") in ("pending", "running"):
                data["status"] = "cancelled"
                pipe.hset(node_key, node_id, json.dumps(data))
        pipe.hset(progress_key, mapping={
            "status": "aborted", "updated_at": str(int(time.time())),
        })
        pipe.expire(progress_key, SCENE_PROGRESS_TTL)
        pipe.expire(node_key, SCENE_PROGRESS_TTL)
        await pipe.execute()
    except Exception:
        logger.warning("scene_abort_redis_failed", scene_exec_no=scene_exec_no)
    logger.info("scene_aborted", scene_exec_no=scene_exec_no, operator=current_user.username)


async def retry_scene_nodes(
    db: AsyncSession,
    *,
    current_user: User,
    scene_exec_no: str,
    node_ids: list[str],
    ip: str | None,
) -> None:
    """重试失败节点校验后下发 tasks.retry_scene_nodes。

    仅重跑选中的失败/已取消节点，结果追加到本次场景执行记录。
    """
    scene_exec = await get_scene_exec_checked(db, current_user, scene_exec_no)
    if scene_exec.created_by != current_user.id and current_user.group_type != 99:
        raise BizException(FORBIDDEN, "无权操作该场景执行记录")
    if scene_exec.status in (_SCENE_STATUS_PENDING, _SCENE_STATUS_RUNNING):
        raise BizException(PARAM_INVALID, "场景正在执行中，无法重试节点")

    # 校验选中节点存在且处于失败/已取消状态
    result = await db.execute(
        select(SceneNodeExec).where(
            SceneNodeExec.scene_exec_id == scene_exec.id,
            SceneNodeExec.node_id.in_(node_ids),
        )
    )
    node_execs = list(result.scalars().all())
    found_ids = {ne.node_id for ne in node_execs}
    missing = [nid for nid in node_ids if nid not in found_ids]
    if missing:
        raise BizException(PARAM_INVALID, f"节点不存在：{','.join(missing)}")
    retryable = [
        ne for ne in node_execs
        if ne.status in (_NODE_STATUS_FAILED, _NODE_STATUS_CANCELLED)
    ]
    if not retryable:
        raise BizException(PARAM_INVALID, "选中的节点不处于失败/已取消状态，无法重试")

    try:
        celery_app.send_task(
            "tasks.retry_scene_nodes",
            args=[scene_exec.id, [ne.node_id for ne in retryable]],
        )
    except Exception as e:
        logger.error("celery_submit_failed", task="tasks.retry_scene_nodes", scene_exec_no=scene_exec_no)
        raise BizException(CELERY_SUBMIT_FAILED) from e

    await audit(
        db, user_id=current_user.id, username=current_user.username, action="EXEC_SCENE",
        resource="scene_exec", resource_id=scene_exec_no,
        detail=f"重试失败节点：{','.join(ne.node_id for ne in retryable)}", ip=ip,
    )
    await db.commit()
    logger.info(
        "scene_retry_nodes_submitted", scene_exec_no=scene_exec_no,
        node_ids=[ne.node_id for ne in retryable], operator=current_user.username,
    )
