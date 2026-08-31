<template>
  <!-- 猫咪行走加载动画 -->
  <span class="cat-loader" :style="{ color: color, display: 'inline-flex', alignItems: 'center', gap: '4px' }">
    <span class="cat-walking" style="display: inline-flex">
      <CatMascot pose="walk" :size="size" />
    </span>
    <span v-if="showDots" class="cat-loader-dots">
      <span class="df-dot">·</span><span class="df-dot">·</span><span class="df-dot">·</span>
    </span>
  </span>
</template>

<script setup lang="ts">
import CatMascot from './CatMascot.vue'

// 猫咪加载动画：用于登录按钮 loading、页面加载等场景
withDefaults(
  defineProps<{
    size?: number
    color?: string
    showDots?: boolean
  }>(),
  { size: 22, color: '#a78bfa', showDots: true },
)
</script>

<style scoped>
.cat-loader-dots {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 2px;
}
</style>
