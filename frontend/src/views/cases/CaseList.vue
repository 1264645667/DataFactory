<template>
  <!-- Case 管理列表页（左侧文件夹收纳 + 右侧列表） -->
  <div class="case-list-page">
    <!-- 文件夹栏 -->
    <div class="folder-panel glass-card">
      <div class="folder-title">文件夹</div>
      <div class="folder-list">
        <div class="folder-item" :class="{ active: activeFolder === 'all' }" @click="selectFolder('all')">
          <n-icon class="folder-icon"><FolderOpenOutline /></n-icon>
          <span class="folder-name">全部</span>
          <span class="folder-count">{{ folderData?.total_count ?? 0 }}</span>
        </div>
        <div class="folder-item" :class="{ active: activeFolder === 'unfiled' }" @click="selectFolder('unfiled')">
          <n-icon class="folder-icon"><FolderOutline /></n-icon>
          <span class="folder-name">未分类</span>
          <span class="folder-count">{{ folderData?.unfiled_count ?? 0 }}</span>
        </div>
        <div
          v-for="f in folderData?.folders ?? []"
          :key="f.id"
          class="folder-item"
          :class="{ active: activeFolder === f.id }"
          @click="selectFolder(f.id)"
        >
          <n-icon class="folder-icon"><FolderOutline /></n-icon>
          <span class="folder-name" :title="f.name">{{ f.name }}</span>
          <span class="folder-count">{{ f.case_count }}</span>
          <n-dropdown trigger="click" :options="folderMenu" @select="(key: string) => onFolderAction(key, f)">
            <n-icon class="folder-more" @click.stop><EllipsisHorizontalOutline /></n-icon>
          </n-dropdown>
        </div>
      </div>
      <div v-if="hasPermission('CASE:CREATE')" class="folder-add" @click="openFolderModal()">+ 新建文件夹</div>
    </div>

    <!-- 右侧 Case 列表 -->
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
        <div class="move-group">
          <n-select
            v-model:value="moveTarget"
            :options="moveOptions"
            size="small"
            placeholder="移动到…"
            style="width: 140px"
            :disabled="selectedIds.length === 0"
          />
          <n-button size="small" :disabled="selectedIds.length === 0 || moveTarget === null" @click="handleBatchMove">移动</n-button>
        </div>
      </div>

      <!-- Case 列表表格 -->
      <n-skeleton v-if="firstLoading" :repeat="6" height="42px" />
      <n-spin v-else :show="loading">
        <n-data-table
          :columns="columns"
          :data="list"
          :pagination="false"
          :scroll-x="1200"
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

    <!-- 文件夹新建/重命名弹窗 -->
    <n-modal v-model:show="folderModalShow" preset="card" :title="editingFolder ? '重命名文件夹' : '新建文件夹'" style="width: 400px">
      <n-input v-model:value="folderName" placeholder="文件夹名称（1~50 字）" maxlength="50" show-count />
      <template #footer>
        <div class="modal-actions">
          <n-button @click="folderModalShow = false">取消</n-button>
          <n-button class="gradient-btn" :loading="folderSaving" @click="handleFolderSave">保存</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 执行确认弹窗（复用 4.4.7） -->
    <ExecuteModal
      v-model:show="executeShow"
      :main-table="executingCase?.main_table ?? ''"
      :related-tables="executingRelated"
      :iterate-info="executingIterate"
      :initial-name="executingCase?.case_name ?? ''"
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
          <n-data-table :columns="historyColumns" :data="historyList" size="small" :pagination="{ pageSize: 10 }" :scroll-x="660" />
          <EmptyState v-if="!historyLoading && historyList.length === 0" description="还没有执行记录" />
          <div v-if="historyList.length > 0" class="history-stats">
            总执行 {{ historyList.length }} 次 · 成功 {{ historyList.filter((h) => h.status === 2).length }} 次 ·
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
import { EllipsisHorizontalOutline, FolderOpenOutline, FolderOutline } from '@vicons/ionicons5'
import { NButton, NTag, type DataTableColumns } from 'naive-ui'
import { casesApi } from '@/api/cases'
import { datasourceApi } from '@/api/datasource'
import { usersApi } from '@/api/users'
import type { CaseFolder, CaseHistoryItem, CaseItem, ExecStatusCode, FolderListResult, LastExecStatusCode } from '@/api/types'
import ExecuteModal from '@/components/business/ExecuteModal.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { useTaskProgress } from '@/composables/useTaskProgress'
import { formatDateTimeMin, formatDurationMs, formatNumber } from '@/utils/formatter'

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
  status: [] as number[],
  timeRange: null as [number, number] | null,
})

const hasFilter = computed(
  () => !!(filters.datasourceId || filters.name || filters.createdBy || filters.status.length || filters.timeRange),
)

const datasourceOptions = ref<Array<{ label: string; value: number }>>([])
const memberOptions = ref<Array<{ label: string; value: number }>>([])

// ---------------- 文件夹收纳 ----------------
/** 当前选中文件夹：all=全部 / unfiled=未分类 / 数字=文件夹ID */
const activeFolder = ref<number | 'all' | 'unfiled'>('all')
const folderData = ref<FolderListResult | null>(null)
const folderModalShow = ref(false)
const folderSaving = ref(false)
const folderName = ref('')
const editingFolder = ref<CaseFolder | null>(null)
const moveTarget = ref<number | null>(null) // -1 = 未分类

const folderMenu = [
  { label: '重命名', key: 'rename' },
  { label: '删除', key: 'delete', props: { style: 'color:#ef4444' } },
]

/** 移动目标选项（-1=未分类） */
const moveOptions = computed(() => [
  { label: '未分类', value: -1 },
  ...(folderData.value?.folders ?? []).map((f) => ({ label: f.name, value: f.id })),
])

async function loadFolders(): Promise<void> {
  try {
    const res = await casesApi.folders()
    folderData.value = res.data
  } catch {
    // 文件夹加载失败不阻塞列表
  }
}

/** 切换文件夹：过滤列表 */
function selectFolder(key: number | 'all' | 'unfiled'): void {
  activeFolder.value = key
  loadList(1)
}

function openFolderModal(folder?: CaseFolder): void {
  editingFolder.value = folder ?? null
  folderName.value = folder?.name ?? ''
  folderModalShow.value = true
}

async function handleFolderSave(): Promise<void> {
  const name = folderName.value.trim()
  if (!name) {
    window.$message.error('请输入文件夹名称')
    return
  }
  folderSaving.value = true
  try {
    if (editingFolder.value) {
      await casesApi.renameFolder(editingFolder.value.id, name)
    } else {
      await casesApi.createFolder(name)
    }
    window.$message.success('已保存')
    folderModalShow.value = false
    await loadFolders()
  } finally {
    folderSaving.value = false
  }
}

/** 文件夹操作（重命名/删除） */
function onFolderAction(key: string, folder: CaseFolder): void {
  if (key === 'rename') {
    openFolderModal(folder)
    return
  }
  window.$dialog.warning({
    title: '确认删除文件夹',
    content: `删除文件夹「${folder.name}」？其中 ${folder.case_count} 个 Case 将移到未分类（Case 本身不删除）。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await casesApi.removeFolder(folder.id)
      window.$message.success('已删除')
      if (activeFolder.value === folder.id) activeFolder.value = 'all'
      await Promise.all([loadFolders(), loadList()])
    },
  })
}

/** 批量移动到文件夹 */
async function handleBatchMove(): Promise<void> {
  if (!selectedIds.value.length || moveTarget.value === null) return
  await casesApi.batchMove(selectedIds.value, moveTarget.value === -1 ? null : moveTarget.value)
  window.$message.success('已移动')
  moveTarget.value = null
  await Promise.all([loadFolders(), loadList()])
}
// 最后执行状态摘要码：0未执行 1成功 2失败 3部分成功
const statusOptions = [
  { label: '成功', value: 1 },
  { label: '失败', value: 2 },
  { label: '未执行', value: 0 },
]

/** Case 列表「最后执行状态」标签（摘要码 0~3） */
function statusTag(status: LastExecStatusCode | null) {
  const map: Record<number, { text: string; type: 'default' | 'success' | 'error' | 'warning' }> = {
    0: { text: '未执行', type: 'default' },
    1: { text: '成功', type: 'success' },
    2: { text: '失败', type: 'error' },
    3: { text: '部分成功', type: 'warning' },
  }
  const s = map[status ?? 0] ?? map[0]!
  return h(NTag, { size: 'small', type: s.type }, () => s.text)
}

/** 执行历史状态标签（完整码 0~6）：0待执行 1执行中 2成功 3失败 4重试中 5部分成功 6已中止 */
function execStatusTag(status: ExecStatusCode) {
  const map: Record<number, { text: string; type: 'default' | 'success' | 'error' | 'warning' | 'info' }> = {
    0: { text: '待执行', type: 'default' },
    1: { text: '执行中', type: 'info' },
    2: { text: '成功', type: 'success' },
    3: { text: '失败', type: 'error' },
    4: { text: '重试中', type: 'warning' },
    5: { text: '部分成功', type: 'warning' },
    6: { text: '已中止', type: 'default' },
  }
  const s = map[status] ?? { text: String(status), type: 'default' as const }
  return h(NTag, { size: 'small', type: s.type }, () => s.text)
}

const columns: DataTableColumns<CaseItem> = [
  { type: 'selection' },
  {
    title: 'Case 名称',
    key: 'case_name',
    minWidth: 170,
    ellipsis: { tooltip: true },
    render: (row) =>
      h(
        'a',
        { style: 'color:#a78bfa;cursor:pointer;font-weight:600', onClick: () => router.push(`/cases/${row.id}`) },
        row.case_name,
      ),
  },
  { title: '数据源', key: 'datasource_name', width: 110, ellipsis: { tooltip: true } },
  { title: '主表', key: 'main_table', width: 150, ellipsis: { tooltip: true } },
  { title: '关联表数', key: 'related_count', width: 78 },
  { title: '创建人', key: 'creator_name', width: 76 },
  { title: '创建时间', key: 'created_at', width: 130, render: (r) => formatDateTimeMin(r.created_at) },
  {
    title: '最后执行时间',
    key: 'last_exec_at',
    width: 130,
    render: (r) => (r.last_exec_at ? formatDateTimeMin(r.last_exec_at) : h('span', { style: 'color:#64748b' }, '未执行')),
  },
  { title: '最后执行状态', key: 'last_exec_status', width: 110, render: (r) => statusTag(r.last_exec_status) },
  {
    title: '操作',
    key: 'actions',
    width: 210,
    fixed: 'right',
    render: (row) => {
      const btns = []
      if (hasPermission('CASE:EXECUTE')) {
        btns.push(h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => openExecute(row) }, () => '执行'))
      }
      if (hasPermission('CASE:EDIT')) {
        btns.push(
          h(
            NButton,
            { text: true, size: 'small', onClick: () => {
              // Redis 造数 Case（main_table 为 redis: 前缀展示名）走 Redis 配置页
              if (row.main_table?.startsWith('redis:')) {
                router.push({ name: 'RedisConfig', query: { datasource_id: row.datasource_id, case_id: row.id } })
              } else {
                router.push({ name: 'EngineConfig', params: { tableName: row.main_table }, query: { datasource_id: row.datasource_id, case_id: row.id } })
              }
            } },
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
      // 文件夹过滤：all 不过滤 / unfiled 未分类 / 数字 指定文件夹
      folder_id: typeof activeFolder.value === 'number' ? activeFolder.value : undefined,
      unfiled: activeFolder.value === 'unfiled' ? true : undefined,
    })
    list.value = res.data.items ?? []
    total.value = res.data.total ?? 0
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
  const cfg = res.data.config
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
  copyName.value = `${row.case_name}_copy`
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
    content: `确认删除 Case「${row.case_name}」？删除后不可恢复，历史执行记录将保留。`,
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
    .map((c) => ({ case_id: c.id, name: c.case_name, target_count: 1000 }))
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
    // 每个 Case 生成独立任务（task_nos 与请求 items 同序），全部纳入进度管理
    res.data.task_nos.forEach((taskNo, idx) => {
      trackTask(taskNo, batchItems.value[idx]?.name ?? '')
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
  { title: '执行时间', key: 'start_at', width: 160, render: (r) => formatDateTimeMin(r.start_at) },
  { title: '造数条数', key: 'target_count', width: 110, render: (r) => formatNumber(r.target_count) },
  { title: '实际插入', key: 'success_count', width: 110, render: (r) => formatNumber(r.success_count) },
  { title: '状态', key: 'status', width: 100, render: (r) => execStatusTag(r.status) },
  { title: '耗时', key: 'duration_ms', width: 90, render: (r) => formatDurationMs(r.duration_ms) },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render: (r) => h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => router.push({ path: '/overview', query: { task_no: r.task_no } }) }, () => '查看详情'),
  },
]

async function openHistory(row: CaseItem): Promise<void> {
  historyCaseName.value = row.case_name
  historyShow.value = true
  historyLoading.value = true
  try {
    const res = await casesApi.history(row.id)
    historyList.value = res.data.items ?? []
  } finally {
    historyLoading.value = false
  }
}

onMounted(async () => {
  loadList(1)
  loadFolders()
  try {
    const [dsRes, userRes] = await Promise.all([
      datasourceApi.list(),
      usersApi.members().catch(() => null),
    ])
    datasourceOptions.value = dsRes.data.map((d) => ({ label: d.name, value: d.id }))
    if (userRes) memberOptions.value = (userRes.data ?? []).map((u) => ({ label: u.real_name ?? u.username, value: u.id }))
  } catch {
    // 下拉数据失败不阻塞页面
  }
})
</script>

<style scoped>
.case-list-page {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
/* 左侧文件夹栏 */
.folder-panel {
  width: 184px;
  flex-shrink: 0;
  padding: 12px;
  position: sticky;
  top: 0;
}
.folder-title {
  font-size: 13px;
  font-weight: 600;
  color: #94a3b8;
  padding: 0 8px 8px;
}
.folder-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: calc(100vh - 220px);
  overflow-y: auto;
}
.folder-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: #cbd5e1;
  transition: background 0.15s;
}
.folder-item:hover {
  background: rgba(124, 58, 237, 0.1);
}
.folder-item.active {
  background: rgba(124, 58, 237, 0.18);
  color: #a78bfa;
}
.folder-icon {
  color: #64748b;
  flex-shrink: 0;
}
.folder-item.active .folder-icon {
  color: #a78bfa;
}
.folder-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.folder-count {
  font-size: 11px;
  color: #64748b;
  background: rgba(148, 163, 184, 0.1);
  border-radius: 8px;
  padding: 0 6px;
  flex-shrink: 0;
}
.folder-more {
  color: #64748b;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}
.folder-item:hover .folder-more {
  opacity: 1;
}
.folder-add {
  margin-top: 8px;
  padding: 7px 8px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  font-size: 13px;
  color: #a78bfa;
  cursor: pointer;
  text-align: center;
}
.folder-add:hover {
  background: rgba(124, 58, 237, 0.1);
  border-radius: 6px;
}
/* 右侧列表 */
.list-card {
  flex: 1;
  min-width: 0;
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
  align-items: center;
}
.move-group {
  display: flex;
  gap: 6px;
  margin-left: auto;
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
