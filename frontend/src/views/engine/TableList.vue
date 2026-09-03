<template>
  <!-- 造数引擎 · 表列表页 -->
  <div class="engine-page">
    <!-- 数据源选择栏（吸顶） -->
    <div class="ds-bar glass-card">
      <span class="ds-label">数据源</span>
      <n-select
        :value="currentId"
        :options="dsOptions"
        style="width: 220px"
        size="small"
        @update:value="handleSelect"
      />
      <!-- 连接状态指示灯 -->
      <span class="ds-status">
        <span class="status-light" :class="statusLightClass" />
        {{ statusText }}
      </span>
      <span class="ds-sync-time">表结构最后同步于 {{ formatDateTime(current?.last_sync_at) }}</span>
      <n-button size="small" :loading="syncing" class="gradient-btn" @click="handleSync">立即刷新</n-button>
    </div>

    <!-- Redis 数据源：无表结构，进入 Redis 造数配置 -->
    <div v-if="isRedisDs" class="table-card gradient-border-card redis-entry">
      <n-icon size="40" color="#f59e0b"><FlashOutline /></n-icon>
      <h3>Redis 造数</h3>
      <p class="dim">
        当前数据源为 Redis（db{{ current?.database_name ?? 0 }}），无需表结构同步。
        通过 Key 模板 + 字段策略直接造数，支持 string/json/hash/list/set/zset，
        支持「每行一个 Key」与「聚合单 Key」两种模式。
      </p>
      <n-button class="gradient-btn" size="small" @click="goRedisConfig">新建 Redis 造数 Case</n-button>
    </div>

    <!-- 表列表 -->
    <div v-else class="table-card gradient-border-card">
      <div class="table-toolbar">
        <n-input
          v-model:value="keyword"
          size="small"
          clearable
          placeholder="搜索表名或备注"
          style="width: 240px"
        >
          <template #prefix><n-icon><SearchOutline /></n-icon></template>
        </n-input>
        <n-radio-group v-model:value="sortBy" size="small">
          <n-radio-button value="name">字母序</n-radio-button>
          <n-radio-button value="rows">数据量</n-radio-button>
          <n-radio-button value="columns">字段数</n-radio-button>
        </n-radio-group>
      </div>

      <!-- 首次加载骨架屏 -->
      <n-skeleton v-if="firstLoading" :repeat="6" height="44px" />
      <n-spin v-else :show="loading">
        <n-data-table
          :columns="columns"
          :data="pagedTables"
          :pagination="false"
          size="small"
          :row-props="rowProps"
        />
        <EmptyState v-if="!loading && filteredTables.length === 0" description="暂无数据，小猫在打盹～" />
        <div class="pager">
          <n-pagination
            v-model:page="page"
            v-model:page-size="pageSize"
            :item-count="filteredTables.length"
            :page-sizes="[20, 50, 100]"
            show-size-picker
          />
        </div>
      </n-spin>
    </div>

    <!-- 查看已有 Case 弹窗 -->
    <n-modal v-model:show="casesModalShow" preset="card" :title="`以 ${activeTable} 为主表的 Case`" style="width: 720px; max-width: 92vw">
      <n-spin :show="casesLoading">
        <n-data-table :columns="caseColumns" :data="relatedCases" size="small" :pagination="{ pageSize: 8 }" />
        <EmptyState v-if="!casesLoading && relatedCases.length === 0" description="该表还没有 Case，去配置一个吧" />
      </n-spin>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { SearchOutline, FlashOutline } from '@vicons/ionicons5'
import { NButton, NIcon, NTag, type DataTableColumns } from 'naive-ui'
import { engineApi } from '@/api/engine'
import { casesApi } from '@/api/cases'
import { datasourceApi } from '@/api/datasource'
import type { CaseItem, TableInfo } from '@/api/types'
import { useDatasource } from '@/composables/useDatasource'
import { formatDateTime, formatNumber } from '@/utils/formatter'
import EmptyState from '@/components/common/EmptyState.vue'

const router = useRouter()
const { list, current, currentId, init, select, refreshStatus, startStatusPolling } = useDatasource()

const tables = ref<TableInfo[]>([])
const loading = ref(false)
const firstLoading = ref(true)
const syncing = ref(false)
const keyword = ref('')
const sortBy = ref<'name' | 'rows' | 'columns'>('name')
const page = ref(1)
const pageSize = ref(20)

const dsOptions = computed(() => list.value.map((d) => ({ label: d.name, value: d.id })))

/** 当前数据源是否为 Redis 类型（切换到 Redis 时展示造数入口而非表列表） */
const isRedisDs = computed(() => (current.value?.db_type || '').toLowerCase() === 'redis')

/** 进入 Redis 造数配置页 */
function goRedisConfig(): void {
  router.push({ name: 'RedisConfig', query: { datasource_id: currentId.value } })
}

// 连接状态灯：status=3 为同步中；其余看心跳 online（true 在线 / false 离线 / null 未检测）
const statusText = computed(() => {
  const d = current.value
  if (!d) return '未知'
  if (d.status === 3) return '同步中'
  if (d.online === true) return '在线'
  if (d.online === false) return '离线'
  return '未检测'
})
const statusLightClass = computed(() => {
  const d = current.value
  if (!d || d.online == null) return 'light-red'
  if (d.status === 3) return 'light-yellow'
  return d.online ? 'light-green' : 'light-red'
})

// 本地过滤 + 排序（搜索本地过滤无需请求后端）
const filteredTables = computed(() => {
  let data = tables.value
  const kw = keyword.value.trim().toLowerCase()
  if (kw) {
    data = data.filter(
      (t) => t.table_name.toLowerCase().includes(kw) || (t.table_comment ?? '').toLowerCase().includes(kw),
    )
  }
  const sorted = [...data]
  if (sortBy.value === 'name') sorted.sort((a, b) => a.table_name.localeCompare(b.table_name))
  else if (sortBy.value === 'rows') sorted.sort((a, b) => b.table_rows - a.table_rows)
  else sorted.sort((a, b) => b.column_count - a.column_count)
  return sorted
})

const pagedTables = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredTables.value.slice(start, start + pageSize.value)
})

const PK_TYPE_TEXT: Record<string, string> = { none: '无主键', single: '单主键', composite: '联合主键' }

const columns: DataTableColumns<TableInfo> = [
  {
    title: '表名',
    key: 'table_name',
    render: (row) =>
      h('a', { style: 'color:#a78bfa;cursor:pointer;font-weight:600', onClick: () => goConfig(row.table_name) }, row.table_name),
  },
  { title: '中文备注', key: 'table_comment', render: (r) => r.table_comment || '-', ellipsis: { tooltip: true } },
  { title: '数据量（估算）', key: 'table_rows', width: 130, render: (r) => formatNumber(r.table_rows) },
  { title: '字段数', key: 'column_count', width: 90 },
  { title: '主键类型', key: 'pk_type', width: 100, render: (r) => PK_TYPE_TEXT[r.pk_type] ?? '-' },
  { title: '唯一索引数', key: 'unique_index_count', width: 100 },
  { title: '最后同步', key: 'synced_at', width: 160, render: (r) => formatDateTime(r.synced_at) },
  {
    title: '操作',
    key: 'actions',
    width: 190,
    render: (row) =>
      h('div', { style: 'display:flex;gap:10px' }, [
        h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => goConfig(row.table_name) }, () => '进入配置'),
        h(NButton, { text: true, size: 'small', onClick: () => openRelatedCases(row.table_name) }, () => '查看已有 Case'),
      ]),
  },
]

function rowProps(): { style: string } {
  return { style: 'cursor:default' }
}

async function loadTables(): Promise<void> {
  if (!currentId.value) return
  if (isRedisDs.value) {
    // Redis 数据源无表结构，跳过表列表加载
    tables.value = []
    firstLoading.value = false
    return
  }
  loading.value = true
  try {
    const res = await engineApi.tables(currentId.value)
    tables.value = res.data
    page.value = 1
  } finally {
    loading.value = false
    firstLoading.value = false
  }
}

function handleSelect(id: number): void {
  select(id)
}

// 切换数据源后立即刷新表列表 + 重启心跳轮询
watch(currentId, (id) => {
  if (id != null) {
    loadTables()
    startStatusPolling(id)
  }
})

/** 手动触发表结构同步（加锁防重复由后端处理） */
async function handleSync(): Promise<void> {
  if (!currentId.value) return
  syncing.value = true
  try {
    await datasourceApi.sync(currentId.value)
    window.$message.success('同步任务已触发，稍候自动刷新')
    setTimeout(async () => {
      await refreshStatus(currentId.value!)
      await loadTables()
    }, 4000)
  } finally {
    syncing.value = false
  }
}

function goConfig(tableName: string): void {
  router.push({ name: 'EngineConfig', params: { tableName }, query: { datasource_id: currentId.value } })
}

// ---------------- 查看已有 Case ----------------
const casesModalShow = ref(false)
const casesLoading = ref(false)
const relatedCases = ref<CaseItem[]>([])
const activeTable = ref('')

const caseColumns: DataTableColumns<CaseItem> = [
  { title: 'Case 名称', key: 'case_name', render: (r) => h('a', { style: 'color:#a78bfa;cursor:pointer', onClick: () => router.push(`/cases/${r.id}`) }, r.case_name) },
  { title: '创建人', key: 'creator_name', width: 100 },
  { title: '创建时间', key: 'created_at', width: 150, render: (r) => formatDateTime(r.created_at) },
  {
    title: '最后执行状态',
    key: 'last_exec_status',
    width: 110,
    render: (r) => {
      // 摘要码：0未执行 1成功 2失败 3部分成功
      if (r.last_exec_status == null || r.last_exec_status === 0) return h(NTag, { size: 'small' }, () => '未执行')
      const map: Record<number, { type: 'success' | 'warning' | 'error'; text: string }> = {
        1: { type: 'success', text: '成功' },
        2: { type: 'error', text: '失败' },
        3: { type: 'warning', text: '部分成功' },
      }
      const s = map[r.last_exec_status] ?? { type: 'error' as const, text: String(r.last_exec_status) }
      return h(NTag, { size: 'small', type: s.type }, () => s.text)
    },
  },
]

async function openRelatedCases(tableName: string): Promise<void> {
  activeTable.value = tableName
  casesModalShow.value = true
  casesLoading.value = true
  try {
    const res = await casesApi.list({ page: 1, page_size: 100, datasource_id: currentId.value ?? undefined, main_table: tableName })
    relatedCases.value = res.data.items ?? []
  } finally {
    casesLoading.value = false
  }
}

onMounted(async () => {
  await init()
  if (currentId.value != null) {
    await loadTables()
    startStatusPolling(currentId.value)
  }
  firstLoading.value = currentId.value == null ? false : firstLoading.value
})
</script>

<style scoped>
.engine-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
/* 数据源选择栏吸顶 */
.ds-bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 18px;
}
.ds-label {
  font-size: 13px;
  color: #94a3b8;
}
.ds-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #94a3b8;
}
.status-light {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.light-green { background: #22c55e; box-shadow: 0 0 8px #22c55e; }
.light-red { background: #ef4444; box-shadow: 0 0 8px #ef4444; }
.light-yellow { background: #f59e0b; box-shadow: 0 0 8px #f59e0b; animation: pulse 1.2s infinite; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.ds-sync-time {
  font-size: 12px;
  color: #64748b;
  flex: 1;
}
.table-card {
  padding: 16px;
}
.table-toolbar {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.redis-entry {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 48px 20px;
  text-align: center;
}
.redis-entry h3 {
  margin: 0;
  color: #e2e8f0;
}
.redis-entry p {
  max-width: 520px;
  margin: 0 0 8px;
  line-height: 1.8;
}
</style>
