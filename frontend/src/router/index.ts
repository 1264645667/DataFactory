import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// 路由表：meta.public 为白名单，meta.permission 为所需菜单权限
const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginPage.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/register/RegisterPage.vue'),
    meta: { public: true, title: '申请注册' },
  },
  {
    path: '/',
    component: () => import('@/components/layout/AppLayout.vue'),
    redirect: '/overview',
    children: [
      {
        path: 'overview',
        name: 'Overview',
        component: () => import('@/views/overview/OverviewPage.vue'),
        meta: { title: '造数总览', permission: 'OVERVIEW:VIEW' },
      },
      {
        path: 'engine',
        name: 'Engine',
        component: () => import('@/views/engine/TableList.vue'),
        meta: { title: '造数引擎', permission: 'ENGINE:VIEW' },
      },
      {
        path: 'engine/config/:tableName',
        name: 'EngineConfig',
        component: () => import('@/views/engine/FieldConfig.vue'),
        meta: { title: '字段配置', permission: 'ENGINE:VIEW', parent: '/engine' },
      },
      {
        path: 'engine/redis-config',
        name: 'RedisConfig',
        component: () => import('@/views/engine/RedisConfig.vue'),
        meta: { title: 'Redis 造数配置', permission: 'ENGINE:VIEW', parent: '/engine' },
      },
      {
        path: 'cases',
        name: 'Cases',
        component: () => import('@/views/cases/CaseList.vue'),
        meta: { title: 'Case 管理', permission: 'CASE:VIEW' },
      },
      {
        path: 'cases/:id',
        name: 'CaseDetail',
        component: () => import('@/views/cases/CaseDetail.vue'),
        meta: { title: 'Case 详情', permission: 'CASE:VIEW', parent: '/cases' },
      },
      {
        path: 'scenes',
        name: 'Scenes',
        component: () => import('@/views/scenes/SceneList.vue'),
        meta: { title: '场景管理', permission: 'SCENE:VIEW' },
      },
      {
        path: 'scenes/editor/:id?',
        name: 'SceneEditor',
        component: () => import('@/views/scenes/SceneEditor.vue'),
        meta: { title: '场景编排', permission: 'SCENE:VIEW', parent: '/scenes' },
      },
      {
        path: 'scenes/:id',
        name: 'SceneDetail',
        component: () => import('@/views/scenes/SceneDetail.vue'),
        meta: { title: '场景详情', permission: 'SCENE:VIEW', parent: '/scenes' },
      },
      {
        path: 'tools',
        name: 'Tools',
        component: () => import('@/views/tools/ToolsPage.vue'),
        meta: { title: '快捷工具', permission: 'TOOL:USE' },
      },
      {
        path: 'datasources',
        name: 'Datasources',
        component: () => import('@/views/datasource/DatasourceList.vue'),
        meta: { title: '数据源管理', permission: 'DATASOURCE:VIEW' },
      },
      {
        path: 'admin/users',
        name: 'UserManage',
        component: () => import('@/views/admin/UserManage.vue'),
        meta: { title: '用户管理', permission: 'USER:APPROVE' },
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('@/views/profile/ProfilePage.vue'),
        meta: { title: '个人中心' },
      },
      {
        path: 'notifications',
        name: 'Notifications',
        component: () => import('@/views/notifications/NotificationList.vue'),
        meta: { title: '消息通知' },
      },
      {
        // 兼容历史通知里的旧链接 /tasks/{task_no} → 总览页任务详情抽屉
        path: 'tasks/:task_no',
        redirect: (to) => ({ path: '/overview', query: { task_no: String(to.params.task_no) } }),
      },
      {
        path: '403',
        name: 'Forbidden',
        component: () => import('@/views/error/Forbidden.vue'),
        meta: { title: '无权限' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/error/NotFound.vue'),
    meta: { public: true, title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 权限导航守卫
router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  // 白名单：登录页、注册页等公开路由
  if (to.meta.public) {
    // 已登录用户访问登录页 → 直接进入主界面
    if (to.path === '/login' && authStore.isLoggedIn) return '/overview'
    return true
  }

  // 未登录 → 跳转登录页（记录来源路径）
  if (!authStore.isLoggedIn) {
    return { path: '/login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : {} }
  }

  // 已登录但用户信息未加载（刷新页面场景）→ 先拉取用户信息
  if (!authStore.user) {
    try {
      await authStore.fetchMe()
    } catch {
      // Token 无效 → 清理后跳登录页
      authStore.clearLocal()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  // 检查菜单权限，无权限 → 403 页
  const requiredPermission = to.meta.permission as string | undefined
  if (requiredPermission && !authStore.hasPermission(requiredPermission)) {
    return '/403'
  }

  return true
})

// 路由跳转后更新页面标题
router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · DataForge 造数工厂` : 'DataForge 造数工厂'
})

export default router
