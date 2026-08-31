import request from '@/utils/request'
import type {
  ApiResponse,
  CaseConfigJson,
  CaseDetail,
  CaseHistoryItem,
  CaseItem,
  CaseListQuery,
  ExecuteResult,
  PageResult,
} from './types'

// Case 管理模块 /api/v1/cases
export const casesApi = {
  /** Case 列表（分页 + 筛选） */
  list(params: CaseListQuery) {
    return request.get<unknown, ApiResponse<PageResult<CaseItem>>>('/v1/cases', { params })
  },
  /** Case 详情（含 config_json） */
  detail(id: number) {
    return request.get<unknown, ApiResponse<CaseDetail>>(`/v1/cases/${id}`)
  },
  /** 修改 Case 配置 */
  update(id: number, params: { name?: string; config_json?: CaseConfigJson }) {
    return request.put<unknown, ApiResponse<null>>(`/v1/cases/${id}`, params)
  },
  /** 逻辑删除 Case */
  remove(id: number) {
    return request.delete<unknown, ApiResponse<null>>(`/v1/cases/${id}`)
  },
  /** 执行 Case（返回 task_no） */
  execute(id: number, targetCount: number) {
    return request.post<unknown, ApiResponse<ExecuteResult>>(`/v1/cases/${id}/execute`, {
      target_count: targetCount,
    })
  },
  /** 复制 Case */
  copy(id: number, name: string) {
    return request.post<unknown, ApiResponse<{ case_id: number }>>(`/v1/cases/${id}/copy`, { name })
  },
  /** 查看 Case 执行历史 */
  history(id: number, params?: { page?: number; page_size?: number }) {
    return request.get<unknown, ApiResponse<PageResult<CaseHistoryItem>>>(`/v1/cases/${id}/history`, { params })
  },
  /** 批量执行（多个 case_id + 各自条数） */
  batchExecute(items: Array<{ case_id: number; target_count: number }>) {
    return request.post<unknown, ApiResponse<{ tasks: Array<{ case_id: number; task_no: string }> }>>(
      '/v1/cases/batch-execute',
      { items },
    )
  },
}
