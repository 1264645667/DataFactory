<template>
  <!-- 场景列表页（PRD 6.2/6.5） -->
  <div class="scene-list-page">
    <div class="gradient-border-card list-card">
      <!-- 筛选条件行 -->
      <div class="filter-row">
        <n-input v-model:value="filters.name" size="small" clearable placeholder="场景名称搜索" style="width: 180px" @keydown.enter="loadList(1)" @clear="loadList(1)" />
        <n-select v-model:value="filters.createdBy" :options="memberOptions" clearable size="small" placeholder="创建人" style="width: 140px" @update:value="loadList(1)" />
        <n-select v-model:value="filters.status" :options="statusOptions" multiple clearable size="small" placeholder="最后执行状态" style="width: 200px" @update:value="loadList(1)" />
        <n-date-picker v-model:value="filters.timeRange" type="daterange" size="small" clearable style="width: 260px" @update:value="loadList(1)" />
        <n-button size="small" class="gradient-btn" @click="loadList(1)">查询</n-button>
      </div>

      <!-- 操作按钮行 -->
      <div class="op-row">
        <n-button v-if="hasPermission('SCENE:CREATE')" size="small" class="gradient-btn" @click="router.push('/scenes/editor')">
          + 新建场景
        </n-button>
        <n-button size="small" type="error" ghost :disabled="selectedIds.length === 0" @click="handleBatchDelete">批量删除</n-button>
      </div>

      <!-- 场景列表 -->
      <n-skeleton v-if="firstLoading" :repeat="6" height="42px" />
      <n-spin v-else :show="loading">
        <n-data-table
          :columns="columns"
          :data="list"
          :pagination="false"
          size="small"
          :row-key="(row: SceneItem) => row.id"
          :checked-row-keys="selectedIds"
          @update:checked-row-keys="(keys: number[]) => (selectedIds = keys)"
        />
        <EmptyState
          v-if="!loading && list.length === 0"
          :description="hasFilter ? '没有符合条件的数据，小猫在打盹～' : '还没有场景，把多个 Case 编排成一键执行流程吧'"
          :button-text="hasFilter ? '清空筛选' : ''"
          @action="clearFilters"
        />
        <div class="pager">
          <n-pagination v-model:page="page" :item-count="total" :page-size="pageSize" @update:page="loadList" />
        </div>
      </n-spin>
    </div>

    <!-- 执行确认弹窗（PRD 6.4.2：执行计划预览） -->
    <n-modal v-model:show="executeShow" preset="card" title="准备执行场景" style="width: 560px">
      <n-spin :show="planLoading">
        <n-descriptions :column="2" size="small" label-placement="left">
          <n-descriptions-item label="场景名称">{{ executingScene?.name }}</n-descriptions-item>
          <n-descriptions-item label="节点数量">{{ planLayers.flat().length }} 个 Case</n-descriptions-item>
        </n-descriptions>
        <div class="plan-preview">
          <div class="plan-title">执行计划预览</div>
          <div v-for="(layer, li) in planLayers" :key="li" class="plan-layer">
            <div class="plan-layer-title">
              第 {{ li + 1 }} 批{{ layer.length > 1 ? '（并行' + (li > 0 ? '，等待第' + li + '批完成' : '') + '）' : li > 0 ? '（等待第' + li + '批完成）' : '' }}
            </div>
            <div v-for="node in layer" :key="node.node_id" class="plan-node">
              ├─ Case「{{ node.case_name }}」 → {{ formatNumber(node.target_count) }} 条
            </div>
          </div>
          <div class="plan-total">
            总计：{{ planLayers.flat().length }} 个 Case，共
            {{ formatNumber(planLayers.flat().reduce((s, n) => s + (n.target_count ?? 0), 0)) }} 条数据
          </div>
        </div>
        <n-alert type="info" class="mt-3" :show-icon="false">注意：操作不可逆，请确认目标数据源和条数</n-alert>
      </n-spin>
      <template #footer>
        <div class="modal-actions">
          <n-button @click="executeShow = false">取消</n-button>
          <n-button class="gradient-btn" :loading="executing" @click="handleExecute">确认执行</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 复制弹窗 -->
    <n-modal v-model:show="copyShow" preset="card" title="复制场景" style="width: 420px">
      <n-input v-model:value="copyName" placeholder="新场景名称" />
      <template #footer>
        <div class="modal-actions">
          <n-button @click="copyShow = false">取消</n-button>
          <n-button class="gradient-btn" :loading="copying" @click="handleCopy">确认</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 执行历史抽屉 -->
    <n-drawer v-model:show="historyShow" :width="720" placement="right">
      <n-drawer-content :title="`执行历史 · ${historySceneName}`" closable>
        <n-spin :show="historyLoading">
          <n-data-table :columns="historyColumns" :data="historyList" size="small" :pagination="{ pageSize: 10 }" />
          <EmptyState v-if="!historyLoading && historyList.length === 0" description="还没有执行记录" />
        </n-spin>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NTag, type DataTableColumns } from 'naive-ui'
import { scenesApi } from '@/api/scenes'
import { usersApi } from '@/api/users'
import type { SceneHistoryItem, SceneItem, SceneNode, SceneStatus } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { useSceneProgress } from '@/composables/useSceneProgress'
import { buildLayers } from '@/utils/dag'
import { formatDateTimeMin, formatDuration, formatNumber } from '@/utils/formatter'

const router = useRouter()
const { hasPermission } = useAuth()
const { trackScene } = useSceneProgress()

const list = ref<SceneItem[]>([])
const loading = ref(false)
const firstLoading = ref(true)
const page = ref(1)
const pageSize = 20
const total = ref(0)
const selectedIds = ref<number[]>([])

const filters = reactive({
  name: '',
  createdBy: null as number | null,
  status: [] as string[],
  timeRange: null as [number, number] | null,
})

const hasFilter = computed(() => !!(filters.name || filters.createdBy || filters.status.length || filters.timeRange))
const memberOptions = ref<Array<{ label: string; value: number }>>([])
const statusOptions = [
  { label: '成功', value: 'success' },
  { label: '失败', value: 'failed' },
  { label: '部分成功', value: 'partial_success' },
  { label: '未执行', value: 'none' },
]

const EXEC_MODE_TEXT: Record<string, string> = { serial: '纯串行', parallel: '含并行', mixed: '混合' }

function statusTag(status: SceneStatus | null) {
  if (!status) return h(NTag, { size: 'small' }, () => '未执行')
  const map: Record<string, { type: 'success' | 'warning' | 'info' | 'error'; text: string }> = {
    success: { type: 'success', text: '成功' },
    failed: { type: 'error', text: '失败' },
    partial_success: { type: 'warning', text: '部分成功' },
    running: { type: 'info', text: '执行中' },
    aborted: { type: 'error', text: '已中止' },
  }
  const s = map[status] ?? { type: 'info' as const, text: status }
  return h(NTag, { size: 'small', type: s.type }, () => s.text)
}

const columns: DataTableColumns<SceneItem> = [
  { type: 'selection' },
  {
    title: '场景名称',
    key: 'name',
    width: 200,
    render: (row) =>
      h('a', { style: 'color:#a78bfa;cursor:pointer;font-weight:600', onClick: () => router.push(`/scenes/${row.id}`) }, row.name),
  },
  { title: '包含 Case 数', key: 'node_count', width: 100 },
  { title: '执行模式', key: 'exec_mode', width: 100, render: (r) => EXEC_MODE_TEXT[r.exec_mode] ?? r.exec_mode },
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
      if (hasPermission('SCENE:EXECUTE')) {
        btns.push(h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => openExecute(row) }, () => '执行'))
      }
      if (hasPermission('SCENE:EDIT')) {
        btns.push(h(NButton, { text: true, size: 'small', onClick: () => router.push(`/scenes/editor/${row.id}`) }, () => '编辑'))
      }
      if (hasPermission('SCENE:CREATE')) {
        btns.push(h(NButton, { text: true, size: 'small', onClick: () => openCopy(row) }, () => '复制'))
      }
      btns.push(h(NButton, { text: true, size: 'small', onClick: () => openHistory(row) }, () => '历史'))
      if (hasPermission('SCENE:DELETE')) {
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
    const res = await scenesApi.list({
      page: page.value,
      page_size: pageSize,
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
  filters.name = ''
  filters.createdBy = null
  filters.status = []
  filters.timeRange = null
  loadList(1)
}

// ---------------- 执行场景 ----------------
const executeShow = ref(false)
const planLoading = ref(false)
const executing = ref(false)
const executingScene = ref<SceneItem | null>(null)
const planLayers = ref<SceneNode[][]>([])

/** 打开执行确认弹窗：拉取场景详情，前端拓扑分层生成执行计划预览 */
async function openExecute(row: SceneItem): Promise<void> {
  executingScene.value = row
  executeShow.value = true
  planLoading.value = true
  try {
    const res = await scenesApi.detail(row.id)
    const nodes = res.data.nodes_json
    const edges = res.data.edges_json
    const layers = buildLayers(nodes.map((n) => n.node_id), edges)
    planLayers.value = layers.map((layer) => layer.map((id) => nodes.find((n) => n.node_id === id)!).filter(Boolean))
  } catch (e) {
    executeShow.value = false
  } finally {
    planLoading.value = false
  }
}

async function handleExecute(): Promise<void> {
  if (!executingScene.value) return
  executing.value = true
  try {
    const res = await scenesApi.execute(executingScene.value.id)
    executeShow.value = false
    trackScene(res.data.scene_exec_no, executingScene.value.name)
    loadList()
  } finally {
    executing.value = false
  }
}

// ---------------- 复制 ----------------
const copyShow = ref(false)
const copying = ref(false)
const copyName = ref('')
const copyTarget = ref<SceneItem | null>(null)

function openCopy(row: SceneItem): void {
  copyTarget.value = row
  copyName.value = `${row.name}_copy`
  copyShow.value = true
}

async function handleCopy(): Promise<void> {
  if (!copyTarget.value || !copyName.value.trim()) return
  copying.value = true
  try {
    await scenesApi.copy(copyTarget.value.id, copyName.value.trim())
    copyShow.value = false
    window.$message.success('复制成功')
    loadList()
  } finally {
    copying.value = false
  }
}

// ---------------- 删除 ----------------
function handleDelete(row: SceneItem): void {
  window.$dialog.warning({
    title: '确认删除',
    content: `确认删除场景「${row.name}」？删除后不可恢复，历史执行记录将保留。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await scenesApi.remove(row.id)
      window.$message.success('已删除')
      loadList()
    },
  })
}

function handleBatchDelete(): void {
  window.$dialog.warning({
    title: '确认批量删除',
    content: `确认删除选中的 ${selectedIds.value.length} 个场景？删除后不可恢复，历史执行记录将保留。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await Promise.all(selectedIds.value.map((id) => scenesApi.remove(id)))
      window.$message.success('已批量删除')
      loadList()
    },
  })
}

// ---------------- 执行历史 ----------------
const historyShow = ref(false)
const historyLoading = ref(false)
const historyList = ref<SceneHistoryItem[]>([])
const historySceneName = ref('')

const historyColumns: DataTableColumns<SceneHistoryItem> = [
  { title: '执行编号', key: 'scene_exec_no', width: 160 },
  { title: '执行时间', key: 'started_at', width: 140, render: (r) => formatDateTimeMin(r.started_at) },
  { title: '节点数', key: 'node_count', width: 70 },
  { title: '成功节点', key: 'success_nodes', width: 80 },
  { title: '失败节点', key: 'fail_nodes', width: 80 },
  { title: '总造数条数', key: 'total_rows', width: 110, render: (r) => formatNumber(r.total_rows) },
  { title: '状态', key: 'status', width: 100, render: (r) => statusTag(r.status) },
  { title: '耗时', key: 'duration_seconds', width: 80, render: (r) => formatDuration(r.duration_seconds) },
  { title: '操作人', key: 'created_by_name', width: 80 },
]

async function openHistory(row: SceneItem): Promise<void> {
  historySceneName.value = row.name
  historyShow.value = true
  historyLoading.value = true
  try {
    const res = await scenesApi.history(row.id, { page: 1, page_size: 50 })
    historyList.value = res.data.list
  } finally {
    historyLoading.value = false
  }
}

onMounted(async () => {
  loadList(1)
  try {
    const userRes = await usersApi.list({ page: 1, page_size: 100 }).catch(() => null)
    if (userRes) memberOptions.value = userRes.data.list.map((u) => ({ label: u.real_name, value: u.id }))
  } catch {
    // 忽略
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
.plan-preview {
  margin-top: 12px;
  border: 1px solid rgba(124, 58, 237, 0.25);
  border-radius: 8px;
  padding: 12px 14px;
  background: rgba(124, 58, 237, 0.05);
  font-size: 13px;
}
.plan-title {
  font-weight: 600;
  color: #a78bfa;
  margin-bottom: 8px;
}
.plan-layer {
  margin-bottom: 8px;
}
.plan-layer-title {
  color: #94a3b8;
  font-size: 12px;
  margin-bottom: 4px;
}
.plan-node {
  padding-left: 12px;
  padding: 2px 0 2px 12px;
  color: #e2e8f0;
}
.plan-total {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed rgba(148, 163, 184, 0.2);
  font-weight: 600;
  color: #c4b5fd;
}
.mt-3 {
  margin-top: 12px;
}
</style>
