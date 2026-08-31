import request from '@/utils/request'
import type { ApiResponse, LoginParams, LoginResult, RegisterParams, UserInfo } from './types'

// 认证模块 /api/v1/auth
export const authApi = {
  /** 用户登录，返回 JWT Token */
  login(params: LoginParams) {
    return request.post<unknown, ApiResponse<LoginResult>>('/v1/auth/login', params)
  },
  /** 提交注册申请 */
  register(params: RegisterParams) {
    return request.post<unknown, ApiResponse<null>>('/v1/auth/register', params)
  },
  /** 主动登出（Token 加入黑名单） */
  logout() {
    return request.post<unknown, ApiResponse<null>>('/v1/auth/logout')
  },
  /** 获取当前用户信息及权限列表 */
  me() {
    return request.get<unknown, ApiResponse<UserInfo>>('/v1/auth/me')
  },
}
