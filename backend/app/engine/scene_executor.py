"""场景 DAG 调度执行器

职责：
- 拓扑分层（Kahn，dep_analyzer.build_layers）
- 初始化场景进度 Redis Key（df:scene:progress / df:scene:node_progress，24h TTL）
- 逐层提交节点：每节点创建独立 df_exec_task，下发 tasks.execute_data_gen Celery 任务
- 轮询等待层完成（每 2 秒读 Redis 节点进度）→ 检查 abort 失败策略 → 取消后续层
- 汇总场景终态；支持 retry_failed_nodes 重试失败节点

节点任务完成后的回写（Redis 节点进度 + df_scene_node_exec）由 tasks.execute_data_gen 完成，
本调度器只读 Redis 做终态轮询。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import structlog

from app.celery_app import celery_app
from app.core.redis_client import sync_redis_client
from app.db.session import SyncSessionLocal
from app.engine.dep_analyzer import build_layers
from app.engine.strategies.pk_strategies import next_snowflake_id
from app.models import Case, ExecTask, Scene, SceneExec, SceneNodeExec

logger = structlog.get_logger(__name__)

# ---------------- 状态枚举 ----------------
# df_scene_exec.status
SCENE_STATUS_PENDING = 0
SCENE_STATUS_RUNNING = 1
SCENE_STATUS_SUCCESS = 2
SCENE_STATUS_FAILED = 3
SCENE_STATUS_PARTIAL = 4
SCENE_STATUS_ABORTED = 5

# df_scene_node_exec.status
NODE_STATUS_PENDING = 0
NODE_STATUS_RUNNING = 1
NODE_STATUS_SUCCESS = 2
NODE_STATUS_FAILED = 3
NODE_STATUS_CANCELLED = 4    # 已取消（前置终止）

# Redis 节点进度终态字符串（execute_data_gen 回写）
NODE_TERMINAL_STATES = {"success", "failed", "partial_success", "cancelled", "aborted"}

REDIS_SCENE_STATUS_MAP = {
    SCENE_STATUS_SUCCESS: "success",
    SCENE_STATUS_FAILED: "failed",
    SCENE_STATUS_PARTIAL: "partial_success",
    SCENE_STATUS_ABORTED: "aborted",
}

# ---------------- Redis Key ----------------
SCENE_PROGRESS_KEY = "df:scene:progress:{scene_exec_no}"
SCENE_NODE_PROGRESS_KEY = "df:scene:node_progress:{scene_exec_no}"
SCENE_PROGRESS_TTL = 24 * 3600     # 场景进度 24h
LAYER_WAIT_TIMEOUT = 7200          # 单层等待超时 2h
POLL_INTERVAL = 2.0                # 层完成轮询间隔 2s


def _decode(value: Any) -> Any:
    """Redis 返回值兼容 bytes/str"""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


# 进度初始化与更新

def _init_scene_progress(scene_exec: SceneExec, nodes: list[dict], layers: list[list[str]]) -> None:
    """初始化场景进度 Redis Key"""
    now = str(int(time.time()))
    total_rows = sum(int(node.get("target_count") or 0) for node in nodes)
    layer_of = {nid: layer_no for layer_no, layer in enumerate(layers) for nid in layer}

    pipe = sync_redis_client.pipeline()
    progress_key = SCENE_PROGRESS_KEY.format(scene_exec_no=scene_exec.scene_exec_no)
    pipe.hset(progress_key, mapping={
        "status": "running",
        "node_count": str(len(nodes)),
        "success_count": "0",
        "fail_count": "0",
        "current_layer": "0",
        "total_layers": str(len(layers)),
        "target_rows": str(total_rows),
        "success_rows": "0",
        "start_at": now,
        "updated_at": now,
    })
    pipe.expire(progress_key, SCENE_PROGRESS_TTL)

    node_key = SCENE_NODE_PROGRESS_KEY.format(scene_exec_no=scene_exec.scene_exec_no)
    for node in nodes:
        pipe.hset(node_key, node["node_id"], json.dumps({
            "status": "pending",
            "target": int(node.get("target_count") or 0),
            "success": 0,
            "task_no": None,
            "layer": layer_of[node["node_id"]],
        }))
    pipe.expire(node_key, SCENE_PROGRESS_TTL)
    pipe.execute()


def _set_node_progress(scene_exec_no: str, node_id: str, data: dict) -> None:
    """更新单个节点的 Redis 进度（保留未提供的既有字段）"""
    node_key = SCENE_NODE_PROGRESS_KEY.format(scene_exec_no=scene_exec_no)
    raw = sync_redis_client.hget(node_key, node_id)
    current = json.loads(_decode(raw)) if raw else {}
    current.update(data)
    sync_redis_client.hset(node_key, node_id, json.dumps(current))


def _refresh_scene_progress(session, scene_exec: SceneExec) -> None:
    """按 df_scene_node_exec 当前状态刷新场景整体进度"""
    rows = (
        session.query(SceneNodeExec)
        .filter(SceneNodeExec.scene_exec_id == scene_exec.id)
        .all()
    )
    success_nodes = sum(1 for row in rows if row.status == NODE_STATUS_SUCCESS)
    failed_nodes = sum(1 for row in rows if row.status in (NODE_STATUS_FAILED, NODE_STATUS_CANCELLED))
    success_rows = sum(int(row.success_count or 0) for row in rows)
    sync_redis_client.hset(
        SCENE_PROGRESS_KEY.format(scene_exec_no=scene_exec.scene_exec_no),
        mapping={
            "success_count": str(success_nodes),
            "fail_count": str(failed_nodes),
            "success_rows": str(success_rows),
            "updated_at": str(int(time.time())),
        },
    )


# 节点提交与层等待

def _create_node_exec_task(session, scene_exec: SceneExec, case: Case, target_count: int) -> ExecTask:
    """为场景节点创建独立的造数执行任务（复用单 Case 执行体系）"""
    exec_task = ExecTask(
        task_no=f"TK{next_snowflake_id()}",
        case_id=case.id,
        case_name=case.case_name,
        case_snapshot=case.config_json,
        datasource_id=case.datasource_id,
        datasource_name=case.datasource_name,
        main_table=case.main_table,
        related_tables=case.related_tables,
        target_count=target_count,
        success_count=0,
        fail_count=0,
        retry_count=0,
        status=0,  # 待执行
        group_type=scene_exec.group_type,
        created_by=scene_exec.created_by,
        created_at=datetime.now(),
    )
    session.add(exec_task)
    session.flush()  # 取 exec_task.id
    return exec_task


def _submit_layer_nodes(session, scene_exec: SceneExec, layer_no: int, layer_nodes: list[dict]) -> None:
    """并行提交一层内所有节点：创建节点执行记录 + 独立 ExecTask + 下发 Celery 任务"""
    for node in layer_nodes:
        node_id = node["node_id"]
        target_count = int(node.get("target_count") or 0)
        fail_strategy = node.get("fail_strategy") or "continue"
        case = session.get(Case, node["case_id"])

        node_exec = SceneNodeExec(
            scene_exec_id=scene_exec.id,
            node_id=node_id,
            case_id=node["case_id"],
            case_name=node.get("case_name") or (case.case_name if case else ""),
            layer_no=layer_no,
            target_count=target_count,
            success_count=0,
            fail_count=0,
            fail_strategy=fail_strategy,
            status=NODE_STATUS_RUNNING,
            start_at=datetime.now(),
            created_at=datetime.now(),
        )
        session.add(node_exec)
        session.flush()

        if case is None or case.is_deleted:
            # 关联 Case 不存在/已删除：节点直接置为失败，不下发任务
            node_exec.status = NODE_STATUS_FAILED
            node_exec.error_msg = "关联 Case 不存在或已删除"
            node_exec.finish_at = datetime.now()
            node_exec.duration_ms = 0
            _set_node_progress(scene_exec.scene_exec_no, node_id, {
                "status": "failed", "success": 0, "task_no": None,
            })
            continue

        exec_task = _create_node_exec_task(session, scene_exec, case, target_count)
        celery_result = celery_app.send_task(
            "tasks.execute_data_gen",
            args=[exec_task.id],
            kwargs={"scene_exec_no": scene_exec.scene_exec_no, "node_id": node_id},
        )
        exec_task.celery_task_id = celery_result.id
        node_exec.exec_task_id = exec_task.id
        node_exec.exec_task_no = exec_task.task_no
        _set_node_progress(scene_exec.scene_exec_no, node_id, {
            "status": "running",
            "success": 0,
            "task_no": exec_task.task_no,
        })
        logger.info(
            "scene_node_submitted",
            scene_exec_no=scene_exec.scene_exec_no, node_id=node_id,
            task_no=exec_task.task_no, layer_no=layer_no,
        )
    session.commit()


def _wait_for_layer_completion(scene_exec_no: str, node_ids: list[str],
                               timeout: int = LAYER_WAIT_TIMEOUT) -> None:
    """轮询 Redis 节点进度，等待本层全部节点达到终态（每 2 秒）"""
    node_key = SCENE_NODE_PROGRESS_KEY.format(scene_exec_no=scene_exec_no)
    deadline = time.time() + timeout
    pending = set(node_ids)
    while pending:
        raws = sync_redis_client.hmget(node_key, *sorted(pending))
        for nid, raw in zip(sorted(pending), raws):
            if not raw:
                continue
            data = json.loads(_decode(raw))
            if data.get("status") in NODE_TERMINAL_STATES:
                pending.discard(nid)
        if not pending:
            return
        if time.time() > deadline:
            raise TimeoutError(f"等待场景层节点完成超时: {sorted(pending)}")
        time.sleep(POLL_INTERVAL)


def _collect_abort_nodes(session, scene_exec_id: int, layer_node_ids: list[str]) -> list[str]:
    """收集本层中「失败且失败策略=abort」的节点"""
    rows = (
        session.query(SceneNodeExec)
        .filter(
            SceneNodeExec.scene_exec_id == scene_exec_id,
            SceneNodeExec.node_id.in_(layer_node_ids),
        )
        .all()
    )
    return [
        row.node_id for row in rows
        if row.status == NODE_STATUS_FAILED and row.fail_strategy == "abort"
    ]


def _cancel_remaining_nodes(session, scene_exec: SceneExec, remaining_node_ids: list[str],
                            node_map: dict[str, dict], layer_of: dict[str, int]) -> None:
    """取消后续所有层的节点（abort 策略触发）"""
    now = datetime.now()
    for node_id in remaining_node_ids:
        node_exec = (
            session.query(SceneNodeExec)
            .filter(SceneNodeExec.scene_exec_id == scene_exec.id, SceneNodeExec.node_id == node_id)
            .first()
        )
        if node_exec is None:
            # 后续层节点尚未提交，补建「已取消」记录保证执行明细完整
            node_conf = node_map[node_id]
            node_exec = SceneNodeExec(
                scene_exec_id=scene_exec.id,
                node_id=node_id,
                case_id=node_conf["case_id"],
                case_name=node_conf.get("case_name") or "",
                layer_no=layer_of[node_id],
                target_count=int(node_conf.get("target_count") or 0),
                success_count=0,
                fail_count=0,
                fail_strategy=node_conf.get("fail_strategy") or "continue",
                status=NODE_STATUS_CANCELLED,
                error_msg="前置节点触发终止策略，已取消",
                finish_at=now,
                created_at=now,
            )
            session.add(node_exec)
        elif node_exec.status == NODE_STATUS_PENDING:
            node_exec.status = NODE_STATUS_CANCELLED
            node_exec.error_msg = "前置节点触发终止策略，已取消"
            node_exec.finish_at = now
        _set_node_progress(scene_exec.scene_exec_no, node_id, {"status": "cancelled"})
    session.commit()


# 场景终态

def _finalize_scene(session, scene_exec: SceneExec, aborted: bool) -> int:
    """汇总场景终态：更新 df_scene_exec / df_scene / Redis 进度"""
    rows = (
        session.query(SceneNodeExec)
        .filter(SceneNodeExec.scene_exec_id == scene_exec.id)
        .all()
    )
    success_nodes = sum(1 for row in rows if row.status == NODE_STATUS_SUCCESS)
    failed_nodes = sum(1 for row in rows if row.status in (NODE_STATUS_FAILED, NODE_STATUS_CANCELLED))
    total_rows = sum(int(row.success_count or 0) for row in rows)

    if aborted:
        # 触发终止策略 → 场景失败
        final = SCENE_STATUS_FAILED
    elif failed_nodes == 0:
        final = SCENE_STATUS_SUCCESS
    elif success_nodes == 0:
        final = SCENE_STATUS_FAILED
    else:
        final = SCENE_STATUS_PARTIAL

    now = datetime.now()
    scene_exec.status = final
    scene_exec.success_count = success_nodes
    scene_exec.fail_count = failed_nodes
    scene_exec.total_rows = total_rows
    scene_exec.finish_at = now
    if scene_exec.start_at:
        scene_exec.duration_ms = int((now - scene_exec.start_at).total_seconds() * 1000)
    if final != SCENE_STATUS_SUCCESS:
        first_error = next(
            (row.error_msg for row in rows
             if row.status in (NODE_STATUS_FAILED, NODE_STATUS_CANCELLED) and row.error_msg),
            None,
        )
        scene_exec.error_msg = (first_error or "")[:2000]
    else:
        scene_exec.error_msg = None

    # 场景表冗余执行信息（last_exec_status：1=成功 2=失败 3=部分成功 4=已中止）
    scene = session.get(Scene, scene_exec.scene_id)
    if scene is not None:
        scene.last_exec_at = now
        scene.last_exec_status = {
            SCENE_STATUS_SUCCESS: 1, SCENE_STATUS_FAILED: 2,
            SCENE_STATUS_PARTIAL: 3, SCENE_STATUS_ABORTED: 4,
        }.get(final, 2)
        scene.exec_count = (scene.exec_count or 0) + 1
    session.commit()

    # Redis 场景进度终态
    progress_key = SCENE_PROGRESS_KEY.format(scene_exec_no=scene_exec.scene_exec_no)
    pipe = sync_redis_client.pipeline()
    pipe.hset(progress_key, mapping={
        "status": REDIS_SCENE_STATUS_MAP.get(final, "failed"),
        "success_count": str(success_nodes),
        "fail_count": str(failed_nodes),
        "success_rows": str(total_rows),
        "updated_at": str(int(time.time())),
    })
    pipe.expire(progress_key, SCENE_PROGRESS_TTL)
    pipe.expire(SCENE_NODE_PROGRESS_KEY.format(scene_exec_no=scene_exec.scene_exec_no), SCENE_PROGRESS_TTL)
    pipe.execute()
    logger.info(
        "scene_exec_finish",
        scene_exec_no=scene_exec.scene_exec_no, status=final,
        success_nodes=success_nodes, failed_nodes=failed_nodes, total_rows=total_rows,
    )
    return final


def _mark_scene_failed(session, scene_exec: SceneExec, message: str) -> None:
    """初始化/异常阶段的快速失败标记"""
    scene_exec.status = SCENE_STATUS_FAILED
    scene_exec.error_msg = message[:2000]
    scene_exec.finish_at = datetime.now()
    if scene_exec.start_at:
        scene_exec.duration_ms = int(
            (scene_exec.finish_at - scene_exec.start_at).total_seconds() * 1000
        )
    session.commit()
    try:
        progress_key = SCENE_PROGRESS_KEY.format(scene_exec_no=scene_exec.scene_exec_no)
        if sync_redis_client.exists(progress_key):
            sync_redis_client.hset(progress_key, mapping={
                "status": "failed", "updated_at": str(int(time.time())),
            })
            sync_redis_client.expire(progress_key, SCENE_PROGRESS_TTL)
    except Exception:
        pass


# 对外入口

def execute_scene_task(scene_exec_id: int) -> dict:
    """场景执行主入口：DAG 分层调度，不直接插入数据"""
    session = SyncSessionLocal()
    try:
        scene_exec = session.get(SceneExec, scene_exec_id)
        if scene_exec is None:
            logger.error("scene_exec_not_found", scene_exec_id=scene_exec_id)
            return {"scene_exec_id": scene_exec_id, "status": "failed", "error": "场景执行记录不存在"}
        if scene_exec.status not in (SCENE_STATUS_PENDING,):
            return {"scene_exec_id": scene_exec_id, "scene_exec_no": scene_exec.scene_exec_no,
                    "status": "skipped", "error": f"场景状态为 {scene_exec.status}，不可重复执行"}

        log = logger.bind(scene_exec_no=scene_exec.scene_exec_no)
        try:
            snapshot = json.loads(scene_exec.scene_snapshot)
            nodes = snapshot.get("nodes") or []
            edges = snapshot.get("edges") or []
            if not nodes:
                raise ValueError("场景快照缺少节点配置(nodes)")
            layers = build_layers(nodes, edges)
        except Exception as exc:
            log.exception("scene_prepare_failed")
            _mark_scene_failed(session, scene_exec, f"场景初始化失败: {exc}")
            return {"scene_exec_id": scene_exec_id, "scene_exec_no": scene_exec.scene_exec_no,
                    "status": "failed", "status_code": SCENE_STATUS_FAILED, "error": str(exc)[:500]}

        # 标记执行中
        scene_exec.status = SCENE_STATUS_RUNNING
        scene_exec.start_at = datetime.now()
        scene_exec.node_count = len(nodes)
        scene_exec.error_msg = None
        session.commit()

        _init_scene_progress(scene_exec, nodes, layers)
        node_map = {node["node_id"]: node for node in nodes}
        layer_of = {nid: layer_no for layer_no, layer in enumerate(layers) for nid in layer}
        log.info("scene_exec_start", node_count=len(nodes), total_layers=len(layers))

        aborted = False
        try:
            for layer_no, layer_node_ids in enumerate(layers):
                sync_redis_client.hset(
                    SCENE_PROGRESS_KEY.format(scene_exec_no=scene_exec.scene_exec_no),
                    mapping={"current_layer": str(layer_no), "updated_at": str(int(time.time()))},
                )
                log.info("scene_layer_start", layer_no=layer_no, node_count=len(layer_node_ids))

                # 3a. 并行提交本层所有节点
                layer_nodes = [node_map[nid] for nid in layer_node_ids]
                _submit_layer_nodes(session, scene_exec, layer_no, layer_nodes)

                # 3b. 轮询等待本层全部节点达到终态
                _wait_for_layer_completion(scene_exec.scene_exec_no, layer_node_ids)
                _refresh_scene_progress(session, scene_exec)

                # 3c. 检查失败策略：存在 abort 节点失败则取消后续层并终止场景
                abort_nodes = _collect_abort_nodes(session, scene_exec.id, layer_node_ids)
                if abort_nodes:
                    remaining = [
                        nid for future_layer in layers[layer_no + 1:] for nid in future_layer
                    ]
                    _cancel_remaining_nodes(session, scene_exec, remaining, node_map, layer_of)
                    aborted = True
                    log.warning("scene_aborted_by_nodes", abort_nodes=abort_nodes)
                    break

            final = _finalize_scene(session, scene_exec, aborted=aborted)
            return {
                "scene_exec_id": scene_exec_id,
                "scene_exec_no": scene_exec.scene_exec_no,
                "status": REDIS_SCENE_STATUS_MAP.get(final, "failed"),
                "status_code": final,
                "success_count": int(scene_exec.success_count or 0),
                "fail_count": int(scene_exec.fail_count or 0),
                "total_rows": int(scene_exec.total_rows or 0),
                "duration_ms": int(scene_exec.duration_ms or 0),
                "error": scene_exec.error_msg,
            }
        except Exception as exc:
            log.exception("scene_exec_error")
            session.rollback()
            _mark_scene_failed(session, scene_exec, f"场景执行异常: {exc}")
            return {"scene_exec_id": scene_exec_id, "scene_exec_no": scene_exec.scene_exec_no,
                    "status": "failed", "status_code": SCENE_STATUS_FAILED, "error": str(exc)[:500]}
    finally:
        session.close()


def retry_failed_nodes(scene_exec_id: int, node_ids: list[str]) -> dict:
    """重试失败节点

    - 仅重新执行选中的失败/已取消节点，造数条数使用原配置
    - 重试结果追加到本次场景执行记录（不新建场景执行记录）
    - 已成功节点不受影响，不重新执行
    """
    session = SyncSessionLocal()
    try:
        scene_exec = session.get(SceneExec, scene_exec_id)
        if scene_exec is None:
            return {"scene_exec_id": scene_exec_id, "status": "failed", "error": "场景执行记录不存在"}
        log = logger.bind(scene_exec_no=scene_exec.scene_exec_no)

        node_execs = (
            session.query(SceneNodeExec)
            .filter(
                SceneNodeExec.scene_exec_id == scene_exec_id,
                SceneNodeExec.node_id.in_(node_ids),
                SceneNodeExec.status.in_([NODE_STATUS_FAILED, NODE_STATUS_CANCELLED]),
            )
            .all()
        )
        if not node_execs:
            return {"scene_exec_id": scene_exec_id, "scene_exec_no": scene_exec.scene_exec_no,
                    "status": "skipped", "error": "选中的节点不存在或不处于失败/已取消状态"}

        # 场景状态置回执行中
        scene_exec.status = SCENE_STATUS_RUNNING
        scene_exec.error_msg = None
        session.commit()
        sync_redis_client.hset(
            SCENE_PROGRESS_KEY.format(scene_exec_no=scene_exec.scene_exec_no),
            mapping={"status": "running", "updated_at": str(int(time.time()))},
        )

        submitted: list[str] = []
        for node_exec in node_execs:
            case = session.get(Case, node_exec.case_id)
            if case is None or case.is_deleted:
                node_exec.error_msg = "关联 Case 不存在或已删除，无法重试"
                continue
            exec_task = _create_node_exec_task(session, scene_exec, case, int(node_exec.target_count))
            celery_result = celery_app.send_task(
                "tasks.execute_data_gen",
                args=[exec_task.id],
                kwargs={"scene_exec_no": scene_exec.scene_exec_no, "node_id": node_exec.node_id},
            )
            exec_task.celery_task_id = celery_result.id
            # 重试结果复用原节点记录（追加到本次场景执行记录）
            node_exec.exec_task_id = exec_task.id
            node_exec.exec_task_no = exec_task.task_no
            node_exec.status = NODE_STATUS_RUNNING
            node_exec.error_msg = None
            node_exec.success_count = 0
            node_exec.fail_count = 0
            node_exec.start_at = datetime.now()
            node_exec.finish_at = None
            node_exec.duration_ms = None
            _set_node_progress(scene_exec.scene_exec_no, node_exec.node_id, {
                "status": "running", "success": 0, "task_no": exec_task.task_no,
            })
            submitted.append(node_exec.node_id)
            log.info("scene_node_retry_submitted", node_id=node_exec.node_id, task_no=exec_task.task_no)
        session.commit()

        if submitted:
            _wait_for_layer_completion(scene_exec.scene_exec_no, submitted)
        final = _finalize_scene(session, scene_exec, aborted=False)
        return {
            "scene_exec_id": scene_exec_id,
            "scene_exec_no": scene_exec.scene_exec_no,
            "status": REDIS_SCENE_STATUS_MAP.get(final, "failed"),
            "status_code": final,
            "success_count": int(scene_exec.success_count or 0),
            "fail_count": int(scene_exec.fail_count or 0),
            "total_rows": int(scene_exec.total_rows or 0),
            "duration_ms": int(scene_exec.duration_ms or 0),
            "error": scene_exec.error_msg,
        }
    finally:
        session.close()
