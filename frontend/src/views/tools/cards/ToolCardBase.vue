<template>
  <!-- 工具卡片基座展开/收起、一键复制、历史回填、导出 CSV/TXT、大批量进度条 -->
  <div class="tool-card gradient-border-card">
    <!-- 卡片头：名称 + 简介 + 展开开关 -->
    <div class="tool-head" @click="expanded = !expanded">
      <div class="tool-head-text">
        <span class="tool-name">{{ title }}</span>
        <span class="tool-desc">{{ desc }}</span>
      </div>
      <n-icon :size="16" class="tool-toggle" :class="{ expanded }">
        <ChevronDownOutline />
      </n-icon>
    </div>

    <div v-show="expanded" class="tool-body">
      <!-- 参数区 -->
      <div class="tool-params">
        <slot name="params" />
      </div>

      <!-- 生成按钮 + 历史回填 -->
      <div class="tool-actions">
        <n-button class="gradient-btn" size="small" :loading="loading" @click="handleGenerate">
          {{ generateText }}
        </n-button>
        <n-popover v-if="history.length > 0" trigger="click" placement="bottom-start">
          <template #trigger>
            <n-button size="small" quaternary>历史参数（{{ history.length }}）</n-button>
          </template>
          <div class="history-list">
            <div v-for="(h, i) in history" :key="i" class="history-item" @click="applyHistory(h)">
              {{ summarize(h) }}
            </div>
          </div>
        </n-popover>
      </div>

      <!-- 大批量生成进度条（>1000 条） -->
      <n-progress
        v-if="loading && showProgress"
        type="line"
        :percentage="100"
        status="default"
        processing
        :show-indicator="false"
        class="tool-progress"
      />

      <!-- 结果区 -->
      <div v-if="hasResult" class="tool-result">
        <div class="result-toolbar">
          <span class="result-count">已生成 {{ resultCount }} 条</span>
          <div class="result-btns">
            <n-button size="tiny" :type="copied ? 'success' : 'primary'" secondary @click="handleCopy">
              {{ copied ? '已复制' : '一键复制' }}
            </n-button>
            <!-- 结果 ≥100 条时展示导出按钮 -->
            <template v-if="exportData && resultCount >= 100">
              <n-button size="tiny" secondary @click="handleExport('csv')">导出 CSV</n-button>
              <n-button size="tiny" secondary @click="handleExport('txt')">导出 TXT</n-button>
            </template>
          </div>
        </div>
        <slot name="result" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ChevronDownOutline } from '@vicons/ionicons5'
import { copyText, formatFileTimestamp } from '@/utils/formatter'

// 导出数据结构
interface ExportData {
  headers: string[]
  rows: string[][]
}

const props = withDefaults(
  defineProps<{
    toolKey: string
    title: string
    desc: string
    loading?: boolean
    /** 结果条数 */
    resultCount?: number
    /** 是否有结果 */
    hasResult?: boolean
    /** 一键复制的文本（换行分隔） */
    copyContent?: string
    /** 导出数据（≥100 条时显示导出按钮） */
    exportData?: ExportData | null
    /** 当前参数快照（用于历史回填） */
    paramsSnapshot?: Record<string, unknown>
    /** 生成按钮文案 */
    generateText?: string
    /** 是否显示进度条（数量 >1000 时） */
    showProgress?: boolean
  }>(),
  {
    loading: false,
    resultCount: 0,
    hasResult: false,
    copyContent: '',
    exportData: null,
    paramsSnapshot: () => ({}),
    generateText: '生成',
    showProgress: false,
  },
)

const emit = defineEmits<{
  (e: 'generate'): void
  (e: 'refill', params: Record<string, unknown>): void
}>()

const expanded = ref(true)
const copied = ref(false)

// ---------------- 生成历史（localStorage 保留最近 5 次） ----------------
const history = ref<Array<Record<string, unknown>>>([])
const historyKey = `df_tool_hist_${props.toolKey}`

onMounted(() => {
  try {
    history.value = JSON.parse(localStorage.getItem(historyKey) ?? '[]')
  } catch {
    history.value = []
  }
})

function recordHistory(): void {
  const snapshot = props.paramsSnapshot
  if (!snapshot || Object.keys(snapshot).length === 0) return
  const serialized = JSON.stringify(snapshot)
  history.value = [snapshot, ...history.value.filter((h) => JSON.stringify(h) !== serialized)].slice(0, 5)
  localStorage.setItem(historyKey, JSON.stringify(history.value))
}

function applyHistory(params: Record<string, unknown>): void {
  emit('refill', params)
  window.$message.success('已回填历史参数')
}

function summarize(params: Record<string, unknown>): string {
  return Object.entries(params)
    .map(([k, v]) => `${k}=${v}`)
    .join('，')
}

function handleGenerate(): void {
  recordHistory()
  emit('generate')
}

// ---------------- 一键复制 ----------------
function handleCopy(): void {
  if (!props.copyContent) return
  copyText(props.copyContent).then((ok) => {
    if (ok) {
      copied.value = true
      setTimeout(() => (copied.value = false), 1500)
    } else {
      window.$message.error('复制失败')
    }
  })
}

// ---------------- 导出 CSV / TXT（前端 Blob 本地生成） ----------------
function handleExport(ext: 'csv' | 'txt'): void {
  const data = props.exportData
  if (!data) return
  let content: string
  let mime: string
  if (ext === 'csv') {
    // 加 BOM 保证 Excel 打开中文不乱码
    content = '﻿' + [data.headers.join(','), ...data.rows.map((r) => r.join(','))].join('\n')
    mime = 'text/csv;charset=utf-8'
  } else {
    content = data.rows.map((r) => r.join(' ')).join('\n')
    mime = 'text/plain;charset=utf-8'
  }
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `dataforge_${props.toolKey}_${formatFileTimestamp()}.${ext}`
  a.click()
  URL.revokeObjectURL(url)
  window.$message.success(`已导出 ${data.rows.length} 条数据`)
}
</script>

<style scoped>
.tool-card {
  padding: 14px 16px;
  break-inside: avoid;
  margin-bottom: 16px;
}
.tool-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
}
.tool-head-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.tool-name {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
}
.tool-desc {
  font-size: 11px;
  color: #64748b;
}
.tool-toggle {
  color: #64748b;
  transition: transform 0.2s ease;
}
.tool-toggle.expanded {
  transform: rotate(180deg);
}
.tool-body {
  padding-top: 12px;
}
.tool-params {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tool-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 12px;
}
.tool-progress {
  margin-top: 10px;
}
.tool-result {
  margin-top: 12px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  padding-top: 10px;
}
.result-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.result-count {
  font-size: 12px;
  color: #94a3b8;
}
.result-btns {
  display: flex;
  gap: 6px;
}
.history-list {
  max-width: 320px;
}
.history-item {
  font-size: 12px;
  color: #94a3b8;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
}
.history-item:hover {
  background: rgba(124, 58, 237, 0.12);
  color: #e2e8f0;
}
</style>
