<template>
  <!-- 统一社会信用代码生成器 -->
  <ToolCardBase
    tool-key="credit-code"
    title="统一社会信用代码生成器"
    desc="符合 GB 32100-2015 标准，18 位合法代码含校验位"
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
        <span class="param-label">登记部门</span>
        <n-select v-model:value="params.department" :options="deptOptions" size="small" style="width: 180px" />
      </div>
      <div class="param-row">
        <span class="param-label">生成数量</span>
        <n-input-number v-model:value="params.count" :min="1" :max="100" size="small" style="width: 140px" />
      </div>
    </template>
    <template #result>
      <div class="result-list">
        <span v-for="(item, i) in items" :key="i" class="result-chip" title="点击复制" @click="copyItem(item)">{{ item }}</span>
      </div>
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { toolsApi } from '@/api/tools'
import ToolCardBase from './ToolCardBase.vue'
import { useApiTool } from './useApiTool'
import { copyItem } from '@/utils/formatter'

const deptOptions = [
  { label: '全部', value: '' },
  { label: '工商', value: '工商' },
  { label: '机构编制', value: '机构编制' },
  { label: '民政', value: '民政' },
  { label: '司法行政', value: '司法行政' },
  { label: '文化', value: '文化' },
  { label: '外交', value: '外交' },
  { label: '旅游', value: '旅游' },
]

const { params, items, loading, generate, refill } = useApiTool(
  { department: '', count: 10 },
  async (p) => (await toolsApi.creditCode(p)).data.results ?? [],
)

const copyContent = computed(() => items.value.join('\n'))
const exportData = computed(() => ({
  headers: ['统一社会信用代码'],
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
