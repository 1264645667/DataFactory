<template>
  <!-- 时间戳转换工具 -->
  <ToolCardBase tool-key="timestamp" title="时间戳转换工具" desc="时间戳与日期双向转换，支持时区选择">
    <template #params>
      <!-- 当前时间实时展示 -->
      <div class="now-panel">
        <div class="now-row"><span class="now-label">当前时间</span><span class="now-value">{{ nowText }}</span></div>
        <div class="now-row"><span class="now-label">秒级时间戳</span><span class="now-value mono">{{ nowSeconds }}</span></div>
        <div class="now-row"><span class="now-label">毫秒时间戳</span><span class="now-value mono">{{ nowMs }}</span></div>
      </div>
      <!-- 时间戳 → 日期 -->
      <div class="convert-block">
        <div class="param-row">
          <span class="param-label">时间戳</span>
          <n-input v-model:value="tsInput" size="small" placeholder="10 位秒 / 13 位毫秒" style="width: 200px" />
          <n-select
            v-model:value="timezone"
            :options="tzOptions"
            size="small"
            style="width: 130px"
          />
          <n-button size="small" class="gradient-btn" @click="tsToDate">转换</n-button>
        </div>
        <div v-if="tsResult" class="convert-result">{{ tsResult }}</div>
      </div>
      <!-- 日期 → 时间戳 -->
      <div class="convert-block">
        <div class="param-row">
          <span class="param-label">日期时间</span>
          <n-date-picker v-model:value="dateInput" type="datetime" size="small" style="width: 200px" />
          <n-button size="small" class="gradient-btn" @click="dateToTs">转换</n-button>
        </div>
        <div v-if="dateResult" class="convert-result mono">{{ dateResult }}</div>
      </div>
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ToolCardBase from './ToolCardBase.vue'

// 当前时间每秒刷新
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  timer = setInterval(() => (now.value = Date.now()), 1000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const nowSeconds = computed(() => Math.floor(now.value / 1000))
const nowMs = computed(() => now.value)
const nowText = computed(() => formatInTz(now.value, timezone.value))

const timezone = ref(8)
const tzOptions = [
  { label: 'UTC+8 北京', value: 8 },
  { label: 'UTC+0 伦敦', value: 0 },
  { label: 'UTC+9 东京', value: 9 },
  { label: 'UTC-5 纽约', value: -5 },
]

function pad(n: number): string {
  return n < 10 ? `0${n}` : `${n}`
}

/** 按指定时区格式化时间戳 */
function formatInTz(ms: number, tz: number): string {
  const d = new Date(ms + tz * 3600000)
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`
}

// 时间戳 → 日期
const tsInput = ref('')
const tsResult = ref('')

function tsToDate(): void {
  const raw = tsInput.value.trim()
  if (!/^\d{10}(\d{3})?$/.test(raw)) {
    window.$message.error('请输入 10 位（秒）或 13 位（毫秒）时间戳')
    return
  }
  const ms = raw.length === 13 ? Number(raw) : Number(raw) * 1000
  tsResult.value = `${formatInTz(ms, timezone.value)}（UTC${timezone.value >= 0 ? '+' : ''}${timezone.value}）`
}

// 日期 → 时间戳
const dateInput = ref<number | null>(null)
const dateResult = ref('')

function dateToTs(): void {
  if (!dateInput.value) {
    window.$message.error('请选择日期时间')
    return
  }
  dateResult.value = `秒级：${Math.floor(dateInput.value / 1000)}　毫秒：${dateInput.value}`
}
</script>

<style scoped>
.now-panel {
  border: 1px solid rgba(124, 58, 237, 0.25);
  border-radius: 8px;
  padding: 10px 12px;
  background: rgba(124, 58, 237, 0.05);
}
.now-row {
  display: flex;
  gap: 10px;
  padding: 2px 0;
  font-size: 12px;
}
.now-label {
  width: 80px;
  color: #64748b;
}
.now-value {
  color: #c4b5fd;
}
.mono {
  font-family: monospace;
}
.convert-block {
  padding-top: 10px;
  border-top: 1px dashed rgba(148, 163, 184, 0.15);
}
.param-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.param-label {
  width: 60px;
  font-size: 12px;
  color: #94a3b8;
  flex-shrink: 0;
}
.convert-result {
  margin-top: 8px;
  font-size: 13px;
  color: #34d399;
  padding-left: 70px;
}
</style>
