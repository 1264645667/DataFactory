"""Case 管理模块请求/响应 Schema（API 清单 10.5 + PRD 第 5 章）。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.engine import CaseConfig


class CaseListItem(BaseModel):
    """Case 列表项（PRD 5.2.2 表格列）。"""

    id: int
    case_name: str
    datasource_id: int
    datasource_name: str
    main_table: str
    related_count: int | None = 0
    created_by: int
    creator_name: str | None = Field(default=None, description="创建人真实姓名")
    created_at: datetime
    last_exec_at: datetime | None = None
    last_exec_status: int | None = Field(
        default=None, description="0=未执行 1=成功 2=失败 3=部分成功"
    )
    exec_count: int = 0


class CaseDetail(BaseModel):
    """Case 详情（含 config_json，PRD 5.4）。"""

    id: int
    case_name: str
    datasource_id: int
    datasource_name: str
    main_table: str
    related_tables: list[str] = []
    related_count: int | None = 0
    config: CaseConfig
    group_type: int
    created_by: int
    creator_name: str | None = None
    created_at: datetime
    updated_at: datetime
    last_exec_at: datetime | None = None
    last_exec_status: int | None = None
    exec_count: int = 0


class CaseUpdateRequest(BaseModel):
    """修改 Case 配置（覆盖式更新，PRD 5.5 不做版本管理）。"""

    case_name: str = Field(min_length=1, max_length=200)
    config: CaseConfig


class CaseExecuteRequest(BaseModel):
    """执行 Case（PRD 5.3.1：只需输入造数条数，可覆盖执行参数）。"""

    target_count: int = Field(gt=0)
    batch_size: int | None = Field(default=None, gt=0)
    max_workers: int | None = Field(default=None, gt=0, le=32)
    disable_unique_checks: bool = False
    disable_fk_checks: bool = False


class CaseExecuteResponse(BaseModel):
    task_no: str


class CaseCopyRequest(BaseModel):
    """复制 Case（默认名称为「原Case名_copy」）。"""

    case_name: str | None = Field(default=None, max_length=200)


class CaseCopyResponse(BaseModel):
    case_id: int
    case_name: str


class CaseHistoryItem(BaseModel):
    """Case 执行历史项（PRD 5.3.4）。"""

    task_no: str
    target_count: int
    success_count: int
    fail_count: int
    status: int = Field(description="0=待执行 1=执行中 2=成功 3=失败 4=重试中 5=部分成功 6=已中止")
    duration_ms: int | None = None
    start_at: datetime | None = None
    finish_at: datetime | None = None
    created_at: datetime


class CaseBatchExecuteItem(BaseModel):
    """批量执行单个 Case 的参数。"""

    case_id: int
    target_count: int = Field(gt=0)


class CaseBatchExecuteRequest(BaseModel):
    """批量执行（PRD 5.3.6：每个 Case 独立条数，串行提交）。"""

    items: list[CaseBatchExecuteItem] = Field(min_length=1)


class CaseBatchExecuteResponse(BaseModel):
    task_nos: list[str]
