<template>
  <!-- 个人中心改密码 / 默认数据源 / 猫咪头像 / 操作日志 -->
  <div class="profile-page">
    <div class="profile-grid">
      <!-- 修改密码 -->
      <div class="gradient-border-card profile-card">
        <h4 class="card-title">修改密码</h4>
        <n-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-placement="top" size="small">
          <n-form-item path="oldPassword" label="原密码">
            <n-input v-model:value="pwdForm.oldPassword" type="password" show-password-on="click" />
          </n-form-item>
          <n-form-item path="newPassword" label="新密码">
            <n-input v-model:value="pwdForm.newPassword" type="password" show-password-on="click" placeholder="≥8 位，含数字和字母" />
          </n-form-item>
          <n-form-item path="confirmPassword" label="确认新密码">
            <n-input v-model:value="pwdForm.confirmPassword" type="password" show-password-on="click" />
          </n-form-item>
          <n-button class="gradient-btn" size="small" :loading="pwdSaving" @click="handleChangePwd">保存修改</n-button>
        </n-form>
      </div>

      <!-- 默认数据源 -->
      <div class="gradient-border-card profile-card">
        <h4 class="card-title">默认数据源</h4>
        <p class="card-tip">进入造数引擎时将自动选中该数据源</p>
        <n-select v-model:value="defaultDsId" :options="dsOptions" clearable placeholder="选择本组可用数据源" size="small" />
        <n-button class="gradient-btn mt-3" size="small" :loading="dsSaving" @click="handleSaveDs">保存</n-button>
      </div>

      <!-- 头像设置（10 款猫咪头像） -->
      <div class="gradient-border-card profile-card avatar-card">
        <h4 class="card-title">头像设置</h4>
        <p class="card-tip">10 款猫咪头像可选</p>
        <div class="avatar-grid">
          <div
            v-for="i in 10"
            :key="i - 1"
            class="avatar-option"
            :class="{ active: avatar === i - 1 }"
            :style="{ color: AVATAR_COLORS[(i - 1) % AVATAR_COLORS.length] }"
            @click="avatar = i - 1"
          >
            <CatMascot :size="44" pose="sit" />
          </div>
        </div>
        <n-button class="gradient-btn mt-3" size="small" :loading="avatarSaving" @click="handleSaveAvatar">保存头像</n-button>
      </div>
    </div>

    <!-- 操作日志 -->
    <div class="gradient-border-card logs-card">
      <h4 class="card-title">操作日志{{ isAdmin ? '（全量）' : '（本组）' }}</h4>
      <div class="filter-row">
        <n-input v-model:value="logFilters.operator" size="small" clearable placeholder="操作人" style="width: 140px" @keydown.enter="loadLogs(1)" />
        <n-select v-model:value="logFilters.action" :options="actionOptions" clearable size="small" placeholder="操作类型" style="width: 160px" @update:value="loadLogs(1)" />
        <n-select
          v-if="isAdmin"
          v-model:value="logFilters.groupType"
          :options="[
            { label: '销项组', value: 1 },
            { label: '申报组', value: 2 },
          ]"
          clearable
          size="small"
          placeholder="分组"
          style="width: 120px"
          @update:value="loadLogs(1)"
        />
        <n-date-picker v-model:value="logFilters.timeRange" type="datetimerange" size="small" clearable style="width: 320px" @update:value="loadLogs(1)" />
        <n-button size="small" class="gradient-btn" @click="loadLogs(1)">查询</n-button>
      </div>
      <n-spin :show="logsLoading">
        <n-data-table :columns="logColumns" :data="logs" size="small" :pagination="false" />
        <EmptyState v-if="!logsLoading && logs.length === 0" />
        <div class="pager">
          <n-pagination v-model:page="logPage" :item-count="logTotal" :page-size="logPageSize" @update:page="loadLogs" />
        </div>
      </n-spin>
    </div>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, type DataTableColumns, type FormInst, type FormRules } from 'naive-ui'
import { usersApi } from '@/api/users'
import { datasourceApi } from '@/api/datasource'
import type { AuditLogItem } from '@/api/types'
import CatMascot from '@/components/common/CatMascot.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/formatter'
import { groupName } from '@/utils/permission'

const router = useRouter()
const { isAdmin, logout } = useAuth()
const authStore = useAuthStore()

// ---------------- 修改密码 ----------------
const pwdFormRef = ref<FormInst | null>(null)
const pwdSaving = ref(false)
const pwdForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })

const pwdRules: FormRules = {
  oldPassword: [{ required: true, message: '请输入原密码', trigger: ['input', 'blur'] }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: ['input', 'blur'] },
    { pattern: /^(?=.*[a-zA-Z])(?=.*\d).{8,}$/, message: '至少 8 位且包含数字和字母', trigger: ['input', 'blur'] },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: ['input', 'blur'] },
    { validator: (_r, v) => v === pwdForm.newPassword, message: '两次输入的密码不一致', trigger: ['input', 'blur'] },
  ],
}

async function handleChangePwd(): Promise<void> {
  try {
    await pwdFormRef.value?.validate()
  } catch {
    return
  }
  pwdSaving.value = true
  try {
    await usersApi.changePassword(pwdForm.oldPassword, pwdForm.newPassword)
    window.$message.success('密码已修改，请重新登录')
    await logout()
  } finally {
    pwdSaving.value = false
  }
}

// ---------------- 默认数据源 ----------------
const dsOptions = ref<Array<{ label: string; value: number }>>([])
const defaultDsId = ref<number | null>(authStore.user?.default_datasource_id ?? null)
const dsSaving = ref(false)

async function handleSaveDs(): Promise<void> {
  dsSaving.value = true
  try {
    await usersApi.setDefaultDatasource(defaultDsId.value)
    await authStore.fetchMe()
    window.$message.success('默认数据源已更新')
  } finally {
    dsSaving.value = false
  }
}

// ---------------- 头像设置 ----------------
const AVATAR_COLORS = ['#a78bfa', '#f472b6', '#60a5fa', '#34d399', '#fbbf24', '#fb7185', '#22d3ee', '#c084fc', '#f97316', '#4ade80']
const avatar = ref(authStore.user?.avatar_index ?? 1)
const avatarSaving = ref(false)

async function handleSaveAvatar(): Promise<void> {
  avatarSaving.value = true
  try {
    await usersApi.updateAvatar(avatar.value)
    await authStore.fetchMe()
    window.$message.success('头像已更新')
  } finally {
    avatarSaving.value = false
  }
}

// ---------------- 操作日志 ----------------
const logs = ref<AuditLogItem[]>([])
const logsLoading = ref(false)
const logPage = ref(1)
const logPageSize = 20
const logTotal = ref(0)

const logFilters = reactive({
  operator: '',
  action: null as string | null,
  groupType: null as number | null,
  timeRange: null as [number, number] | null,
})

// 操作类型枚举
const ACTION_TYPES = [
  '用户登录', '用户登出', '注册申请', '审批通过', '审批拒绝',
  '创建Case', '修改Case', '删除Case', '执行Case', '复制Case',
  '创建场景', '修改场景', '删除场景', '执行场景',
  '新增数据源', '编辑数据源', '删除数据源', '同步数据源',
  '权限变更', '禁用用户', '重置密码',
]
const actionOptions = ACTION_TYPES.map((a) => ({ label: a, value: a }))

const logColumns: DataTableColumns<AuditLogItem> = [
  { title: '操作时间', key: 'created_at', width: 165, render: (r) => formatDateTime(r.created_at) },
  {
    title: '操作人',
    key: 'username',
    width: 130,
    render: (r) => {
      const name = r.real_name || r.username
      return isAdmin.value && r.group_type ? `${name}（${groupName(r.group_type)}）` : name
    },
  },
  { title: '操作类型', key: 'action', width: 110 },
  { title: '操作对象', key: 'resource', width: 190, ellipsis: { tooltip: true } },
  {
    title: '操作详情',
    key: 'detail',
    width: 90,
    render: (r) =>
      r.detail
        ? h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => showDetail(r) }, () => '展开')
        : '-',
  },
  { title: 'IP 地址', key: 'ip', width: 120 },
]

function showDetail(row: AuditLogItem): void {
  let pretty = row.detail ?? ''
  try {
    pretty = JSON.stringify(JSON.parse(pretty), null, 2)
  } catch {
    // 非 JSON 原文展示
  }
  window.$dialog.info({
    title: '操作详情',
    content: () => h('pre', { style: 'font-size:12px;white-space:pre-wrap;word-break:break-all;max-height:400px;overflow:auto' }, pretty),
    positiveText: '关闭',
  })
}

async function loadLogs(p?: number): Promise<void> {
  if (p) logPage.value = p
  logsLoading.value = true
  try {
    const [start, end] = logFilters.timeRange ?? [null, null]
    const res = await usersApi.auditLogs({
      username: logFilters.operator || undefined,
      action: logFilters.action ?? undefined,
      group_type: logFilters.groupType ?? undefined,
      start_time: start ? new Date(start).toISOString() : undefined,
      end_time: end ? new Date(end).toISOString() : undefined,
    })
    // 后端返回纯数组不分页，前端切片展示
    const all = res.data ?? []
    logTotal.value = all.length
    const begin = (logPage.value - 1) * logPageSize
    logs.value = all.slice(begin, begin + logPageSize)
  } finally {
    logsLoading.value = false
  }
}

onMounted(async () => {
  loadLogs(1)
  try {
    const res = await datasourceApi.list()
    dsOptions.value = res.data.map((d) => ({ label: d.name, value: d.id }))
  } catch {
    // 数据源下拉失败不阻塞
  }
})
</script>

<style scoped>
.profile-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}
.profile-card {
  padding: 18px;
}
.card-title {
  margin: 0 0 12px;
  font-size: 14px;
  color: #a78bfa;
}
.card-tip {
  margin: 0 0 10px;
  font-size: 12px;
  color: #64748b;
}
.mt-3 {
  margin-top: 12px;
}
.avatar-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
}
.avatar-option {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.15);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.avatar-option:hover {
  border-color: rgba(124, 58, 237, 0.5);
}
.avatar-option.active {
  border-color: #7c3aed;
  background: rgba(124, 58, 237, 0.12);
  box-shadow: 0 0 10px rgba(124, 58, 237, 0.3);
}
.logs-card {
  padding: 18px;
}
.filter-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
