"""造数引擎模块请求/响应 Schema。"""

from datetime import datetime

from pydantic import BaseModel, Field


# ── 表结构信息 ────────────────────────────────────────────────


class TableItem(BaseModel):
    """表列表项。"""

    table_name: str
    table_comment: str | None = None
    table_rows: int | None = Field(default=0, description="估算行数(information_schema)")
    column_count: int | None = 0
    pk_type: str | None = Field(default="none", description="none/single/composite")
    unique_index_count: int | None = 0
    synced_at: datetime | None = None


class ColumnInfo(BaseModel):
    """表字段详情。"""

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


# ── Case 配置──────────────


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
    跨数据源关联时，表的数据源由 CaseConfig.table_datasources 指定。
    """

    source_table: str | None = None
    source_column: str
    target_table: str
    target_column: str


class RedisSyncConfig(BaseModel):
    """MySQL Case → Redis 联动同步配置（造数批次成功后按模板写 Redis）。

    key_template / value_template 占位符：
    - {表名.字段名}：引用本 Case 生成的字段值（如 {tax_change.customertaxno}）
    - {i}：行在批次内的序号（0 起）；{incr}：全局递增序号（1 起，跨批次连续）
    - {uuid} / {uuid:8}：随机 UUID（可指定截断长度）；{rand:6}：指定位数随机数字
    - {task_no}：执行任务编号；{ts} / {ts_ms}：当前时间戳（秒/毫秒）
    """

    name: str | None = Field(default=None, max_length=100, description="备注名（批次日志展示用）")
    datasource_id: int = Field(description="目标 Redis 数据源 ID")
    key_template: str = Field(min_length=1, max_length=500)
    write_mode: str = Field(default="per_row", description="per_row=每行一个Key / single_key=聚合到一个Key")
    data_type: str = Field(default="string", description="string/json/hash/list/set/zset")
    # 参与 value 组装的字段（table.column 格式）；为空时取主表全部非 SKIP 字段
    fields: list[str] = []
    value_template: str | None = Field(default=None, max_length=2000,
                                       description="自定义 value 模板，为空按 data_type 默认组装")
    score_field: str | None = Field(default=None, description="zset 分数字段（table.column）")
    ttl_seconds: int = Field(default=0, ge=0, description="Key 过期时间（秒），0=不过期")


class RedisCaseConfig(BaseModel):
    """纯 Redis 造数配置（case_type=redis 时生效）。

    key_template 占位符：{字段名} 引用 field_configs 生成的值；
    其余同 RedisSyncConfig（{incr}/{uuid}/{rand:N}/{i}/{ts} 等）。
    """

    key_template: str = Field(min_length=1, max_length=500)
    write_mode: str = Field(default="per_row", description="per_row=每行一个Key / single_key=聚合到一个Key")
    data_type: str = Field(default="json", description="string/json/hash/list/set/zset")
    # value 字段生成策略（column_name 即字段名，复用造数策略引擎）
    field_configs: list[FieldConfig] = []
    value_template: str | None = Field(default=None, max_length=2000)
    score_field: str | None = Field(default=None, description="zset 分数字段名")
    ttl_seconds: int = Field(default=0, ge=0)


class CaseConfig(BaseModel):
    """完整造数配置（df_case.config_json 的结构化表示）。"""

    version: str = "1.0"
    case_type: str = Field(default="mysql", description="mysql=关系库造数 / redis=Redis造数")
    main_table: str = Field(default="", description="主操作表（redis Case 时可为空）")
    field_configs: list[FieldConfig] = []
    associations: list[AssociationConfig] = []
    # 关联表字段策略覆盖：{表名: [FieldConfig]}，缺省的关联表由执行器从缓存自动推断
    related_field_configs: dict[str, list[FieldConfig]] = {}
    # 跨数据源关联：{表名: 数据源ID}，缺省为 Case 主数据源（仅关联表需要声明）
    table_datasources: dict[str, int] = {}
    # MySQL Case → Redis 联动同步配置
    redis_syncs: list[RedisSyncConfig] = []
    # 纯 Redis 造数配置（case_type=redis 必填）
    redis_config: RedisCaseConfig | None = None


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
