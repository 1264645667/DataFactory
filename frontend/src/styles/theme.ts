import type { GlobalThemeOverrides } from 'naive-ui'

// Naive UI 暗色主题覆盖（按架构文档 3.3）
export const darkThemeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#7c3aed', // 主色：紫色
    primaryColorHover: '#8b5cf6',
    primaryColorPressed: '#6d28d9',
    primaryColorSuppl: '#8b5cf6',
    bodyColor: '#0d0d0d', // 页面背景：极深黑
    cardColor: '#1a1a2e', // 卡片背景
    modalColor: '#1a1a2e',
    popoverColor: '#232340',
    borderColor: 'rgba(124,58,237,0.3)', // 边框：紫色半透明
    textColorBase: '#e2e8f0',
    textColor1: '#f1f5f9',
    textColor2: '#94a3b8',
    textColor3: '#64748b',
    fontFamily: '"Inter", "PingFang SC", "Source Han Sans SC", "Microsoft YaHei", sans-serif',
    borderRadius: '8px',
  },
  Card: {
    color: 'rgba(26,26,46,0.72)',
    borderColor: 'rgba(124,58,237,0.22)',
  },
  DataTable: {
    thColor: 'rgba(124,58,237,0.08)',
    tdColor: 'transparent',
    borderColor: 'rgba(148,163,184,0.12)',
    thTextColor: '#94a3b8',
  },
  Button: {
    // 主按钮渐变效果在 global.css 的 .gradient-btn 中额外处理
    textColorPrimary: '#ffffff',
  },
  Dialog: {
    color: '#1a1a2e',
  },
  Tag: {
    borderRadius: '4px',
  },
  Pagination: {
    itemColorActive: 'rgba(124,58,237,0.16)',
  },
}
