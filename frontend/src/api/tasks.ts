import request from '@/utils/request'
import type { ApiResponse, TaskDetailData, TaskProgressData } from './types'

// 任务进度模块 /api/v1/tasks
export const tasksApi = {
  /** 获取任务实时进度（前端轮询） */
  progress(taskNo: string) {
    return request.get<unknown, ApiResponse<TaskProgressData>>(`/v1/tasks/${taskNo}/progress`)
  },
  /** 强制停止任务（无 body） */
  abort(taskNo: string) {
    return request.post<unknown, ApiResponse<null>>(`/v1/tasks/${taskNo}/abort`)
  },
  /** 重试失败批次（断点续传），body 必传（可为空对象，空则重试全部失败批次） */
  retryBatches(taskNo: string, params: { batch_nos?: number[]; round_no?: number }) {
    return request.post<unknown, ApiResponse<null>>(`/v1/tasks/${taskNo}/retry-batches`, params)
  },
  /** 任务详情（含分批次日志 batch_logs） */
  detail(taskNo: string) {
    return request.get<unknown, ApiResponse<TaskDetailData>>(`/v1/tasks/${taskNo}/detail`)
  },
  /** 一键回滚（删除任务已写入的 MySQL 行与 Redis Key） */
  rollback(taskNo: string) {
    return request.post<unknown, ApiResponse<{ task_no: string; rollback_rows: number }>>(
      `/v1/tasks/${taskNo}/rollback`,
    )
  },
}
