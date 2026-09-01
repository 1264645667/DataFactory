<template>
  <!-- 登录页（PRD 2.5）：左 60% 插画区 + 右 40% 玻璃态登录卡片 -->
  <div class="login-page">
    <!-- 左侧插画区 -->
    <div class="login-art">
      <div class="art-cat">
        <CatMascot :size="280" pose="sit" style="color: rgba(196, 181, 253, 0.85)" />
      </div>
      <p class="art-slogan">DataForge · 让造数变成一件优雅的事</p>
    </div>

    <!-- 右侧登录卡片 -->
    <div class="login-side">
      <div class="glass-card login-card" :class="{ 'df-shake': shaking }">
        <div class="login-logo">
          <AppLogo />
        </div>
        <n-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent="handleLogin">
          <n-form-item path="username" :show-label="false">
            <n-input v-model:value="form.username" placeholder="用户名" :disabled="loading">
              <template #prefix>
                <n-icon><PawOutline /></n-icon>
              </template>
            </n-input>
          </n-form-item>
          <n-form-item path="password" :show-label="false">
            <n-input
              v-model:value="form.password"
              type="password"
              show-password-on="click"
              placeholder="密码"
              :disabled="loading"
              @keydown.enter.prevent="handleLogin"
              class="custom-input"
            />
          </n-form-item>
          <n-button class="gradient-btn login-btn" size="large" block :loading="loading" attr-type="submit">
            <template v-if="loading"><CatLoader :size="18" color="#fff" :show-dots="false" /></template>
            <template v-else>登 录</template>
          </n-button>
        </n-form>
        <div class="login-links">
          <span class="dim">没有账号？</span>
          <router-link to="/register" class="link">申请注册</router-link>
        </div>
      </div>
    </div>

    <!-- 登录成功全屏渐出过渡 -->
    <transition name="fullscreen-fade">
      <div v-if="successOverlay" class="success-overlay">
        <CatMascot :size="160" pose="celebrate" style="color: #a78bfa" />
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PawOutline } from '@vicons/ionicons5'
import type { FormInst, FormRules } from 'naive-ui'
import AppLogo from '@/components/common/AppLogo.vue'
import CatMascot from '@/components/common/CatMascot.vue'
import CatLoader from '@/components/common/CatLoader.vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref<FormInst | null>(null)
const form = reactive({ username: '', password: '' })
const loading = ref(false)
const shaking = ref(false)
const successOverlay = ref(false)

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: ['input', 'blur'] }],
  password: [{ required: true, message: '请输入密码', trigger: ['input', 'blur'] }],
}

/** 登录：失败时输入框红色抖动，成功时全屏渐出过渡到主界面 */
async function handleLogin(): Promise<void> {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    await authStore.login(form.username, form.password)
    // 成功：全屏渐出过渡后跳转
    successOverlay.value = true
    setTimeout(() => {
      const redirect = (route.query.redirect as string) || '/overview'
      router.push(redirect)
    }, 600)
  } catch {
    // 失败：抖动动效（错误提示已由拦截器弹出，含 1103/1104/1005 等）
    shaking.value = true
    setTimeout(() => (shaking.value = false), 450)
  } finally {
    loading.value = false
  }
}
</script>
<style>
  /* 覆盖自动填充样式 */
.custom-input .n-input__input-el:-webkit-autofill {
  -webkit-box-shadow: 0 0 0 1000px #f0f2f5 inset !important; /* 使用内阴影覆盖背景色 */
  -webkit-text-fill-color: #333 !important; /* 同时设置文字颜色 */
}


.custom-input .n-input__input-el {
  --n-color: #e6f7ff; /* 默认背景色 */
  --n-color-focus: #bae7ff; /* 聚焦背景色 */
}
</style>

<style scoped>
.login-page {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
/* 左侧 60% 插画区：深渐变背景 */
.login-art {
  width: 60%;
  background: linear-gradient(160deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 30px;
}
.art-cat {
  filter: drop-shadow(0 0 30px rgba(124, 58, 237, 0.35));
}
.art-slogan {
  color: rgba(226, 232, 240, 0.7);
  font-size: 16px;
  letter-spacing: 3px;
}
/* 右侧 40% 表单区 */
.login-side {
  width: 40%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0d0d0d;
  padding: 24px;
}
.login-card {
  width: 100%;
  max-width: 400px;
  padding: 40px 36px;
}
.login-logo {
  display: flex;
  justify-content: center;
  margin-bottom: 32px;
}
.login-btn {
  margin-top: 6px;
  height: 44px;
  font-size: 15px;
  letter-spacing: 6px;
}
.login-links {
  margin-top: 18px;
  text-align: center;
  font-size: 13px;
}
.dim {
  color: #64748b;
}
.link {
  color: #a78bfa;
  text-decoration: none;
}
.link:hover {
  text-decoration: underline;
}
.success-overlay {
  position: fixed;
  inset: 0;
  background: #0d0d0d;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

</style>
