<template>
  <!-- JSON 格式化工具 -->
  <ToolCardBase
    tool-key="json"
    title="JSON 格式化工具"
    desc="美化 / 压缩 / 转义 / 校验 JSON"
    :has-result="!!output || !!errorMsg"
    :copy-content="output"
    :result-count="output ? 1 : 0"
  >
    <template #params>
      <n-input v-model:value="input" type="textarea" :rows="6" placeholder="粘贴 JSON 文本" class="mono-area" />
      <div class="btn-row">
        <n-button size="small" class="gradient-btn" @click="beautify">美化</n-button>
        <n-button size="small" @click="compress">压缩</n-button>
        <n-button size="small" @click="escape">转义</n-button>
        <n-button size="small" @click="unescape">反转义</n-button>
        <n-button size="small" type="warning" secondary @click="validate">校验</n-button>
      </div>
    </template>
    <template #result>
      <n-alert v-if="errorMsg" type="error" :show-icon="false" class="error-alert">{{ errorMsg }}</n-alert>
      <n-input v-else :value="output" type="textarea" :rows="8" readonly class="mono-area" />
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ToolCardBase from './ToolCardBase.vue'

const input = ref('')
const output = ref('')
const errorMsg = ref('')

/** 解析 JSON，失败时提取错误行号 */
function parse(): unknown | null {
  errorMsg.value = ''
  try {
    return JSON.parse(input.value)
  } catch (e) {
    const msg = (e as Error).message
    // 尝试从错误信息中提取位置并换算行号
    const posMatch = msg.match(/position (\d+)/)
    if (posMatch) {
      const pos = Number(posMatch[1])
      const line = input.value.slice(0, pos).split('\n').length
      errorMsg.value = `JSON 不合法：第 ${line} 行附近出错（${msg}）`
    } else {
      errorMsg.value = `JSON 不合法：${msg}`
    }
    return null
  }
}

function beautify(): void {
  const obj = parse()
  if (obj !== null) output.value = JSON.stringify(obj, null, 2)
}

function compress(): void {
  const obj = parse()
  if (obj !== null) output.value = JSON.stringify(obj)
}

function escape(): void {
  output.value = JSON.stringify(input.value)
  errorMsg.value = ''
}

function unescape(): void {
  try {
    const v = JSON.parse(input.value)
    if (typeof v !== 'string') throw new Error('not a string')
    output.value = v
    errorMsg.value = ''
  } catch {
    window.$message.error('反转义失败：请输入合法的转义字符串（含引号）')
  }
}

function validate(): void {
  const obj = parse()
  if (obj !== null) {
    output.value = ''
    window.$message.success('JSON 合法')
  }
}
</script>

<style scoped>
.mono-area {
  font-family: monospace;
}
.btn-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.error-alert {
  font-size: 12px;
}
</style>
