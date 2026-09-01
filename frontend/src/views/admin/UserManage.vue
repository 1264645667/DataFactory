<template>
  <!-- 用户管理页（PRD 2.7，仅管理员）：待审批 Tab（红点）+ 全部用户 Tab -->
  <div class="user-manage-page">
    <div class="gradient-border-card list-card">
      <n-tabs v-model:value="activeTab" type="line" @update:value="handleTabChange">
        <!-- Tab1：待审批用户 -->
        <n-tab name="pending">
          <n-badge :value="pendingList.length" :max="99" :show="pendingList.length > 0" type="error">
            待审批用户
          </n-badge>
        </n-tab>
        <!-- Tab2：全部用户 -->
        <n-tab name="all">全部用户</n-tab>
      </n-tabs>

      <!-- 待审批列表 -->
      <div v-show="activeTab === 'pending'">
        <n-spin :show="pendingLoading">
          <n-data-table :columns="pendingColumns" :data="pendingList" size="small" :pagination="false" />
          <EmptyState v-if="!pendingLoading && pendingList.length === 0" description="没有待审批的申请" />
        </n-spin>
      </div>

      <!-- 全部用户列表 -->
      <div v-show="activeTab === 'all'">
        <n-spin :show="usersLoading">
          <n-data-table :columns="userColumns" :data="userList" size="small" :pagination="false" />
          <div class="pager">
            <n-pagination v-model:page="userPage" :item-count="userTotal" :page-size="userPageSize" @update:page="loadUsers" />
          </div>
        </n-spin>
      </div>
    </div>

    <!-- 权限分配弹窗（树形 Checkbox，全选/反选） -->
    <n-modal v-model:show="permShow" preset="card" :title="permTitle" style="width: 480px">
      <div class="perm-toolbar">
        <n-button text size="tiny" type="primary" @click="checkAll">全选</n-button>
        <n-button text size="tiny" type="primary" @click="checkedKeys = []">反选清空</n-button>
      </div>
      <n-tree
        :data="permTreeData"
        checkable
        cascade
        expand-all
        :checked-keys="checkedKeys"
        @update:checked-keys="(keys: string[]) => (checkedKeys = keys)"
      />
      <template #footer>
        <div class="modal-actions">
          <n-button @click="permShow = false">取消</n-button>
          <n-button class="gradient-btn" :loading="permSaving" @click="handleSavePerms">保存</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 拒绝原因弹窗 -->
    <n-modal v-model:show="rejectShow" preset="card" title="拒绝注册申请" style="width: 420px">
      <n-input
        v-model:value="rejectReason"
        type="textarea"
        :rows="3"
        maxlength="200"
        show-count
        placeholder="请填写拒绝原因（必填）"
      />
      <template #footer>
        <div class="modal-actions">
          <n-button @click="rejectShow = false">取消</n-button>
          <n-button type="error" :loading="rejecting" @click="handleReject">确认拒绝</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 重置密码结果弹窗 -->
    <n-modal v-model:show="tempPwdShow" preset="card" title="密码已重置" style="width: 420px">
      <p class="temp-pwd-tip">请将临时密码告知用户，并提醒其登录后尽快修改：</p>
      <div class="temp-pwd-box">
        <span class="temp-pwd">{{ tempPassword }}</span>
        <n-button text size="small" type="primary" @click="copyTempPwd">复制</n-button>
      </div>
      <template #footer>
        <div class="modal-actions">
          <n-button class="gradient-btn" @click="tempPwdShow = false">知道了</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { NButton, NTag, type DataTableColumns, type TreeOption } from 'naive-ui'
import { usersApi } from '@/api/users'
import type { AdminUserItem, PendingUser } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import { ALL_PERMISSION_KEYS, PERMISSION_TREE, groupName } from '@/utils/permission'
import { copyText, formatDateTimeMin } from '@/utils/formatter'

const activeTab = ref<'pending' | 'all'>('pending')

// ---------------- 待审批 ----------------
const pendingList = ref<PendingUser[]>([])
const pendingLoading = ref(false)

const pendingColumns: DataTableColumns<PendingUser> = [
  { title: '申请人', key: 'real_name', width: 110, render: (r) => `${r.real_name}（${r.username}）` },
  { title: '申请分组', key: 'group_type', width: 100, render: (r) => groupName(r.group_type) },
  { title: '申请时间', key: 'created_at', width: 150, render: (r) => formatDateTimeMin(r.created_at) },
  { title: '申请理由', key: 'apply_reason', ellipsis: { tooltip: true }, render: (r) => r.apply_reason || '-' },
  {
    title: '操作',
    key: 'actions',
    width: 140,
    render: (row) =>
      h('div', { style: 'display:flex;gap:10px' }, [
        h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => openApprove(row) }, () => '通过'),
        h(NButton, { text: true, size: 'small', type: 'error', onClick: () => openReject(row) }, () => '拒绝'),
      ]),
  },
]

async function loadPending(): Promise<void> {
  pendingLoading.value = true
  try {
    const res = await usersApi.pending()
    pendingList.value = res.data
  } finally {
    pendingLoading.value = false
  }
}

// ---------------- 全部用户 ----------------
const userList = ref<AdminUserItem[]>([])
const usersLoading = ref(false)
const userPage = ref(1)
const userPageSize = 20
const userTotal = ref(0)

const USER_STATUS: Record<number, { type: 'success' | 'warning' | 'error' | 'default'; text: string }> = {
  0: { type: 'warning', text: '待审批' },
  1: { type: 'success', text: '正常' },
  2: { type: 'error', text: '已禁用' },
  3: { type: 'default', text: '已拒绝' },
}

const userColumns: DataTableColumns<AdminUserItem> = [
  { title: '用户名', key: 'username', width: 110 },
  { title: '真实姓名', key: 'real_name', width: 100 },
  { title: '分组', key: 'group_type', width: 90, render: (r) => groupName(r.group_type) },
  {
    title: '状态',
    key: 'status',
    width: 90,
    render: (r) => {
      const s = USER_STATUS[r.status] ?? { type: 'default' as const, text: '未知' }
      return h(NTag, { size: 'small', type: s.type }, () => s.text)
    },
  },
  {
    title: '已授权菜单',
    key: 'permissions',
    ellipsis: { tooltip: true },
    render: (r) => (r.permissions?.length ? `${r.permissions.length} 项权限` : '-'),
  },
  { title: '默认数据源', key: 'default_datasource_id', width: 110, render: (r) => r.default_datasource_id ?? '-' },
  { title: '注册时间', key: 'created_at', width: 140, render: (r) => formatDateTimeMin(r.created_at) },
  {
    title: '操作',
    key: 'actions',
    width: 210,
    render: (row) =>
      h('div', { style: 'display:flex;gap:8px' }, [
        h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => openEditPerms(row) }, () => '编辑权限'),
        row.status === 2
          ? h(NButton, { text: true, size: 'small', onClick: () => handleEnable(row) }, () => '启用')
          : h(NButton, { text: true, size: 'small', type: 'warning', onClick: () => handleDisable(row) }, () => '禁用'),
        h(NButton, { text: true, size: 'small', type: 'error', onClick: () => handleResetPwd(row) }, () => '重置密码'),
      ]),
  },
]

async function loadUsers(p?: number): Promise<void> {
  if (p) userPage.value = p
  usersLoading.value = true
  try {
    const res = await usersApi.list({ page: userPage.value, page_size: userPageSize })
    userList.value = res.data.items ?? []
    userTotal.value = res.data.total
  } finally {
    usersLoading.value = false
  }
}

function handleTabChange(): void {
  if (activeTab.value === 'pending') loadPending()
  else loadUsers(1)
}

// ---------------- 权限分配弹窗 ----------------
const permShow = ref(false)
const permSaving = ref(false)
const permTitle = ref('分配权限')
const checkedKeys = ref<string[]>([])
const permTarget = ref<{ id: number; mode: 'approve' | 'edit' } | null>(null)

// 权限树（PRD 2.3 菜单权限体系）
const permTreeData: TreeOption[] = PERMISSION_TREE.map((g) => ({
  label: g.label,
  key: g.key,
  children: g.children?.map((c) => ({ label: c.label, key: c.key })),
}))

function checkAll(): void {
  checkedKeys.value = [...ALL_PERMISSION_KEYS]
}

/** 审批通过：弹出权限分配弹窗 */
function openApprove(row: PendingUser): void {
  permTarget.value = { id: row.id, mode: 'approve' }
  permTitle.value = `通过申请并分配权限 · ${row.real_name}`
  checkedKeys.value = []
  permShow.value = true
}

/** 编辑已有用户权限 */
function openEditPerms(row: AdminUserItem): void {
  permTarget.value = { id: row.id, mode: 'edit' }
  permTitle.value = `编辑权限 · ${row.real_name}`
  checkedKeys.value = [...(row.permissions ?? [])]
  permShow.value = true
}

/** 保存权限：审批模式调 approve，编辑模式调 updatePermissions（保存后立即生效） */
async function handleSavePerms(): Promise<void> {
  if (!permTarget.value) return
  // 仅保留叶子权限编码
  const perms = checkedKeys.value.filter((k) => ALL_PERMISSION_KEYS.includes(k))
  permSaving.value = true
  try {
    if (permTarget.value.mode === 'approve') {
      await usersApi.approve(permTarget.value.id, { menu_codes: perms })
      window.$message.success('已通过审批')
      loadPending()
    } else {
      await usersApi.updatePermissions(permTarget.value.id, { menu_codes: perms })
      window.$message.success('权限已更新，立即生效')
      loadUsers()
    }
    permShow.value = false
  } finally {
    permSaving.value = false
  }
}

// ---------------- 拒绝 ----------------
const rejectShow = ref(false)
const rejecting = ref(false)
const rejectReason = ref('')
const rejectTarget = ref<PendingUser | null>(null)

function openReject(row: PendingUser): void {
  rejectTarget.value = row
  rejectReason.value = ''
  rejectShow.value = true
}

async function handleReject(): Promise<void> {
  if (!rejectTarget.value) return
  if (!rejectReason.value.trim()) {
    window.$message.error('请填写拒绝原因')
    return
  }
  rejecting.value = true
  try {
    await usersApi.reject(rejectTarget.value.id, { reject_reason: rejectReason.value.trim() })
    window.$message.success('已拒绝')
    rejectShow.value = false
    loadPending()
  } finally {
    rejecting.value = false
  }
}

// ---------------- 禁用 / 启用 / 重置密码 ----------------
function handleDisable(row: AdminUserItem): void {
  window.$dialog.warning({
    title: '禁用用户',
    content: `确认禁用用户「${row.real_name}（${row.username}）」？禁用后该用户将无法登录。`,
    positiveText: '确认禁用',
    negativeText: '取消',
    onPositiveClick: async () => {
      await usersApi.disable(row.id)
      window.$message.success('已禁用')
      loadUsers()
    },
  })
}

async function handleEnable(row: AdminUserItem): Promise<void> {
  await usersApi.enable(row.id)
  window.$message.success('已启用')
  loadUsers()
}

const tempPwdShow = ref(false)
const tempPassword = ref('')

function handleResetPwd(row: AdminUserItem): void {
  window.$dialog.warning({
    title: '重置密码',
    content: `确认重置「${row.real_name}（${row.username}）」的密码？将生成临时密码。`,
    positiveText: '确认重置',
    negativeText: '取消',
    onPositiveClick: async () => {
      const res = await usersApi.resetPassword(row.id)
      tempPassword.value = res.data.temp_password
      tempPwdShow.value = true
    },
  })
}

function copyTempPwd(): void {
  copyText(tempPassword.value).then(() => window.$message.success('已复制'))
}

onMounted(() => {
  loadPending()
  loadUsers(1)
})
</script>

<style scoped>
.list-card {
  padding: 16px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.perm-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
}
.temp-pwd-tip {
  color: #94a3b8;
  font-size: 13px;
  margin: 0 0 12px;
}
.temp-pwd-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 1px dashed rgba(124, 58, 237, 0.4);
  border-radius: 8px;
  padding: 10px 14px;
}
.temp-pwd {
  font-size: 16px;
  font-weight: 700;
  color: #c4b5fd;
  letter-spacing: 1px;
}
</style>
