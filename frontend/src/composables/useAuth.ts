import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// 认证组合式函数：封装登录态相关操作
export function useAuth() {
  const authStore = useAuthStore()
  const router = useRouter()

  const user = computed(() => authStore.user)
  const isLoggedIn = computed(() => authStore.isLoggedIn)
  const isAdmin = computed(() => authStore.user?.role === 'ADMIN')

  function hasPermission(perm: string): boolean {
    return authStore.hasPermission(perm)
  }

  /** 登出并跳转登录页 */
  async function logout(): Promise<void> {
    await authStore.logout()
    router.push('/login')
  }

  return { user, isLoggedIn, isAdmin, hasPermission, logout }
}
