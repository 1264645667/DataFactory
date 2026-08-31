import { computed, onBeforeUnmount, ref } from 'vue'
import { datasourceApi } from '@/api/datasource'
import { useAuthStore } from '@/stores/auth'
import { useDatasourceStore } from '@/stores/datasource'

// 数据源组合式函数：列表加载、自动选中默认数据源、心跳状态轮询（30s）
export function useDatasource() {
  const dsStore = useDatasourceStore()
  const authStore = useAuthStore()

  const loading = computed(() => dsStore.loading)
  const list = computed(() => dsStore.list)
  const current = computed(() => dsStore.current)
  const currentId = computed(() => dsStore.currentId)

  /** 加载列表并按用户默认数据源自动选中 */
  async function init(): Promise<void> {
    await dsStore.fetchList()
    dsStore.autoSelect(authStore.user?.default_datasource_id)
  }

  function select(id: number): void {
    dsStore.setCurrent(id)
  }

  // ---------- 心跳状态轮询（每 30 秒） ----------
  const statusTimer = ref<ReturnType<typeof setInterval> | null>(null)

  async function refreshStatus(id: number): Promise<void> {
    try {
      const res = await datasourceApi.status(id)
      const target = dsStore.list.find((d) => d.id === id)
      if (target) {
        target.status = res.data.status
        target.cache_status = res.data.cache_status
        target.last_sync_at = res.data.last_sync_at
      }
    } catch {
      // 心跳失败静默
    }
  }

  function startStatusPolling(id: number): void {
    stopStatusPolling()
    statusTimer.value = setInterval(() => refreshStatus(id), 30_000)
  }

  function stopStatusPolling(): void {
    if (statusTimer.value) {
      clearInterval(statusTimer.value)
      statusTimer.value = null
    }
  }

  onBeforeUnmount(stopStatusPolling)

  return { list, loading, current, currentId, init, select, refreshStatus, startStatusPolling, stopStatusPolling }
}
