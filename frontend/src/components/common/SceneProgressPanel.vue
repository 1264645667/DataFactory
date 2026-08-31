<template>
  <!-- 场景执行进度面板（PRD 6.4.4）：分层节点状态 / 强制停止场景 -->
  <n-modal
    :show="true"
    :mask-closable="false"
    :closable="false"
    preset="card"
    style="width: 680px; max-width: 92vw"
  >
    <template #header>
      <div class="sp-header">
        <span class="sp-title">{{ titleText }}</span>
        <n-text depth="3" class="sp-no">{{ entry.sceneExecNo }}</n-text>
      </div>
    </template>
    <template #header-extra>
      <div class="sp-header-btns">
        <n-button quaternary circle size="small" @click="handleMinimize">
          <template #icon><n-icon><RemoveOutline /></n-icon></template>
        </n-button>
        <n-button v-if="isTerminal" quaternary circle size="small" @click="handleClose">
          <template #icon><n-icon><CloseOutline /></n-icon></template>
        </n-button>
      </div>
    </template>

    <n-spin :show="!data">
      <!-- 场景总进度 -->
      <div class="sp-overall">
        <div class="sp-overall-line">
          <span>
            节点进度：{{ overall?.success_count ?? 0 }}/{{ overall?.node_count ?? 0 }} 完成
            <n-text depth="3" class="ml-2">
              {{ overall?.running_count ?? 0 }} 执行中 · {{ overall?.pending_count ?? 0 }} 等待 ·
              {{ overall?.fail_count ?? 0 }} 失败
            </n-text>
          </span>
        </div>
        <n-progress
          type="line"
          :percentage="percent"
          :status="progressStatus"
          :height="12"
          border-radius="6px"
          processing
        />
        <div class="sp-rows">
          整体造数进度：{{ formatNumber(overall?.target_rows) }} 条目标 / 已完成
          {{ formatNumber(overall?.success_rows) }} 条
        </div>
      </div>

      <!-- 执行计划可视化（按层展示） -->
      <div class="sp-layers">
        <div v-for="layer in data?.layers ?? []" :key="layer.layer_no" class="sp-layer">
          <div class="sp-layer-title">第 {{ layer.layer_no + 1 }} 批</div>
          <div
            v-for="node in layer.nodes"
            :key="node.node_id"
            class="sp-node"
            :class="{ clickable: !!node.task_no, failed: node.status === 'failed' }"
            @click="openNodeTask(node)"
          >
            <span class="sp-node-icon">{{ nodeIcon(node.status) }}</span>
            <span class="sp-node-name">{{ node.case_name }}</span>
            <span class="sp-node-count">{{ formatNumber(node.success) }}/{{ formatNumber(node.target) }}</span>
            <span class="sp-node-status">{{ nodeStatusText(node) }}</span>
          </div>
        </div>
      </div>

      <div class="sp-footer-info">
        <span>已用时：{{ formatDuration(data?.elapsed_seconds) }}</span>
        <span>当前批次：{{ (data?.current_layer ?? 0) + 1 }} / {{ data?.total_layers ?? '-' }}</span>
      </div>
    </n-spin>

    <template #footer>
      <div class="sp-actions">
        <n-button @click="handleMinimize">最小化</n-button>
        <n-popconfirm v-if="!isTerminal" @positive-click="handleAbort">
          <template #trigger>
            <n-button type="error" ghost :loading="aborting">强制停止场景</n-button>
          </template>
          确认强制停止整个场景？执行中节点将被终止，等待中节点将取消。
        </n-popconfirm>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { CloseOutline, RemoveOutline } from '@vicons/ionicons5'
import { useSceneProgress } from '@/composables/useSceneProgress'
import { useTaskProgress } from '@/composables/useTaskProgress'
import { formatDuration, formatNumber } from '@/utils/formatter'
import type { SceneNodeProgress } from '@/api/types'

const props = defineProps<{ sceneExecNo: string }>()

const { store, minimize, closeTerminal, abortScene } = useSceneProgress()
const { trackTask } = useTaskProgress()

const entry = computed(() => store.scenes.get(props.sceneExecNo)!)
const data = computed(() => entry.value?.data ?? null)
const overall = computed(() => data.value?.overall ?? null)
const percent = computed(() => entry.value?.overallPercent ?? 0)
const isTerminal = computed(() =>
  ['success', 'failed', 'partial_success', 'aborted'].includes(entry.value?.status ?? ''),
)
const aborting = ref(false)

const titleText = computed(() => {
  switch (entry.value?.status) {
    case 'success':
      return '场景执行完成'
    case 'failed':
      return '场景执行失败'
    case 'partial_success':
      return '场景部分完成'
    case 'aborted':
      return '场景已中止'
    default:
      return `场景执行中 · ${entry.value?.sceneName ?? ''}`
  }
})

const progressStatus = computed(() => {
  if (entry.value?.status === 'success') return 'success'
  if (entry.value?.status === 'failed' || entry.value?.status === 'aborted') return 'error'
  if (entry.value?.status === 'partial_success') return 'warning'
  return 'default'
})

/** 节点状态图标（不用 emoji，用文字/符号标识） */
function nodeIcon(status: SceneNodeProgress['status']): string {
  return {
    pending: '○',
    running: '◉',
    success: '●',
    failed: '✕',
    cancelled: '»',
  }[status]
}

function nodeStatusText(node: SceneNodeProgress): string {
  if (node.status === 'running' && node.target > 0) {
    return `执行中 ${Math.round((node.success / node.target) * 100)}%`
  }
  return {
    pending: '等待前置完成',
    running: '执行中',
    success: '成功',
    failed: '失败',
    cancelled: '已取消',
  }[node.status]
}

/** 点击节点行：展开该节点对应的 Case 任务进度面板（复用 4.4.8） */
function openNodeTask(node: SceneNodeProgress): void {
  if (node.task_no) {
    trackTask(node.task_no, node.case_name)
  }
}

function handleMinimize(): void {
  minimize(props.sceneExecNo)
}

function handleClose(): void {
  closeTerminal(props.sceneExecNo)
}

async function handleAbort(): Promise<void> {
  aborting.value = true
  try {
    await abortScene(props.sceneExecNo)
    window.$message.success('已发送场景停止指令')
  } finally {
    aborting.value = false
  }
}
</script>

<style scoped>
.sp-header {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.sp-title {
  font-size: 15px;
  font-weight: 600;
}
.sp-no {
  font-size: 12px;
}
.sp-header-btns {
  display: flex;
  gap: 4px;
}
.sp-overall {
  margin-bottom: 16px;
}
.sp-overall-line {
  font-size: 13px;
  margin-bottom: 8px;
}
.sp-rows {
  margin-top: 8px;
  font-size: 12px;
  color: #94a3b8;
}
.sp-layers {
  max-height: 340px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.sp-layer-title {
  font-size: 12px;
  color: #a78bfa;
  margin-bottom: 6px;
  font-weight: 600;
}
.sp-node {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid rgba(124, 58, 237, 0.15);
  border-radius: 8px;
  margin-bottom: 6px;
  background: rgba(124, 58, 237, 0.04);
  font-size: 13px;
}
.sp-node.clickable {
  cursor: pointer;
}
.sp-node.clickable:hover {
  border-color: rgba(124, 58, 237, 0.5);
}
.sp-node.failed {
  border-color: rgba(248, 113, 113, 0.5);
}
.sp-node-icon {
  width: 18px;
  text-align: center;
  color: #a78bfa;
}
.sp-node-name {
  flex: 1;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sp-node-count {
  color: #94a3b8;
  font-size: 12px;
}
.sp-node-status {
  color: #64748b;
  font-size: 12px;
  min-width: 90px;
  text-align: right;
}
.sp-footer-info {
  display: flex;
  gap: 24px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  font-size: 12px;
  color: #94a3b8;
}
.sp-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
