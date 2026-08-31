// 登录过期事件总线（极简发布订阅）
// request 拦截器收到 1001/1006 时触发 'expired'，ReloginModal 监听并弹出重登框

type Listener = () => void

const listeners = new Set<Listener>()

/** 订阅登录过期事件 */
export function onAuthExpired(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** 触发登录过期事件 */
export function emitAuthExpired(): void {
  listeners.forEach((fn) => fn())
}

// ---------- 用户交互时间追踪（用于区分「页面加载期」与「用户操作期」） ----------
let lastInteractionAt = 0

function trackInteraction(): void {
  lastInteractionAt = Date.now()
}

if (typeof window !== 'undefined') {
  window.addEventListener('pointerdown', trackInteraction, { passive: true })
  window.addEventListener('keydown', trackInteraction, { passive: true })
}

/**
 * 判断当前是否属于「用户操作中」：
 * 最近 8 秒内有用户交互 → 弹出重登 Modal（保留页面状态）；
 * 否则视为页面加载期 → 直接跳转登录页（按 PRD 1.4.3）
 */
export function isUserInteracting(): boolean {
  return Date.now() - lastInteractionAt < 8000
}
