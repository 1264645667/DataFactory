<template>
  <!-- 顶栏：面包屑 + 消息通知铃铛 -->
  <div class="topbar">
    <n-breadcrumb>
      <n-breadcrumb-item @click="go('/overview')">DataForge</n-breadcrumb-item>
      <n-breadcrumb-item v-if="parentTitle" @click="go(parentPath)">{{ parentTitle }}</n-breadcrumb-item>
      <n-breadcrumb-item>{{ currentTitle }}</n-breadcrumb-item>
    </n-breadcrumb>
    <div class="topbar-right">
      <NotificationBell />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import NotificationBell from './NotificationBell.vue'

const route = useRoute()
const router = useRouter()

const currentTitle = computed(() => (route.meta.title as string) ?? '')
// 二级页面显示父级面包屑
const parentPath = computed(() => (route.meta.parent as string) ?? '')
const parentTitle = computed(() => {
  if (!parentPath.value) return ''
  const map: Record<string, string> = {
    '/engine': '造数引擎',
    '/cases': 'Case 管理',
    '/scenes': '场景管理',
  }
  return map[parentPath.value] ?? ''
})

function go(path: string): void {
  if (path) router.push(path)
}
</script>

<style scoped>
.topbar {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid rgba(124, 58, 237, 0.15);
  background: rgba(13, 13, 13, 0.7);
  backdrop-filter: blur(10px);
  position: sticky;
  top: 0;
  z-index: 100;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
</style>
