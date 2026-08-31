<template>
  <!-- 随机地址生成器（PRD 7.3.7） -->
  <ToolCardBase
    tool-key="address"
    title="随机地址生成器"
    desc="内置全国行政区划数据，精确到街道门牌号"
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
        <span class="param-label">省份</span>
        <n-select v-model:value="params.province" :options="provinceOptions" size="small" style="width: 160px" />
      </div>
      <div class="param-row">
        <span class="param-label">精度</span>
        <n-radio-group v-model:value="params.precision" size="small">
          <n-radio-button value="city">省市</n-radio-button>
          <n-radio-button value="district">省市区</n-radio-button>
          <n-radio-button value="street">省市区街道+门牌号</n-radio-button>
        </n-radio-group>
      </div>
      <div class="param-row">
        <span class="param-label">生成数量</span>
        <n-input-number v-model:value="params.count" :min="1" :max="500" size="small" style="width: 140px" />
      </div>
    </template>
    <template #result>
      <div class="result-list-col">
        <div v-for="(item, i) in items" :key="i" class="result-line">{{ item.address }}</div>
      </div>
    </template>
  </ToolCardBase>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { toolsApi } from '@/api/tools'
import ToolCardBase from './ToolCardBase.vue'
import { useApiTool } from './useApiTool'

const PROVINCES = ['不限', '北京', '天津', '河北', '山西', '内蒙古', '辽宁', '吉林', '黑龙江', '上海', '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南', '广东', '广西', '海南', '重庆', '四川', '贵州', '云南', '西藏', '陕西', '甘肃', '青海', '宁夏', '新疆']
const provinceOptions = PROVINCES.map((p) => ({ label: p, value: p === '不限' ? '' : p }))

const { params, items, loading, generate, refill } = useApiTool(
  { province: '', precision: 'street', count: 10 },
  async (p) => (await toolsApi.address(p)).data.list,
)

const copyContent = computed(() => items.value.map((i) => i.address).join('\n'))
const exportData = computed(() => ({
  headers: ['地址'],
  rows: items.value.map((i) => [i.address]),
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
.result-list-col {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 260px;
  overflow-y: auto;
}
.result-line {
  font-size: 12px;
  color: #c4b5fd;
  padding: 4px 8px;
  border-radius: 4px;
  background: rgba(124, 58, 237, 0.06);
}
</style>
