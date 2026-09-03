"""任务进度模块请求/响应 Schema。"""

from datetime import datetime

from pydantic import BaseModel, Field


# ── 任务实时进度─────────────────────────


class TaskTableProgress(BaseModel):
    """单表实时进度。"""

    table_name: str
    role: str = Field(default="related", description="main=主表 related=关联表")
    target: int
    success: int
    failed: int
    progress_percent: float
    insert_rate: float = Field(description="条/秒（最近3秒滑动窗口）")
    status: str = Field(description="pending/running/success/failed")


class TaskOverallProgress(BaseModel):
    """任务整体进度。"""

    target_total: int
    success_total: int
    fail_total: int
    progress_percent: float
    insert_rate: float
    estimated_remaining_seconds: int | None = None


class TaskProgressResponse(BaseModel):
    """任务实时进度（GET /tasks/{task_no}/progress）。"""

    task_no: str
    status: str = Field(
        description="submitted/running/success/failed/partial_success/aborted"
    )
    start_at: datetime | None = None
    elapsed_seconds: int | None = None
    batch_size: int | None = None
    concurrency: int | None = None
    # ITERATE_LIST 遍历模式轮次信息
    current_round: int | None = None
    total_rounds: int | None = None
    current_drive_value: str | None = None
    overall: TaskOverallProgress
    tables: list[TaskTableProgress] = []


# ── 重试失败批次（断点续传）─────────────────────────────────────


class RetryBatchesRequest(BaseModel):
    """重试失败批次；遍历模式可按轮次重试。"""

    batch_nos: list[int] | None = Field(
        default=None, description="指定批次序号列表，为空=全部失败批次"
    )
    round_no: int | None = Field(default=None, description="遍历模式指定重试轮次")


# ── 任务详情 ──────────────────────────────────────────────────


class BatchLogItem(BaseModel):
    """分批次日志项。"""

    id: int
    table_name: str
    batch_no: int
    batch_size: int
    status: int = Field(description="0=待执行 1=成功 2=失败")
    retry_times: int
    error_msg: str | None = None
    start_at: datetime | None = None
    finish_at: datetime | None = None
    duration_ms: int | None = None
    # 遍历模式扩展
    round_no: int | None = None
    drive_value: str | None = None


class TaskDetailResponse(BaseModel):
    """任务详情（GET /tasks/{task_no}/detail，含分批次日志）。"""

    task_no: str
    case_id: int
    case_name: str
    datasource_id: int
    datasource_name: str
    main_table: str
    related_tables: list[str] = []
    target_count: int
    success_count: int
    fail_count: int
    retry_count: int
    status: int = Field(
        description="0=待执行 1=执行中 2=成功 3=失败 4=重试中 5=部分成功 6=已中止"
    )
    error_msg: str | None = None
    # ── 回滚状态 ──
    rollback_status: int = Field(default=0, description="0=未回滚 1=回滚中 2=已回滚 3=回滚失败")
    rolled_back_at: datetime | None = None
    rollback_rows: int = Field(default=0, description="当前可回滚条数（未回滚的回滚日志累计）")
    rollback_targets: list[str] = Field(default=[], description="可回滚目标列表（表名/Redis标识）")
    table_ds_names: dict[str, str] = Field(default={}, description="表名→数据源名（跨数据源 Case 展示用）")
    start_at: datetime | None = None
    finish_at: datetime | None = None
    duration_ms: int | None = None
    created_by: int
    created_at: datetime
    batch_logs: list[BatchLogItem] = []
