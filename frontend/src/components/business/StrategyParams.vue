<template>
  <!-- 策略参数动态控件（PRD 4.4.4）：根据策略类型渲染不同输入组件 -->
  <div class="strategy-params">
    <!-- 随机 X 位生成 -->
    <n-input-number
      v-if="strategy === 'RANDOM_FIXED_LEN'"
      :value="numVal('length')"
      size="small"
      :min="1"
      :max="column.char_max_length ?? undefined"
      placeholder="位数 X"
      style="width: 130px"
      @update:value="set('length', $event)"
    />

    <!-- 随机 X~Y 位生成 -->
    <div v-else-if="strategy === 'RANDOM_RANGE_LEN'" class="param-inline">
      <n-input-number :value="numVal('min_length')" size="small" :min="1" placeholder="X" style="width: 100px" @update:value="set('min_length', $event)" />
      <span class="dim">~</span>
      <n-input-number :value="numVal('max_length')" size="small" :min="1" :max="column.char_max_length ?? undefined" placeholder="Y" style="width: 100px" @update:value="set('max_length', $event)" />
    </div>

    <!-- 自定义输入 -->
    <n-input
      v-else-if="strategy === 'CUSTOM_VALUE'"
      :value="strVal('value')"
      size="small"
      placeholder="自定义值（留空为 NULL）"
      style="width: 220px"
      @update:value="set('value', $event)"
    />

    <!-- 从列表随机选取 -->
    <n-input
      v-else-if="strategy === 'PICK_FROM_LIST'"
      :value="strVal('list')"
      type="textarea"
      :rows="2"
      size="small"
      placeholder="每行一个值"
      style="width: 240px"
      @update:value="set('list', $event)"
    />

    <!-- 按序遍历插入：值列表 + 每值条数 -->
    <div v-else-if="strategy === 'ITERATE_LIST'" class="param-stack">
      <n-input
        :value="strVal('list')"
        type="textarea"
        :rows="2"
        size="small"
        placeholder="遍历值列表，每行一个值"
        style="width: 240px"
        @update:value="set('list', $event)"
      />
      <div class="param-inline">
        <span class="dim">每值插入</span>
        <n-input-number :value="numVal('rows_per_value')" size="small" :min="1" placeholder="条数" style="width: 110px" @update:value="set('rows_per_value', $event)" />
        <span class="dim">条</span>
      </div>
    </div>

    <!-- 指定值自增：前缀(可选) + 起始值 + 补零位数(可选)；字符字段配前缀可生成 test0001 这类序列 -->
    <div v-else-if="strategy === 'INCR_FROM'" class="param-inline">
      <n-input
        :value="strVal('prefix')"
        size="small"
        placeholder="前缀(可空)"
        style="width: 96px"
        @update:value="set('prefix', $event)"
      />
      <n-input-number
        :value="numVal('start')"
        size="small"
        :min="1"
        placeholder="起始值"
        style="width: 100px"
        @update:value="set('start', $event)"
      />
      <n-input-number
        :value="numVal('pad_length')"
        size="small"
        :min="0"
        placeholder="补零位"
        style="width: 88px"
        @update:value="set('pad_length', $event)"
      />
    </div>

    <!-- 字段运算派生：源字段 + 运算符 + 操作数（B = A×0.8 / A-5000 等） -->
    <div v-else-if="strategy === 'DERIVED'" class="param-inline">
      <n-select
        :value="strVal('source_column')"
        :options="siblingColumns ?? []"
        size="small"
        filterable
        placeholder="源字段"
        style="width: 150px"
        @update:value="set('source_column', $event)"
      />
      <n-select
        :value="strVal('operator')"
        :options="OPERATOR_OPTIONS"
        size="small"
        placeholder="运算"
        style="width: 80px"
        @update:value="set('operator', $event)"
      />
      <n-input-number
        :value="numVal('operand')"
        size="small"
        placeholder="数值"
        style="width: 110px"
        @update:value="set('operand', $event)"
      />
    </div>

    <!-- 随机时间段 -->
    <n-date-picker
      v-else-if="strategy === 'RANDOM_TIME_RANGE'"
      :value="rangeVal"
      type="datetimerange"
      size="small"
      style="width: 300px"
      @update:value="setRange"
    />

    <!-- 固定时间 -->
    <n-date-picker
      v-else-if="strategy === 'FIXED_TIME'"
      :value="numVal('fixed_time')"
      type="datetime"
      size="small"
      style="width: 200px"
      @update:value="set('fixed_time', $event)"
    />

    <!-- 无参数策略 -->
    <span v-else class="dim no-params">—</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ColumnInfo, StrategyCode } from '@/api/types'

// 策略参数组件：v-model 绑定 params 对象（直接修改传入对象字段）
const props = defineProps<{
  strategy: StrategyCode
  column: ColumnInfo
  modelValue: Record<string, unknown>
  /** 同表其他数字字段选项（DERIVED 派生策略选源字段用） */
  siblingColumns?: Array<{ label: string; value: string }>
}>()

const emit = defineEmits<{ (e: 'update:modelValue', v: Record<string, unknown>): void }>()

// DERIVED 运算符选项
const OPERATOR_OPTIONS = [
  { label: '×', value: 'multiply' },
  { label: '÷', value: 'divide' },
  { label: '+', value: 'add' },
  { label: '−', value: 'subtract' },
]

function numVal(key: string): number | null {
  const v = props.modelValue[key]
  return typeof v === 'number' ? v : v != null && v !== '' && !Number.isNaN(Number(v)) ? Number(v) : null
}

function strVal(key: string): string {
  const v = props.modelValue[key]
  return v == null ? '' : String(v)
}

function set(key: string, value: unknown): void {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

// 时间范围选择器 ↔ params 两个字段
const rangeVal = computed<[number, number] | null>(() => {
  const s = props.modelValue.range_start
  const e = props.modelValue.range_end
  return typeof s === 'number' && typeof e === 'number' ? [s, e] : null
})

function setRange(v: [number, number] | null): void {
  emit('update:modelValue', {
    ...props.modelValue,
    range_start: v?.[0] ?? null,
    range_end: v?.[1] ?? null,
  })
}
</script>

<style scoped>
.strategy-params {
  display: flex;
  align-items: center;
}
.param-inline {
  display: flex;
  align-items: center;
  gap: 6px;
}
.param-stack {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dim {
  color: #64748b;
  font-size: 12px;
}
.no-params {
  padding-left: 4px;
}
</style>
