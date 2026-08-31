import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { scenesApi } from '@/api/scenes'
import type { SceneProgressData, SceneStatus } from '@/api/types'

// ============================================================
// 场景任务进度 Store（按架构文档 3.4.2，与 taskProgressStore 对称）
// ============================================================

export interface SceneProgressEntry {
  sceneExecNo: string
  sceneName: string
  status: SceneStatus
  nodeCount: number
  completedNodes: number
  overallPercent: number
  data: SceneProgressData | null
  panelVisible: boolean
  pollingTimer: ReturnType<typeof setTimeout> | null
}

const TERMINAL_STATUS: SceneStatus[] = ['success', 'failed', 'partial_success', 'aborted']

export const useSceneProgressStore = defineStore('sceneProgress', () => {
  const scenes = ref<Map<string, SceneProgressEntry>>(new Map())

  const activeScenes = computed(() =>
    [...scenes.value.values()].filter((s) => ['submitted', 'running'].includes(s.status)),
  )

  const activeCount = computed(() => activeScenes.value.length)

  const averageProgress = computed(() => {
    if (activeScenes.value.length === 0) return 0
    const sum = activeScenes.value.reduce((acc, s) => acc + s.overallPercent, 0)
    return Math.round(sum / activeScenes.value.length)
  })

  const latestProgress = computed(() => {
    const sorted = [...activeScenes.value].sort((a, b) => b.sceneExecNo.localeCompare(a.sceneExecNo))
    return sorted[0]?.overallPercent ?? 0
  })

  const lastActiveExecNo = ref<string | null>(null)

  function updateScene(no: string, patch: Partial<SceneProgressEntry>): void {
    const entry = scenes.value.get(no)
    if (entry) scenes.value.set(no, { ...entry, ...patch })
  }

  /** 新增场景执行任务并开始轮询 */
  function addScene(sceneExecNo: string, sceneName: string): void {
    scenes.value.set(sceneExecNo, {
      sceneExecNo,
      sceneName,
      status: 'submitted',
      nodeCount: 0,
      completedNodes: 0,
      overallPercent: 0,
      data: null,
      panelVisible: true,
      pollingTimer: null,
    })
    lastActiveExecNo.value = sceneExecNo
    schedulePoll(sceneExecNo, 1500)
  }

  function schedulePoll(no: string, delay: number): void {
    const entry = scenes.value.get(no)
    if (!entry) return
    const timer = setTimeout(() => pollOnce(no), delay)
    updateScene(no, { pollingTimer: timer })
  }

  async function pollOnce(no: string): Promise<void> {
    const entry = scenes.value.get(no)
    if (!entry) return
    try {
      const res = await scenesApi.execProgress(no)
      const d = res.data
      const o = d.overall
      const doneNodes = (o?.success_count ?? 0) + (o?.fail_count ?? 0)
      const percent =
        o && o.target_rows > 0 ? Math.round((o.success_rows / o.target_rows) * 100) : 0
      updateScene(no, {
        status: d.status,
        nodeCount: o?.node_count ?? 0,
        completedNodes: doneNodes,
        overallPercent: percent,
        data: d,
      })
      if (TERMINAL_STATUS.includes(d.status)) {
        stopPolling(no)
        scheduleCleanup(no)
        return
      }
      schedulePoll(no, 2000)
    } catch {
      // 轮询失败静默重试（重登成功后自动恢复）
      schedulePoll(no, 3000)
    }
  }

  function stopPolling(no: string): void {
    const entry = scenes.value.get(no)
    if (entry?.pollingTimer) {
      clearTimeout(entry.pollingTimer)
      updateScene(no, { pollingTimer: null })
    }
  }

  function minimize(no: string): void {
    updateScene(no, { panelVisible: false })
  }

  function expand(no: string): void {
    updateScene(no, { panelVisible: true })
    lastActiveExecNo.value = no
  }

  function scheduleCleanup(no: string): void {
    setTimeout(() => {
      stopPolling(no)
      scenes.value.delete(no)
    }, 5 * 60 * 1000)
  }

  function removeScene(no: string): void {
    stopPolling(no)
    scenes.value.delete(no)
  }

  return {
    scenes,
    activeScenes,
    activeCount,
    averageProgress,
    latestProgress,
    lastActiveExecNo,
    addScene,
    updateScene,
    stopPolling,
    minimize,
    expand,
    scheduleCleanup,
    removeScene,
  }
})
