import axios, { AxiosError, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import type { ApiResponse } from '@/api/types'
import { getErrorMessage } from './errorCode'
import { emitAuthExpired, isUserInteracting } from './authEvents'

// ============================================================
// Axios 封装：统一注入 Token、统一处理 code != 0、登录过期重试
// ============================================================

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
  // 数组参数序列化为重复 key（status=1&status=2），FastAPI list 参数要求此格式；
  // axios 默认的 status[]=1 形式 FastAPI 收不到，会导致多选筛选静默失效
  paramsSerializer: (params) => {
    const search = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value == null) return
      if (Array.isArray(value)) {
        value.forEach((v) => search.append(key, String(v)))
      } else {
        search.append(key, String(value))
      }
    })
    return search.toString()
  },
})

// ---------- 请求拦截：注入 JWT Token ----------
request.interceptors.request.use((config) => {
  const token = localStorage.getItem('df_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ---------- 登录过期处理：等待重登结果 ----------
// 重登中标记，避免多个并发请求重复弹窗
let reauthWaiting: Array<(ok: boolean) => void> = []

/**
 * 处理 1001/1006：
 * - 用户操作期 → 弹出重登 Modal，返回 Promise 等待重登结果
 * - 页面加载期 → 清空 Token 并直接跳转登录页
 */
function handleAuthExpired(): Promise<boolean> {
  // 页面加载期或已在登录页 → 直接跳转
  if (!isUserInteracting() || window.location.pathname === '/login') {
    localStorage.removeItem('df_token')
    if (window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
    return Promise.resolve(false)
  }
  emitAuthExpired()
  return new Promise<boolean>((resolve) => {
    reauthWaiting.push(resolve)
  })
}

/** 重登流程结束后由 ReloginModal 调用：唤醒所有等待中的请求 */
export function settleReauth(success: boolean): void {
  const waiters = reauthWaiting
  reauthWaiting = []
  waiters.forEach((resolve) => resolve(success))
}

/** 判断是否登录过期错误码 */
function isAuthExpiredCode(code: number | undefined): boolean {
  return code === 1001 || code === 1006
}

// ---------- 响应拦截：统一处理业务错误码 ----------
request.interceptors.response.use(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async (res: AxiosResponse<ApiResponse>): Promise<any> => {
    const body = res.data
    // 非统一响应格式（如健康检查）直接透传
    if (!body || typeof body.code !== 'number') {
      return body
    }
    // 成功
    if (body.code === 0) {
      return body
    }
    // 登录过期：弹重登 Modal 或跳转登录页，成功后重试原请求
    if (isAuthExpiredCode(body.code)) {
      const ok = await handleAuthExpired()
      if (ok) {
        return request.request(res.config)
      }
      return Promise.reject(new Error('登录已过期'))
    }
    // 其他业务错误：弹出中文提示
    const msg = getErrorMessage(body.code, body.message)
    window.$message?.error(msg)
    return Promise.reject(Object.assign(new Error(msg), { code: body.code, data: body }))
  },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async (error: AxiosError<ApiResponse>): Promise<any> => {
    const code = error.response?.data?.code
    // HTTP 层 401 或业务 1001/1006
    if (error.response?.status === 401 || isAuthExpiredCode(code)) {
      const ok = await handleAuthExpired()
      if (ok && error.config) {
        return request.request(error.config as AxiosRequestConfig)
      }
      return Promise.reject(error)
    }
    const msg = getErrorMessage(code, error.response?.data?.message)
    window.$message?.error(msg)
    return Promise.reject(Object.assign(error, { code }))
  },
)

export default request
