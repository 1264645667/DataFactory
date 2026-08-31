import request from '@/utils/request'
import type {
  AdminUserItem,
  ApiResponse,
  AuditLogItem,
  PageResult,
  PendingUser,
} from './types'

// 用户管理模块 /api/v1/users
export const usersApi = {
  /** 待审批用户列表 */
  pending() {
    return request.get<unknown, ApiResponse<PendingUser[]>>('/v1/users/pending')
  },
  /** 审批通过并分配权限 */
  approve(id: number, permissions: string[]) {
    return request.post<unknown, ApiResponse<null>>(`/v1/users/${id}/approve`, { permissions })
  },
  /** 审批拒绝（必填原因） */
  reject(id: number, reason: string) {
    return request.post<unknown, ApiResponse<null>>(`/v1/users/${id}/reject`, { reason })
  },
  /** 全部用户列表（分页） */
  list(params: { page?: number; page_size?: number; keyword?: string }) {
    return request.get<unknown, ApiResponse<PageResult<AdminUserItem>>>('/v1/users', { params })
  },
  /** 更新用户菜单权限 */
  updatePermissions(id: number, permissions: string[]) {
    return request.put<unknown, ApiResponse<null>>(`/v1/users/${id}/permissions`, { permissions })
  },
  /** 禁用用户 */
  disable(id: number) {
    return request.post<unknown, ApiResponse<null>>(`/v1/users/${id}/disable`)
  },
  /** 启用用户 */
  enable(id: number) {
    return request.post<unknown, ApiResponse<null>>(`/v1/users/${id}/enable`)
  },
  /** 重置密码（返回临时密码） */
  resetPassword(id: number) {
    return request.post<unknown, ApiResponse<{ temp_password: string }>>(`/v1/users/${id}/reset-password`)
  },
  /** 修改自己密码 */
  changePassword(oldPassword: string, newPassword: string) {
    return request.put<unknown, ApiResponse<null>>('/v1/users/me/password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },
  /** 更新头像序号 */
  updateAvatar(avatar: number) {
    return request.put<unknown, ApiResponse<null>>('/v1/users/me/avatar', { avatar })
  },
  /** 设置默认数据源 */
  setDefaultDatasource(datasourceId: number | null) {
    return request.put<unknown, ApiResponse<null>>('/v1/users/me/default-datasource', {
      datasource_id: datasourceId,
    })
  },
  /** 查询操作日志（普通用户看本组，管理员看全量） */
  auditLogs(params: {
    page?: number
    page_size?: number
    operator?: string
    action?: string
    group_type?: number
    start_time?: string
    end_time?: string
  }) {
    return request.get<unknown, ApiResponse<PageResult<AuditLogItem>>>('/v1/users/audit-logs', { params })
  },
}
