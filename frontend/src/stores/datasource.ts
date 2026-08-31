import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { datasourceApi } from '@/api/datasource'
import type { Datasource } from '@/api/types'

// 数据源 Store：列表缓存 + 当前选中数据源
export const useDatasourceStore = defineStore('datasource', () => {
  const list = ref<Datasource[]>([])
  const loading = ref(false)
  /** 当前选中数据源 ID（造数引擎使用），持久化到 localStorage */
  const currentId = ref<number | null>(
    localStorage.getItem('df_current_ds') ? Number(localStorage.getItem('df_current_ds')) : null,
  )

  const current = computed(() => list.value.find((d) => d.id === currentId.value) ?? null)

  /** 拉取数据源列表 */
  async function fetchList(): Promise<void> {
    loading.value = true
    try {
      const res = await datasourceApi.list()
      list.value = res.data
    } finally {
      loading.value = false
    }
  }

  /** 切换当前数据源 */
  function setCurrent(id: number | null): void {
    currentId.value = id
    if (id != null) {
      localStorage.setItem('df_current_ds', String(id))
    } else {
      localStorage.removeItem('df_current_ds')
    }
  }

  /** 按用户默认数据源自动选中（无默认则取第一个） */
  function autoSelect(defaultId: number | null | undefined): void {
    if (currentId.value && list.value.some((d) => d.id === currentId.value)) return
    const target =
      (defaultId && list.value.find((d) => d.id === defaultId)) || list.value[0] || null
    setCurrent(target ? target.id : null)
  }

  return { list, loading, currentId, current, fetchList, setCurrent, autoSelect }
})
