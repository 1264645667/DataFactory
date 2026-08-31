<template>
  <!-- Case 详情页（PRD 5.4）：只读配置 + 关联关系可视化 -->
  <div class="case-detail-page">
    <n-spin :show="loading">
      <template v-if="detail">
        <!-- 基本信息卡片 -->
        <div class="gradient-border-card info-card">
          <div class="info-head">
            <h3 class="info-title">{{ detail.name }}</h3>
            <div class="info-actions">
              <n-button v-if="hasPermission('CASE:EDIT')" size="small" @click="goEdit">编辑</n-button>
              <n-button v-if="hasPermission('CASE:EXECUTE')" size="small" class="gradient-btn" @click="executeShow = true">执行</n-button>
              <n-button v-if="hasPermission('CASE:COPY')" size="small" @click="copyShow = true">复制</n-button>
            </div>
          </div>
          <n-descriptions :column="3" label-placement="left" size="small">
            <n-descriptions-item label="数据源">{{ detail.datasource_name }}</n-descriptions-item>
            <n-descriptions-item label="主表">{{ detail.main_table }}</n-descriptions-item>
            <n-descriptions-item label="创建人">{{ detail.created_by_name }}</n-descriptions-item>
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
                <text :x="line.labelX" :y="line.labelY" fill="#94a3b8" font-size="11">{{ line.label }}</text>
              </g>
              <!-- 主表节点 -->
              <g>
                <rect x="20" :y="mainNodeY" :width="nodeW" :height="nodeH" rx="8" fill="rgba(124,58,237,0.15)" stroke="#7c3aed" />
                <text :x="20 + nodeW / 2" :y="mainNodeY + nodeH / 2 - 4" fill="#e2e8f0" font-size="13" font-weight="600" text-anchor="middle">{{ detail.main_table }}</text>
                <text :x="20 + nodeW / 2" :y="mainNodeY + nodeH / 2 + 13" fill="#64748b" font-size="11" text-anchor="middle">主表</text>
              </g>
              <!-- 关联表节点 -->
              <g v-for="(node, i) in relatedNodes" :key="`n-${i}`">
                <rect :x="node.x" :y="node.y" :width="nodeW" :height="nodeH" rx="8" fill="rgba(37,99,235,0.12)" stroke="#2563eb" />
                <text :x="node.x + nodeW / 2" :y="node.y + nodeH / 2 + 4" fill="#e2e8f0" font-size="12" text-anchor="middle">{{ node.name }}</text>
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
      :initial-name="detail?.name ?? ''"
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

const route = useRoute()
const router = useRouter()
const { hasPermission } = useAuth()
const { trackTask } = useTaskProgress()

const caseId = Number(route.params.id)
const loading = ref(true)
const detail = ref<CaseDetail | null>(null)

const config = computed(() => detail.value?.config_json ?? { version: '1.0', main_table: '', field_configs: [], associations: [] })
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

// ---------------- 关联关系图（简单节点-连线图） ----------------
const nodeW = 150
const nodeH = 46
const graphWidth = 620

const relatedNodes = computed(() => {
  const tables = relatedTables.value
  return tables.map((name, i) => ({ name, x: 420, y: 20 + i * 76 }))
})

const graphHeight = computed(() => Math.max(120, 20 + relatedNodes.value.length * 76 + 20))
const mainNodeY = computed(() => Math.max(20, (graphHeight.value - nodeH) / 2))

const graphLines = computed(() => {
  const lines: Array<{ path: string; label: string; labelX: number; labelY: number }> = []
  const mainCX = 20 + nodeW
  const mainCY = mainNodeY.value + nodeH / 2
  config.value.associations.forEach((a) => {
    const node = relatedNodes.value.find((n) => n.name === a.target_table)
    if (!node) return
    const tx = node.x
    const ty = node.y + nodeH / 2
    const midX = (mainCX + tx) / 2
    lines.push({
      path: `M ${mainCX} ${mainCY} C ${midX} ${mainCY}, ${midX} ${ty}, ${tx} ${ty}`,
      label: `${a.source_column} → ${a.target_column}`,
      labelX: midX - 40,
      labelY: (mainCY + ty) / 2 - 6,
    })
  })
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
    copyName.value = `${res.data.name}_copy`
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
