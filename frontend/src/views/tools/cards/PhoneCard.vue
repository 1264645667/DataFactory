<template>
  <!-- 手机号生成器 -->
  <ToolCardBase
    tool-key="phone"
    title="手机号生成器"
    desc="基于真实号段前缀（170+ 号段数据）"
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
        <span class="param-label">运营商</span>
        <n-radio-group v-model:value="params.carrier" size="small">
          <n-radio-button value="random">随机</n-radio-button>
          <n-radio-button value="mobile">中国移动</n-radio-button>
          <n-radio-button value="unicom">中国联通</n-radio-button>
          <n-radio-button value="telecom">中国电信</n-radio-button>
        </n-radio-group>
      </div>
      <div class="param-row">
        <span class="param-label">生成数量</span>
        <n-input-number v-model:value="params.count" :min="1" :max="1000" size="small" style="width: 140px" />
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

const { params, items, loading, generate, refill } = useApiTool(
  { carrier: 'random', count: 10 },
  async (p) => (await toolsApi.phone(p)).data.results ?? [],
)

const copyContent = computed(() => items.value.join('\n'))
const exportData = computed(() => ({
  headers: ['手机号'],
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
