<template>
  <!-- 404 页面 -->
  <div class="error-page">
    <CatMascot pose="sleep" :size="160" style="color: #7c6aa8" />
    <h2 class="error-code">404</h2>
    <p class="error-text">页面不存在，小猫也找不到它了～</p>
    <n-button class="gradient-btn" @click="router.push('/overview')">返回首页</n-button>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import CatMascot from '@/components/common/CatMascot.vue'

const router = useRouter()
</script>

<style scoped>
.error-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  background: #0d0d0d;
}
.error-code {
  margin: 0;
  font-size: 42px;
  font-weight: 800;
  color: #a78bfa;
}
.error-text {
  margin: 0 0 10px;
  color: #94a3b8;
}
</style>
