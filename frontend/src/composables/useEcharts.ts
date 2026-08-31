import { onBeforeUnmount, onMounted, type Ref } from 'vue'
import * as echarts from 'echarts'

// ECharts 组合式函数：暗色主题初始化 + 自适应缩放 + 自动销毁
export function useEcharts(elRef: Ref<HTMLElement | null>) {
  let chart: echarts.ECharts | null = null
  let observer: ResizeObserver | null = null

  function init(): void {
    if (!elRef.value || chart) return
    chart = echarts.init(elRef.value, 'dark')
    observer = new ResizeObserver(() => chart?.resize())
    observer.observe(elRef.value)
  }

  function setOption(option: echarts.EChartsOption): void {
    if (!chart) init()
    chart?.setOption(option, true)
  }

  function on(event: string, handler: (params: unknown) => void): void {
    if (!chart) init()
    chart?.on(event, handler)
  }

  onMounted(init)

  onBeforeUnmount(() => {
    observer?.disconnect()
    chart?.dispose()
    chart = null
  })

  return { setOption, on }
}
