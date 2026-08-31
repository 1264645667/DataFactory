<template>
  <!-- SQL 数据转义工具（PRD 7.3.14，纯前端本地实现） -->
  <ToolCardBase
    tool-key="sql-escape"
    title="SQL 数据转义工具"
    desc="输出 SQL 安全的转义字符串（防注入）"
    :has-result="!!output"
    :copy-content="output"
    :result-count="output ? 1 : 0"
  >
    <template #params>
      <div class="param-row">
        <span class="param-label">模式</span>
        <n-radio-group v-model:value="mode" size="small">
          <n-radio-button value="mysql">MySQL</n-radio-button>
          <n-radio-button value="general">通用</n-radio-button>
        </n-radio-group>
      </div>
      <n-input v-model:value="input" type="textarea" :rows="4" placeholder="输入原始字符串" />
      <n-button size="small" class="gradient-btn" @click="doEscape">转义</n-button>
    </template>
    <template #result>
      <n-input :value="output" type="textarea" :rows="4" readonly class="mono-area" />
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ToolCardBase from './ToolCardBase.vue'

const mode = ref<'mysql' | 'general'>('mysql')
const input = ref('')
const output = ref('')

/** SQL 转义：MySQL 模式额外转义反斜杠等特殊字符，通用模式仅转义单引号 */
function doEscape(): void {
  const s = input.value
  if (mode.value === 'mysql') {
    output.value = s
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/"/g, '\\"')
      .replace(/\n/g, '\\n')
      .replace(/\r/g, '\\r')
      .replace(/\t/g, '\\t')
      .replace(/\0/g, '\\0')
  } else {
    // 通用标准：单引号双写
    output.value = s.replace(/'/g, "''")
  }
}
</script>

<style scoped>
.param-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.param-label {
  width: 40px;
  font-size: 12px;
  color: #94a3b8;
}
.mono-area {
  font-family: monospace;
}
</style>
