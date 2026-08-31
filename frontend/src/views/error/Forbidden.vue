<template>
  <!-- 403 无权限页面 -->
  <div class="error-page">
    <CatMascot pose="wait" :size="160" style="color: #7c6aa8" />
    <h2 class="error-code">403</h2>
    <p class="error-text">没有访问该页面的权限，请联系管理员开通</p>
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
  height: 100%;
  min-height: 60vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
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
