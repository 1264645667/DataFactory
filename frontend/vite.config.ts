import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import UnoCSS from 'unocss/vite'
import { fileURLToPath, URL } from 'node:url'

// Vite 配置：开发环境将 /api 代理到本地后端 8000 端口
export default defineConfig({
  plugins: [vue(), UnoCSS()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        // 拆分大依赖，优化首屏加载
        manualChunks: {
          echarts: ['echarts'],
          naive: ['naive-ui'],
          vueflow: ['@vue-flow/core', '@vue-flow/background', '@vue-flow/controls'],
        },
      },
    },
  },
})
