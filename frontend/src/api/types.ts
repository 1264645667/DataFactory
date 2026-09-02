// 全部 TypeScript 类型定义，与后端 Schema 一一对应

/** 统一响应格式 */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
  trace_id?: string
}

/** 分页结果（与后端 PageData schema 对齐） */
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ---------------- 用户与认证 ----------------

/** 分组类型：1 销项组 / 2 申报组 / 99 管理员 */
export type GroupType = 1 | 2 | 99
/** 用户状态：0 待审批 / 1 正常 / 2 禁用 / 3 已拒绝 */
export type UserStatus = 0 | 1 | 2 | 3

export interface UserInfo {
  id: number
  username: string
  real_name: string
  /** 1=销项组 2=申报组 99=管理员 */
  group_type: GroupType
  status: UserStatus
  /** 头像序号（1~10） */
  avatar_index: number
  permissions: string[]
  default_datasource_id: number | null
  created_at?: string
}

export interface LoginParams {
  username: string
  password: string
}

export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
  user: UserInfo
}

export interface RegisterParams {
  username: string
  password: string
  real_name: string
  group_type: 1 | 2
  /** 申请理由（后端字段 apply_reason） */
  apply_reason?: string
}

/** 待审批用户（后端 PendingUserItem） */
export interface PendingUser {
  id: number
  username: string
  real_name: string
  group_type: GroupType
  /** 申请理由（后端字段 apply_reason） */
  apply_reason: string | null
  created_at: string
}

/** 用户管理列表项（后端 UserListItem） */
export interface AdminUserItem {
  id: number
  username: string
  real_name: string
  group_type: GroupType
  status: UserStatus
  permissions: string[]
  default_datasource_id: number | null
  last_login_at: string | null
  created_at: string
}

/** 操作日志（后端 AuditLogItem，纯数组返回不分页） */
export interface AuditLogItem {
  id: number
  user_id: number
  /** 操作人账号 */
  username: string
  /** 操作人姓名 */
  real_name?: string | null
  group_type?: GroupType | null
  action: string
  /** 操作对象类型（case/scene/datasource 等） */
  resource: string | null
  resource_id?: string | null
  detail: string | null
  ip: string | null
  created_at: string
}

// ---------------- 数据源 ----------------

export interface Datasource {
  id: number
  name: string
  db_type: string
  host: string
  port: number
  database_name: string
  username: string
  group_type: GroupType
  /** 缓存状态：0=未初始化 1=正常 2=异常 3=同步中 */
  status: number
  /** 连接状态（30s 心跳）：null=暂无心跳数据 */
  online: boolean | null
  table_count: number
  last_sync_at: string | null
  remark: string | null
  is_default?: boolean
}

export interface DatasourceForm {
  name: string
  db_type: string
  host: string
  port: number
  database_name: string
  username: string
  password?: string
  group_type: GroupType
  remark?: string
}

/** 测试连接响应 */
export interface DatasourceTestResult {
  success: boolean
  message: string
  db_version?: string | null
}

/** 数据源心跳状态响应 */
export interface DatasourceStatus {
  datasource_id: number
  online: boolean
  latency_ms?: number | null
  error?: string | null
  checked_at: string
}

// ---------------- 造数引擎 ----------------

export type PkType = 'none' | 'single' | 'composite'

export interface TableInfo {
  table_name: string
  table_comment: string | null
  /** 估算行数（后端字段 table_rows） */
  table_rows: number
  column_count: number
  pk_type: PkType
  unique_index_count: number
  synced_at: string | null
}

export interface ColumnInfo {
  column_name: string
  column_comment: string | null
  data_type: string
  column_type: string
  /** 后端返回 0/1 */
  is_nullable: number
  is_primary_key: number
  is_unique: number
  char_max_length: number | null
  numeric_precision?: number | null
  numeric_scale?: number | null
  ordinal_position?: number
  column_default: string | null
  extra: string | null
  /** 后端自动推断的默认策略（4.4.3-A） */
  suggested_strategy?: string
  suggested_params?: Record<string, unknown>
}

export interface IndexInfo {
  index_name: string
  /** 索引列名列表（后端字段 column_names） */
  column_names: string[]
  /** 后端返回 0/1 */
  is_unique: number
  is_primary: number
}

/** 造数策略编码 */
export type StrategyCode =
  | 'DEFAULT'
  | 'SKIP'
  | 'RANDOM_FIXED_LEN'
  | 'RANDOM_RANGE_LEN'
  | 'CUSTOM_VALUE'
  | 'PICK_FROM_LIST'
  | 'ITERATE_LIST'
  | 'UUID'
  | 'SNOWFLAKE'
  | 'INCR_FROM'
  | 'DERIVED'
  | 'TOOL_GEN'
  | 'NOW'
  | 'RANDOM_TIME_RANGE'
  | 'FIXED_TIME'

/** 字段策略配置（config.field_configs 元素） */
export interface FieldStrategyConfig {
  column_name: string
  data_type: string
  column_type: string
  is_nullable: boolean
  is_primary_key: boolean
  strategy: StrategyCode
  strategy_params: Record<string, unknown>
}

/** 字段关联（config.associations 元素，支持多级：source_table 缺省为主表） */
export interface Association {
  /** 源表（多级关联时指定，缺省为主表） */
  source_table?: string | null
  source_column: string
  target_table: string
  target_column: string
}

/** Case config 完整结构 */
export interface CaseConfigJson {
  version: string
  main_table: string
  field_configs: FieldStrategyConfig[]
  associations: Association[]
  /** 关联表字段策略覆盖：{表名: 字段配置数组}，缺省的关联表由执行器自动推断 */
  related_field_configs?: Record<string, FieldStrategyConfig[]>
}

/** 保存/执行 Case 请求体（后端要求 config 嵌套） */
export interface EngineSaveParams {
  case_name: string
  datasource_id: number
  config: CaseConfigJson
}

export interface EngineExecuteParams extends EngineSaveParams {
  target_count: number
  batch_size?: number | null
  max_workers?: number | null
  disable_unique_checks?: boolean
  disable_fk_checks?: boolean
}

/** POST /engine/execute 响应（后端 EngineExecuteResponse） */
export interface ExecuteResult {
  case_id: number
  task_no: string
}

/** POST /engine/save 响应（后端 EngineSaveResponse） */
export interface EngineSaveResult {
  case_id: number
  case_name: string
}

// ---------------- Case 管理 ----------------

/**
 * 执行状态（完整码，df_exec_task.status，用于执行记录/历史/任务详情）：
 * 0待执行 1执行中 2成功 3失败 4重试中 5部分成功 6已中止
 */
export type ExecStatusCode = 0 | 1 | 2 | 3 | 4 | 5 | 6

/**
 * Case 列表「最后执行状态」摘要码（df_case.last_exec_status）：
 * 0未执行 1成功 2失败 3部分成功
 */
export type LastExecStatusCode = 0 | 1 | 2 | 3

export interface CaseItem {
  id: number
  /** Case 名称（后端字段 case_name） */
  case_name: string
  datasource_id: number
  datasource_name: string
  main_table: string
  /** 关联表数（后端字段 related_count） */
  related_count: number
  created_by: number
  /** 创建人姓名（后端字段 creator_name） */
  creator_name: string | null
  created_at: string
  last_exec_at: string | null
  /** 最后执行状态摘要码 0未执行 1成功 2失败 3部分成功 */
  last_exec_status: LastExecStatusCode | null
  exec_count: number
}

export interface CaseDetail {
  id: number
  case_name: string
  datasource_id: number
  datasource_name: string
  main_table: string
  related_tables: string[]
  related_count: number
  /** 完整造数配置（后端字段 config） */
  config: CaseConfigJson
  group_type: GroupType
  created_by: number
  creator_name: string | null
  created_at: string
  updated_at: string
  last_exec_at: string | null
  last_exec_status: LastExecStatusCode | null
  exec_count: number
}

export interface CaseListQuery {
  page?: number
  page_size?: number
  datasource_id?: number
  /** Case 名称模糊搜索（后端参数名 name） */
  name?: string
  created_by?: number
  /** 最后执行状态多选（摘要码 0~3） */
  last_exec_status?: number[]
  start_time?: string
  end_time?: string
  main_table?: string
}

/** Case 执行历史项（后端 CaseHistoryItem） */
export interface CaseHistoryItem {
  task_no: string
  target_count: number
  success_count: number
  fail_count: number
  /** 完整状态码 0~6 */
  status: ExecStatusCode
  duration_ms: number | null
  start_at: string | null
  finish_at: string | null
  created_at: string
}

/** Case 执行历史响应（后端为 dict，含统计，不分页） */
export interface CaseHistoryResult {
  items: CaseHistoryItem[]
  total_count: number
  success_count: number
  total_rows: number
}

/** 批量执行响应（后端 CaseBatchExecuteResponse，与请求 items 同序） */
export interface CaseBatchExecuteResult {
  task_nos: string[]
}

/** 执行单个 Case 响应（后端 CaseExecuteResponse） */
export interface CaseExecuteResponse {
  task_no: string
}

// ---------------- 任务进度 ----------------

export type TaskStatus = 'submitted' | 'running' | 'success' | 'failed' | 'partial_success' | 'aborted'
export type TableRunStatus = 'pending' | 'running' | 'success' | 'failed'

export interface TaskOverall {
  target_total: number
  success_total: number
  fail_total: number
  progress_percent: number
  insert_rate: number
  estimated_remaining_seconds: number | null
}

export interface TaskTableProgress {
  table_name: string
  role: 'main' | 'related'
  target: number
  success: number
  failed: number
  progress_percent: number
  insert_rate: number
  status: TableRunStatus
}

/**
 * 任务实时进度（后端 TaskProgressResponse，平铺结构）。
 * 遍历模式通过 current_round/total_rounds/current_drive_value 判断（total_rounds 非空即遍历任务）。
 */
export interface TaskProgressData {
  task_no: string
  status: TaskStatus
  start_at?: string | null
  elapsed_seconds: number | null
  batch_size: number | null
  concurrency: number | null
  /** 遍历模式当前轮次（非遍历为 null） */
  current_round?: number | null
  /** 遍历模式总轮次（非遍历为 null） */
  total_rounds?: number | null
  /** 遍历模式当前驱动值 */
  current_drive_value?: string | null
  overall: TaskOverall
  tables: TaskTableProgress[]
}

/** 分批次日志（后端 BatchLogItem） */
export interface BatchLog {
  id: number
  table_name: string
  batch_no: number
  batch_size: number
  /** 批次状态：0待执行 1成功 2失败 */
  status: number
  retry_times: number
  error_msg: string | null
  start_at: string | null
  finish_at: string | null
  duration_ms: number | null
  round_no?: number | null
  drive_value?: string | null
}

/** 任务详情（后端 TaskDetailResponse） */
export interface TaskDetailData {
  task_no: string
  case_id: number
  case_name: string
  datasource_id: number
  datasource_name: string
  main_table: string
  related_tables: string[]
  target_count: number
  success_count: number
  fail_count: number
  retry_count: number
  /** 完整状态码 0~6 */
  status: ExecStatusCode
  error_msg: string | null
  start_at: string | null
  finish_at: string | null
  duration_ms: number | null
  created_by: number
  created_at: string
  batch_logs: BatchLog[]
}

// ---------------- 场景管理 ----------------

export type FailStrategy = 'continue' | 'abort'

export interface SceneNode {
  node_id: string
  case_id: number
  case_name: string
  target_count: number
  fail_strategy: FailStrategy
  position: { x: number; y: number }
}

export interface SceneEdge {
  edge_id: string
  source: string
  target: string
}

export type SceneExecMode = 'serial' | 'parallel' | 'mixed'
export type SceneStatus = 'submitted' | 'running' | 'success' | 'failed' | 'partial_success' | 'aborted'

/** 场景列表「最后执行状态」摘要码：0未执行 1成功 2失败 3部分成功 4已中止 */
export type SceneLastExecStatusCode = 0 | 1 | 2 | 3 | 4

export interface SceneItem {
  id: number
  /** 场景名称（后端字段 scene_name） */
  scene_name: string
  description: string | null
  node_count: number
  exec_mode: SceneExecMode
  created_by: number
  /** 创建人姓名（后端字段 creator_name） */
  creator_name: string | null
  created_at: string
  last_exec_at: string | null
  last_exec_status: SceneLastExecStatusCode | null
  exec_count: number
}

export interface SceneDetail {
  id: number
  scene_name: string
  description: string | null
  /** 节点列表（后端字段 nodes，非 nodes_json） */
  nodes: SceneNode[]
  /** 连线列表（后端字段 edges，非 edges_json） */
  edges: SceneEdge[]
  node_count: number
  exec_mode: SceneExecMode
  group_type: GroupType
  created_by: number
  creator_name: string | null
  created_at: string
  updated_at: string
  last_exec_at: string | null
  last_exec_status: SceneLastExecStatusCode | null
  exec_count: number
}

/** 场景保存请求体（后端 SceneCreateRequest/SceneUpdateRequest） */
export interface SceneSaveParams {
  scene_name: string
  description?: string | null
  nodes: SceneNode[]
  edges: SceneEdge[]
}

export interface SceneNodeProgress {
  node_id: string
  case_name: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
  target: number
  success: number
  task_no: string | null
  layer: number
}

export interface SceneLayer {
  layer_no: number
  status: 'pending' | 'running' | 'success' | 'failed'
  nodes: SceneNodeProgress[]
}

export interface SceneProgressData {
  scene_exec_no: string
  status: SceneStatus
  total_layers: number
  current_layer: number
  elapsed_seconds: number | null
  overall: {
    node_count: number
    success_count: number
    fail_count: number
    pending_count: number
    running_count: number
    target_rows: number
    success_rows: number
  }
  layers: SceneLayer[]
}

/** 场景执行历史项（后端 SceneExecHistoryItem，纯数组返回不分页） */
export interface SceneHistoryItem {
  scene_exec_no: string
  node_count: number
  /** 成功节点数（后端字段 success_count） */
  success_count: number
  /** 失败节点数（后端字段 fail_count） */
  fail_count: number
  total_rows: number
  /** 场景执行状态：0待执行 1执行中 2成功 3失败 4部分成功 5已中止 */
  status: number
  error_msg: string | null
  duration_ms: number | null
  start_at: string | null
  finish_at: string | null
  created_at: string
}

// ---------------- 造数总览 ----------------

export interface OverviewMetrics {
  total_case_count: number
  total_scene_count: number
  today_exec_count: number
  total_row_count: number
  exec_success_rate: number
  active_datasource_count: number
  group_member_count: number
  /** 各指标「较昨日」环比增量，键为后端指标字段名 */
  compare_yesterday?: Record<string, number>
}

export interface TrendPoint {
  date: string
  exec_count: number
  row_count: number
  success_rate: number
}

/** 趋势响应（后端 TrendResponse 包裹结构） */
export interface TrendResult {
  range_days: number
  points: TrendPoint[]
}

export interface StatusDistItem {
  status: string
  count: number
  percent: number
}

/** 状态分布响应（后端 StatusDistResponse 包裹结构） */
export interface StatusDistResult {
  total: number
  items: StatusDistItem[]
}

export interface TableTopItem {
  table_name: string
  datasource_name: string
  row_count: number
  case_count: number
}

export interface MemberRankItem {
  user_id?: number
  username?: string
  real_name: string
  row_count: number
  exec_count?: number
}

/** 执行记录明细行（后端 ExecRecordItem） */
export interface ExecRecord {
  task_no: string
  case_name: string
  datasource_name: string
  main_table: string
  /** 关联表数（后端字段 related_count） */
  related_count: number
  target_count: number
  success_count: number
  /** 完整状态码 0~6 */
  status: ExecStatusCode
  duration_ms: number | null
  /** 操作人（后端字段 creator_name） */
  creator_name: string | null
  /** 执行时间（后端字段 start_at） */
  start_at: string | null
  created_at: string
}

export interface ExecRecordQuery {
  page?: number
  page_size?: number
  start_time?: string
  end_time?: string
  /** 执行状态多选（完整码 0~6） */
  status?: number[]
  datasource_id?: number
  created_by?: number
  case_name?: string
  table_name?: string
}

// ---------------- 消息通知 ----------------

/** 通知优先级：1=高(红) 2=中(黄) 3=普通(绿) */
export type NotifyPriority = 1 | 2 | 3

export interface NotificationItem {
  id: number
  /** 消息类型（后端字段 msg_type） */
  msg_type: string
  /** 优先级数字码 1高 2中 3普通 */
  priority: NotifyPriority
  title: string
  content: string
  /** 跳转链接（后端字段 link_url） */
  link_url: string | null
  /** 已读标志：0未读 1已读 */
  is_read: number
  read_at: string | null
  created_at: string
}

/** 未读数响应（后端 UnreadCountResponse） */
export interface UnreadCountResult {
  unread_count: number
}

/** 通知列表查询（后端用 is_read/priority，不用 filter） */
export interface NotificationQuery {
  page?: number
  page_size?: number
  /** 0=未读 1=已读 */
  is_read?: number
  /** 1高 2中 3普通 */
  priority?: number
}

// ---------------- 快捷工具 ----------------

/** 工具生成结果统一结构 */
export interface ToolResult<T = Record<string, unknown>> {
  count: number
  results: T[]
}

export interface IdCardItem {
  /** 身份证号（后端字段 id_card） */
  id_card: string
  province: string
  birth_date: string
  gender: string
  check_digit?: string
}

export interface SnowflakeItem {
  /** 雪花 ID（后端 int，前端需按字符串处理避免精度丢失） */
  id: string
  timestamp: number
  machine_id: number
  datacenter_id: number
  sequence: number
}
