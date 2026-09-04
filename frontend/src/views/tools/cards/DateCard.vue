<template>
  <!-- 日期批量生成器 -->
  <ToolCardBase
    tool-key="date"
    title="日期批量生成器"
    desc="指定范围内批量生成多种格式日期"
    :loading="loading"
    :result-count="items.length"
    :has-result="items.length > 0"
    :copy-content="copyContent"
    :export-data="exportData"
    :params-snapshot="snapshot"
    :show-progress="params.count > 1000"
    @generate="generate"
    @refill="refill"
  >
    <template #params>
      <div class="param-row">
        <span class="param-label">日期范围</span>
        <n-date-picker v-model:value="dateRange" type="daterange" size="small" style="width: 260px" />
      </div>
      <div class="param-row">
        <span class="param-label">格式</span>
        <n-select
          v-model:value="params.fmt"
          :options="[
            { label: 'yyyy-MM-dd', value: 'yyyy-MM-dd' },
            { label: 'yyyy/MM/dd', value: 'yyyy/MM/dd' },
            { label: 'yyyyMMdd', value: 'yyyyMMdd' },
            { label: '时间戳（秒）', value: 'timestamp' },
          ]"
          size="small"
          style="width: 160px"
        />
      </div>
      <div class="param-row">
        <span class="param-label">是否去重</span>
        <n-radio-group v-model:value="params.dedup" size="small">
          <n-radio-button :value="true">去重</n-radio-button>
          <n-radio-button :value="false">不去重</n-radio-button>
        </n-radio-group>
      </div>
      <div class="param-row">
        <span class="param-label">生成数量</span>
        <n-input-number v-model:value="params.count" :min="1" :max="10000" size="small" style="width: 140px" />
      </div>
    </template>
    <template #result>
      <div class="result-list">
        <span v-for="(item, i) in items" :key="i" class="result-chip" title="点击复制" @click="copyItem(String(item))">{{ item }}</span>
      </div>
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { toolsApi } from '@/api/tools'
import ToolCardBase from './ToolCardBase.vue'
import { useApiTool } from './useApiTool'
import { copyItem, formatDate } from '@/utils/formatter'

const today = Date.now()
const dateRange = ref<[number, number]>([today - 30 * 86400000, today])

const { params, items, loading, generate, refill } = useApiTool(
  { start_date: formatDate(today - 30 * 86400000), end_date: formatDate(today), fmt: 'yyyy-MM-dd', dedup: true, count: 100 },
  async (p) => (await toolsApi.date(p)).data.results ?? [],
)

watch(dateRange, (range) => {
  if (range) {
    params.start_date = formatDate(range[0])
    params.end_date = formatDate(range[1])
  }
})

const snapshot = computed(() => ({ ...params }))
const copyContent = computed(() => items.value.map((i) => String(i)).join('\n'))
const exportData = computed(() => ({
  headers: ['日期'],
  rows: items.value.map((i) => [String(i)]),
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
