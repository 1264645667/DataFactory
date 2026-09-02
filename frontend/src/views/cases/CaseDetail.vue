<template>
  <!-- Case 详情页（PRD 5.4）：只读配置 + 关联关系可视化 -->
  <div class="case-detail-page">
    <n-spin :show="loading">
      <template v-if="detail">
        <!-- 基本信息卡片 -->
        <div class="gradient-border-card info-card">
          <div class="info-head">
            <h3 class="info-title">{{ detail.case_name }}</h3>
            <div class="info-actions">
              <n-button v-if="hasPermission('CASE:EDIT')" size="small" @click="goEdit">编辑</n-button>
              <n-button v-if="hasPermission('CASE:EXECUTE')" size="small" class="gradient-btn" @click="executeShow = true">执行</n-button>
              <n-button v-if="hasPermission('CASE:COPY')" size="small" @click="copyShow = true">复制</n-button>
            </div>
          </div>
          <n-descriptions :column="3" label-placement="left" size="small">
            <n-descriptions-item label="数据源">{{ detail.datasource_name }}</n-descriptions-item>
            <n-descriptions-item label="主表">{{ detail.main_table }}</n-descriptions-item>
            <n-descriptions-item label="创建人">{{ detail.creator_name }}</n-descriptions-item>
            <n-descriptions-item label="创建时间">{{ formatDateTime(detail.created_at) }}</n-descriptions-item>
            <n-descriptions-item label="最后执行">{{ detail.last_exec_at ? formatDateTime(detail.last_exec_at) : '未执行' }}</n-descriptions-item>
          </n-descriptions>
        </div>

        <!-- 关联关系可视化 -->
        <div class="gradient-border-card graph-card">
          <h4 class="section-title">关联关系</h4>
          <div v-if="config.associations.length > 0" class="graph-wrap">
            <svg :width="graphWidth" :height="graphHeight" class="assoc-graph">
              <!-- 连线 -->
              <g v-for="(line, i) in graphLines" :key="`l-${i}`">
                <path :d="line.path" stroke="#7c3aed" stroke-width="1.6" fill="none" opacity="0.75" />
                <text :x="line.labelX" :y="line.labelY" fill="#94a3b8" font-size="11" text-anchor="middle">{{ line.label }}</text>
              </g>
              <!-- 节点（按拓扑层次从左到右：主表 → 各级关联表） -->
              <g v-for="node in layoutNodes" :key="node.name">
                <rect
                  :x="node.x"
                  :y="node.y"
                  :width="nodeW"
                  :height="nodeH"
                  rx="8"
                  :fill="node.isMain ? 'rgba(124,58,237,0.15)' : 'rgba(37,99,235,0.12)'"
                  :stroke="node.isMain ? '#7c3aed' : '#2563eb'"
                />
                <text
                  :x="node.x + nodeW / 2"
                  :y="node.isMain ? node.y + nodeH / 2 - 4 : node.y + nodeH / 2 + 4"
                  fill="#e2e8f0"
                  font-size="13"
                  :font-weight="node.isMain ? 600 : 400"
                  text-anchor="middle"
                >{{ node.name }}</text>
                <text
                  v-if="node.isMain"
                  :x="node.x + nodeW / 2"
                  :y="node.y + nodeH / 2 + 13"
                  fill="#64748b"
                  font-size="11"
                  text-anchor="middle"
                >主表</text>
              </g>
            </svg>
          </div>
          <EmptyState v-else description="该 Case 没有配置字段关联" :size="70" />
        </div>

        <!-- 字段配置列表（只读） -->
        <div class="gradient-border-card fields-card">
          <h4 class="section-title">字段配置（只读）</h4>
          <n-data-table :columns="fieldColumns" :data="config.field_configs" size="small" :pagination="{ pageSize: 20 }" />
        </div>
      </template>
    </n-spin>

    <!-- 执行弹窗 -->
    <ExecuteModal
      v-model:show="executeShow"
      :main-table="detail?.main_table ?? ''"
      :related-tables="relatedTables"
      :iterate-info="iterateInfo"
      :initial-name="detail?.case_name ?? ''"
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
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NTag, type DataTableColumns } from 'naive-ui'
import { casesApi } from '@/api/cases'
import type { CaseDetail, FieldStrategyConfig } from '@/api/types'
import ExecuteModal from '@/components/business/ExecuteModal.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { useTaskProgress } from '@/composables/useTaskProgress'
import { formatDateTime } from '@/utils/formatter'
import { STRATEGY_LABELS, columnTypeColor } from '@/utils/strategy'
import { buildLayers } from '@/utils/dag'

const route = useRoute()
const router = useRouter()
const { hasPermission } = useAuth()
const { trackTask } = useTaskProgress()

const caseId = Number(route.params.id)
const loading = ref(true)
const detail = ref<CaseDetail | null>(null)

const config = computed(() => detail.value?.config ?? { version: '1.0', main_table: '', field_configs: [], associations: [] })
const relatedTables = computed(() => [...new Set(config.value.associations.map((a) => a.target_table))])

const iterateInfo = computed(() => {
  const f = config.value.field_configs.find((x) => x.strategy === 'ITERATE_LIST')
  if (!f) return null
  const values = String(f.strategy_params?.list ?? '').split('\n').map((s) => s.trim()).filter(Boolean)
  if (!values.length) return null
  return { field: `${config.value.main_table}.${f.column_name}`, values, rowsPerValue: Number(f.strategy_params?.rows_per_value ?? 1) }
})

// ---------------- 字段配置只读表格 ----------------
const fieldColumns: DataTableColumns<FieldStrategyConfig> = [
  { title: '字段名', key: 'column_name', width: 170, render: (r) => h('span', { style: 'font-weight:600' }, r.column_name) },
  {
    title: '类型',
    key: 'column_type',
    width: 130,
    render: (r) => h('span', { style: `color:${columnTypeColor(r.data_type)}` }, r.column_type),
  },
  { title: '可空', key: 'is_nullable', width: 70, render: (r) => (r.is_nullable ? '是' : '否') },
  {
    title: '造数策略',
    key: 'strategy',
    width: 160,
    render: (r) => h(NTag, { size: 'small', type: r.strategy === 'SKIP' ? 'default' : 'primary' }, () => STRATEGY_LABELS[r.strategy] ?? r.strategy),
  },
  {
    title: '策略参数',
    key: 'strategy_params',
    render: (r) => {
      const entries = Object.entries(r.strategy_params ?? {}).filter(([, v]) => v != null && v !== '')
      if (!entries.length) return '-'
      return h('span', { style: 'color:#94a3b8;font-size:12px' }, entries.map(([k, v]) => `${k}=${String(v).slice(0, 40)}`).join('，'))
    },
  },
]

// ---------------- 关联关系图（拓扑分层布局，支持多级关联） ----------------
const nodeW = 150
const nodeH = 46
const gapX = 210
const gapY = 80

interface GraphNode {
  name: string
  x: number
  y: number
  isMain: boolean
}

// 表级节点与边（多级关联：source_table 缺省为主表）
const tableGraph = computed(() => {
  const mainTable = config.value.main_table
  const nodeSet = new Set<string>([mainTable])
  const edges: Array<{ source: string; target: string }> = []
  for (const a of config.value.associations) {
    const src = a.source_table || mainTable
    nodeSet.add(src)
    nodeSet.add(a.target_table)
    edges.push({ source: src, target: a.target_table })
  }
  return { nodes: [...nodeSet], edges }
})

// 拓扑分层：主表在第 0 层，下游表按依赖层次逐层向右展开，层内垂直堆叠
const layoutNodes = computed<GraphNode[]>(() => {
  const { nodes, edges } = tableGraph.value
  let layers: string[][]
  try {
    layers = buildLayers(nodes, edges)
  } catch {
    layers = [nodes] // 有环时退化为单列（保存时已被环检测拦截，此处兜底）
  }
  const result: GraphNode[] = []
  layers.forEach((layer, li) => {
    layer.forEach((name, ni) => {
      result.push({ name, x: 30 + li * gapX, y: 30 + ni * gapY, isMain: name === config.value.main_table })
    })
  })
  return result
})

const graphWidth = computed(() => {
  const xs = layoutNodes.value.map((n) => n.x)
  return Math.max(620, (xs.length ? Math.max(...xs) : 30) + nodeW + 40)
})
const graphHeight = computed(() => {
  const ys = layoutNodes.value.map((n) => n.y)
  return Math.max(140, (ys.length ? Math.max(...ys) : 30) + nodeH + 30)
})

const graphLines = computed(() => {
  const posMap = new Map(layoutNodes.value.map((n) => [n.name, n]))
  const lines: Array<{ path: string; label: string; labelX: number; labelY: number }> = []
  const pairCount = new Map<string, number>()
  for (const a of config.value.associations) {
    const src = a.source_table || config.value.main_table
    const srcNode = posMap.get(src)
    const tgtNode = posMap.get(a.target_table)
    if (!srcNode || !tgtNode) continue
    // 同一对表之间的多条字段关联：标签纵向错开，避免重叠
    const pairKey = `${src}⟩${a.target_table}`
    const idx = pairCount.get(pairKey) ?? 0
    pairCount.set(pairKey, idx + 1)
    const sx = srcNode.x + nodeW
    const sy = srcNode.y + nodeH / 2
    const tx = tgtNode.x
    const ty = tgtNode.y + nodeH / 2
    const midX = (sx + tx) / 2
    lines.push({
      path: `M ${sx} ${sy} C ${midX} ${sy}, ${midX} ${ty}, ${tx} ${ty}`,
      label: `${a.source_column} → ${a.target_column}`,
      labelX: midX,
      labelY: (sy + ty) / 2 - 6 - idx * 14,
    })
  }
  return lines
})

// ---------------- 操作 ----------------
const executeShow = ref(false)
const executing = ref(false)
const copyShow = ref(false)
const copying = ref(false)
const copyName = ref('')

function goEdit(): void {
  if (!detail.value) return
  router.push({
    name: 'EngineConfig',
    params: { tableName: detail.value.main_table },
    query: { datasource_id: detail.value.datasource_id, case_id: detail.value.id },
  })
}

async function handleExecute(payload: { caseName: string; targetCount: number }): Promise<void> {
  if (!detail.value) return
  executing.value = true
  try {
    const res = await casesApi.execute(detail.value.id, payload.targetCount)
    executeShow.value = false
    trackTask(res.data.task_no, payload.caseName)
  } finally {
    executing.value = false
  }
}

async function handleCopy(): Promise<void> {
  if (!detail.value || !copyName.value.trim()) return
  copying.value = true
  try {
    const res = await casesApi.copy(detail.value.id, copyName.value.trim())
    copyShow.value = false
    window.$message.success('复制成功')
    router.push(`/cases/${res.data.case_id}`)
  } finally {
    copying.value = false
  }
}

onMounted(async () => {
  try {
    const res = await casesApi.detail(caseId)
    detail.value = res.data
    copyName.value = `${res.data.case_name}_copy`
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.case-detail-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.info-card {
  padding: 18px;
}
.info-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.info-title {
  margin: 0;
  font-size: 17px;
  color: #f1f5f9;
}
.info-actions {
  display: flex;
  gap: 10px;
}
.graph-card,
.fields-card {
  padding: 18px;
}
.section-title {
  margin: 0 0 12px;
  font-size: 14px;
  color: #a78bfa;
}
.graph-wrap {
  overflow-x: auto;
}
.assoc-graph {
  display: block;
  margin: 0 auto;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
