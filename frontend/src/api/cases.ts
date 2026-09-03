import request from '@/utils/request'
import type {
  ApiResponse,
  CaseBatchExecuteResult,
  CaseConfigJson,
  CaseDetail,
  CaseExecuteResponse,
  CaseHistoryResult,
  CaseItem,
  CaseListQuery,
  FolderListResult,
  PageResult,
} from './types'

// Case 管理模块 /api/v1/cases
export const casesApi = {
  /** Case 列表（分页 + 筛选） */
  list(params: CaseListQuery) {
    return request.get<unknown, ApiResponse<PageResult<CaseItem>>>('/v1/cases', { params })
  },
  /** Case 详情（含 config） */
  detail(id: number) {
    return request.get<unknown, ApiResponse<CaseDetail>>(`/v1/cases/${id}`)
  },
  /** 修改 Case 配置 */
  update(id: number, params: { case_name: string; config: CaseConfigJson }) {
    return request.put<unknown, ApiResponse<null>>(`/v1/cases/${id}`, params)
  },
  /** 逻辑删除 Case */
  remove(id: number) {
    return request.delete<unknown, ApiResponse<null>>(`/v1/cases/${id}`)
  },
  /** 执行 Case（返回 task_no） */
  execute(id: number, targetCount: number) {
    return request.post<unknown, ApiResponse<CaseExecuteResponse>>(`/v1/cases/${id}/execute`, {
      target_count: targetCount,
    })
  },
  /** 复制 Case */
  copy(id: number, caseName: string | null) {
    return request.post<unknown, ApiResponse<{ case_id: number }>>(`/v1/cases/${id}/copy`, { case_name: caseName })
  },
  /** 查看 Case 执行历史（后端返回 dict 含统计，不分页） */
  history(id: number) {
    return request.get<unknown, ApiResponse<CaseHistoryResult>>(`/v1/cases/${id}/history`)
  },
  /** 批量执行（多个 case_id + 各自条数，返回与 items 同序的 task_nos） */
  batchExecute(items: Array<{ case_id: number; target_count: number }>) {
    return request.post<unknown, ApiResponse<CaseBatchExecuteResult>>('/v1/cases/batch-execute', { items })
  },
  /** 文件夹列表（含收纳数/总数/未分类数） */
  folders() {
    return request.get<unknown, ApiResponse<FolderListResult>>('/v1/cases/folders')
  },
  /** 新建文件夹 */
  createFolder(name: string) {
    return request.post<unknown, ApiResponse<null>>('/v1/cases/folders', { name })
  },
  /** 重命名文件夹 */
  renameFolder(id: number, name: string) {
    return request.put<unknown, ApiResponse<null>>(`/v1/cases/folders/${id}`, { name })
  },
  /** 删除文件夹（其中 Case 移到未分类） */
  removeFolder(id: number) {
    return request.delete<unknown, ApiResponse<null>>(`/v1/cases/folders/${id}`)
  },
  /** 批量移动 Case 到文件夹（folderId 为 null 移到未分类） */
  batchMove(caseIds: number[], folderId: number | null) {
    return request.put<unknown, ApiResponse<null>>('/v1/cases/batch-move', { case_ids: caseIds, folder_id: folderId })
  },
}
