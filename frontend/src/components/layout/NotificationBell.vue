<template>
  <!-- 消息铃铛（PRD 11.2）：未读角标 + 下拉最近 10 条 + 60s 轮询 + 新消息抖动 -->
  <n-popover trigger="click" placement="bottom-end" :width="360" v-model:show="popoverShow">
    <template #trigger>
      <div class="bell-wrap" :class="{ 'bell-shake': shaking }" @animationend="shaking = false">
        <n-badge :value="unreadCount" :max="99" :show="unreadCount > 0">
          <n-icon :size="22" :color="unreadCount > 0 ? '#a78bfa' : '#64748b'">
            <NotificationsOutline />
          </n-icon>
        </n-badge>
      </div>
    </template>
    <div class="bell-panel">
      <div class="bell-panel-header">未读消息</div>
      <n-spin :show="loading">
        <div v-if="recentList.length === 0" class="bell-empty">
          <CatMascot pose="sleep" :size="56" style="color: #6d5a9e" />
          <span>没有未读消息，小猫在打盹～</span>
        </div>
        <div
          v-for="item in recentList"
          :key="item.id"
          class="bell-item"
          @click="handleClick(item)"
        >
          <span class="bell-priority" :class="`p-${item.priority}`" />
          <div class="bell-item-body">
            <div class="bell-item-title">{{ item.title }}</div>
            <div class="bell-item-content">{{ item.content }}</div>
            <div class="bell-item-time">{{ formatDateTime(item.created_at) }}</div>
          </div>
        </div>
      </n-spin>
      <div class="bell-panel-footer" @click="goAll">查看全部</div>
    </div>
  </n-popover>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NotificationsOutline } from '@vicons/ionicons5'
import { notificationsApi } from '@/api/notifications'
import type { NotificationItem } from '@/api/types'
import CatMascot from '@/components/common/CatMascot.vue'
import { formatDateTime } from '@/utils/formatter'

const router = useRouter()

const unreadCount = ref(0)
const recentList = ref<NotificationItem[]>([])
const loading = ref(false)
const popoverShow = ref(false)
const shaking = ref(false)

let timer: ReturnType<typeof setInterval> | null = null

/** 轮询未读数量（每 60 秒），数量增加时触发铃铛抖动 */
async function fetchUnread(): Promise<void> {
  try {
    const res = await notificationsApi.unreadCount()
    if (res.data.unread_count > unreadCount.value) {
      shaking.value = true
    }
    unreadCount.value = res.data.unread_count
  } catch {
    // 轮询失败静默
  }
}

/** 打开下拉时加载最近 10 条未读消息 */
async function fetchRecent(): Promise<void> {
  loading.value = true
  try {
    const res = await notificationsApi.list({ page: 1, page_size: 10, is_read: 0 })
    recentList.value = res.data.items ?? []
  } finally {
    loading.value = false
  }
}

/** 点击消息：标记已读并跳转关联页面 */
async function handleClick(item: NotificationItem): Promise<void> {
  try {
    await notificationsApi.markRead(item.id)
    unreadCount.value = Math.max(0, unreadCount.value - 1)
    recentList.value = recentList.value.filter((n) => n.id !== item.id)
  } catch {
    // 标记失败不阻塞跳转
  }
  if (item.link_url) {
    popoverShow.value = false
    router.push(item.link_url)
  }
}

function goAll(): void {
  popoverShow.value = false
  router.push('/notifications')
}

onMounted(() => {
  fetchUnread()
  timer = setInterval(fetchUnread, 60_000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

// 下拉打开时刷新最近消息
watch(popoverShow, (show) => {
  if (show) fetchRecent()
})
</script>

<style scoped>
.bell-wrap {
  cursor: pointer;
  display: flex;
  align-items: center;
  padding: 4px;
}
.bell-panel-header {
  font-weight: 600;
  font-size: 13px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}
.bell-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px 0;
  color: #64748b;
  font-size: 12px;
}
.bell-item {
  display: flex;
  gap: 10px;
  padding: 10px 6px;
  border-radius: 6px;
  cursor: pointer;
}
.bell-item:hover {
  background: rgba(124, 58, 237, 0.1);
}
.bell-priority {
  width: 3px;
  border-radius: 2px;
  flex-shrink: 0;
}
.bell-priority.p-1 { background: #ef4444; }
.bell-priority.p-2 { background: #f59e0b; }
.bell-priority.p-3 { background: #22c55e; }
.bell-item-body {
  flex: 1;
  overflow: hidden;
}
.bell-item-title {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
}
.bell-item-content {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.bell-item-time {
  font-size: 11px;
  color: #64748b;
  margin-top: 4px;
}
.bell-panel-footer {
  text-align: center;
  padding-top: 8px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  color: #a78bfa;
  font-size: 12px;
  cursor: pointer;
}
.bell-panel-footer:hover {
  text-decoration: underline;
}
</style>
