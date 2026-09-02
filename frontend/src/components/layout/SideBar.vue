<template>
  <!-- 侧边栏220px 可折叠 64px，分组菜单，权限隐藏，底部猫咪+用户信息 -->
  <div class="sidebar" :class="{ collapsed }">
    <!-- Logo 区 -->
    <div class="sidebar-logo" @click="go('/overview')">
      <AppLogo :collapsed="collapsed" />
    </div>

    <!-- 菜单区 -->
    <n-scrollbar class="sidebar-menu">
      <template v-for="(group, gi) in visibleGroups" :key="gi">
        <div v-if="group.title && !collapsed" class="menu-group-title">{{ group.title }}</div>
        <div v-else-if="group.title && collapsed" class="menu-group-divider" />
        <n-tooltip
          v-for="item in group.items"
          :key="item.route"
          :disabled="!collapsed"
          placement="right"
        >
          <template #trigger>
            <div
              class="menu-item"
              :class="{ active: isActive(item.route), collapsed }"
              @click="go(item.route)"
            >
              <n-icon :size="19" class="menu-icon"><component :is="item.icon" /></n-icon>
              <span v-if="!collapsed" class="menu-label">{{ item.label }}</span>
            </div>
          </template>
          {{ item.label }}
        </n-tooltip>
      </template>
    </n-scrollbar>

    <!-- 折叠开关 -->
    <div class="sidebar-collapse" @click="collapsed = !collapsed">
      <n-icon :size="16">
        <ChevronBackOutline v-if="!collapsed" />
        <ChevronForwardOutline v-else />
      </n-icon>
    </div>

    <!-- 底部：猫咪装饰 + 用户信息 -->
    <div class="sidebar-footer">
      <div v-if="!collapsed" class="footer-cat">
        <CatMascot :size="46" pose="sit" style="color: #6d5a9e" />
      </div>
      <div class="footer-user" :class="{ collapsed }">
        <div class="user-avatar" :style="{ color: avatarColor }">
          <CatMascot :size="collapsed ? 30 : 34" pose="sit" />
        </div>
        <div v-if="!collapsed" class="user-info">
          <span class="user-name">{{ authStore.user?.real_name || authStore.user?.username }}</span>
          <span class="user-group">{{ groupName(authStore.user?.group_type) }}</span>
        </div>
      </div>
      <div v-if="!collapsed" class="footer-actions">
        <n-button text size="small" @click="go('/profile')">个人中心</n-button>
        <n-button text size="small" type="error" @click="handleLogout">退出登录</n-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  BarChartOutline,
  BuildOutline,
  ChevronBackOutline,
  ChevronForwardOutline,
  FolderOpenOutline,
  GitNetworkOutline,
  PeopleOutline,
  ServerOutline,
  FlashOutline,
} from '@vicons/ionicons5'
import AppLogo from '@/components/common/AppLogo.vue'
import CatMascot from '@/components/common/CatMascot.vue'
import { useAuth } from '@/composables/useAuth'
import { useAuthStore } from '@/stores/auth'
import { groupName } from '@/utils/permission'

interface MenuItem {
  label: string
  icon: unknown
  route: string
  permission: string
}

interface MenuGroup {
  title: string
  items: MenuItem[]
}

// 菜单配置
const MENU_GROUPS: MenuGroup[] = [
  {
    title: '',
    items: [{ label: '造数总览', icon: BarChartOutline, route: '/overview', permission: 'OVERVIEW:VIEW' }],
  },
  {
    title: '造数',
    items: [
      { label: '造数引擎', icon: FlashOutline, route: '/engine', permission: 'ENGINE:VIEW' },
      { label: 'Case 管理', icon: FolderOpenOutline, route: '/cases', permission: 'CASE:VIEW' },
      { label: '场景管理', icon: GitNetworkOutline, route: '/scenes', permission: 'SCENE:VIEW' },
    ],
  },
  {
    title: '工具',
    items: [{ label: '快捷工具', icon: BuildOutline, route: '/tools', permission: 'TOOL:USE' }],
  },
  {
    title: '管理',
    items: [
      { label: '数据源管理', icon: ServerOutline, route: '/datasources', permission: 'DATASOURCE:VIEW' },
      { label: '用户管理', icon: PeopleOutline, route: '/admin/users', permission: 'USER:APPROVE' },
    ],
  },
]

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { hasPermission, logout } = useAuth()

const collapsed = ref(false)

// 无权限的菜单项直接隐藏；分组内全部无权限时分组标题也隐藏
const visibleGroups = computed(() =>
  MENU_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((item) => hasPermission(item.permission)),
  })).filter((g) => g.items.length > 0),
)

// 头像颜色（按 avatar 序号取色板）
const AVATAR_COLORS = ['#a78bfa', '#f472b6', '#60a5fa', '#34d399', '#fbbf24', '#fb7185', '#22d3ee', '#c084fc', '#f97316', '#4ade80']
const avatarColor = computed(() => AVATAR_COLORS[((authStore.user?.avatar_index ?? 1) - 1) % AVATAR_COLORS.length])

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(`${path}/`)
}

function go(path: string): void {
  router.push(path)
}

async function handleLogout(): Promise<void> {
  await logout()
}
</script>

<style scoped>
.sidebar {
  width: 220px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: rgba(16, 16, 24, 0.9);
  border-right: 1px solid rgba(124, 58, 237, 0.18);
  transition: width 0.2s ease;
  position: relative;
}
.sidebar.collapsed {
  width: 64px;
}
.sidebar-logo {
  padding: 18px 16px 14px;
  cursor: pointer;
}
.sidebar-menu {
  flex: 1;
  padding: 4px 0;
}
.menu-group-title {
  padding: 14px 18px 6px;
  font-size: 11px;
  color: #4b5563;
  letter-spacing: 2px;
}
.menu-group-divider {
  margin: 10px 12px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}
.menu-item {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 2px 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: #94a3b8;
  position: relative;
  transition: background 0.15s ease, color 0.15s ease;
}
.menu-item.collapsed {
  justify-content: center;
  padding: 10px 0;
}
.menu-item:hover {
  background: rgba(124, 58, 237, 0.1);
  color: #e2e8f0;
}
/* 激活态：左侧 3px 紫色竖条 + 浅紫背景 */
.menu-item.active {
  background: rgba(124, 58, 237, 0.18);
  color: #c4b5fd;
}
.menu-item.active::before {
  content: '';
  position: absolute;
  left: -10px;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 2px;
  background: #7c3aed;
  box-shadow: 0 0 8px rgba(124, 58, 237, 0.8);
}
.menu-icon {
  flex-shrink: 0;
}
.menu-label {
  font-size: 13px;
  white-space: nowrap;
}
.sidebar-collapse {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 34px;
  margin: 0 10px;
  border-top: 1px solid rgba(148, 163, 184, 0.1);
  color: #64748b;
  cursor: pointer;
}
.sidebar-collapse:hover {
  color: #a78bfa;
}
.sidebar-footer {
  padding: 10px 14px 14px;
  border-top: 1px solid rgba(124, 58, 237, 0.15);
}
.footer-cat {
  display: flex;
  justify-content: center;
  padding-bottom: 6px;
}
.footer-user {
  display: flex;
  align-items: center;
  gap: 10px;
}
.footer-user.collapsed {
  justify-content: center;
}
.user-avatar {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: rgba(124, 58, 237, 0.12);
  border: 1px solid rgba(124, 58, 237, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}
.user-info {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  overflow: hidden;
}
.user-name {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}
.user-group {
  font-size: 11px;
  color: #64748b;
}
.footer-actions {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
}
</style>
