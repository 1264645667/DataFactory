import request from '@/utils/request'
import type {
  ApiResponse,
  ColumnInfo,
  EngineExecuteParams,
  EngineSaveParams,
  ExecuteResult,
  IndexInfo,
  TableInfo,
} from './types'

// 造数引擎模块 /api/v1/engine
export const engineApi = {
  /** 获取指定数据源的表列表 */
  tables(datasourceId: number, params?: { keyword?: string; sort?: 'name' | 'rows' | 'columns' }) {
    return request.get<unknown, ApiResponse<TableInfo[]>>('/v1/engine/tables', {
      params: { datasource_id: datasourceId, ...params },
    })
  },
  /** 获取表字段详情（含自动推断策略） */
  columns(datasourceId: number, tableName: string) {
    return request.get<unknown, ApiResponse<{ table: TableInfo & { engine?: string; charset?: string; created_at?: string }; columns: ColumnInfo[] }>>(
      `/v1/engine/tables/${encodeURIComponent(tableName)}/columns`,
      { params: { datasource_id: datasourceId } },
    )
  },
  /** 获取表索引信息 */
  indexes(datasourceId: number, tableName: string) {
    return request.get<unknown, ApiResponse<IndexInfo[]>>(
      `/v1/engine/tables/${encodeURIComponent(tableName)}/indexes`,
      { params: { datasource_id: datasourceId } },
    )
  },
  /** 创建 Case 并立即执行（返回 task_no） */
  execute(params: EngineExecuteParams) {
    return request.post<unknown, ApiResponse<ExecuteResult>>('/v1/engine/execute', params)
  },
  /** 仅保存 Case，不执行 */
  save(params: EngineSaveParams) {
    return request.post<unknown, ApiResponse<{ case_id: number }>>('/v1/engine/save', params)
  },
}
