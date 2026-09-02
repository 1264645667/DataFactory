<template>
  <!-- 注册页与登录页一致布局，右侧替换为注册表单 -->
  <div class="register-page">
    <!-- 左侧插画区 -->
    <div class="register-art">
      <div class="art-cat">
        <CatMascot :size="280" pose="sit" style="color: rgba(196, 181, 253, 0.85)" />
      </div>
      <p class="art-slogan">DataForge · 让造数变成一件优雅的事</p>
    </div>

    <!-- 右侧注册卡片 -->
    <div class="register-side">
      <!-- 提交成功提示页 -->
      <div v-if="submitted" class="glass-card register-card success-card">
        <CatMascot :size="140" pose="wait" style="color: #a78bfa" />
        <h2 class="success-title">申请已提交！</h2>
        <p class="success-text">你的账号正在等待管理员审批<br />审批通过后你将收到系统消息通知</p>
        <n-button class="gradient-btn" block @click="goLogin">返回登录页</n-button>
      </div>

      <!-- 注册表单 -->
      <div v-else class="glass-card register-card">
        <div class="register-logo"><AppLogo /></div>
        <n-form ref="formRef" :model="form" :rules="rules" size="large" label-placement="top">
          <n-form-item path="username" label="用户名">
            <n-input v-model:value="form.username" placeholder="4~20 位，仅字母/数字/下划线" />
            <template #feedback>用户名将作为登录账号，创建后不可修改</template>
          </n-form-item>
          <n-form-item path="password" label="密码">
            <n-input v-model:value="form.password" type="password" show-password-on="click" placeholder="≥8 位，须含数字和字母" />
            <!-- 密码强度指示条 -->
            <div class="strength-bar">
              <div class="strength-track">
                <div class="strength-fill" :class="strengthClass" :style="{ width: strengthWidth }" />
              </div>
              <span class="strength-text">{{ strengthText }}</span>
            </div>
          </n-form-item>
          <n-form-item path="confirmPassword" label="确认密码">
            <n-input v-model:value="form.confirmPassword" type="password" show-password-on="click" placeholder="再次输入密码" />
          </n-form-item>
          <n-form-item path="realName" label="真实姓名">
            <n-input v-model:value="form.realName" placeholder="2~20 字" />
            <template #feedback>用于团队识别，请填写真实姓名</template>
          </n-form-item>
          <n-form-item path="groupType" label="申请分组">
            <n-radio-group v-model:value="form.groupType">
              <n-radio :value="1">销项组</n-radio>
              <n-radio :value="2">申报组</n-radio>
            </n-radio-group>
            <template #feedback>请根据你所在业务组选择，审批后不可自行修改</template>
          </n-form-item>
          <n-form-item path="apply_reason" label="申请理由（选填）">
            <n-input
              v-model:value="form.apply_reason"
              type="textarea"
              :rows="2"
              maxlength="200"
              show-count
              placeholder="选填，说明申请目的有助于加快审批"
            />
          </n-form-item>
          <n-button class="gradient-btn" block size="large" :loading="loading" @click="handleSubmit">
            提交申请
          </n-button>
        </n-form>
        <div class="register-links">
          <router-link to="/login" class="link">返回登录</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { FormInst, FormRules } from 'naive-ui'
import AppLogo from '@/components/common/AppLogo.vue'
import CatMascot from '@/components/common/CatMascot.vue'
import { authApi } from '@/api/auth'

const router = useRouter()

const formRef = ref<FormInst | null>(null)
const loading = ref(false)
const submitted = ref(false)

const form = reactive({
  username: '',
  password: '',
  confirmPassword: '',
  realName: '',
  groupType: 1 as 1 | 2,
  apply_reason: '',
})

// 密码强度：弱（仅满足长度）/ 中（数字+字母）/ 强（含特殊字符或长度 ≥12）
const strength = computed(() => {
  const p = form.password
  if (!p) return 0
  const hasLetter = /[a-zA-Z]/.test(p)
  const hasDigit = /\d/.test(p)
  const hasSpecial = /[^a-zA-Z0-9]/.test(p)
  if (p.length >= 12 && hasLetter && hasDigit) return 3
  if (p.length >= 8 && hasLetter && hasDigit) return hasSpecial ? 3 : 2
  if (p.length >= 6) return 1
  return p.length > 0 ? 1 : 0
})
const strengthWidth = computed(() => ['0%', '33%', '66%', '100%'][strength.value])
const strengthText = computed(() => ['', '弱', '中', '强'][strength.value])
const strengthClass = computed(() => ['', 's-weak', 's-mid', 's-strong'][strength.value])

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: ['input', 'blur'] },
    { pattern: /^[a-zA-Z0-9_]{4,20}$/, message: '4~20 位，仅字母/数字/下划线', trigger: ['input', 'blur'] },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: ['input', 'blur'] },
    { pattern: /^(?=.*[a-zA-Z])(?=.*\d).{8,}$/, message: '至少 8 位且包含数字和字母', trigger: ['input', 'blur'] },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: ['input', 'blur'] },
    {
      validator: (_r, v) => v === form.password,
      message: '两次输入的密码不一致',
      trigger: ['input', 'blur'],
    },
  ],
  realName: [
    { required: true, message: '请输入真实姓名', trigger: ['input', 'blur'] },
    { min: 2, max: 20, message: '2~20 字', trigger: ['input', 'blur'] },
  ],
  groupType: [{ required: true, type: 'number', message: '请选择申请分组', trigger: ['change'] }],
}

async function handleSubmit(): Promise<void> {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    await authApi.register({
      username: form.username,
      password: form.password,
      real_name: form.realName,
      group_type: form.groupType,
      apply_reason: form.apply_reason || undefined,
    })
    submitted.value = true
  } catch {
    // 1105 等错误提示由拦截器统一弹出
  } finally {
    loading.value = false
  }
}

function goLogin(): void {
  router.push('/login')
}
</script>

<style scoped>
.register-page {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.register-art {
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
.register-side {
  width: 40%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0d0d0d;
  padding: 24px;
  overflow-y: auto;
}
.register-card {
  width: 100%;
  max-width: 420px;
  padding: 32px 36px;
}
.register-logo {
  display: flex;
  justify-content: center;
  margin-bottom: 20px;
}
.strength-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  width: 100%;
}
.strength-track {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: rgba(148, 163, 184, 0.15);
  overflow: hidden;
}
.strength-fill {
  height: 100%;
  transition: width 0.25s ease;
}
.strength-fill.s-weak { background: #ef4444; }
.strength-fill.s-mid { background: #f59e0b; }
.strength-fill.s-strong { background: #22c55e; }
.strength-text {
  font-size: 11px;
  color: #64748b;
  width: 20px;
}
.register-links {
  margin-top: 14px;
  text-align: center;
  font-size: 13px;
}
.link {
  color: #a78bfa;
  text-decoration: none;
}
.link:hover {
  text-decoration: underline;
}
.success-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 14px;
  padding: 48px 36px;
}
.success-title {
  margin: 0;
  font-size: 20px;
  color: #e2e8f0;
}
.success-text {
  margin: 0 0 12px;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.9;
}
</style>
