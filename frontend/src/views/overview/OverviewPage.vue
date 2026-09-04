<template>
  <!-- 造数总览：指标卡片 + 趋势折线 + 状态饼图 + Top10 柱状 + 成员条形 + 执行记录明细 -->
  <div class="overview-page">
    <!-- 指标卡片行 -->
    <n-spin :show="metricsLoading">
      <div class="metrics-row">
        <div v-for="card in metricCards" :key="card.key" class="metric-card gradient-border-card">
          <div class="metric-head">
            <span class="metric-name">{{ card.name }}</span>
            <n-icon :size="18" :color="card.color"><component :is="card.icon" /></n-icon>
          </div>
          <div class="metric-value">{{ card.value }}</div>
          <div class="metric-delta" v-if="card.delta != null">
            <span :class="card.delta >= 0 ? 'delta-up' : 'delta-down'">
              较昨日 {{ card.delta >= 0 ? '↑' : '↓' }} {{ Math.abs(card.delta) }}
            </span>
          </div>
        </div>
      </div>
    </n-spin>

    <!-- 图表区 -->
    <div class="charts-row">
      <div class="chart-card gradient-border-card" style="flex: 6">
        <div class="chart-head">
          <span class="chart-title">执行趋势</span>
          <n-radio-group v-model:value="trendDays" size="small" @update:value="loadCharts">
            <n-radio-button :value="7">近 7 天</n-radio-button>
            <n-radio-button :value="30">近 30 天</n-radio-button>
            <n-radio-button :value="90">近 90 天</n-radio-button>
          </n-radio-group>
        </div>
        <div v-if="!trendData.length && !chartsLoading" class="chart-empty">暂无数据</div>
        <div ref="trendRef" class="chart-body" />
      </div>
      <div class="chart-card gradient-border-card" style="flex: 4">
        <div class="chart-head"><span class="chart-title">执行状态分布</span></div>
        <div v-if="!statusData.length && !chartsLoading" class="chart-empty">暂无数据</div>
        <div ref="pieRef" class="chart-body" />
      </div>
    </div>
    <div class="charts-row">
      <div class="chart-card gradient-border-card" style="flex: 1">
        <div class="chart-head"><span class="chart-title">表操作量 Top10</span></div>
        <div v-if="!top10Data.length && !chartsLoading" class="chart-empty">暂无数据</div>
        <div ref="top10Ref" class="chart-body" />
      </div>
      <div class="chart-card gradient-border-card" style="flex: 1">
        <div class="chart-head"><span class="chart-title">成员贡献排行</span></div>
        <div v-if="!memberData.length && !chartsLoading" class="chart-empty">暂无数据</div>
        <div ref="memberRef" class="chart-body" />
      </div>
    </div>

    <!-- 执行记录明细表 -->
    <div class="records-card gradient-border-card">
      <div class="chart-head"><span class="chart-title">执行记录明细</span></div>
      <!-- 筛选条件行 -->
      <div class="filter-row">
        <n-date-picker
          v-model:value="filters.timeRange"
          type="datetimerange"
          size="small"
          clearable
          style="width: 320px"
          @update:value="loadRecords(1)"
        />
        <n-select
          v-model:value="filters.status"
          :options="statusOptions"
          multiple
          clearable
          size="small"
          placeholder="执行状态"
          style="width: 200px"
          @update:value="loadRecords(1)"
        />
        <n-select
          v-model:value="filters.datasourceId"
          :options="datasourceOptions"
          clearable
          size="small"
          placeholder="数据源"
          style="width: 160px"
          @update:value="loadRecords(1)"
        />
        <n-select
          v-model:value="filters.createdBy"
          :options="memberOptions"
          clearable
          size="small"
          placeholder="操作人"
          style="width: 140px"
          @update:value="loadRecords(1)"
        />
        <n-input
          v-model:value="filters.caseName"
          size="small"
          clearable
          placeholder="Case 名称模糊搜索"
          style="width: 180px"
          @keydown.enter="loadRecords(1)"
          @clear="loadRecords(1)"
        />
        <n-button size="small" class="gradient-btn" @click="loadRecords(1)">查询</n-button>
      </div>
      <!-- 表格（首次加载骨架屏，刷新时 spin 遮罩） -->
      <n-skeleton v-if="recordsFirstLoading" :repeat="5" height="42px" style="margin-top: 12px" />
      <n-spin v-else :show="recordsLoading">
        <n-data-table
          :columns="recordColumns"
          :data="records"
          :pagination="false"
          size="small"
          class="records-table"
        />
        <div class="pager">
          <n-pagination
            v-model:page="page"
            :item-count="recordTotal"
            :page-size="pageSize"
            @update:page="loadRecords"
          />
        </div>
        <EmptyState v-if="!recordsLoading && records.length === 0" />
      </n-spin>
    </div>

    <!-- 执行详情抽屉 -->
    <n-drawer v-model:show="drawerShow" :width="640" placement="right">
      <n-drawer-content title="执行详情" closable>
        <n-spin :show="detailLoading">
          <template v-if="detail">
            <n-descriptions :column="2" label-placement="left" size="small" bordered>
              <n-descriptions-item label="执行编号">{{ detail.task_no }}</n-descriptions-item>
              <n-descriptions-item label="状态">
                <n-tag :type="statusTagType(detail.status)" size="small">{{ statusText(detail.status) }}</n-tag>
              </n-descriptions-item>
              <n-descriptions-item label="Case 名称">{{ detail.case_name }}</n-descriptions-item>
              <n-descriptions-item label="数据源">{{ detail.datasource_name }}</n-descriptions-item>
              <n-descriptions-item label="主表">{{ detail.main_table }}</n-descriptions-item>
              <n-descriptions-item label="目标条数">{{ formatNumber(detail.target_count) }}</n-descriptions-item>
              <n-descriptions-item label="实际插入">{{ formatNumber(detail.success_count) }}</n-descriptions-item>
              <n-descriptions-item label="耗时">{{ formatDurationMs(detail.duration_ms) }}</n-descriptions-item>
            </n-descriptions>

            <!-- 错误信息 -->
            <n-alert v-if="detail.error_msg" type="error" class="mt-4" title="错误信息">
              <div class="error-msg">
                <span>{{ detail.error_msg }}</span>
                <n-button text size="tiny" type="primary" @click="copyError">复制</n-button>
              </div>
            </n-alert>

            <!-- 回滚状态与操作（终态任务且已采集回滚数据时可用） -->
            <div v-if="[2, 3, 5].includes(detail.status)" class="rollback-bar">
              <template v-if="detail.rollback_status === 2">
                <n-tag size="small" type="info">已回滚</n-tag>
                <span class="dim">{{ detail.rolled_back_at ? `回滚于 ${formatDateTime(detail.rolled_back_at)}` : '' }}</span>
              </template>
              <template v-else-if="detail.rollback_status === 1">
                <n-tag size="small" type="warning">回滚中…</n-tag>
                <n-button size="tiny" @click="openDetail(detail.task_no)">刷新状态</n-button>
              </template>
              <template v-else>
                <n-button
                  v-if="detail.rollback_rows > 0"
                  size="small"
                  type="error"
                  ghost
                  :loading="rollbackSubmitting"
                  @click="handleRollback"
                >一键回滚（约 {{ formatNumber(detail.rollback_rows) }} 条）</n-button>
                <span v-else class="dim">未采集回滚数据（无主键表或超规模阈值），不支持回滚</span>
                <n-tag v-if="detail.rollback_status === 3" size="small" type="error">上次回滚部分失败，可重试</n-tag>
              </template>
            </div>

            <!-- 分批次日志 -->
            <h4 class="section-title">分批次日志</h4>
            <n-data-table
              :columns="batchColumns"
              :data="detail.batch_logs"
              size="small"
              :pagination="false"
              max-height="320"
            />
          </template>
        </n-spin>
      </n-drawer-content>
    </n-drawer>

    <!-- Top10 下钻弹窗 -->
    <n-modal v-model:show="drillShow" preset="card" title="该表相关执行记录" style="width: 860px; max-width: 94vw">
      <n-data-table :columns="recordColumns" :data="drillRecords" size="small" :pagination="{ pageSize: 8 }" />
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  AlbumsOutline,
  CheckmarkCircleOutline,
  FlashOutline,
  LayersOutline,
  PeopleOutline,
  ServerOutline,
  StatsChartOutline,
} from '@vicons/ionicons5'
import { NButton, NTag, type DataTableColumns } from 'naive-ui'
import { overviewApi } from '@/api/overview'
import { datasourceApi } from '@/api/datasource'
import { usersApi } from '@/api/users'
import { tasksApi } from '@/api/tasks'
import type {
  ExecRecord,
  MemberRankItem,
  OverviewMetrics,
  StatusDistItem,
  TableTopItem,
  TaskDetailData,
  TrendPoint,
  BatchLog,
} from '@/api/types'
import { useEcharts } from '@/composables/useEcharts'
import { copyText, formatDateTime, formatDurationMs, formatNumber } from '@/utils/formatter'
import EmptyState from '@/components/common/EmptyState.vue'

const route = useRoute()

// ---------------- 指标卡片 ----------------
const metrics = ref<OverviewMetrics | null>(null)
const metricsLoading = ref(true)

const metricCards = computed(() => {
  const m = metrics.value
  const d = m?.compare_yesterday ?? {}
  return [
    { key: 'cases', name: '总 Case 数', value: formatNumber(m?.total_case_count), icon: LayersOutline, color: '#a78bfa', delta: d.total_case_count },
    { key: 'scenes', name: '总场景数', value: formatNumber(m?.total_scene_count), icon: AlbumsOutline, color: '#60a5fa', delta: d.total_scene_count },
    { key: 'today', name: '今日执行次数', value: formatNumber(m?.today_exec_count), icon: FlashOutline, color: '#fbbf24', delta: d.today_exec_count },
    { key: 'rows', name: '累计造数条数', value: formatNumber(m?.total_row_count), icon: StatsChartOutline, color: '#34d399', delta: d.total_row_count },
    { key: 'rate', name: '执行成功率', value: m && typeof m.exec_success_rate === 'number' ? `${m.exec_success_rate.toFixed(1)}%` : '-', icon: CheckmarkCircleOutline, color: '#22c55e', delta: d.exec_success_rate },
    { key: 'ds', name: '活跃数据源数', value: formatNumber(m?.active_datasource_count), icon: ServerOutline, color: '#22d3ee', delta: d.active_datasource_count },
    { key: 'member', name: '本组成员数', value: formatNumber(m?.group_member_count), icon: PeopleOutline, color: '#f472b6', delta: d.group_member_count },
  ]
})

// ---------------- 图表 ----------------
const trendDays = ref<7 | 30 | 90>(30)
const chartsLoading = ref(true)
const trendData = ref<TrendPoint[]>([])
const statusData = ref<StatusDistItem[]>([])
const top10Data = ref<TableTopItem[]>([])
const memberData = ref<MemberRankItem[]>([])

const trendRef = ref<HTMLElement | null>(null)
const pieRef = ref<HTMLElement | null>(null)
const top10Ref = ref<HTMLElement | null>(null)
const memberRef = ref<HTMLElement | null>(null)

const trendChart = useEcharts(trendRef)
const pieChart = useEcharts(pieRef)
const top10Chart = useEcharts(top10Ref)
const memberChart = useEcharts(memberRef)

/** 执行状态完整码：0待执行 1执行中 2成功 3失败 4重试中 5部分成功 6已中止 */
const STATUS_CODE_NAME: Record<number, string> = {
  0: '待执行',
  1: '执行中',
  2: '成功',
  3: '失败',
  4: '重试中',
  5: '部分成功',
  6: '已中止',
}
/** 状态分布接口返回的字符串状态 → 中文名 */
const DIST_STATUS_NAME: Record<string, string> = {
  submitted: '待执行',
  running: '执行中',
  success: '成功',
  failed: '失败',
  retrying: '重试中',
  partial_success: '部分成功',
  aborted: '已中止',
}
/** 状态分布字符串状态 → 完整状态码 */
const DIST_STATUS_CODE: Record<string, number> = {
  submitted: 0,
  running: 1,
  success: 2,
  failed: 3,
  retrying: 4,
  partial_success: 5,
  aborted: 6,
}
const STATUS_COLOR: Record<string, string> = {
  success: '#22c55e',
  failed: '#ef4444',
  running: '#3b82f6',
  retrying: '#f97316',
  partial_success: '#eab308',
  aborted: '#64748b',
  submitted: '#94a3b8',
}

async function loadCharts(): Promise<void> {
  chartsLoading.value = true
  try {
    const [trend, dist, top10, member] = await Promise.all([
      overviewApi.trend(trendDays.value),
      overviewApi.statusDist(trendDays.value),
      overviewApi.tableTop10(trendDays.value),
      overviewApi.memberRank(trendDays.value),
    ])
    trendData.value = trend.data.points ?? []
    statusData.value = dist.data.items ?? []
    top10Data.value = top10.data
    memberData.value = member.data
    renderTrend()
    renderPie()
    renderTop10()
    renderMember()
  } finally {
    chartsLoading.value = false
  }
}

function renderTrend(): void {
  if (!trendData.value.length) return
  trendChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { data: ['执行次数', '造数条数'], textStyle: { color: '#94a3b8' } },
    grid: { left: 60, right: 60, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: trendData.value.map((p) => p.date.slice(5)) },
    yAxis: [
      { type: 'value', name: '执行次数' },
      { type: 'value', name: '造数条数', splitLine: { show: false } },
    ],
    series: [
      {
        name: '执行次数',
        type: 'line',
        smooth: true,
        data: trendData.value.map((p) => p.exec_count),
        lineStyle: { color: '#7c3aed' },
        itemStyle: { color: '#7c3aed' },
        areaStyle: { color: 'rgba(124,58,237,0.15)' },
      },
      {
        name: '造数条数',
        type: 'line',
        smooth: true,
        yAxisIndex: 1,
        data: trendData.value.map((p) => p.row_count),
        lineStyle: { color: '#2563eb' },
        itemStyle: { color: '#2563eb' },
      },
    ],
  })
}

function renderPie(): void {
  if (!statusData.value.length) return
  const total = statusData.value.reduce((s, i) => s + i.count, 0)
  pieChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item' },
    title: { text: String(formatNumber(total)), subtext: '总执行次数', left: 'center', top: '42%', textStyle: { color: '#e2e8f0', fontSize: 20 }, subtextStyle: { color: '#64748b' } },
    series: [
      {
        type: 'pie',
        radius: ['52%', '72%'],
        label: { color: '#94a3b8' },
        data: statusData.value.map((i) => ({
          name: DIST_STATUS_NAME[i.status] ?? i.status,
          value: i.count,
          itemStyle: { color: STATUS_COLOR[i.status] ?? '#94a3b8' },
        })),
      },
    ],
  })
  // 点击扇形 → 明细表按状态过滤（字符串状态名 → 完整状态码 0~6）
  pieChart.on('click', (params: unknown) => {
    const name = (params as { name: string }).name
    const key = Object.entries(DIST_STATUS_NAME).find(([, v]) => v === name)?.[0]
    const statusCode = key != null ? DIST_STATUS_CODE[key] : undefined
    if (statusCode != null) {
      filters.status = [statusCode]
      loadRecords(1)
    }
  })
}

const drillShow = ref(false)
const drillRecords = ref<ExecRecord[]>([])

function renderTop10(): void {
  if (!top10Data.value.length) return
  top10Chart.setOption({
    backgroundColor: 'transparent',
    // shadow 指针覆盖整个类目带（含 y 轴截断标签），tooltip 展示完整表名
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      // 超长表名（如 Redis key 模板）强制断行并限制在图表区内，避免 tooltip 溢出屏幕被裁
      confine: true,
      extraCssText: 'max-width: 340px; white-space: normal; word-break: break-all;',
      formatter: (params: unknown) => {
        const p = (params as Array<{ dataIndex: number }>)[0]
        const item = top10Data.value[p?.dataIndex ?? -1]
        if (!item) return ''
        return `${item.table_name} <span style="color:#94a3b8">@${item.datasource_name}</span><br/>造数条数：${formatNumber(item.row_count)}<br/>关联 Case：${item.case_count}`
      },
    },
    grid: { left: 152, right: 30, top: 20, bottom: 30 },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      inverse: true,
      data: top10Data.value.map((i) => (i.table_name.length > 20 ? `${i.table_name.slice(0, 20)}…` : i.table_name)),
    },
    series: [
      {
        type: 'bar',
        data: top10Data.value.map((i) => i.row_count),
        itemStyle: { borderRadius: [0, 4, 4, 0], color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#7c3aed' }, { offset: 1, color: '#2563eb' }] } },
      },
    ],
  })
  // 点击柱子 → 下钻弹窗展示该表执行记录
  top10Chart.on('click', async (params: unknown) => {
    const idx = (params as { dataIndex: number }).dataIndex
    const item = top10Data.value[idx]
    if (!item) return
    const res = await overviewApi.execRecords({ page: 1, page_size: 50, table_name: item.table_name })
    drillRecords.value = res.data.items ?? []
    drillShow.value = true
  })
}

function renderMember(): void {
  if (!memberData.value.length) return
  const top = memberData.value.slice(0, 10)
  memberChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: 100, right: 40, top: 20, bottom: 30 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', inverse: true, data: top.map((i) => i.real_name) },
    series: [
      {
        type: 'bar',
        data: top.map((i) => i.row_count),
        label: { show: true, position: 'right', color: '#94a3b8', formatter: (p: { value?: unknown }) => formatNumber(Number(p.value)) },
        itemStyle: { borderRadius: [0, 4, 4, 0], color: '#8b5cf6' },
      },
    ],
  })
}

// ---------------- 执行记录明细 ----------------
const records = ref<ExecRecord[]>([])
const recordsLoading = ref(false)
const recordsFirstLoading = ref(true)
const page = ref(1)
const pageSize = 20
const recordTotal = ref(0)

const filters = reactive({
  timeRange: null as [number, number] | null,
  status: [] as number[],
  datasourceId: null as number | null,
  createdBy: null as number | null,
  caseName: '',
})

const statusOptions = Object.entries(STATUS_CODE_NAME).map(([value, label]) => ({ value: Number(value), label }))

const datasourceOptions = ref<Array<{ label: string; value: number }>>([])
const memberOptions = ref<Array<{ label: string; value: number }>>([])

function statusText(s: number): string {
  return STATUS_CODE_NAME[s] ?? String(s)
}
function statusTagType(s: number): 'success' | 'error' | 'info' | 'warning' | 'default' {
  if (s === 2) return 'success'
  if (s === 3 || s === 6) return 'error'
  if (s === 5) return 'warning'
  if (s === 0 || s === 1 || s === 4) return 'info'
  return 'default'
}

const recordColumns: DataTableColumns<ExecRecord> = [
  {
    title: '执行编号',
    key: 'task_no',
    width: 170,
    render: (row) =>
      h(
        NButton,
        { text: true, size: 'tiny', type: 'primary', onClick: () => copyText(row.task_no).then(() => window.$message.success('已复制')) },
        () => row.task_no,
      ),
  },
  {
    title: 'Case 名称',
    key: 'case_name',
    width: 180,
    ellipsis: { tooltip: true },
  },
  { title: '数据源', key: 'datasource_name', width: 110 },
  { title: '主表', key: 'main_table', width: 140, ellipsis: { tooltip: true } },
  { title: '关联表数', key: 'related_count', width: 80 },
  { title: '目标条数', key: 'target_count', width: 100, render: (r) => formatNumber(r.target_count) },
  { title: '实际插入', key: 'success_count', width: 100, render: (r) => formatNumber(r.success_count) },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (r) => h(NTag, { size: 'small', type: statusTagType(r.status) }, () => statusText(r.status)),
  },
  { title: '耗时', key: 'duration_ms', width: 90, render: (r) => formatDurationMs(r.duration_ms) },
  { title: '操作人', key: 'creator_name', width: 80, render: (r) => r.creator_name ?? '-' },
  { title: '执行时间', key: 'start_at', width: 160, render: (r) => formatDateTime(r.start_at) },
  {
    title: '操作',
    key: 'actions',
    width: 150,
    render: (r) =>
      h('div', { style: 'display:flex;gap:8px' }, [
        h(NButton, { text: true, size: 'small', type: 'primary', onClick: () => openDetail(r.task_no) }, () => '查看详情'),
        [3, 5].includes(r.status)
          ? h(NButton, { text: true, size: 'small', type: 'warning', onClick: () => retryTask(r.task_no) }, () => '重新执行')
          : null,
      ]),
  },
]

async function loadRecords(p?: number): Promise<void> {
  if (p) page.value = p
  recordsLoading.value = true
  try {
    const [start, end] = filters.timeRange ?? [null, null]
    const res = await overviewApi.execRecords({
      page: page.value,
      page_size: pageSize,
      start_time: start ? new Date(start).toISOString() : undefined,
      end_time: end ? new Date(end).toISOString() : undefined,
      status: filters.status.length ? filters.status : undefined,
      datasource_id: filters.datasourceId ?? undefined,
      created_by: filters.createdBy ?? undefined,
      case_name: filters.caseName || undefined,
    })
    records.value = res.data.items ?? []
    recordTotal.value = res.data.total
  } finally {
    recordsLoading.value = false
    recordsFirstLoading.value = false
  }
}

// ---------------- 执行详情抽屉 ----------------
const drawerShow = ref(false)
const detailLoading = ref(false)
const detail = ref<TaskDetailData | null>(null)

const batchColumns: DataTableColumns<BatchLog> = [
  {
    title: '目标表',
    key: 'table_name',
    ellipsis: { tooltip: true },
    // 跨数据源 Case：非主数据源的表带 @数据源 后缀（主数据源表保持简洁）
    render: (r) => {
      const dsName = detail.value?.table_ds_names?.[r.table_name]
      const isForeign = dsName && dsName !== detail.value?.datasource_name
      return h('span', null, [
        r.table_name,
        isForeign ? h('span', { style: 'color:#f59e0b;font-size:11px;margin-left:4px' }, `@${dsName}`) : null,
      ])
    },
  },
  { title: '批次号', key: 'batch_no', width: 70 },
  { title: '批次大小', key: 'batch_size', width: 100, render: (r) => formatNumber(r.batch_size) },
  {
    title: '状态',
    key: 'status',
    width: 90,
    render: (r) =>
      h(
        NTag,
        { size: 'small', type: r.status === 1 ? 'success' : r.status === 2 ? 'error' : 'warning' },
        () => ({ 0: '待执行', 1: '成功', 2: '失败' })[r.status as 0 | 1 | 2] ?? String(r.status),
      ),
  },
  { title: '耗时', key: 'duration_ms', width: 90, render: (r) => (r.duration_ms != null ? `${r.duration_ms}ms` : '-') },
  { title: '错误信息', key: 'error_msg', ellipsis: { tooltip: true }, render: (r) => r.error_msg ?? '-' },
]

async function openDetail(taskNo: string): Promise<void> {
  drawerShow.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const res = await tasksApi.detail(taskNo)
    detail.value = res.data
  } finally {
    detailLoading.value = false
  }
}

function copyError(): void {
  if (detail.value?.error_msg) {
    copyText(detail.value.error_msg).then(() => window.$message.success('已复制'))
  }
}

/** 重新执行（断点续传：重试失败批次） */
async function retryTask(taskNo: string): Promise<void> {
  const res = await tasksApi.detail(taskNo)
  const batchNos = res.data.batch_logs.filter((b) => b.status === 2).map((b) => b.batch_no)
  await tasksApi.retryBatches(taskNo, { batch_nos: batchNos })
  window.$message.success('已提交重试，可在进度面板查看')
  const { useTaskProgress } = await import('@/composables/useTaskProgress')
  const { trackTask } = useTaskProgress()
  trackTask(taskNo, '')
}

// ---------------- 一键回滚 ----------------
const rollbackSubmitting = ref(false)

/** 一键回滚：删除本任务已写入的 MySQL 行与 Redis Key（二次确认） */
function handleRollback(): void {
  if (!detail.value) return
  const d = detail.value
  window.$dialog.warning({
    title: '确认回滚',
    content: `将删除任务 ${d.task_no} 写入的约 ${formatNumber(d.rollback_rows)} 条数据（${d.rollback_targets.join('、') || '-'}）。此操作不可恢复，是否继续？`,
    positiveText: '确认回滚',
    negativeText: '取消',
    onPositiveClick: async () => {
      rollbackSubmitting.value = true
      try {
        await tasksApi.rollback(d.task_no)
        window.$message.success('回滚任务已提交，完成后将收到通知')
        await openDetail(d.task_no)
      } finally {
        rollbackSubmitting.value = false
      }
    },
  })
}

// ---------------- 初始化 ----------------
onMounted(async () => {
  // 默认时间范围：近 7 天
  const now = Date.now()
  filters.timeRange = [now - 7 * 24 * 3600 * 1000, now]

  loadRecords(1)
  loadCharts()
  try {
    const m = await overviewApi.metrics()
    metrics.value = m.data
  } finally {
    metricsLoading.value = false
  }
  // 筛选下拉数据源
  try {
    const [dsRes, userRes] = await Promise.all([
      datasourceApi.list(),
      usersApi.members().catch(() => null),
    ])
    datasourceOptions.value = dsRes.data.map((d) => ({ label: d.name, value: d.id }))
    if (userRes) {
      memberOptions.value = (userRes.data ?? []).map((u) => ({ label: u.real_name ?? u.username, value: u.id }))
    }
  } catch {
    // 下拉数据失败不阻塞页面
  }
  // 从进度面板「查看详情」跳入时自动打开抽屉
  const taskNo = route.query.task_no as string | undefined
  if (taskNo) openDetail(taskNo)
})
</script>

<style scoped>
.overview-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px;
}
.metric-card {
  padding: 16px;
}
.metric-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.metric-name {
  font-size: 12px;
  color: #94a3b8;
}
.metric-value {
  font-size: 26px;
  font-weight: 700;
  margin-top: 8px;
  color: #f1f5f9;
}
.metric-delta {
  margin-top: 6px;
  font-size: 11px;
  border-top: 1px solid;
  border-image: linear-gradient(90deg, rgba(124, 58, 237, 0.5), transparent) 1;
  padding-top: 6px;
}
.delta-up { color: #22c55e; }
.delta-down { color: #ef4444; }
.charts-row {
  display: flex;
  gap: 16px;
}
/* 窄窗口：图表卡片纵向堆叠，避免互相挤压裁切 */
@media (max-width: 1200px) {
  .charts-row {
    flex-direction: column;
  }
}
.chart-card {
  padding: 16px;
  min-width: 0;
  position: relative;
}
.chart-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.chart-title {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
}
.chart-body {
  height: 280px;
}
.chart-empty {
  position: absolute;
  inset: 56px 0 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  font-size: 13px;
  background: rgba(26, 26, 46, 0.6);
  z-index: 2;
}
.records-card {
  padding: 16px;
}
.filter-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.records-table {
  min-height: 200px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.section-title {
  margin: 18px 0 10px;
  font-size: 13px;
  color: #a78bfa;
}
.error-msg {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  word-break: break-all;
}
.rollback-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}
.rollback-bar .dim {
  color: #64748b;
  font-size: 12px;
}
</style>
