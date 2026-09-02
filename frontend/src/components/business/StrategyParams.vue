<template>
  <!-- 策略参数动态控件根据策略类型渲染不同输入组件 -->
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

    <!-- 快捷工具生成：工具下拉 + 各工具可选参数（身份证/手机号/银行卡/地址等） -->
    <div v-else-if="strategy === 'TOOL_GEN'" class="param-stack">
      <n-select
        :value="strVal('tool')"
        :options="TOOL_OPTIONS"
        size="small"
        placeholder="选择生成工具"
        style="width: 200px"
        @update:value="set('tool', $event)"
      />
      <div class="param-inline">
        <!-- 身份证/地址：省份（可空） -->
        <n-input
          v-if="toolIs('idcard') || toolIs('address')"
          :value="strVal('province')"
          size="small"
          placeholder="省份(可空)"
          style="width: 120px"
          @update:value="set('province', $event)"
        />
        <!-- 身份证/姓名：性别 -->
        <n-select
          v-if="toolIs('idcard') || toolIs('name')"
          :value="strVal('gender')"
          :options="GENDER_OPTIONS"
          size="small"
          placeholder="性别"
          style="width: 90px"
          @update:value="set('gender', $event)"
        />
        <!-- 手机号：运营商 -->
        <n-select
          v-if="toolIs('phone')"
          :value="strVal('carrier')"
          :options="CARRIER_OPTIONS"
          size="small"
          placeholder="运营商"
          style="width: 100px"
          @update:value="set('carrier', $event)"
        />
        <!-- 银行卡：银行 + 卡类型 -->
        <template v-if="toolIs('bankcard')">
          <n-input
            :value="strVal('bank')"
            size="small"
            placeholder="银行(可空)"
            style="width: 140px"
            @update:value="set('bank', $event)"
          />
          <n-select
            :value="strVal('card_type')"
            :options="CARD_TYPE_OPTIONS"
            size="small"
            placeholder="卡类型"
            style="width: 96px"
            @update:value="set('card_type', $event)"
          />
        </template>
        <!-- 姓名：语言 -->
        <n-select
          v-if="toolIs('name')"
          :value="strVal('language')"
          :options="LANGUAGE_OPTIONS"
          size="small"
          placeholder="语言"
          style="width: 90px"
          @update:value="set('language', $event)"
        />
        <!-- 信用代码：登记部门（可空） -->
        <n-input
          v-if="toolIs('credit_code')"
          :value="strVal('department')"
          size="small"
          placeholder="登记部门(可空)"
          style="width: 140px"
          @update:value="set('department', $event)"
        />
        <!-- 纳税人识别号：类型 -->
        <n-select
          v-if="toolIs('taxpayer_id')"
          :value="strVal('taxpayer_type')"
          :options="TAXPAYER_TYPE_OPTIONS"
          size="small"
          placeholder="类型"
          style="width: 96px"
          @update:value="set('taxpayer_type', $event)"
        />
        <!-- 地址：精度 -->
        <n-select
          v-if="toolIs('address')"
          :value="strVal('precision')"
          :options="PRECISION_OPTIONS"
          size="small"
          placeholder="精度"
          style="width: 160px"
          @update:value="set('precision', $event)"
        />
      </div>
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

// TOOL_GEN 工具选项与各工具的可选参数选项
const TOOL_OPTIONS = [
  { label: '身份证号', value: 'idcard' },
  { label: '手机号', value: 'phone' },
  { label: '银行卡号', value: 'bankcard' },
  { label: '姓名', value: 'name' },
  { label: '统一社会信用代码', value: 'credit_code' },
  { label: '纳税人识别号', value: 'taxpayer_id' },
  { label: '地址', value: 'address' },
]
const GENDER_OPTIONS = [
  { label: '随机', value: 'random' },
  { label: '男', value: 'male' },
  { label: '女', value: 'female' },
]
const CARRIER_OPTIONS = [
  { label: '随机', value: 'random' },
  { label: '移动', value: 'mobile' },
  { label: '联通', value: 'unicom' },
  { label: '电信', value: 'telecom' },
]
const CARD_TYPE_OPTIONS = [
  { label: '借记卡', value: 'debit' },
  { label: '信用卡', value: 'credit' },
]
const LANGUAGE_OPTIONS = [
  { label: '中文', value: 'zh' },
  { label: '英文', value: 'en' },
]
const TAXPAYER_TYPE_OPTIONS = [
  { label: '企业', value: 'enterprise' },
  { label: '个人', value: 'personal' },
]
const PRECISION_OPTIONS = [
  { label: '省市区街道+门牌', value: 'full' },
  { label: '省市区', value: 'province_city_district' },
  { label: '省市', value: 'province_city' },
]

/** 当前是否选中某工具（TOOL_GEN 参数区条件渲染用） */
function toolIs(tool: string): boolean {
  return strVal('tool') === tool
}

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
