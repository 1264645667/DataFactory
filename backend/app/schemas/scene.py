"""场景管理模块请求/响应 Schema（API 清单 10.6 + PRD 第 6 章 + 架构文档 4.3/6.9.3）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── 场景编排（架构文档 4.3 nodes_json / edges_json 格式规范）─────


class SceneNodePosition(BaseModel):
    """画布坐标（仅用于前端渲染）。"""

    x: float = 0
    y: float = 0


class SceneNode(BaseModel):
    """场景节点配置。"""

    node_id: str = Field(description="前端生成的 UUID，全场景唯一")
    case_id: int
    case_name: str
    target_count: int = Field(gt=0, description="本节点造数条数")
    fail_strategy: Literal["continue", "abort"] = "continue"
    position: SceneNodePosition = Field(default_factory=SceneNodePosition)


class SceneEdge(BaseModel):
    """节点依赖连线。"""

    edge_id: str
    source: str = Field(description="前置节点 node_id")
    target: str = Field(description="后置节点 node_id")


class SceneCreateRequest(BaseModel):
    """新建场景。"""

    scene_name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    nodes: list[SceneNode] = Field(min_length=2, description="场景至少需要 2 个 Case 节点")
    edges: list[SceneEdge] = []


class SceneUpdateRequest(BaseModel):
    """编辑场景。"""

    scene_name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    nodes: list[SceneNode] = Field(min_length=2)
    edges: list[SceneEdge] = []


class SceneCopyRequest(BaseModel):
    """复制场景。"""

    scene_name: str | None = Field(default=None, max_length=200)


# ── 场景查询 ──────────────────────────────────────────────────


class SceneListItem(BaseModel):
    """场景列表项（PRD 6.2.2 表格列）。"""

    id: int
    scene_name: str
    description: str | None = None
    node_count: int
    exec_mode: str = Field(description="serial=纯串行 parallel=纯并行 mixed=混合")
    created_by: int
    creator_name: str | None = None
    created_at: datetime
    last_exec_at: datetime | None = None
    last_exec_status: int | None = Field(
        default=None, description="0=未执行 1=成功 2=失败 3=部分成功 4=已中止"
    )
    exec_count: int = 0


class SceneDetail(BaseModel):
    """场景详情（含 nodes_json + edges_json）。"""

    id: int
    scene_name: str
    description: str | None = None
    nodes: list[SceneNode]
    edges: list[SceneEdge]
    node_count: int
    exec_mode: str
    group_type: int
    created_by: int
    creator_name: str | None = None
    created_at: datetime
    updated_at: datetime
    last_exec_at: datetime | None = None
    last_exec_status: int | None = None
    exec_count: int = 0


# ── 场景执行 ──────────────────────────────────────────────────


class SceneExecuteResponse(BaseModel):
    scene_exec_no: str


class SceneExecHistoryItem(BaseModel):
    """场景执行历史项。"""

    scene_exec_no: str
    node_count: int
    success_count: int
    fail_count: int
    total_rows: int
    status: int = Field(description="0=待执行 1=执行中 2=成功 3=失败 4=部分成功 5=已中止")
    error_msg: str | None = None
    duration_ms: int | None = None
    start_at: datetime | None = None
    finish_at: datetime | None = None
    created_at: datetime


class SceneRetryNodesRequest(BaseModel):
    """重试失败节点（PRD 6.6）。"""

    node_ids: list[str] = Field(min_length=1, description="需重试的节点 node_id 列表")


# ── 场景执行进度（架构文档 6.9.3 响应结构）──────────────────────


class SceneNodeProgress(BaseModel):
    """单个节点实时进度。"""

    node_id: str
    case_name: str
    status: str = Field(description="pending/running/success/failed/cancelled")
    target: int
    success: int
    task_no: str | None = None
    layer: int


class SceneLayerProgress(BaseModel):
    """拓扑分层进度。"""

    layer_no: int
    status: str = Field(description="pending/running/success/failed")
    nodes: list[SceneNodeProgress] = []


class SceneProgressOverall(BaseModel):
    """场景整体进度。"""

    node_count: int
    success_count: int
    fail_count: int
    pending_count: int
    running_count: int
    target_rows: int
    success_rows: int


class SceneProgressResponse(BaseModel):
    """场景执行实时进度（GET /scenes/exec/{scene_exec_no}/progress）。"""

    scene_exec_no: str
    status: str = Field(description="submitted/running/success/failed/partial_success/aborted")
    total_layers: int
    current_layer: int
    elapsed_seconds: int | None = None
    overall: SceneProgressOverall
    layers: list[SceneLayerProgress] = []
