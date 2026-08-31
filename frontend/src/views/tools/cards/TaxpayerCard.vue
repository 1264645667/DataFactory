<template>
  <!-- 纳税人识别号生成器（PRD 7.3.6） -->
  <ToolCardBase
    tool-key="taxpayer-id"
    title="纳税人识别号生成器"
    desc="支持企业 / 个人两种类型"
    :loading="loading"
    :result-count="items.length"
    :has-result="items.length > 0"
    :copy-content="copyContent"
    :export-data="exportData"
    :params-snapshot="{ ...params }"
    @generate="generate"
    @refill="refill"
  >
    <template #params>
      <div class="param-row">
        <span class="param-label">类型</span>
        <n-radio-group v-model:value="params.type" size="small">
          <n-radio-button value="enterprise">企业</n-radio-button>
          <n-radio-button value="personal">个人</n-radio-button>
        </n-radio-group>
      </div>
      <div class="param-row">
        <span class="param-label">生成数量</span>
        <n-input-number v-model:value="params.count" :min="1" :max="100" size="small" style="width: 140px" />
      </div>
    </template>
    <template #result>
      <div class="result-list">
        <span v-for="(item, i) in items" :key="i" class="result-chip">{{ item.taxpayer_id }}</span>
      </div>
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { toolsApi } from '@/api/tools'
import ToolCardBase from './ToolCardBase.vue'
import { useApiTool } from './useApiTool'

const { params, items, loading, generate, refill } = useApiTool(
  { type: 'enterprise', count: 10 },
  async (p) => (await toolsApi.taxpayerId(p)).data.list,
)

const copyContent = computed(() => items.value.map((i) => i.taxpayer_id).join('\n'))
const exportData = computed(() => ({
  headers: ['纳税人识别号'],
  rows: items.value.map((i) => [i.taxpayer_id]),
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
.result-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 260px;
  overflow-y: auto;
}
.result-chip {
  font-size: 12px;
  color: #c4b5fd;
  background: rgba(124, 58, 237, 0.1);
  border: 1px solid rgba(124, 58, 237, 0.25);
  border-radius: 6px;
  padding: 3px 10px;
}
</style>
