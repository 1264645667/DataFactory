<template>
  <!-- UUID 批量生成器 -->
  <ToolCardBase
    tool-key="uuid"
    title="UUID 批量生成器"
    desc="支持含连字符 / 大写 / 小写多种格式"
    :loading="loading"
    :result-count="items.length"
    :has-result="items.length > 0"
    :copy-content="copyContent"
    :export-data="exportData"
    :params-snapshot="{ ...params }"
    :show-progress="params.count > 1000"
    @generate="generate"
    @refill="refill"
  >
    <template #params>
      <div class="param-row">
        <span class="param-label">格式</span>
        <n-radio-group v-model:value="params.fmt" size="small" class="wrap-radio">
          <n-radio-button value="hyphen">含连字符·小写</n-radio-button>
          <n-radio-button value="plain">无连字符·小写</n-radio-button>
          <n-radio-button value="upper">含连字符·大写</n-radio-button>
          <n-radio-button value="lower">无连字符·大写</n-radio-button>
        </n-radio-group>
      </div>
      <div class="param-row">
        <span class="param-label">生成数量</span>
        <n-input-number v-model:value="params.count" :min="1" :max="10000" size="small" style="width: 140px" />
      </div>
    </template>
    <template #result>
      <n-input :value="copyContent" type="textarea" :rows="8" readonly class="result-textarea" />
      <div class="result-tip">已生成 {{ items.length }} 个，一键复制全部</div>
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { toolsApi } from '@/api/tools'
import ToolCardBase from './ToolCardBase.vue'
import { useApiTool } from './useApiTool'

const { params, items, loading, generate, refill } = useApiTool(
  { fmt: 'hyphen' as 'hyphen' | 'plain' | 'upper' | 'lower', count: 100 },
  async (p) => (await toolsApi.uuid(p)).data.results ?? [],
)

const copyContent = computed(() => items.value.join('\n'))
const exportData = computed(() => ({
  headers: ['UUID'],
  rows: items.value.map((i) => [i]),
}))
</script>

<style scoped>
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
.result-textarea {
  font-family: monospace;
}
.result-tip {
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
}
</style>
