<template>
  <!-- 身份证号生成器（PRD 7.3.1） -->
  <ToolCardBase
    tool-key="idcard"
    title="身份证号生成器"
    desc="符合 GB/T 11643-1999 标准，含正确校验位"
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
        <span class="param-label">省份</span>
        <n-select v-model:value="params.province" :options="provinceOptions" size="small" style="width: 160px" />
      </div>
      <div class="param-row">
        <span class="param-label">性别</span>
        <n-radio-group v-model:value="params.gender" size="small">
          <n-radio-button value="random">随机</n-radio-button>
          <n-radio-button value="male">男</n-radio-button>
          <n-radio-button value="female">女</n-radio-button>
        </n-radio-group>
      </div>
      <div class="param-row">
        <span class="param-label">出生年份</span>
        <n-slider v-model:value="yearRange" range :min="1950" :max="2010" style="flex: 1; max-width: 260px" />
        <span class="param-value">{{ yearRange[0] }} ~ {{ yearRange[1] }}</span>
      </div>
      <div class="param-row">
        <span class="param-label">生成数量</span>
        <n-input-number v-model:value="params.count" :min="1" :max="1000" size="small" style="width: 140px" />
      </div>
    </template>
    <template #result>
      <n-data-table :columns="columns" :data="items" size="small" :pagination="{ pageSize: 10 }" />
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { DataTableColumns } from 'naive-ui'
import { toolsApi } from '@/api/tools'
import type { IdCardItem } from '@/api/types'
import ToolCardBase from './ToolCardBase.vue'
import { useApiTool } from './useApiTool'

const PROVINCES = ['不限', '北京', '天津', '河北', '山西', '内蒙古', '辽宁', '吉林', '黑龙江', '上海', '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南', '广东', '广西', '海南', '重庆', '四川', '贵州', '云南', '西藏', '陕西', '甘肃', '青海', '宁夏', '新疆']
const provinceOptions = PROVINCES.map((p) => ({ label: p, value: p === '不限' ? '' : p }))

const yearRange = ref<[number, number]>([1980, 2000])

const { params, items, loading, generate, refill } = useApiTool(
  { province: '', gender: 'random', birth_year_start: 1980, birth_year_end: 2000, count: 10 },
  async (p) => (await toolsApi.idcard(p)).data.results ?? [],
)

// 滑动条与参数双向同步
watch(yearRange, ([min, max]) => {
  params.birth_year_start = min
  params.birth_year_end = max
})

const columns: DataTableColumns<IdCardItem> = [
  { title: '身份证号', key: 'id_card' },
  { title: '省份', key: 'province', width: 90 },
  { title: '出生日期', key: 'birth_date', width: 110 },
  { title: '性别', key: 'gender', width: 60 },
  { title: '校验位', key: 'check_digit', width: 70, render: (r) => r.check_digit ?? '✓' },
]

const copyContent = computed(() => items.value.map((i) => i.id_card).join('\n'))
const exportData = computed(() => ({
  headers: ['身份证号', '省份', '出生日期', '性别'],
  rows: items.value.map((i) => [i.id_card, i.province, i.birth_date, i.gender]),
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
.param-value {
  font-size: 12px;
  color: #a78bfa;
  flex-shrink: 0;
}
</style>
