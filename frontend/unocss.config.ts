import { defineConfig, presetUno, presetAttributify } from 'unocss'

// UnoCSS 原子化 CSS 配置
export default defineConfig({
  presets: [presetUno(), presetAttributify()],
  theme: {
    colors: {
      primary: '#7c3aed',
      'primary-hover': '#8b5cf6',
      'primary-pressed': '#6d28d9',
      page: '#0d0d0d',
      card: '#1a1a2e',
    },
  },
  shortcuts: {
    // 渐变文本
    'text-gradient': 'bg-gradient-to-r from-[#a78bfa] to-[#60a5fa] bg-clip-text text-transparent',
  },
})
