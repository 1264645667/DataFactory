import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import App from './App.vue'
import router from './router'

// UnoCSS 原子样式 + 全局自定义样式
import 'virtual:uno.css'
import './styles/global.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(naive)  // Naive UI 组件库全局注册（n-* 组件）

app.mount('#app')
