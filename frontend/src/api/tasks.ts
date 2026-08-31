import request from '@/utils/request'
import type { ApiResponse, TaskDetailData, TaskProgressData } from './types'

// 任务进度模块 /api/v1/tasks
export const tasksApi = {
  /** 获取任务实时进度（前端轮询） */
  progress(taskNo: string) {
    return request.get<unknown, ApiResponse<TaskProgressData>>(`/v1/tasks/${taskNo}/progress`)
  },
  /** 强制停止任务 */
  abort(taskNo: string) {
    return request.post<unknown, ApiResponse<null>>(`/v1/tasks/${taskNo}/abort`)
  },
  /** 重试失败批次（断点续传） */
  retryBatches(taskNo: string) {
    return request.post<unknown, ApiResponse<null>>(`/v1/tasks/${taskNo}/retry-batches`)
  },
  /** 任务详情（含分批次日志） */
  detail(taskNo: string) {
    return request.get<unknown, ApiResponse<TaskDetailData>>(`/v1/tasks/${taskNo}/detail`)
  },
}
