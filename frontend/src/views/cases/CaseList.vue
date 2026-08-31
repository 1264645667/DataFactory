<template>
  <!-- Case 管理列表页（PRD 5.2/5.3） -->
  <div class="case-list-page">
    <div class="gradient-border-card list-card">
      <!-- 筛选条件行 -->
      <div class="filter-row">
        <n-select v-model:value="filters.datasourceId" :options="datasourceOptions" clearable size="small" placeholder="数据源" style="width: 160px" @update:value="loadList(1)" />
        <n-input v-model:value="filters.name" size="small" clearable placeholder="Case 名称搜索" style="width: 180px" @keydown.enter="loadList(1)" @clear="loadList(1)" />
        <n-select v-model:value="filters.createdBy" :options="memberOptions" clearable size="small" placeholder="创建人" style="width: 140px" @update:value="loadList(1)" />
        <n-select v-model:value="filters.status" :options="statusOptions" multiple clearable size="small" placeholder="最后执行状态" style="width: 200px" @update:value="loadList(1)" />
        <n-date-picker v-model:value="filters.timeRange" type="daterange" size="small" clearable style="width: 260px" @update:value="loadList(1)" />
        <n-button size="small" class="gradient-btn" @click="loadList(1)">查询</n-button>
      </div>

      <!-- 操作按钮行 -->
      <div class="op-row">
        <n-button size="small" :disabled="selectedIds.length === 0" @click="openBatchExecute">批量执行</n-button>
        <n-button size="small" type="error" ghost :disabled="selectedIds.length === 0" @click="handleBatchDelete">批量删除</n-button>
      </div>

      <!-- Case 列表表格 -->
      <n-skeleton v-if="firstLoading" :repeat="6" height="42px" />
      <n-spin v-else :show="loading">
        <n-data-table
          :columns="columns"
          :data="list"
          :pagination="false"
          size="small"
          :row-key="(row: CaseItem) => row.id"
          :checked-row-keys="selectedIds"
          @update:checked-row-keys="(keys: number[]) => (selectedIds = keys)"
        />
        <EmptyState
          v-if="!loading && list.length === 0"
          :description="hasFilter ? '没有符合条件的数据，小猫在打盹～' : '还没有 Case，去造数引擎创建第一个吧 →'"
          :button-text="hasFilter ? '清空筛选' : ''"
          @action="clearFilters"
        />
        <div class="pager">
          <n-pagination v-model:page="page" :item-count="total" :page-size="pageSize" @update:page="loadList" />
        </div>
      </n-spin>
    </div>

    <!-- 执行确认弹窗（复用 4.4.7） -->
    <ExecuteModal
      v-model:show="executeShow"
      :main-table="executingCase?.main_table ?? ''"
      :related-tables="executingRelated"
      :iterate-info="executingIterate"
      :initial-name="executingCase?.name ?? ''"
      name-readonly
      :submitting="executing"
      @confirm="handleExecute"
    />

    <!-- 复制弹窗 -->
    <n-modal v-model:show="copyShow" preset="card" title="复制 Case" style="width: 420px">
      <n-input v-model:value="copyName" placeholder="新 Case 名称" />
      <template #footer>
        <div class="modal-actions">
          <n-button @click="copyShow = false">取消</n-button>
          <n-button class="gradient-btn" :loading="copying" @click="handleCopy">确认</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 批量执行弹窗 -->
    <n-modal v-model:show="batchShow" preset="card" title="批量执行" style="width: 620px; max-width: 92vw">
      <div class="batch-head">
        <span>共 {{ batchItems.length }} 个 Case，将依次串行提交</span>
        <div class="batch-uniform">
          <n-input-number v-model:value="uniformCount" :min="1" size="small" placeholder="统一条数" style="width: 130px" />
          <n-button size="small" @click="applyUniform">统一设置</n-button>
        </div>
      </div>
      <div v-for="item in batchItems" :key="item.case_id" class="batch-row">
        <span class="batch-name">{{ item.name }}</span>
        <n-input-number v-model:value="item.target_count" :min="1" size="small" placeholder="造数条数" style="width: 160px" />
      </div>
      <template #footer>
        <div class="modal-actions">
          <n-button @click="batchShow = false">取消</n-button>
          <n-button class="gradient-btn" :loading="batchExecuting" @click="handleBatchExecute">确认执行</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 执行历史抽屉 -->
    <n-drawer v-model:show="historyShow" :width="680" placement="right">
      <n-drawer-content :title="`执行历史 · ${historyCaseName}`" closable>
        <n-spin :show="historyLoading">
          <n-data-table :columns="historyColumns" :data="historyList" size="small" :pagination="{ pageSize: 10 }" />
          <EmptyState v-if="!historyLoading && historyList.length === 0" description="还没有执行记录" />
          <div v-if="historyList.length > 0" class="history-stats">
            总执行 {{ historyList.length }} 次 · 成功 {{ historyList.filter((h) => h.status === 'success').length }} 次 ·
            累计造数 {{ formatNumber(historyList.reduce((s, h) => s + (h.success_count ?? 0), 0)) }} 条
          </div>
        </n-spin>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NTag, type DataTableColumns } from 'naive-ui'
import { casesApi } from '@/api/cases'
import { datasourceApi } from '@/api/datasource'
import { usersApi } from '@/api/users'
import type { CaseHistoryItem, CaseItem } from '@/api/types'
import ExecuteModal from '@/components/business/ExecuteModal.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { useTaskProgress } from '@/composables/useTaskProgress'
import { formatDateTimeMin, formatDuration, formatNumber } from '@/utils/formatter'

const router = useRouter()
const { hasPermission } = useAuth()
const { trackTask } = useTaskProgress()

const list = ref<CaseItem[]>([])
const loading = ref(false)
const firstLoading = ref(true)
const page = ref(1)
const pageSize = 20
const total = ref(0)
const selectedIds = ref<number[]>([])
const flashId = ref<number | null>(null)

const filters = reactive({
  datasourceId: null as number | null,
  name: '',
  createdBy: null as number | null,
  status: [] as string[],
  timeRange: null as [number, number] | null,
})

const hasFilter = computed(
  () => !!(filters.datasourceId || filters.name || filters.createdBy || filters.status.length || filters.timeRange),
)

const datasourceOptions = ref<Array<{ label: string; value: number }>>([])
const memberOptions = ref<Array<{ label: string; value: number }>>([])
const statusOptions = [
  { label: '成功', value: 'success' },
  { label: '失败', value: 'failed' },
  { label: '未执行', value: 'none' },
]

function statusTag(status: string | null) {
  if (!status) return h(NTag, { size: 'small' }, () => '未执行')
  const type = status === 'success' ? 'success' : status === 'partial_success' ? 'warning' : status === 'running' ? 'info' : 'error'
  const text = { success: '成功', failed: '失败', partial_success: '部分成功', running: '执行中', aborted: '已中止' }[status] ?? status
  return h(NTag, { size: 'small', type: type as 'success' | 'warning' | 'info' | 'error' }, () => text)
}

const columns: DataTableColumns<CaseItem> = [
  { type: 'selection' },
  {
    title: 'Case 名称',
    key: 'name',
    width: 200,
    render: (row) =>
      h(
        'a',
        { style: 'color:#a78bfa;cursor:pointer;font-weight:600', onClick: () => router.push(`/cases/${row.id}`) },
        row.name,
      ),
  },
  { title: '数据源', key: 'datasource_name', width: 120 },
  { title: '主表', key: 'main_table', width: 150, ellipsis: { tooltip: true } },
  { title: '关联表数', key: 'related_table_count', width: 80 },
  { title: '创建人', key: 'created_by_name', width: 80 },
  { title: '创建时间', key: 'created_at', width: 140, render: (r) => formatDateTimeMin(r.created_at) },
  {
    title: '最后执行时间',
    key: 'last_exec_at',
    width: 140,
    render: (r) => (r.last_exec_at ? formatDateTimeMin(r.last_exec_at) : h('span', { style: 'color:#64748b' }, '未执行')),
  },
  { title: '最后执行状态', key: 'last_exec_status', width: 100, render: (r) => statusTag(r.last_exec_status) },
  {
    title: '操作',
    key: 'actions',
    width: 230,
    render: (row) => {
      const btns = []
      if (hasPermission('CASE:EXECUTE')) {
        btns.push(h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => openExecute(row) }, () => '执行'))
      }
      if (hasPermission('CASE:EDIT')) {
        btns.push(
          h(
            NButton,
            { text: true, size: 'small', onClick: () => router.push({ name: 'EngineConfig', params: { tableName: row.main_table }, query: { datasource_id: row.datasource_id, case_id: row.id } }) },
            () => '修改',
          ),
        )
      }
      if (hasPermission('CASE:COPY')) {
        btns.push(h(NButton, { text: true, size: 'small', onClick: () => openCopy(row) }, () => '复制'))
      }
      btns.push(h(NButton, { text: true, size: 'small', onClick: () => openHistory(row) }, () => '历史'))
      if (hasPermission('CASE:DELETE')) {
        btns.push(h(NButton, { text: true, size: 'small', type: 'error', onClick: () => handleDelete(row) }, () => '删除'))
      }
      return h('div', { style: 'display:flex;gap:8px' }, btns)
    },
  },
]

async function loadList(p?: number): Promise<void> {
  if (p) page.value = p
  loading.value = true
  try {
    const [start, end] = filters.timeRange ?? [null, null]
    const res = await casesApi.list({
      page: page.value,
      page_size: pageSize,
      datasource_id: filters.datasourceId ?? undefined,
      name: filters.name || undefined,
      created_by: filters.createdBy ?? undefined,
      last_exec_status: filters.status.length ? filters.status : undefined,
      start_time: start ? new Date(start).toISOString() : undefined,
      end_time: end ? new Date(end).toISOString() : undefined,
    })
    list.value = res.data.list
    total.value = res.data.total
    selectedIds.value = []
  } finally {
    loading.value = false
    firstLoading.value = false
  }
}

function clearFilters(): void {
  filters.datasourceId = null
  filters.name = ''
  filters.createdBy = null
  filters.status = []
  filters.timeRange = null
  loadList(1)
}

// ---------------- 执行 ----------------
const executeShow = ref(false)
const executing = ref(false)
const executingCase = ref<CaseItem | null>(null)
const executingRelated = ref<string[]>([])
const executingIterate = ref<{ field: string; values: string[]; rowsPerValue: number } | null>(null)

async function openExecute(row: CaseItem): Promise<void> {
  // 拉取 Case 详情展示配置摘要
  const res = await casesApi.detail(row.id)
  const cfg = res.data.config_json
  executingCase.value = row
  executingRelated.value = [...new Set(cfg.associations.map((a) => a.target_table))]
  const iterateField = cfg.field_configs.find((f) => f.strategy === 'ITERATE_LIST')
  if (iterateField) {
    const values = String(iterateField.strategy_params?.list ?? '').split('\n').map((s) => s.trim()).filter(Boolean)
    executingIterate.value = values.length
      ? { field: `${cfg.main_table}.${iterateField.column_name}`, values, rowsPerValue: Number(iterateField.strategy_params?.rows_per_value ?? 1) }
      : null
  } else {
    executingIterate.value = null
  }
  executeShow.value = true
}

async function handleExecute(payload: { caseName: string; targetCount: number }): Promise<void> {
  if (!executingCase.value) return
  executing.value = true
  try {
    const res = await casesApi.execute(executingCase.value.id, payload.targetCount)
    executeShow.value = false
    trackTask(res.data.task_no, payload.caseName)
    loadList()
  } finally {
    executing.value = false
  }
}

// ---------------- 复制 ----------------
const copyShow = ref(false)
const copying = ref(false)
const copyName = ref('')
const copyTarget = ref<CaseItem | null>(null)

function openCopy(row: CaseItem): void {
  copyTarget.value = row
  copyName.value = `${row.name}_copy`
  copyShow.value = true
}

async function handleCopy(): Promise<void> {
  if (!copyTarget.value || !copyName.value.trim()) return
  copying.value = true
  try {
    const res = await casesApi.copy(copyTarget.value.id, copyName.value.trim())
    copyShow.value = false
    window.$message.success('复制成功')
    await loadList()
    // 高亮闪烁新行
    flashId.value = res.data.case_id
    setTimeout(() => (flashId.value = null), 1700)
  } finally {
    copying.value = false
  }
}

// ---------------- 删除 ----------------
function handleDelete(row: CaseItem): void {
  window.$dialog.warning({
    title: '确认删除',
    content: `确认删除 Case「${row.name}」？删除后不可恢复，历史执行记录将保留。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await casesApi.remove(row.id)
      window.$message.success('已删除')
      loadList()
    },
  })
}

function handleBatchDelete(): void {
  window.$dialog.warning({
    title: '确认批量删除',
    content: `确认删除选中的 ${selectedIds.value.length} 个 Case？删除后不可恢复，历史执行记录将保留。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await Promise.all(selectedIds.value.map((id) => casesApi.remove(id)))
      window.$message.success('已批量删除')
      loadList()
    },
  })
}

// ---------------- 批量执行 ----------------
const batchShow = ref(false)
const batchExecuting = ref(false)
const batchItems = ref<Array<{ case_id: number; name: string; target_count: number | null }>>([])
const uniformCount = ref<number | null>(null)

function openBatchExecute(): void {
  batchItems.value = list.value
    .filter((c) => selectedIds.value.includes(c.id))
    .map((c) => ({ case_id: c.id, name: c.name, target_count: 1000 }))
  batchShow.value = true
}

function applyUniform(): void {
  if (!uniformCount.value) return
  batchItems.value.forEach((i) => (i.target_count = uniformCount.value))
}

async function handleBatchExecute(): Promise<void> {
  const invalid = batchItems.value.find((i) => !i.target_count || i.target_count < 1)
  if (invalid) {
    window.$message.error(`请填写「${invalid.name}」的执行条数`)
    return
  }
  batchExecuting.value = true
  try {
    const res = await casesApi.batchExecute(batchItems.value.map((i) => ({ case_id: i.case_id, target_count: i.target_count! })))
    batchShow.value = false
    // 每个 Case 生成独立任务，全部纳入进度管理
    res.data.tasks.forEach((t) => {
      const item = batchItems.value.find((i) => i.case_id === t.case_id)
      trackTask(t.task_no, item?.name ?? '')
    })
  } finally {
    batchExecuting.value = false
  }
}

// ---------------- 执行历史 ----------------
const historyShow = ref(false)
const historyLoading = ref(false)
const historyList = ref<CaseHistoryItem[]>([])
const historyCaseName = ref('')

const historyColumns: DataTableColumns<CaseHistoryItem> = [
  { title: '执行时间', key: 'started_at', width: 160, render: (r) => formatDateTimeMin(r.started_at) },
  { title: '造数条数', key: 'target_count', width: 110, render: (r) => formatNumber(r.target_count) },
  { title: '实际插入', key: 'success_count', width: 110, render: (r) => formatNumber(r.success_count) },
  { title: '状态', key: 'status', width: 100, render: (r) => statusTag(r.status) },
  { title: '耗时', key: 'duration_seconds', width: 90, render: (r) => formatDuration(r.duration_seconds) },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render: (r) => h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => router.push({ path: '/overview', query: { task_no: r.task_no } }) }, () => '查看详情'),
  },
]

async function openHistory(row: CaseItem): Promise<void> {
  historyCaseName.value = row.name
  historyShow.value = true
  historyLoading.value = true
  try {
    const res = await casesApi.history(row.id, { page: 1, page_size: 50 })
    historyList.value = res.data.list
  } finally {
    historyLoading.value = false
  }
}

onMounted(async () => {
  loadList(1)
  try {
    const [dsRes, userRes] = await Promise.all([
      datasourceApi.list(),
      usersApi.list({ page: 1, page_size: 100 }).catch(() => null),
    ])
    datasourceOptions.value = dsRes.data.map((d) => ({ label: d.name, value: d.id }))
    if (userRes) memberOptions.value = userRes.data.list.map((u) => ({ label: u.real_name, value: u.id }))
  } catch {
    // 下拉数据失败不阻塞页面
  }
})
</script>

<style scoped>
.list-card {
  padding: 16px;
}
.filter-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.op-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
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
.batch-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 13px;
  color: #94a3b8;
}
.batch-uniform {
  display: flex;
  gap: 8px;
}
.batch-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
}
.batch-name {
  font-size: 13px;
  color: #e2e8f0;
}
.history-stats {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  font-size: 12px;
  color: #94a3b8;
}
</style>
