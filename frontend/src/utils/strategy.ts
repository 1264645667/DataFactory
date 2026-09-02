import type { ColumnInfo, StrategyCode } from '@/api/types'

// ============================================================
// 造数策略工具：策略选项、默认策略推断（PRD 4.4.3-A）、参数校验
// ============================================================

export const STRATEGY_LABELS: Record<string, string> = {
  DEFAULT: 'Default（随机）',
  SKIP: '数据库自动填充',
  RANDOM_FIXED_LEN: '随机 X 位生成',
  RANDOM_RANGE_LEN: '随机 X~Y 位生成',
  CUSTOM_VALUE: '自定义输入',
  PICK_FROM_LIST: '从列表随机选取',
  ITERATE_LIST: '按序遍历插入',
  UUID: '随机 UUID',
  SNOWFLAKE: '雪花 ID',
  INCR_FROM: '指定值自增',
  DERIVED: '字段运算派生',
  TOOL_GEN: '快捷工具生成',
  NOW: '当前时间',
  RANDOM_TIME_RANGE: '随机时间段',
  FIXED_TIME: '固定时间',
}

const TIME_TYPES = ['datetime', 'timestamp', 'date', 'time', 'year']
const NUM_TYPES = ['int', 'bigint', 'smallint', 'mediumint', 'tinyint', 'decimal', 'float', 'double']
const CHAR_TYPES = ['varchar', 'char', 'text', 'longtext', 'mediumtext', 'tinytext', 'json', 'enum', 'set']

export function isTimeType(dataType: string): boolean {
  return TIME_TYPES.includes(dataType)
}
export function isNumType(dataType: string): boolean {
  return NUM_TYPES.includes(dataType)
}
export function isCharType(dataType: string): boolean {
  return CHAR_TYPES.includes(dataType)
}
export function isBoolType(column: ColumnInfo): boolean {
  return column.data_type === 'tinyint' && column.column_type.includes('(1)')
}
/** 是否 AUTO_INCREMENT 列 */
export function isAutoIncrement(column: ColumnInfo): boolean {
  return (column.extra ?? '').toLowerCase().includes('auto_increment')
}

export interface StrategyOption {
  label: string
  value: StrategyCode
}

/**
 * 根据字段元数据返回可用的策略选项（PRD 4.4.4）
 */
export function getStrategyOptions(column: ColumnInfo): StrategyOption[] {
  // AUTO_INCREMENT 主键：仅 SKIP
  if (isAutoIncrement(column) && column.is_primary_key) {
    return [{ label: STRATEGY_LABELS.SKIP, value: 'SKIP' }]
  }
  // 主键 / 唯一索引字段：专属策略
  if (column.is_primary_key || column.is_unique) {
    const opts: StrategyOption[] = [{ label: STRATEGY_LABELS.UUID, value: 'UUID' }]
    if (isNumType(column.data_type)) {
      opts.push({ label: STRATEGY_LABELS.SNOWFLAKE, value: 'SNOWFLAKE' })
      opts.push({ label: STRATEGY_LABELS.INCR_FROM, value: 'INCR_FROM' })
    }
    return opts
  }
  // 时间类字段
  if (isTimeType(column.data_type)) {
    return [
      { label: STRATEGY_LABELS.NOW, value: 'NOW' },
      { label: STRATEGY_LABELS.RANDOM_TIME_RANGE, value: 'RANDOM_TIME_RANGE' },
      { label: STRATEGY_LABELS.FIXED_TIME, value: 'FIXED_TIME' },
      { label: STRATEGY_LABELS.CUSTOM_VALUE, value: 'CUSTOM_VALUE' },
    ]
  }
  // 布尔 / 枚举字段
  if (isBoolType(column)) {
    return [
      { label: STRATEGY_LABELS.DEFAULT, value: 'DEFAULT' },
      { label: STRATEGY_LABELS.PICK_FROM_LIST, value: 'PICK_FROM_LIST' },
      { label: STRATEGY_LABELS.CUSTOM_VALUE, value: 'CUSTOM_VALUE' },
    ]
  }
  // 通用字符 / 数字字段
  const opts: StrategyOption[] = [
    { label: STRATEGY_LABELS.DEFAULT, value: 'DEFAULT' },
    { label: STRATEGY_LABELS.RANDOM_FIXED_LEN, value: 'RANDOM_FIXED_LEN' },
    { label: STRATEGY_LABELS.RANDOM_RANGE_LEN, value: 'RANDOM_RANGE_LEN' },
    { label: STRATEGY_LABELS.CUSTOM_VALUE, value: 'CUSTOM_VALUE' },
    { label: STRATEGY_LABELS.PICK_FROM_LIST, value: 'PICK_FROM_LIST' },
    { label: STRATEGY_LABELS.ITERATE_LIST, value: 'ITERATE_LIST' },
    // 指定值自增：数字字段生成纯数字，字符字段可配前缀生成 test0001 这类序列
    { label: STRATEGY_LABELS.INCR_FROM, value: 'INCR_FROM' },
  ]
  // 字符字段支持快捷工具生成（身份证/手机号/银行卡/地址等）
  if (isCharType(column.data_type)) {
    opts.push({ label: STRATEGY_LABELS.TOOL_GEN, value: 'TOOL_GEN' })
  }
  // 数字字段支持字段运算派生（B = A×0.8 / A-5000 等）
  if (isNumType(column.data_type)) {
    opts.push({ label: STRATEGY_LABELS.DERIVED, value: 'DERIVED' })
  }
  return opts
}

/**
 * 前端兜底默认策略推断（PRD 4.4.3-A，后端未返回 suggested_strategy 时使用）
 */
export function inferDefaultStrategy(column: ColumnInfo): { strategy: StrategyCode; params: Record<string, unknown> } {
  const name = column.column_name.toLowerCase()
  const dt = column.data_type
  const maxLen = column.char_max_length

  // 1. 自增主键 → SKIP
  if (column.is_primary_key && isAutoIncrement(column)) return { strategy: 'SKIP', params: {} }
  // 2/3. 非自增主键
  if (column.is_primary_key && isNumType(dt)) return { strategy: 'SNOWFLAKE', params: {} }
  if (column.is_primary_key) return { strategy: 'UUID', params: {} }
  // 4/5. 唯一索引字段
  if (column.is_unique && isNumType(dt)) return { strategy: 'INCR_FROM', params: { start: 1 } }
  if (column.is_unique) return { strategy: 'UUID', params: {} }
  // 6/7/8. 时间字段名规则
  if (/^(created_at|create_time|created_time|updated_at|update_time|updated_time)$/.test(name)) {
    return { strategy: 'NOW', params: {} }
  }
  if (/^(deleted_at|delete_time)$/.test(name)) return { strategy: 'CUSTOM_VALUE', params: { value: null } }
  // 9. 逻辑删除标记
  if (/^(is_deleted|is_del|del_flag)$/.test(name)) return { strategy: 'CUSTOM_VALUE', params: { value: 0 } }
  // 10. 手机号
  if (/(phone|mobile|tel)/.test(name) && (maxLen === 11 || maxLen === 13)) {
    return { strategy: 'RANDOM_FIXED_LEN', params: { length: 11 } }
  }
  // 11. 身份证
  if (/(id_card|identity|id_no)/.test(name) && maxLen === 18) {
    return { strategy: 'RANDOM_FIXED_LEN', params: { length: 18 } }
  }
  // 12. 枚举状态
  if (/(status|state|type|flag)/.test(name) && dt === 'tinyint') {
    return { strategy: 'PICK_FROM_LIST', params: { list: '0\n1' } }
  }
  // 13/14. 时间类
  if (isTimeType(dt)) return { strategy: 'NOW', params: {} }
  // 15. 有默认值
  if (column.column_default != null) return { strategy: 'CUSTOM_VALUE', params: { value: column.column_default } }
  // 16. 兜底
  return { strategy: 'DEFAULT', params: {} }
}

/**
 * 校验策略参数合法性，返回错误提示（null 表示通过），按 PRD 4.4.5
 */
export function validateStrategyParams(
  column: ColumnInfo,
  strategy: StrategyCode,
  params: Record<string, unknown>,
): string | null {
  const maxLen = column.char_max_length
  switch (strategy) {
    case 'RANDOM_FIXED_LEN': {
      const len = Number(params.length)
      if (!Number.isInteger(len) || len < 1) return '位数必须为 ≥ 1 的整数'
      if (maxLen && len > maxLen) return `位数不能超过字段最大长度 ${maxLen}`
      return null
    }
    case 'RANDOM_RANGE_LEN': {
      const min = Number(params.min_length)
      const max = Number(params.max_length)
      if (!Number.isInteger(min) || !Number.isInteger(max) || min < 1 || max < 1) return '位数必须为 ≥ 1 的整数'
      if (min >= max) return '最小位数必须小于最大位数'
      if (maxLen && max > maxLen) return `最大位数不能超过字段最大长度 ${maxLen}`
      return null
    }
    case 'CUSTOM_VALUE': {
      const v = params.value
      if (v == null || v === '') return null // 允许 NULL
      if (isNumType(column.data_type) && column.data_type !== 'decimal' && Number.isNaN(Number(v))) {
        return '该字段为数字类型，请输入数字'
      }
      if (maxLen && String(v).length > maxLen && isCharType(column.data_type)) return '输入内容超过字段最大长度'
      if (column.data_type === 'datetime' || column.data_type === 'timestamp') {
        if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(String(v))) return '时间格式不正确（yyyy-MM-dd HH:mm:ss）'
      }
      if (column.data_type === 'date' && !/^\d{4}-\d{2}-\d{2}$/.test(String(v))) return '日期格式不正确（yyyy-MM-dd）'
      return null
    }
    case 'PICK_FROM_LIST':
    case 'ITERATE_LIST': {
      const raw = String(params.list ?? '').trim()
      if (!raw) return '列表不能为空'
      const items = raw.split('\n').map((s) => s.trim()).filter(Boolean)
      if (items.length === 0) return '列表不能为空'
      if (maxLen && isCharType(column.data_type)) {
        const idx = items.findIndex((s) => s.length > maxLen)
        if (idx >= 0) return `第 ${idx + 1} 行值超过字段最大长度 ${maxLen}`
      }
      if (isNumType(column.data_type)) {
        const idx = items.findIndex((s) => Number.isNaN(Number(s)))
        if (idx >= 0) return `第 ${idx + 1} 行值与字段类型不兼容`
      }
      if (strategy === 'ITERATE_LIST') {
        const rows = Number(params.rows_per_value)
        if (!Number.isInteger(rows) || rows < 1) return '每值条数必须 ≥ 1'
      }
      return null
    }
    case 'INCR_FROM': {
      const start = Number(params.start)
      if (!Number.isInteger(start) || start < 1) return '起始值必须为正整数'
      const padLength = params.pad_length
      if (padLength != null && padLength !== '') {
        const p = Number(padLength)
        if (!Number.isInteger(p) || p < 0) return '补零位数必须为非负整数'
      }
      // 字符字段：前缀 + 数字位长度不能超过字段最大长度
      const prefix = String(params.prefix ?? '')
      if (maxLen && isCharType(column.data_type) && (prefix || padLength)) {
        const estimated = prefix.length + Math.max(Number(padLength) || 0, String(start).length)
        if (estimated > maxLen) return `前缀+数字长度约 ${estimated}，超过字段最大长度 ${maxLen}`
      }
      return null
    }
    case 'DERIVED': {
      const source = params.source_column
      if (!source || typeof source !== 'string') return '请选择源字段'
      const op = String(params.operator ?? '')
      if (!['multiply', 'divide', 'add', 'subtract'].includes(op)) return '请选择运算符'
      const operand = Number(params.operand)
      if (params.operand == null || params.operand === '' || Number.isNaN(operand)) return '请输入操作数（数字）'
      if (op === 'divide' && operand === 0) return '除数不能为 0'
      return null
    }
    case 'TOOL_GEN': {
      const tool = String(params.tool ?? '')
      if (!tool) return '请选择生成工具'
      const supported = ['idcard', 'phone', 'bankcard', 'name', 'credit_code', 'taxpayer_id', 'address']
      if (!supported.includes(tool)) return `未知工具类型：${tool}`
      // 定长工具的值长度不能超过字段最大长度
      const typicalLen: Record<string, number> = { idcard: 18, phone: 11, credit_code: 18, taxpayer_id: 18 }
      const need = typicalLen[tool]
      if (need && maxLen && need > maxLen) return `该工具生成值长度约 ${need}，超过字段最大长度 ${maxLen}`
      return null
    }
    case 'RANDOM_TIME_RANGE': {
      if (!params.range_start || !params.range_end) return '请选择随机时间范围'
      return null
    }
    case 'FIXED_TIME': {
      if (!params.fixed_time) return '请选择固定时间'
      return null
    }
    default:
      return null
  }
}

/** 字段类型 Tag 着色（数字类蓝色、字符类绿色、时间类橙色） */
export function columnTypeColor(dataType: string): string {
  if (isNumType(dataType)) return '#60a5fa'
  if (isCharType(dataType)) return '#34d399'
  if (isTimeType(dataType)) return '#fb923c'
  return '#94a3b8'
}

/**
 * 判断源字段与目标字段类型是否兼容（PRD 4.4.6）
 */
export function typesCompatible(source: ColumnInfo, target: ColumnInfo): boolean {
  const group = (dt: string): string => {
    if (isNumType(dt)) return 'num'
    if (isCharType(dt)) return 'char'
    if (isTimeType(dt)) return 'time'
    return 'other'
  }
  return group(source.data_type) === group(target.data_type)
}
