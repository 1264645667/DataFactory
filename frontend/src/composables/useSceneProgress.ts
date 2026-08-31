import { computed } from 'vue'
import { scenesApi } from '@/api/scenes'
import { useSceneProgressStore } from '@/stores/sceneProgress'

// 场景进度组合式函数（轮询在 sceneProgressStore 内统一实现，2s 轮询 + 终态停止）
export function useSceneProgress() {
  const store = useSceneProgressStore()

  /** 提交场景执行：加入进度管理并弹出场景进度面板 */
  function trackScene(sceneExecNo: string, sceneName: string): void {
    store.addScene(sceneExecNo, sceneName)
  }

  /** 强制停止场景 */
  async function abortScene(sceneExecNo: string): Promise<void> {
    await scenesApi.abortExec(sceneExecNo)
    store.updateScene(sceneExecNo, { status: 'aborted' })
  }

  function minimize(sceneExecNo: string): void {
    store.minimize(sceneExecNo)
  }

  function expand(sceneExecNo: string): void {
    store.expand(sceneExecNo)
  }

  function closeTerminal(sceneExecNo: string): void {
    store.removeScene(sceneExecNo)
  }

  const activeCount = computed(() => store.activeCount)

  return { trackScene, abortScene, minimize, expand, closeTerminal, activeCount, store }
}
