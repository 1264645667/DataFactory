import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { tasksApi } from '@/api/tasks'
import type { TaskProgressData, TaskStatus } from '@/api/types'

// ============================================================
// 多任务并发进度 Store（按架构文档 3.4.1）
// 轮询策略（6.6.4）：默认 2s，按速率动态调整 1s/2s/3s，终态停止
// ============================================================

export interface TaskProgressEntry {
  taskNo: string
  caseName: string
  status: TaskStatus
  progressPercent: number
  insertRate: number
  estimatedRemainSeconds: number | null
  data: TaskProgressData | null
  /** 进度面板是否展开 */
  panelVisible: boolean
  pollingTimer: ReturnType<typeof setTimeout> | null
}

const TERMINAL_STATUS: TaskStatus[] = ['success', 'failed', 'partial_success', 'aborted']

export const useTaskProgressStore = defineStore('taskProgress', () => {
  // Map<taskNo, TaskProgressEntry>
  const tasks = ref<Map<string, TaskProgressEntry>>(new Map())

  /** 所有进行中的任务 */
  const activeTasks = computed(() =>
    [...tasks.value.values()].filter((t) => ['submitted', 'running'].includes(t.status)),
  )

  /** 悬浮球角标数量 */
  const activeCount = computed(() => activeTasks.value.length)

  /** 全部任务的平均进度（悬浮球展示） */
  const averageProgress = computed(() => {
    if (activeTasks.value.length === 0) return 0
    const sum = activeTasks.value.reduce((acc, t) => acc + t.progressPercent, 0)
    return Math.round(sum / activeTasks.value.length)
  })

  /** 最新提交任务的进度 */
  const latestProgress = computed(() => {
    const sorted = [...activeTasks.value].sort((a, b) => b.taskNo.localeCompare(a.taskNo))
    return sorted[0]?.progressPercent ?? 0
  })

  /** 最后活跃的任务（点击悬浮球展开用） */
  const lastActiveTaskNo = ref<string | null>(null)

  function updateTask(taskNo: string, patch: Partial<TaskProgressEntry>): void {
    const entry = tasks.value.get(taskNo)
    if (entry) tasks.value.set(taskNo, { ...entry, ...patch })
  }

  /** 新增任务并开始轮询 */
  function addTask(taskNo: string, caseName: string): void {
    tasks.value.set(taskNo, {
      taskNo,
      caseName,
      status: 'submitted',
      progressPercent: 0,
      insertRate: 0,
      estimatedRemainSeconds: null,
      data: null,
      panelVisible: true, // 新任务默认展开面板
      pollingTimer: null,
    })
    lastActiveTaskNo.value = taskNo
    schedulePoll(taskNo, 1500)
  }

  /** 动态频率轮询：速率越快轮询越频繁 */
  function schedulePoll(taskNo: string, delay: number): void {
    const entry = tasks.value.get(taskNo)
    if (!entry) return
    const timer = setTimeout(() => pollOnce(taskNo), delay)
    updateTask(taskNo, { pollingTimer: timer })
  }

  async function pollOnce(taskNo: string): Promise<void> {
    const entry = tasks.value.get(taskNo)
    if (!entry) return
    try {
      const res = await tasksApi.progress(taskNo)
      const d = res.data
      updateTask(taskNo, {
        status: d.status,
        progressPercent: d.overall?.progress_percent ?? 0,
        insertRate: d.overall?.insert_rate ?? 0,
        estimatedRemainSeconds: d.overall?.estimated_remaining_seconds ?? null,
        data: d,
      })
      // 终态：停止轮询并安排清理
      if (TERMINAL_STATUS.includes(d.status)) {
        stopPolling(taskNo)
        scheduleCleanup(taskNo)
        return
      }
      // 动态调整频率：>10万条/s → 1s；>1万 → 2s；否则 3s
      const rate = d.overall?.insert_rate ?? 0
      const nextDelay = rate > 100_000 ? 1000 : rate > 10_000 ? 2000 : 3000
      schedulePoll(taskNo, nextDelay)
    } catch {
      // 轮询失败（如网络抖动 / Token 过期重登中）：保持当前状态，3s 后重试
      // 重登成功后原请求队列会被唤醒，轮询自动恢复
      schedulePoll(taskNo, 3000)
    }
  }

  function stopPolling(taskNo: string): void {
    const entry = tasks.value.get(taskNo)
    if (entry?.pollingTimer) {
      clearTimeout(entry.pollingTimer)
      updateTask(taskNo, { pollingTimer: null })
    }
  }

  /** 最小化面板（任务继续后台执行） */
  function minimize(taskNo: string): void {
    updateTask(taskNo, { panelVisible: false })
  }

  /** 展开面板 */
  function expand(taskNo: string): void {
    updateTask(taskNo, { panelVisible: true })
    lastActiveTaskNo.value = taskNo
  }

  /** 终态任务 5 分钟后自动从 Map 中清除 */
  function scheduleCleanup(taskNo: string): void {
    setTimeout(() => {
      stopPolling(taskNo)
      tasks.value.delete(taskNo)
    }, 5 * 60 * 1000)
  }

  /** 手动移除任务（终态关闭面板时） */
  function removeTask(taskNo: string): void {
    stopPolling(taskNo)
    tasks.value.delete(taskNo)
  }

  return {
    tasks,
    activeTasks,
    activeCount,
    averageProgress,
    latestProgress,
    lastActiveTaskNo,
    addTask,
    updateTask,
    stopPolling,
    minimize,
    expand,
    scheduleCleanup,
    removeTask,
  }
})
