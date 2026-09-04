// 通用格式化工具：数字千分位 / 耗时 / 日期时间

/** 数字千分位格式化，如 1,234,567 */
export function formatNumber(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '-'
  return n.toLocaleString('en-US')
}

/** 速率格式化，如 42,300 条/秒 */
export function formatRate(n: number | null | undefined): string {
  if (n == null || n <= 0) return '-'
  return `${formatNumber(Math.round(n))} 条/秒`
}

/** 耗时格式化：秒 → 「2m 34s」「1h 5m」 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds) || seconds < 0) return '-'
  const s = Math.floor(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rs = s % 60
  if (m < 60) return rs > 0 ? `${m}m ${rs}s` : `${m}m`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm > 0 ? `${h}h ${rm}m` : `${h}h`
}

/** 毫秒耗时格式化 */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms}ms`
  return formatDuration(ms / 1000)
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`
}

/** 日期时间格式化：yyyy-MM-dd HH:mm:ss */
export function formatDateTime(input: string | number | Date | null | undefined): string {
  if (!input) return '-'
  const d = new Date(input)
  if (Number.isNaN(d.getTime())) return '-'
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
}

/** 日期格式化：yyyy-MM-dd HH:mm（分钟级） */
export function formatDateTimeMin(input: string | number | Date | null | undefined): string {
  if (!input) return '-'
  const d = new Date(input)
  if (Number.isNaN(d.getTime())) return '-'
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/** 纯日期：yyyy-MM-dd */
export function formatDate(input: string | number | Date | null | undefined): string {
  if (!input) return '-'
  const d = new Date(input)
  if (Number.isNaN(d.getTime())) return '-'
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

/** 文件导出时间戳：yyyyMMddHHmmss */
export function formatFileTimestamp(d: Date = new Date()): string {
  return `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}${pad2(d.getHours())}${pad2(d.getMinutes())}${pad2(d.getSeconds())}`
}

/** 百分比格式化，保留一位小数 */
export function formatPercent(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '-'
  return `${n.toFixed(1)}%`
}

/** 复制文本到剪贴板（带降级方案） */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // 降级：使用隐藏 textarea
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      return true
    } catch {
      return false
    } finally {
      document.body.removeChild(ta)
    }
  }
}

/** 复制单条数据并弹出轻提示（工具卡片结果项点击复制用） */
export async function copyItem(text: string): Promise<void> {
  const ok = await copyText(text)
  if (ok) {
    window.$message.success(`已复制：${text.length > 40 ? text.slice(0, 40) + '…' : text}`)
  } else {
    window.$message.error('复制失败')
  }
}
