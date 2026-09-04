<template>
  <!-- 随机姓名生成器 -->
  <ToolCardBase
    tool-key="name"
    title="随机姓名生成器"
    desc="百家姓 + 常用汉字库随机组合，支持中英文"
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
        <span class="param-label">语言</span>
        <n-radio-group v-model:value="params.language" size="small">
          <n-radio-button value="zh">中文</n-radio-button>
          <n-radio-button value="en">英文</n-radio-button>
        </n-radio-group>
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
  { language: 'zh', gender: 'random', count: 10 },
  async (p) => (await toolsApi.name(p)).data.results ?? [],
)

const copyContent = computed(() => items.value.join('\n'))
const exportData = computed(() => ({
  headers: ['姓名'],
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
