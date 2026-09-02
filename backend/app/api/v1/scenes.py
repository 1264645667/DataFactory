"""场景管理模块路由

GET    /                              场景列表（分页 + 筛选）
GET    /{scene_id}                    场景详情
POST   /                              新建场景
PUT    /{scene_id}                    编辑场景
DELETE /{scene_id}                    逻辑删除场景
POST   /{scene_id}/execute            执行场景（返回 scene_exec_no）
POST   /{scene_id}/copy               复制场景
GET    /{scene_id}/history            场景执行历史
GET    /exec/{scene_exec_no}/progress     场景执行实时进度
POST   /exec/{scene_exec_no}/abort        强制停止场景
POST   /exec/{scene_exec_no}/retry-nodes  重试失败节点
注意：/exec/* 静态前缀路径必须声明在 /{scene_id} 动态路径之前。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PageParams, require_permission, to_local_naive
from app.db.session import get_db
from app.models.user import User
from app.schemas.response import ApiResponse, PageData
from app.schemas.scene import (
    SceneCopyRequest,
    SceneCreateRequest,
    SceneDetail,
    SceneExecHistoryItem,
    SceneExecuteResponse,
    SceneListItem,
    SceneProgressResponse,
    SceneRetryNodesRequest,
    SceneUpdateRequest,
)
from app.services import scene_service

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ── 执行记录级操作（/exec/*，须先于 /{scene_id} 声明）────────────────


@router.get("/exec/{scene_exec_no}/progress", summary="场景执行实时进度")
async def scene_progress(
    scene_exec_no: str,
    current_user: User = Depends(require_permission("SCENE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SceneProgressResponse]:
    data = await scene_service.get_scene_progress(
        db, current_user=current_user, scene_exec_no=scene_exec_no
    )
    return ApiResponse(data=data)


@router.post("/exec/{scene_exec_no}/abort", summary="强制停止场景")
async def abort_scene(
    scene_exec_no: str,
    request: Request,
    current_user: User = Depends(require_permission("SCENE:EXECUTE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await scene_service.abort_scene(
        db, current_user=current_user, scene_exec_no=scene_exec_no, ip=_ip(request)
    )
    return ApiResponse(message="场景已停止")


@router.post("/exec/{scene_exec_no}/retry-nodes", summary="重试失败节点")
async def retry_nodes(
    scene_exec_no: str,
    body: SceneRetryNodesRequest,
    request: Request,
    current_user: User = Depends(require_permission("SCENE:EXECUTE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await scene_service.retry_scene_nodes(
        db, current_user=current_user, scene_exec_no=scene_exec_no,
        node_ids=body.node_ids, ip=_ip(request),
    )
    return ApiResponse(message="重试任务已提交")


# ── 场景 CRUD ─────────────────────────────────────────────────────


@router.get("", summary="场景列表（分页 + 筛选）")
async def list_scenes(
    page_params: PageParams = Depends(),
    name: str | None = Query(default=None, description="场景名称模糊搜索"),
    created_by: int | None = Query(default=None),
    last_exec_status: list[int] | None = Query(default=None),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    current_user: User = Depends(require_permission("SCENE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PageData[SceneListItem]]:
    data = await scene_service.list_scenes(
        db, current_user=current_user,
        page=page_params.page, page_size=page_params.page_size,
        name=name, created_by=created_by, last_exec_status=last_exec_status,
        start_time=to_local_naive(start_time), end_time=to_local_naive(end_time),
    )
    return ApiResponse(data=data)


@router.get("/{scene_id}", summary="场景详情（含 nodes_json + edges_json）")
async def get_scene(
    scene_id: int,
    current_user: User = Depends(require_permission("SCENE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SceneDetail]:
    data = await scene_service.get_scene_detail(db, current_user=current_user, scene_id=scene_id)
    return ApiResponse(data=data)


@router.post("", summary="新建场景")
async def create_scene(
    body: SceneCreateRequest,
    request: Request,
    current_user: User = Depends(require_permission("SCENE:CREATE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    scene = await scene_service.create_scene(
        db, current_user=current_user, req=body, ip=_ip(request)
    )
    return ApiResponse(
        data={"scene_id": scene.id, "scene_name": scene.scene_name, "exec_mode": scene.exec_mode},
        message="场景已保存",
    )


@router.put("/{scene_id}", summary="编辑场景")
async def update_scene(
    scene_id: int,
    body: SceneUpdateRequest,
    request: Request,
    current_user: User = Depends(require_permission("SCENE:EDIT")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    scene = await scene_service.update_scene(
        db, current_user=current_user, scene_id=scene_id, req=body, ip=_ip(request)
    )
    return ApiResponse(
        data={"scene_id": scene.id, "scene_name": scene.scene_name, "exec_mode": scene.exec_mode},
        message="场景已保存",
    )


@router.delete("/{scene_id}", summary="逻辑删除场景")
async def delete_scene(
    scene_id: int,
    request: Request,
    current_user: User = Depends(require_permission("SCENE:DELETE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await scene_service.delete_scene(db, current_user=current_user, scene_id=scene_id, ip=_ip(request))
    return ApiResponse(message="场景已删除，历史执行记录保留")


@router.post("/{scene_id}/execute", summary="执行场景（返回 scene_exec_no）")
async def execute_scene(
    scene_id: int,
    request: Request,
    current_user: User = Depends(require_permission("SCENE:EXECUTE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SceneExecuteResponse]:
    scene_exec_no = await scene_service.execute_scene(
        db, current_user=current_user, scene_id=scene_id, ip=_ip(request)
    )
    return ApiResponse(data=SceneExecuteResponse(scene_exec_no=scene_exec_no), message="场景任务已提交")


@router.post("/{scene_id}/copy", summary="复制场景（默认名 xxx_copy）")
async def copy_scene(
    scene_id: int,
    body: SceneCopyRequest,
    request: Request,
    current_user: User = Depends(require_permission("SCENE:CREATE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    new_scene = await scene_service.copy_scene(
        db, current_user=current_user, scene_id=scene_id,
        scene_name=body.scene_name, ip=_ip(request),
    )
    return ApiResponse(
        data={"scene_id": new_scene.id, "scene_name": new_scene.scene_name},
        message="复制成功",
    )


@router.get("/{scene_id}/history", summary="场景执行历史列表")
async def scene_history(
    scene_id: int,
    current_user: User = Depends(require_permission("SCENE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[SceneExecHistoryItem]]:
    items = await scene_service.get_scene_history(db, current_user=current_user, scene_id=scene_id)
    return ApiResponse(data=items)
