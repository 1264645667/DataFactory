import { computed } from 'vue'
import { tasksApi } from '@/api/tasks'
import { useTaskProgressStore } from '@/stores/taskProgress'
import type { TaskProgressData } from '@/api/types'

// ============================================================
// 任务进度组合式函数（轮询逻辑在 taskProgressStore 内统一实现：
// 默认 2s，按插入速率动态调整 1s/2s/3s，终态自动停止）
// ============================================================

export function useTaskProgress() {
  const store = useTaskProgressStore()

  /** 提交新任务：加入进度管理并弹出进度面板 */
  function trackTask(taskNo: string, caseName: string): void {
    store.addTask(taskNo, caseName)
  }

  /** 强制停止任务（二次确认后调用） */
  async function abortTask(taskNo: string): Promise<void> {
    await tasksApi.abort(taskNo)
    // 停止后轮询会拉到终态，这里先更新本地状态避免延迟
    store.updateTask(taskNo, { status: 'aborted' })
  }

  function minimize(taskNo: string): void {
    store.minimize(taskNo)
  }

  function expand(taskNo: string): void {
    store.expand(taskNo)
  }

  function closeTerminal(taskNo: string): void {
    store.removeTask(taskNo)
  }

  const activeCount = computed(() => store.activeCount)

  /** 是否遍历任务：total_rounds 非空即遍历模式（遍历信息平铺在进度响应上） */
  function isIterateTask(data: TaskProgressData | null): boolean {
    return data?.total_rounds != null
  }

  /** 遍历进度信息（从平铺字段 current_round/total_rounds/current_drive_value 提取） */
  function iterateProgress(data: TaskProgressData | null): {
    current_round: number
    total_rounds: number
    current_value: string | null
  } | null {
    if (data == null || data.total_rounds == null) return null
    return {
      current_round: data.current_round ?? 0,
      total_rounds: data.total_rounds,
      current_value: data.current_drive_value ?? null,
    }
  }

  return { trackTask, abortTask, minimize, expand, closeTerminal, activeCount, store, isIterateTask, iterateProgress }
}
