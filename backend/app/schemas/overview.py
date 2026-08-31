"""造数总览模块请求/响应 Schema（API 清单 10.8 + PRD 第 3 章）。"""

from datetime import datetime

from pydantic import BaseModel, Field


class OverviewMetrics(BaseModel):
    """核心指标卡片数据（PRD 3.3，6+1 个指标）。

    compare_yesterday 存放各指标「较昨日」环比增量，键为指标字段名。
    """

    total_case_count: int = Field(description="总 Case 数")
    total_scene_count: int = Field(description="总场景数")
    today_exec_count: int = Field(description="今日执行次数（含 Case + 场景）")
    total_row_count: int = Field(description="累计造数条数")
    exec_success_rate: float = Field(description="近 30 天执行成功率（0~100）")
    active_datasource_count: int = Field(description="近 7 天活跃数据源数")
    group_member_count: int = Field(description="本组成员数")
    compare_yesterday: dict[str, float] = Field(default_factory=dict)


class TrendPoint(BaseModel):
    """执行趋势折线图数据点。"""

    date: str = Field(description="yyyy-MM-dd")
    exec_count: int
    row_count: int
    success_rate: float


class TrendResponse(BaseModel):
    range_days: int = Field(description="7/30/90")
    points: list[TrendPoint] = []


class StatusDistItem(BaseModel):
    """执行状态分布项。"""

    status: str = Field(description="success/failed/running/retrying/partial_success")
    count: int
    percent: float


class StatusDistResponse(BaseModel):
    total: int
    items: list[StatusDistItem] = []


class TableTopItem(BaseModel):
    """表操作量 Top10 项。"""

    table_name: str
    datasource_name: str
    row_count: int = Field(description="操作数据条数")
    case_count: int = Field(description="涉及 Case 数")


class MemberRankItem(BaseModel):
    """成员贡献排行项。"""

    user_id: int
    username: str
    real_name: str | None = None
    row_count: int = Field(description="造数条数")
    exec_count: int


class ExecRecordItem(BaseModel):
    """执行记录明细表行（PRD 3.5 表格列）。"""

    task_no: str
    case_name: str
    datasource_name: str
    main_table: str
    related_count: int = Field(description="本次涉及表数量")
    target_count: int
    success_count: int = Field(description="实际插入条数")
    status: int
    duration_ms: int | None = None
    creator_name: str | None = None
    start_at: datetime | None = None
    created_at: datetime
