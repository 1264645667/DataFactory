import { computed } from 'vue'
import { tasksApi } from '@/api/tasks'
import { useTaskProgressStore } from '@/stores/taskProgress'

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

  return { trackTask, abortTask, minimize, expand, closeTerminal, activeCount, store }
}
