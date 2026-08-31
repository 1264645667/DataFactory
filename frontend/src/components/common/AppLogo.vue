<template>
  <!-- 产品 Logo：猫咪图标 + 产品名（收起时只显示猫咪） -->
  <div class="app-logo" :class="{ collapsed }">
    <CatMascot :size="collapsed ? 34 : 40" pose="sit" style="color: #a78bfa; flex-shrink: 0" />
    <div v-if="!collapsed" class="logo-text">
      <span class="logo-name text-gradient">DataForge</span>
      <span class="logo-sub">造数工厂</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import CatMascot from './CatMascot.vue'

withDefaults(defineProps<{ collapsed?: boolean }>(), { collapsed: false })
</script>

<style scoped>
.app-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  overflow: hidden;
  white-space: nowrap;
}
.app-logo.collapsed {
  justify-content: center;
}
.logo-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
.logo-name {
  font-size: 17px;
  font-weight: 700;
}
.logo-sub {
  font-size: 11px;
  color: #64748b;
  letter-spacing: 4px;
}
</style>
