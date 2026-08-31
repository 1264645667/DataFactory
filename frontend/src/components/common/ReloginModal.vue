<template>
  <!-- 登录过期重登弹窗（PRD 1.4.3）：用户名只读，仅输入密码，成功后重试原请求 -->
  <n-modal
    :show="visible"
    :mask-closable="false"
    :closable="false"
    preset="card"
    style="width: 420px"
    title="登录已过期"
  >
    <div class="relogin-body">
      <p class="relogin-tip">
        当前账号（<span class="relogin-username">{{ authStore.user?.username }}</span
        >）的登录已过期，请重新输入密码以继续操作。
      </p>
      <n-form ref="formRef" :model="form" :rules="rules" @submit.prevent="handleRelogin">
        <n-form-item path="password" label="密码" :show-label="false">
          <n-input
            v-model:value="form.password"
            type="password"
            show-password-on="click"
            placeholder="请输入密码"
            size="large"
            :disabled="loading"
            @keydown.enter.prevent="handleRelogin"
          />
        </n-form-item>
      </n-form>
    </div>
    <template #footer>
      <div class="relogin-footer">
        <n-button quaternary :disabled="loading" @click="handleCancel">取消并跳转登录页</n-button>
        <n-button class="gradient-btn" :loading="loading" @click="handleRelogin">重新登录</n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useDialog, useMessage, type FormInst, type FormRules } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { onAuthExpired } from '@/utils/authEvents'
import { settleReauth } from '@/utils/request'

const authStore = useAuthStore()
const router = useRouter()

// 在 Provider 子组件中挂载全局消息 / 对话框 API
window.$message = useMessage()
window.$dialog = useDialog()

const visible = ref(false)
const loading = ref(false)
const formRef = ref<FormInst | null>(null)
const form = reactive({ password: '' })

const rules: FormRules = {
  password: [{ required: true, message: '请输入密码', trigger: ['input', 'blur'] }],
}

let off: (() => void) | null = null

onMounted(() => {
  // 订阅登录过期事件（request 拦截器触发）
  off = onAuthExpired(() => {
    if (!visible.value) {
      form.password = ''
      visible.value = true
    }
  })
})

onBeforeUnmount(() => off?.())

/** 重新登录：成功后唤醒等待中的原请求队列 */
async function handleRelogin(): Promise<void> {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    await authStore.relogin(form.password)
    visible.value = false
    window.$message.success('已重新登录，继续为您执行操作')
    settleReauth(true) // 唤醒原请求重试
  } catch {
    // 错误提示已由拦截器弹出
  } finally {
    loading.value = false
  }
}

/** 取消：清除 Token 跳转登录页，当前页面操作丢失 */
async function handleCancel(): Promise<void> {
  visible.value = false
  settleReauth(false)
  await authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.relogin-tip {
  margin: 0 0 16px;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.7;
}
.relogin-username {
  color: #a78bfa;
  font-weight: 600;
}
.relogin-footer {
  display: flex;
  justify-content: space-between;
}
</style>
