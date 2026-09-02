<template>
  <!-- 银行卡号生成器 -->
  <ToolCardBase
    tool-key="bankcard"
    title="银行卡号生成器"
    desc="基于 BIN 码 + Luhn 算法生成合法卡号"
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
        <span class="param-label">银行</span>
        <n-select v-model:value="params.bank" :options="bankOptions" size="small" style="width: 180px" />
      </div>
      <div class="param-row">
        <span class="param-label">卡类型</span>
        <n-radio-group v-model:value="params.card_type" size="small">
          <n-radio-button value="debit">借记卡</n-radio-button>
          <n-radio-button value="credit">信用卡</n-radio-button>
        </n-radio-group>
      </div>
      <div class="param-row">
        <span class="param-label">生成数量</span>
        <n-input-number v-model:value="params.count" :min="1" :max="100" size="small" style="width: 140px" />
      </div>
    </template>
    <template #result>
      <div class="result-list">
        <span v-for="(item, i) in items" :key="i" class="result-chip">{{ item.card_no }}</span>
      </div>
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { toolsApi } from '@/api/tools'
import ToolCardBase from './ToolCardBase.vue'
import { useApiTool } from './useApiTool'

const bankOptions = [
  { label: '随机', value: '' },
  { label: '中国工商银行', value: '中国工商银行' },
  { label: '中国农业银行', value: '中国农业银行' },
  { label: '中国建设银行', value: '中国建设银行' },
  { label: '招商银行', value: '招商银行' },
  { label: '中国银行', value: '中国银行' },
  { label: '交通银行', value: '交通银行' },
]

const { params, items, loading, generate, refill } = useApiTool(
  { bank: '', card_type: 'debit', count: 10 },
  async (p) => (await toolsApi.bankcard(p)).data.results ?? [],
)

const copyContent = computed(() => items.value.map((i) => i.card_no).join('\n'))
const exportData = computed(() => ({
  headers: ['银行卡号', '银行', '卡类型'],
  rows: items.value.map((i) => [i.card_no, i.bank, i.card_type]),
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
