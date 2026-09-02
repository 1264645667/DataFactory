"""造数引擎模块请求/响应 Schema（API 清单 10.4 + PRD 第 4 章 + 架构文档 4.2）。"""

from datetime import datetime

from pydantic import BaseModel, Field


# ── 表结构信息 ────────────────────────────────────────────────


class TableItem(BaseModel):
    """表列表项（PRD 4.3.1 展示列）。"""

    table_name: str
    table_comment: str | None = None
    table_rows: int | None = Field(default=0, description="估算行数(information_schema)")
    column_count: int | None = 0
    pk_type: str | None = Field(default="none", description="none/single/composite")
    unique_index_count: int | None = 0
    synced_at: datetime | None = None


class ColumnInfo(BaseModel):
    """表字段详情（含 PRD 4.4.3-A 自动推断策略）。"""

    column_name: str
    column_comment: str | None = None
    data_type: str = Field(description="基础类型: varchar/int/datetime等")
    column_type: str = Field(description="完整类型: varchar(255)/int(11)等")
    is_nullable: int
    is_primary_key: int
    is_unique: int
    column_default: str | None = None
    char_max_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None
    ordinal_position: int
    extra: str | None = Field(default=None, description="auto_increment等")
    suggested_strategy: str | None = Field(default=None, description="自动推断的造数策略")
    suggested_params: dict | None = Field(default=None, description="自动推断的策略参数")


class IndexInfo(BaseModel):
    """表索引信息。"""

    index_name: str
    is_unique: int
    is_primary: int
    column_names: list[str] = []


# ── Case 配置（架构文档 4.2 config_json 格式规范）──────────────


class FieldConfig(BaseModel):
    """单个字段的造数策略配置。"""

    column_name: str
    data_type: str
    column_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    strategy: str = Field(
        description=(
            "DEFAULT/RANDOM_FIXED_LEN/RANDOM_RANGE_LEN/CUSTOM_VALUE/PICK_FROM_LIST/"
            "ITERATE_LIST/UUID/SNOWFLAKE/INCR_FROM/NOW/RANDOM_TIME_RANGE/FIXED_TIME/SKIP"
        )
    )
    strategy_params: dict = Field(default_factory=dict)


class AssociationConfig(BaseModel):
    """字段关联配置（支持多级：源表可以是主表或任一已关联表）。

    多级链式示例：A.customername→B.customername，B.customertaxno→C.customertaxno。
    source_table 缺省为主表（向后兼容旧的一级关联配置）。
    """

    source_table: str | None = None
    source_column: str
    target_table: str
    target_column: str


class CaseConfig(BaseModel):
    """完整造数配置（df_case.config_json 的结构化表示）。"""

    version: str = "1.0"
    main_table: str
    field_configs: list[FieldConfig] = []
    associations: list[AssociationConfig] = []


# ── 创建 / 执行 ───────────────────────────────────────────────


class EngineSaveRequest(BaseModel):
    """仅保存 Case，不执行（POST /engine/save）。"""

    case_name: str = Field(min_length=1, max_length=200)
    datasource_id: int
    config: CaseConfig


class EngineSaveResponse(BaseModel):
    case_id: int
    case_name: str


class EngineExecuteRequest(BaseModel):
    """创建 Case 并立即执行（POST /engine/execute）。"""

    case_name: str = Field(min_length=1, max_length=200)
    datasource_id: int
    target_count: int = Field(gt=0, description="目标造数条数")
    config: CaseConfig
    # 执行参数（可空，为空时后端按 6.8.4 自动推荐）
    batch_size: int | None = Field(default=None, gt=0)
    max_workers: int | None = Field(default=None, gt=0, le=32)
    disable_unique_checks: bool = False
    disable_fk_checks: bool = False


class EngineExecuteResponse(BaseModel):
    case_id: int
    task_no: str
