<template>
  <!-- 消息列表页（PRD 11.5）：优先级竖条 / 筛选 / 全部已读 / 点击跳转 -->
  <div class="notify-page">
    <div class="gradient-border-card list-card">
      <!-- 头部操作 -->
      <div class="notify-head">
        <n-radio-group v-model:value="filter" size="small" @update:value="reload">
          <n-radio-button value="all">全部</n-radio-button>
          <n-radio-button value="unread">未读</n-radio-button>
          <n-radio-button value="high">高优先级</n-radio-button>
        </n-radio-group>
        <n-button size="small" :disabled="list.every((n) => n.is_read)" @click="handleReadAll">全部标为已读</n-button>
      </div>

      <!-- 消息列表 -->
      <n-spin :show="loading">
        <div class="notify-list">
          <div
            v-for="item in list"
            :key="item.id"
            class="notify-item"
            :class="{ unread: !item.is_read }"
            @click="handleClick(item)"
          >
            <span class="priority-bar" :class="`p-${item.priority}`" />
            <div class="notify-body">
              <div class="notify-title-row">
                <span class="notify-title">
                  <span v-if="!item.is_read" class="unread-dot" />
                  {{ item.title }}
                </span>
                <span class="notify-time">{{ formatDateTime(item.created_at) }}</span>
              </div>
              <div class="notify-content">{{ item.content }}</div>
              <div v-if="item.link_url" class="notify-link">查看详情 →</div>
            </div>
          </div>
          <EmptyState v-if="!loading && list.length === 0" description="暂无消息，小猫在打盹～" />
        </div>
        <!-- 加载更多 -->
        <div v-if="hasMore" class="load-more">
          <n-button size="small" quaternary :loading="loadingMore" @click="loadMore">加载更多</n-button>
        </div>
      </n-spin>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { notificationsApi } from '@/api/notifications'
import type { NotificationItem, NotificationQuery } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import { formatDateTime } from '@/utils/formatter'

const router = useRouter()

const list = ref<NotificationItem[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const filter = ref<'all' | 'unread' | 'high'>('all')
const page = ref(1)
const pageSize = 20
const total = ref(0)
const hasMore = ref(false)

async function fetchList(append = false): Promise<void> {
  if (append) loadingMore.value = true
  else loading.value = true
  try {
    // filter 转后端参数：'all'→不传，'unread'→is_read=0，'high'→priority=1
    const query: NotificationQuery = { page: page.value, page_size: pageSize }
    if (filter.value === 'unread') query.is_read = 0
    else if (filter.value === 'high') query.priority = 1
    const res = await notificationsApi.list(query)
    const newItems = res.data.items ?? []
    if (append) {
      list.value = [...list.value, ...newItems]
    } else {
      list.value = newItems
    }
    total.value = res.data.total ?? 0
    hasMore.value = list.value.length < total.value
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function reload(): void {
  page.value = 1
  fetchList()
}

function loadMore(): void {
  page.value += 1
  fetchList(true)
}

/** 点击消息行：标记已读，若有关联链接则跳转 */
async function handleClick(item: NotificationItem): Promise<void> {
  if (!item.is_read) {
    try {
      await notificationsApi.markRead(item.id)
      item.is_read = 1
    } catch {
      // 标记失败不阻塞跳转
    }
  }
  if (item.link_url) {
    router.push(item.link_url)
  }
}

/** 全部标为已读 */
async function handleReadAll(): Promise<void> {
  await notificationsApi.markAllRead()
  list.value.forEach((n) => (n.is_read = 1))
  window.$message.success('已全部标为已读')
}

onMounted(reload)
</script>

<style scoped>
.list-card {
  padding: 16px;
}
.notify-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.notify-list {
  display: flex;
  flex-direction: column;
}
.notify-item {
  display: flex;
  gap: 12px;
  padding: 14px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.15s ease;
}
.notify-item:hover {
  background: rgba(124, 58, 237, 0.08);
}
.notify-item.unread {
  background: rgba(124, 58, 237, 0.04);
}
/* 优先级竖条：红/黄/绿 */
.priority-bar {
  width: 3px;
  border-radius: 2px;
  flex-shrink: 0;
}
.priority-bar.p-1 { background: #ef4444; box-shadow: 0 0 6px rgba(239, 68, 68, 0.5); }
.priority-bar.p-2 { background: #f59e0b; }
.priority-bar.p-3 { background: #22c55e; }
.notify-body {
  flex: 1;
  overflow: hidden;
}
.notify-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.notify-title {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.unread-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #7c3aed;
  box-shadow: 0 0 6px #7c3aed;
}
.notify-time {
  font-size: 12px;
  color: #64748b;
  flex-shrink: 0;
}
.notify-content {
  margin-top: 6px;
  font-size: 13px;
  color: #94a3b8;
  line-height: 1.6;
}
.notify-link {
  margin-top: 6px;
  font-size: 12px;
  color: #a78bfa;
}
.load-more {
  display: flex;
  justify-content: center;
  padding-top: 14px;
}
</style>
