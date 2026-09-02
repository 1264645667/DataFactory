<template>
  <!-- 雪花 ID 生成器 -->
  <ToolCardBase
    tool-key="snowflake"
    title="雪花 ID 生成器"
    desc="基于时间戳的分布式 ID，含解析信息"
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
        <span class="param-label">机器 ID</span>
        <n-input-number v-model:value="params.machine_id" :min="0" :max="31" size="small" style="width: 120px" />
      </div>
      <div class="param-row">
        <span class="param-label">数据中心</span>
        <n-input-number v-model:value="params.datacenter_id" :min="0" :max="31" size="small" style="width: 120px" />
      </div>
      <div class="param-row">
        <span class="param-label">生成数量</span>
        <n-input-number v-model:value="params.count" :min="1" :max="1000" size="small" style="width: 120px" />
      </div>
    </template>
    <template #result>
      <n-data-table :columns="columns" :data="items" size="small" :pagination="{ pageSize: 10 }" />
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DataTableColumns } from 'naive-ui'
import { toolsApi } from '@/api/tools'
import type { SnowflakeItem } from '@/api/types'
import ToolCardBase from './ToolCardBase.vue'
import { useApiTool } from './useApiTool'

const { params, items, loading, generate, refill } = useApiTool(
  { machine_id: 1, datacenter_id: 1, count: 10 },
  async (p) => (await toolsApi.snowflake(p)).data.results ?? [],
)

const columns: DataTableColumns<SnowflakeItem> = [
  { title: '雪花 ID', key: 'id' },
  { title: '时间戳', key: 'timestamp', width: 170 },
  { title: '机器 ID', key: 'machine_id', width: 80 },
  { title: '数据中心', key: 'datacenter_id', width: 80 },
  { title: '序列号', key: 'sequence', width: 70 },
]

const copyContent = computed(() => items.value.map((i) => i.id).join('\n'))
const exportData = computed(() => ({
  headers: ['雪花ID', '时间戳', '机器ID', '数据中心', '序列号'],
  rows: items.value.map((i) => [i.id, String(i.timestamp), String(i.machine_id), String(i.datacenter_id), String(i.sequence)]),
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
</style>
