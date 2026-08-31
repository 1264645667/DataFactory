/// <reference types="vite/client" />

// 允许 TS 识别 .vue 单文件组件导入
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

declare module 'virtual:uno.css'
