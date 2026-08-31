// ============================================================
// 全部 TypeScript 类型定义，与后端 Schema 一一对应
// ============================================================

/** 统一响应格式 */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
  trace_id?: string
}

/** 分页结果 */
export interface PageResult<T> {
  list: T[]
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
  group_type: GroupType
  role: 'ADMIN' | 'MEMBER'
  status: UserStatus
  avatar: number
  permissions: string[]
  default_datasource_id: number | null
  created_at?: string
}

export interface LoginParams {
  username: string
  password: string
}

export interface LoginResult {
  token: string
}

export interface RegisterParams {
  username: string
  password: string
  real_name: string
  group_type: 1 | 2
  reason?: string
}

/** 待审批用户 */
export interface PendingUser {
  id: number
  username: string
  real_name: string
  group_type: GroupType
  reason: string | null
  created_at: string
}

/** 用户管理列表项 */
export interface AdminUserItem {
  id: number
  username: string
  real_name: string
  group_type: GroupType
  status: UserStatus
  avatar: number
  permissions: string[]
  default_datasource_name: string | null
  created_at: string
}

/** 操作日志 */
export interface AuditLogItem {
  id: number
  created_at: string
  operator_name: string
  group_type?: GroupType
  action: string
  target: string
  detail: string | null
  ip: string
}

// ---------------- 数据源 ----------------

export type DsConnStatus = 'online' | 'offline' | 'syncing'
export type DsCacheStatus = 'initialized' | 'initializing' | 'not_initialized' | 'syncing'

export interface Datasource {
  id: number
  name: string
  db_type: string
  host: string
  port: number
  database: string
  username: string
  group_type: GroupType
  status: DsConnStatus
  cache_status: DsCacheStatus
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
  database: string
  username: string
  password?: string
  group_type: GroupType
  remark?: string
}

// ---------------- 造数引擎 ----------------

export type PkType = 'none' | 'single' | 'composite'

export interface TableInfo {
  table_name: string
  table_comment: string
  row_count: number
  column_count: number
  pk_type: PkType
  unique_index_count: number
  synced_at: string | null
}

export interface ColumnInfo {
  column_name: string
  column_comment: string
  data_type: string
  column_type: string
  is_nullable: boolean
  is_primary_key: boolean
  is_unique: boolean
  char_max_length: number | null
  column_default: string | null
  extra: string
  /** 后端自动推断的默认策略（4.4.3-A） */
  suggested_strategy?: string
  suggested_params?: Record<string, unknown>
}

export interface IndexInfo {
  index_name: string
  columns: string[]
  is_unique: boolean
  is_primary: boolean
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
  | 'NOW'
  | 'RANDOM_TIME_RANGE'
  | 'FIXED_TIME'

/** 字段策略配置（config_json.field_configs 元素） */
export interface FieldStrategyConfig {
  column_name: string
  data_type: string
  column_type: string
  is_nullable: boolean
  is_primary_key: boolean
  strategy: StrategyCode
  strategy_params: Record<string, unknown>
}

/** 字段关联（config_json.associations 元素） */
export interface Association {
  source_column: string
  target_table: string
  target_column: string
}

/** Case config_json 完整结构（架构文档 4.2） */
export interface CaseConfigJson {
  version: string
  main_table: string
  field_configs: FieldStrategyConfig[]
  associations: Association[]
}

export interface EngineSaveParams {
  case_name: string
  datasource_id: number
  main_table: string
  field_configs: FieldStrategyConfig[]
  associations: Association[]
}

export interface EngineExecuteParams extends EngineSaveParams {
  target_count: number
}

export interface ExecuteResult {
  task_no: string
  status: string
  message?: string
}

// ---------------- Case 管理 ----------------

export type ExecStatus =
  | 'submitted'
  | 'running'
  | 'retrying'
  | 'success'
  | 'failed'
  | 'partial_success'
  | 'aborted'

export interface CaseItem {
  id: number
  name: string
  datasource_id: number
  datasource_name: string
  main_table: string
  related_table_count: number
  created_by_name: string
  created_at: string
  last_exec_at: string | null
  last_exec_status: ExecStatus | null
}

export interface CaseDetail extends CaseItem {
  config_json: CaseConfigJson
}

export interface CaseListQuery {
  page?: number
  page_size?: number
  datasource_id?: number
  name?: string
  created_by?: number
  last_exec_status?: string[]
  start_time?: string
  end_time?: string
  main_table?: string
}

export interface CaseHistoryItem {
  task_no: string
  target_count: number
  success_count: number
  status: ExecStatus
  duration_seconds: number | null
  started_at: string
}

// ---------------- 任务进度（架构文档 6.6.2） ----------------

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

/** ITERATE_LIST 遍历模式进度附加信息 */
export interface IterateProgress {
  total_rounds: number
  finished_rounds: number
  current_value: string | null
  rows_per_value: number
}

export interface TaskProgressData {
  task_no: string
  status: TaskStatus
  start_at?: string
  elapsed_seconds: number
  batch_size: number
  concurrency: number
  overall: TaskOverall
  tables: TaskTableProgress[]
  mode?: 'NORMAL' | 'ITERATE'
  iterate?: IterateProgress
  error_msg?: string | null
}

export interface BatchLog {
  batch_no: number
  batch_size: number
  status: 'success' | 'failed' | 'retrying'
  duration_ms: number
  error_msg: string | null
}

export interface TaskDetailData {
  task_no: string
  case_id: number | null
  case_name: string
  datasource_name: string
  main_table: string
  target_count: number
  success_count: number
  status: TaskStatus
  duration_seconds: number | null
  started_at: string
  params: Record<string, unknown>
  tables: TaskTableProgress[]
  batch_logs: BatchLog[]
  error_msg: string | null
  /** 执行时配置快照（可能与当前 Case 配置不同） */
  case_snapshot: CaseConfigJson | null
}

// ---------------- 场景管理（架构文档 4.3 / 6.9.3） ----------------

export type FailStrategy = 'continue' | 'abort'

export interface SceneNode {
  node_id: string
  case_id: number
  case_name: string
  target_count: number | null
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

export interface SceneItem {
  id: number
  name: string
  node_count: number
  exec_mode: SceneExecMode
  created_by_name: string
  created_at: string
  last_exec_at: string | null
  last_exec_status: SceneStatus | null
}

export interface SceneDetail extends SceneItem {
  nodes_json: SceneNode[]
  edges_json: SceneEdge[]
}

export interface SceneSaveParams {
  name: string
  nodes_json: SceneNode[]
  edges_json: SceneEdge[]
}

export interface SceneNodeProgress {
  node_id: string
  case_name: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
  target: number
  success: number
  task_no: string | null
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
  elapsed_seconds: number
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

export interface SceneHistoryItem {
  scene_exec_no: string
  node_count: number
  success_nodes: number
  fail_nodes: number
  total_rows: number
  status: SceneStatus
  duration_seconds: number | null
  created_by_name: string
  started_at: string
}

// ---------------- 造数总览 ----------------

export interface OverviewMetrics {
  total_cases: number
  total_scenes: number
  today_exec_count: number
  total_rows: number
  success_rate: number
  active_datasources: number
  member_count: number
  /** 各指标「较昨日」环比增量 */
  deltas?: Record<string, number>
}

export interface TrendPoint {
  date: string
  exec_count: number
  row_count: number
  success_rate: number
}

export interface StatusDistItem {
  status: string
  count: number
}

export interface TableTopItem {
  table_name: string
  datasource_name: string
  row_count: number
  case_count: number
}

export interface MemberRankItem {
  real_name: string
  row_count: number
}

export interface ExecRecord {
  task_no: string
  case_id: number | null
  case_name: string
  datasource_name: string
  main_table: string
  table_count: number
  target_count: number
  success_count: number
  status: ExecStatus
  duration_seconds: number | null
  created_by_name: string
  started_at: string
}

export interface ExecRecordQuery {
  page?: number
  page_size?: number
  start_time?: string
  end_time?: string
  status?: string[]
  datasource_id?: number
  created_by?: number
  case_name?: string
  table_name?: string
}

// ---------------- 消息通知 ----------------

export type NotifyPriority = 'high' | 'medium' | 'normal'

export interface NotificationItem {
  id: number
  title: string
  content: string
  type: string
  priority: NotifyPriority
  link: string | null
  is_read: boolean
  created_at: string
}

// ---------------- 快捷工具 ----------------

/** 工具生成结果统一结构 */
export interface ToolResult<T = Record<string, unknown>> {
  list: T[]
}

export interface IdCardItem {
  idcard: string
  province: string
  birth_date: string
  gender: string
}

export interface SnowflakeItem {
  id: string
  timestamp: string
  machine_id: number
  datacenter_id: number
  sequence: number
}
