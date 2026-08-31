<template>
  <!-- 数据源管理列表页（PRD 8.2） -->
  <div class="ds-list-page">
    <div class="gradient-border-card list-card">
      <!-- 顶部操作 -->
      <div class="op-row">
        <n-button v-if="hasPermission('DATASOURCE:ADD')" size="small" class="gradient-btn" @click="openCreate">
          + 新增数据源
        </n-button>
        <n-input v-model:value="keyword" size="small" clearable placeholder="按数据源名称过滤" style="width: 220px">
          <template #prefix><n-icon><SearchOutline /></n-icon></template>
        </n-input>
      </div>

      <!-- 数据源表格 -->
      <n-skeleton v-if="firstLoading" :repeat="5" height="44px" />
      <n-spin v-else :show="loading">
        <n-data-table :columns="columns" :data="filteredList" size="small" :pagination="{ pageSize: 20 }" />
        <EmptyState v-if="!loading && filteredList.length === 0" description="暂无数据源，先新增一个吧" />
      </n-spin>
    </div>

    <!-- 新增/编辑表单弹窗 -->
    <DatasourceForm v-model:show="formShow" :datasource="editingDs" @saved="handleSaved" />

    <!-- 删除二次确认弹窗（PRD 8.2.3） -->
    <n-modal v-model:show="deleteShow" preset="card" title="确认删除数据源" style="width: 520px">
      <n-alert type="warning" :show-icon="false" class="mb-3">
        确认删除数据源「{{ deletingDs?.name }}」？
      </n-alert>
      <div class="delete-detail">
        此操作将同时：
        <ul>
          <li>删除该数据源的所有表结构缓存（df_table_cache / df_column_cache / df_index_cache）</li>
          <li>清除对应 Redis 缓存键</li>
          <li>历史执行记录中数据源名称将保留（冗余字段），不受影响</li>
        </ul>
        已逻辑删除的 Case 的历史执行记录仍可查看。此操作不可恢复。
      </div>
      <template #footer>
        <div class="modal-actions">
          <n-button @click="deleteShow = false">取消</n-button>
          <n-button type="error" :loading="deleting" @click="handleDelete">确认删除</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref } from 'vue'
import { SearchOutline } from '@vicons/ionicons5'
import { NButton, NTag, type DataTableColumns } from 'naive-ui'
import { datasourceApi } from '@/api/datasource'
import { usersApi } from '@/api/users'
import type { Datasource } from '@/api/types'
import DatasourceForm from './DatasourceForm.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { groupName } from '@/utils/permission'
import { formatDateTime } from '@/utils/formatter'

const { hasPermission } = useAuth()

const list = ref<Datasource[]>([])
const loading = ref(false)
const firstLoading = ref(true)
const keyword = ref('')

const filteredList = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return list.value
  return list.value.filter((d) => d.name.toLowerCase().includes(kw))
})

// 连接状态灯
function statusLight(status: string) {
  const color = { online: '#22c55e', offline: '#ef4444', syncing: '#f59e0b' }[status] ?? '#64748b'
  const text = { online: '正常', offline: '异常', syncing: '同步中' }[status] ?? status
  return h('span', { style: 'display:inline-flex;align-items:center;gap:6px' }, [
    h('span', { style: `width:9px;height:9px;border-radius:50%;background:${color};box-shadow:0 0 6px ${color}` }),
    h('span', { style: 'font-size:12px;color:#94a3b8' }, text),
  ])
}

const CACHE_STATUS: Record<string, { type: 'success' | 'warning' | 'error' | 'info'; text: string }> = {
  initialized: { type: 'success', text: '已初始化' },
  initializing: { type: 'warning', text: '初始化中' },
  not_initialized: { type: 'error', text: '未初始化' },
  syncing: { type: 'info', text: '同步中' },
}

const columns: DataTableColumns<Datasource> = [
  {
    title: '数据源名称',
    key: 'name',
    render: (r) =>
      h('span', { style: 'font-weight:600' }, [
        r.name,
        r.is_default ? h('span', { style: 'color:#fbbf24;margin-left:6px', title: '默认数据源' }, '★') : null,
      ]),
  },
  { title: '连接地址', key: 'host', render: (r) => `${r.host}:${r.port}/${r.database}` },
  { title: '所属分组', key: 'group_type', width: 100, render: (r) => groupName(r.group_type) },
  { title: '连接状态', key: 'status', width: 100, render: (r) => statusLight(r.status) },
  {
    title: '缓存状态',
    key: 'cache_status',
    width: 110,
    render: (r) => {
      const s = CACHE_STATUS[r.cache_status] ?? { type: 'default' as const, text: r.cache_status }
      return h(NTag, { size: 'small', type: s.type }, () => s.text)
    },
  },
  { title: '表数量', key: 'table_count', width: 80 },
  { title: '最后同步时间', key: 'last_sync_at', width: 160, render: (r) => formatDateTime(r.last_sync_at) },
  {
    title: '操作',
    key: 'actions',
    width: 260,
    render: (row) => {
      const btns = []
      if (hasPermission('DATASOURCE:EDIT')) {
        btns.push(h(NButton, { text: true, size: 'small', onClick: () => openEdit(row) }, () => '编辑'))
        btns.push(h(NButton, { text: true, size: 'small', onClick: () => handleSync(row) }, () => '立即同步'))
      }
      btns.push(h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => handleTest(row) }, () => '测试连接'))
      btns.push(h(NButton, { text: true, size: 'small', onClick: () => handleSetDefault(row) }, () => '设为默认'))
      if (hasPermission('DATASOURCE:DELETE')) {
        btns.push(h(NButton, { text: true, size: 'small', type: 'error', onClick: () => openDelete(row) }, () => '删除'))
      }
      return h('div', { style: 'display:flex;gap:8px' }, btns)
    },
  },
]

async function loadList(): Promise<void> {
  loading.value = true
  try {
    const res = await datasourceApi.list()
    list.value = res.data
  } finally {
    loading.value = false
    firstLoading.value = false
  }
}

// ---------------- 新增 / 编辑 ----------------
const formShow = ref(false)
const editingDs = ref<Datasource | null>(null)

function openCreate(): void {
  editingDs.value = null
  formShow.value = true
}

function openEdit(row: Datasource): void {
  editingDs.value = row
  formShow.value = true
}

function handleSaved(): void {
  loadList()
  // 保存后后台初始化表结构，延迟刷新状态
  setTimeout(loadList, 5000)
}

// ---------------- 操作 ----------------
async function handleTest(row: Datasource): Promise<void> {
  try {
    const res = await datasourceApi.test({
      host: row.host,
      port: row.port,
      database: row.database,
      username: row.username,
      db_type: row.db_type,
    })
    window.$message.success(`连接成功，数据库版本：${res.data.version ?? 'MySQL'}`)
  } catch {
    // 错误由拦截器提示
  }
}

async function handleSync(row: Datasource): Promise<void> {
  await datasourceApi.sync(row.id)
  window.$message.success('同步任务已触发')
  setTimeout(loadList, 4000)
}

async function handleSetDefault(row: Datasource): Promise<void> {
  await usersApi.setDefaultDatasource(row.id)
  window.$message.success(`已将「${row.name}」设为默认数据源`)
  loadList()
}

// ---------------- 删除（PRD 8.2.3：删除前校验 + 二次确认） ----------------
const deleteShow = ref(false)
const deleting = ref(false)
const deletingDs = ref<Datasource | null>(null)

function openDelete(row: Datasource): void {
  deletingDs.value = row
  deleteShow.value = true
}

async function handleDelete(): Promise<void> {
  if (!deletingDs.value) return
  deleting.value = true
  try {
    await datasourceApi.remove(deletingDs.value.id)
    deleteShow.value = false
    window.$message.success('数据源已删除')
    loadList()
  } catch {
    // 1206 等硬拦截提示由拦截器弹出（存在关联 Case / 执行中任务）
    deleteShow.value = false
  } finally {
    deleting.value = false
  }
}

// 连接状态 30s 轮询刷新
let statusTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  loadList()
  statusTimer = setInterval(loadList, 30_000)
})

onBeforeUnmount(() => {
  if (statusTimer) clearInterval(statusTimer)
})
</script>

<style scoped>
.list-card {
  padding: 16px;
}
.op-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.delete-detail {
  font-size: 13px;
  color: #94a3b8;
  line-height: 1.8;
}
.delete-detail ul {
  margin: 8px 0;
  padding-left: 20px;
}
.mb-3 {
  margin-bottom: 12px;
}
</style>
