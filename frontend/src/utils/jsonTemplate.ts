// JSON 模板解析：把业务 JSON 的叶子标量提取为字段，模板字面量替换为 {字段名} 占位符
// 规则：字符串→带引号 "{field}"；数字/布尔→不带引号 {field}；null 与空数组保持字面量；
// 数组仅首个元素模板化，其余元素原样保留；重名字段自动加序号去重；字段名只保留字母数字下划线

export interface ParsedTemplateField {
  /** 字段名（占位符名） */
  name: string
  /** 推断类型：string / number */
  kind: 'string' | 'number'
  /** 模板中的原始值 */
  value: unknown
}

export interface ParsedTemplate {
  /** 替换为占位符后的模板 */
  template: string
  /** 提取到的字段列表 */
  fields: ParsedTemplateField[]
}

/**
 * 解析 JSON 模板（调用方负责 try/catch JSON.parse 失败场景）。
 * @throws SyntaxError JSON 非法时抛出
 */
export function parseJsonTemplate(raw: string): ParsedTemplate {
  const doc: unknown = JSON.parse(raw)
  const fields: ParsedTemplateField[] = []
  const usedNames = new Set<string>()

  function uniqueName(leaf: string): string {
    const base = leaf.replace(/[^A-Za-z0-9_]/g, '_') || 'field'
    let name = base
    let i = 2
    while (usedNames.has(name)) name = `${base}_${i++}`
    usedNames.add(name)
    return name
  }

  // 当前叶子所属的 key 名（对象遍历时记录，用于字段命名）
  let lastKey = ''

  function walkLeaf(node: unknown): string {
    const name = uniqueName(lastKey || 'field')
    if (typeof node === 'number') {
      fields.push({ name, kind: 'number', value: node })
      return `{${name}}` // 数字不带引号，保持 JSON 数值类型
    }
    if (typeof node === 'boolean') {
      fields.push({ name, kind: 'string', value: String(node) })
      return `{${name}}` // true/false 字面量不带引号
    }
    if (node === null) return 'null'
    fields.push({ name, kind: 'string', value: node })
    return `"{${name}}"` // 字符串带引号
  }

  function walkWithKeys(node: unknown): string {
    if (node !== null && !Array.isArray(node) && typeof node === 'object') {
      const entries = Object.entries(node as Record<string, unknown>).map(([k, v]) => {
        lastKey = k
        const rendered = Array.isArray(v) || (v !== null && typeof v === 'object')
          ? walkContainer(v)
          : walkLeaf(v)
        return `${JSON.stringify(k)}:${rendered}`
      })
      return `{${entries.join(',')}}`
    }
    return walkContainer(node)
  }

  function walkContainer(node: unknown): string {
    if (Array.isArray(node)) {
      if (node.length === 0) return '[]'
      const [first, ...rest] = node
      const parts = [walkWithKeys(first)]
      for (const item of rest) parts.push(JSON.stringify(item))
      return `[${parts.join(',')}]`
    }
    if (node !== null && typeof node === 'object') return walkWithKeys(node)
    return walkLeaf(node)
  }

  const template = walkContainer(doc)
  return { template, fields }
}

/** 模板中的内置占位符（非字段引用） */
export const BUILTIN_TOKEN = /^(incr(:.*)?|uuid(:.*)?|rand:.+|i|task_no|ts|ts_ms)$/

/** 提取模板中引用的字段占位符名（排除内置占位符） */
export function extractFieldRefs(template: string): string[] {
  const refs: string[] = []
  for (const m of template.matchAll(/\{([^{}]+)\}/g)) {
    const token = m[1].trim()
    if (!BUILTIN_TOKEN.test(token) && !refs.includes(token)) refs.push(token)
  }
  return refs
}
