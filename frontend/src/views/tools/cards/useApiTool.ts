import { reactive, ref } from 'vue'

// 工具卡片通用逻辑：参数 / 加载态 / 结果列表 / 历史回填
export function useApiTool<P extends Record<string, unknown>, T>(
  initialParams: P,
  fetcher: (params: P) => Promise<T[]>,
) {
  const params = reactive({ ...initialParams }) as P
  const items = ref<T[]>([])
  const loading = ref(false)

  /** 调用后端生成接口 */
  async function generate(): Promise<void> {
    loading.value = true
    try {
      items.value = await fetcher(params)
    } finally {
      loading.value = false
    }
  }

  /** 历史参数一键回填 */
  function refill(p: Record<string, unknown>): void {
    Object.assign(params, p)
  }

  return { params, items, loading, generate, refill }
}
