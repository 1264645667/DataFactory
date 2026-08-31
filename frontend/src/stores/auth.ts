import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi } from '@/api/auth'
import type { UserInfo } from '@/api/types'
import { hasPermission as checkPermission } from '@/utils/permission'

// 认证 Store：Token、用户信息、权限判断
export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('df_token') ?? '')
  const user = ref<UserInfo | null>(null)

  const isLoggedIn = computed(() => !!token.value)

  /** 权限判断：ADMIN 角色默认全量权限 */
  function hasPermission(perm: string): boolean {
    return checkPermission(user.value, perm)
  }

  /** 登录：保存 Token 并拉取用户信息 */
  async function login(username: string, password: string): Promise<void> {
    const res = await authApi.login({ username, password })
    token.value = res.data.token
    localStorage.setItem('df_token', res.data.token)
    await fetchMe()
  }

  /** 重新登录（登录过期弹窗内使用，不刷新页面） */
  async function relogin(password: string): Promise<void> {
    if (!user.value) throw new Error('当前无登录用户')
    await login(user.value.username, password)
  }

  /** 拉取当前用户信息及权限列表 */
  async function fetchMe(): Promise<void> {
    const res = await authApi.me()
    user.value = res.data
  }

  /** 仅清除本地登录态（不调用后端） */
  function clearLocal(): void {
    token.value = ''
    user.value = null
    localStorage.removeItem('df_token')
  }

  /** 登出：通知后端将 Token 加入黑名单，再清理本地状态 */
  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } catch {
      // 登出接口失败不阻塞本地清理
    }
    clearLocal()
  }

  return { token, user, isLoggedIn, hasPermission, login, relogin, fetchMe, clearLocal, logout }
})
