import request from '@/utils/request'
import type { ApiResponse, Datasource, DatasourceForm } from './types'

// 数据源模块 /api/v1/datasources
export const datasourceApi = {
  /** 数据源列表（含连接状态） */
  list() {
    return request.get<unknown, ApiResponse<Datasource[]>>('/v1/datasources')
  },
  /** 新增数据源 */
  create(form: DatasourceForm) {
    return request.post<unknown, ApiResponse<{ id: number }>>('/v1/datasources', form)
  },
  /** 编辑数据源 */
  update(id: number, form: Partial<DatasourceForm>) {
    return request.put<unknown, ApiResponse<null>>(`/v1/datasources/${id}`, form)
  },
  /** 删除数据源 */
  remove(id: number) {
    return request.delete<unknown, ApiResponse<null>>(`/v1/datasources/${id}`)
  },
  /** 测试连接（表单页按钮，不保存） */
  test(form: Partial<DatasourceForm>) {
    return request.post<unknown, ApiResponse<{ version?: string; message?: string }>>('/v1/datasources/test', form)
  },
  /** 手动触发表结构同步 */
  sync(id: number) {
    return request.post<unknown, ApiResponse<null>>(`/v1/datasources/${id}/sync`)
  },
  /** 获取数据源连接状态（心跳） */
  status(id: number) {
    return request.get<unknown, ApiResponse<{ status: Datasource['status']; cache_status: Datasource['cache_status']; last_sync_at: string | null }>>(`/v1/datasources/${id}/status`)
  },
}
