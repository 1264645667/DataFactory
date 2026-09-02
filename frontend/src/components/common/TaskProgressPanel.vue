<template>
  <!-- 任务执行进度面板总进度 / 分表进度 / 速率 / 预计剩余 / 最小化 / 强制停止 -->
  <n-modal
    :show="true"
    :mask-closable="false"
    :closable="false"
    preset="card"
    class="task-progress-panel"
    style="width: 640px; max-width: 92vw"
  >
    <template #header>
      <div class="panel-header">
        <span class="panel-title">{{ titleText }}</span>
        <n-text depth="3" class="panel-task-no">{{ entry.taskNo }}</n-text>
      </div>
    </template>
    <template #header-extra>
      <div class="panel-header-btns">
        <n-button quaternary circle size="small" @click="handleMinimize">
          <template #icon><n-icon><RemoveOutline /></n-icon></template>
        </n-button>
        <n-button v-if="isTerminal" quaternary circle size="small" @click="handleClose">
          <template #icon><n-icon><CloseOutline /></n-icon></template>
        </n-button>
      </div>
    </template>

    <n-spin :show="!data">
      <!-- ITERATE 遍历模式：轮次进度（遍历信息平铺在进度响应上） -->
      <div v-if="isIterate" class="iterate-block">
        <div class="iterate-rounds">
          当前轮次：{{ iterate?.current_round ?? 0 }} / {{ iterate?.total_rounds ?? 0 }} 轮
          <n-tag v-if="iterate?.current_value != null" size="small" class="ml-2">
            当前值：{{ iterate?.current_value }}
          </n-tag>
        </div>
      </div>

      <!-- 总进度区 -->
      <div class="overall-block">
        <n-progress
          type="line"
          :percentage="percent"
          :status="progressStatus"
          :height="14"
          border-radius="7px"
          processing
        />
        <div class="overall-nums">
          <span>总计：{{ formatNumber(overall?.target_total) }} 条</span>
          <span>已完成：{{ formatNumber(overall?.success_total) }} 条</span>
          <span :class="{ 'text-red': (overall?.fail_total ?? 0) > 0 }">
            失败：{{ formatNumber(overall?.fail_total) }} 条
          </span>
        </div>
        <div class="overall-nums">
          <span>整体速率：{{ formatRate(overall?.insert_rate) }}</span>
          <span v-if="!isTerminal">预计剩余：{{ remainText }}</span>
          <span v-else>总耗时：{{ formatDuration(data?.elapsed_seconds) }}</span>
        </div>
      </div>

      <!-- 分表进度区 -->
      <div class="tables-block">
        <div
          v-for="t in data?.tables ?? []"
          :key="t.table_name"
          class="table-row"
          :class="{ failed: t.status === 'failed' }"
        >
          <div class="table-head">
            <span class="table-name">
              {{ t.table_name }}
              <n-tag size="tiny" :type="t.role === 'main' ? 'primary' : 'default'">
                {{ t.role === 'main' ? '主表' : '关联' }}
              </n-tag>
            </span>
            <span class="table-status">
              <span class="status-dot" :class="`dot-${t.status}`" />
              {{ tableStatusText(t.status) }}
            </span>
          </div>
          <n-progress
            type="line"
            :percentage="Math.min(100, Math.round(t.progress_percent))"
            :status="t.status === 'failed' ? 'error' : t.status === 'success' ? 'success' : 'default'"
            :height="8"
            border-radius="4px"
          />
          <div class="table-foot">
            <span>{{ formatNumber(t.success) }} / {{ formatNumber(t.target) }}</span>
            <span>速率：{{ formatRate(t.insert_rate) }}</span>
          </div>
        </div>
      </div>

      <!-- 失败摘要（进度接口不含 error_msg，具体错误见任务详情） -->
      <n-alert v-if="entry.status === 'failed'" type="error" class="mt-3" title="错误摘要">
        任务执行失败，可点击「查看详情」获取具体错误信息。
      </n-alert>

      <!-- 底部执行参数 -->
      <div class="panel-footer-info">
        <span>已用时：{{ formatDuration(data?.elapsed_seconds) }}</span>
        <span>批次大小：{{ formatNumber(data?.batch_size) }} 条/批</span>
        <span>并发线程：{{ data?.concurrency ?? '-' }}</span>
      </div>
    </n-spin>

    <template #footer>
      <div class="panel-actions">
        <n-button @click="handleMinimize">最小化</n-button>
        <n-button v-if="isTerminal" class="gradient-btn" @click="goDetail">查看详情</n-button>
        <n-popconfirm v-else @positive-click="handleAbort">
          <template #trigger>
            <n-button type="error" ghost :loading="aborting">强制停止</n-button>
          </template>
          确认强制停止任务？已插入的数据不会回滚。
        </n-popconfirm>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CloseOutline, RemoveOutline } from '@vicons/ionicons5'
import { useTaskProgress } from '@/composables/useTaskProgress'
import { formatDuration, formatNumber, formatRate } from '@/utils/formatter'
import type { TableRunStatus } from '@/api/types'

const props = defineProps<{ taskNo: string }>()

const router = useRouter()
const { store, minimize, closeTerminal, abortTask, isIterateTask, iterateProgress } = useTaskProgress()

const entry = computed(() => store.tasks.get(props.taskNo)!)
const data = computed(() => entry.value?.data ?? null)
const overall = computed(() => data.value?.overall ?? null)
const percent = computed(() => Math.min(100, Math.round(overall.value?.progress_percent ?? 0)))
const isTerminal = computed(() =>
  ['success', 'failed', 'partial_success', 'aborted'].includes(entry.value?.status ?? ''),
)
const isIterate = computed(() => isIterateTask(data.value))
const iterate = computed(() => iterateProgress(data.value))
const aborting = ref(false)

// 标题随状态变化
const titleText = computed(() => {
  switch (entry.value?.status) {
    case 'success':
      return '执行完成'
    case 'failed':
      return '执行失败'
    case 'partial_success':
      return '部分完成'
    case 'aborted':
      return '已中止'
    default:
      return `任务执行中 · ${entry.value?.caseName ?? ''}`
  }
})

const progressStatus = computed(() => {
  if (entry.value?.status === 'success') return 'success'
  if (entry.value?.status === 'failed' || entry.value?.status === 'aborted') return 'error'
  if (entry.value?.status === 'partial_success') return 'warning'
  return 'default'
})

const remainText = computed(() => {
  const s = overall.value?.estimated_remaining_seconds
  return s == null ? '估算中' : formatDuration(s)
})

function tableStatusText(s: TableRunStatus): string {
  return { pending: '等待中', running: '插入中', success: '已完成', failed: '失败' }[s]
}

function handleMinimize(): void {
  minimize(props.taskNo)
}

function handleClose(): void {
  closeTerminal(props.taskNo)
}

/** 强制停止：向 Celery 发送 revoke，已插入数据不回滚 */
async function handleAbort(): Promise<void> {
  aborting.value = true
  try {
    await abortTask(props.taskNo)
    window.$message.success('已发送停止指令')
  } finally {
    aborting.value = false
  }
}

/** 查看详情 → 跳总览页并附带 task_no（总览页自动打开详情抽屉） */
function goDetail(): void {
  router.push({ path: '/overview', query: { task_no: props.taskNo } })
  handleMinimize()
}
</script>

<style scoped>
.panel-header {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.panel-title {
  font-size: 15px;
  font-weight: 600;
}
.panel-task-no {
  font-size: 12px;
}
.panel-header-btns {
  display: flex;
  gap: 4px;
}
.iterate-block {
  margin-bottom: 12px;
}
.iterate-rounds {
  font-size: 13px;
  color: #a78bfa;
}
.overall-block {
  margin-bottom: 16px;
}
.overall-nums {
  display: flex;
  gap: 20px;
  margin-top: 8px;
  font-size: 12px;
  color: #94a3b8;
}
.text-red {
  color: #f87171;
}
.tables-block {
  max-height: 300px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 4px;
}
.table-row {
  padding: 10px 12px;
  border: 1px solid rgba(124, 58, 237, 0.18);
  border-radius: 8px;
  background: rgba(124, 58, 237, 0.04);
}
.table-row.failed {
  border-color: rgba(248, 113, 113, 0.5);
  background: rgba(248, 113, 113, 0.06);
}
.table-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 13px;
}
.table-name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.table-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #94a3b8;
  font-size: 12px;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.dot-pending { background: #64748b; }
.dot-running { background: #34d399; box-shadow: 0 0 6px #34d399; }
.dot-success { background: #22c55e; }
.dot-failed { background: #ef4444; box-shadow: 0 0 6px #ef4444; }
.table-foot {
  display: flex;
  justify-content: space-between;
  margin-top: 5px;
  font-size: 12px;
  color: #64748b;
}
.panel-footer-info {
  display: flex;
  gap: 24px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  font-size: 12px;
  color: #94a3b8;
}
.panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
