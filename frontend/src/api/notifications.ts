import request from '@/utils/request'
import type {
  ApiResponse,
  NotificationItem,
  NotificationQuery,
  PageResult,
  UnreadCountResult,
} from './types'

// 消息通知模块 /api/v1/notifications
export const notificationsApi = {
  /** 获取未读消息数量（前端每 60s 轮询） */
  unreadCount() {
    return request.get<unknown, ApiResponse<UnreadCountResult>>('/v1/notifications/unread-count')
  },
  /** 消息列表（分页，用 is_read/priority 筛选） */
  list(params: NotificationQuery) {
    return request.get<unknown, ApiResponse<PageResult<NotificationItem>>>('/v1/notifications', { params })
  },
  /** 标记单条消息为已读 */
  markRead(id: number) {
    return request.post<unknown, ApiResponse<null>>(`/v1/notifications/${id}/read`)
  },
  /** 全部标为已读 */
  markAllRead() {
    return request.post<unknown, ApiResponse<{ updated_count: number }>>('/v1/notifications/read-all')
  },
}
