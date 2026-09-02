<template>
  <!-- Base64 编解码工具 -->
  <ToolCardBase
    tool-key="base64"
    title="Base64 编解码工具"
    desc="文本 Base64 编码 / 解码"
    :has-result="!!output"
    :copy-content="output"
    :result-count="output ? 1 : 0"
  >
    <template #params>
      <n-input v-model:value="input" type="textarea" :rows="4" placeholder="输入待处理的文本" />
      <div class="btn-row">
        <n-button size="small" class="gradient-btn" @click="encode">编码 →</n-button>
        <n-button size="small" class="gradient-btn" @click="decode">← 解码</n-button>
      </div>
    </template>
    <template #result>
      <n-input :value="output" type="textarea" :rows="4" readonly class="output-area" />
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ToolCardBase from './ToolCardBase.vue'

const input = ref('')
const output = ref('')

/** UTF-8 安全的 Base64 编码 */
function encode(): void {
  try {
    output.value = btoa(String.fromCharCode(...new TextEncoder().encode(input.value)))
  } catch {
    window.$message.error('编码失败')
  }
}

/** UTF-8 安全的 Base64 解码 */
function decode(): void {
  try {
    const bytes = Uint8Array.from(atob(input.value.trim()), (c) => c.charCodeAt(0))
    output.value = new TextDecoder().decode(bytes)
  } catch {
    window.$message.error('解码失败：输入不是合法的 Base64')
  }
}
</script>

<style scoped>
.btn-row {
  display: flex;
  gap: 10px;
  justify-content: center;
}
.output-area {
  font-family: monospace;
}
</style>
