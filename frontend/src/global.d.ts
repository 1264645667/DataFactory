import type { DialogProviderInst, MessageProviderInst } from 'naive-ui'

// 全局挂载 Naive UI 的 message / dialog 实例（在 ReloginModal 中赋值）
declare global {
  interface Window {
    $message: MessageProviderInst
    $dialog: DialogProviderInst
  }
}

export {}
