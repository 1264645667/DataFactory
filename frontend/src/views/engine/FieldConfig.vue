<template>
  <!-- 字段配置页（PRD 4.4）：表信息 / 索引 / 字段策略配置 / 关联管理 / 创建并执行 -->
  <div class="field-config-page">
    <!-- 顶部操作栏 -->
    <div class="action-bar glass-card">
      <n-button size="small" quaternary @click="handleBack">
        <template #icon><n-icon><ArrowBackOutline /></n-icon></template>
        返回
      </n-button>
      <div class="action-bar-right">
        <n-button size="small" @click="assocDrawerShow = true">关联管理</n-button>
        <n-button v-if="hasPermission('ENGINE:CREATE')" size="small" @click="openSaveModal">
          {{ isEdit ? '保存修改' : '创建 Case' }}
        </n-button>
        <n-button size="small" @click="handleReset">取消</n-button>
        <n-button v-if="hasPermission('ENGINE:EXECUTE')" size="small" class="gradient-btn" @click="openExecuteModal">
          创建并执行
        </n-button>
      </div>
    </div>

    <n-spin :show="pageLoading">
      <!-- 表结构变更提示（1402） -->
      <n-alert v-if="outdatedFields.length > 0" type="warning" class="mb-3" closable>
        检测到表结构已更新，以下字段配置可能失效：{{ outdatedFields.join('、') }}
      </n-alert>

      <!-- 表基本信息卡片（可折叠） -->
      <n-collapse class="mb-3">
        <n-collapse-item title="表基本信息" name="info">
          <n-descriptions v-if="tableInfo" :column="4" label-placement="left" size="small">
            <n-descriptions-item label="表名">{{ tableInfo.table_name }}</n-descriptions-item>
            <n-descriptions-item label="备注">{{ tableInfo.table_comment || '-' }}</n-descriptions-item>
            <n-descriptions-item label="存储引擎">{{ tableInfo.engine || '-' }}</n-descriptions-item>
            <n-descriptions-item label="字符集">{{ tableInfo.charset || '-' }}</n-descriptions-item>
            <n-descriptions-item label="估算行数">{{ formatNumber(tableInfo.table_rows) }}</n-descriptions-item>
            <n-descriptions-item label="字段总数">{{ fieldRows.length }}</n-descriptions-item>
            <n-descriptions-item label="最后同步">{{ formatDateTime(tableInfo.synced_at) }}</n-descriptions-item>
          </n-descriptions>
        </n-collapse-item>
        <!-- 索引信息展示区 -->
        <n-collapse-item title="索引信息" name="index">
          <div class="index-block">
            <div v-for="idx in indexes" :key="idx.index_name" class="index-row">
              <n-tag size="small" :type="idx.is_primary ? 'error' : idx.is_unique ? 'warning' : 'default'">
                {{ idx.is_primary ? '主键' : idx.is_unique ? '唯一索引' : '普通索引' }}
              </n-tag>
              <span class="index-name">{{ idx.index_name }}</span>
              <span class="dim">({{ idx.column_names.join(', ') }})</span>
            </div>
            <span v-if="indexes.length === 0" class="dim">无索引</span>
          </div>
        </n-collapse-item>
      </n-collapse>

      <!-- 字段配置表格 -->
      <div class="field-card gradient-border-card">
        <div class="field-toolbar">
          <n-input v-model:value="fieldKeyword" size="small" clearable placeholder="按字段名 / 类型搜索" style="width: 220px">
            <template #prefix><n-icon><SearchOutline /></n-icon></template>
          </n-input>
          <span class="dim">共 {{ filteredRows.length }} 个字段</span>
        </div>
        <div class="field-table-wrap">
          <table class="field-table">
            <thead>
              <tr>
                <th style="width: 44px">#</th>
                <th style="width: 170px">字段名</th>
                <th style="width: 130px">字段备注</th>
                <th style="width: 120px">字段类型</th>
                <th style="width: 56px">可空</th>
                <th style="width: 170px">造数策略</th>
                <th>策略参数</th>
                <th style="width: 180px">关联字段</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in filteredRows" :key="row.column.column_name" :class="{ 'row-skip': row.strategy === 'SKIP' }">
                <td class="dim">{{ i + 1 }}</td>
                <td>
                  <n-tooltip placement="top-start">
                    <template #trigger>
                      <span class="field-name">
                        <span v-if="isRequired(row.column)" class="required-star">★</span>
                        {{ row.column.column_name }}
                      </span>
                    </template>
                    {{ row.column.column_type }} · {{ row.column.is_nullable ? '可空' : '非空' }}
                    {{ row.column.column_default != null ? `· 默认 ${row.column.column_default}` : '' }}
                  </n-tooltip>
                </td>
                <td class="dim">{{ row.column.column_comment || '-' }}</td>
                <td>
                  <n-tag size="small" :bordered="false" :style="{ color: columnTypeColor(row.column.data_type), background: 'rgba(148,163,184,0.08)' }">
                    {{ row.column.column_type }}
                  </n-tag>
                </td>
                <td>
                  <n-icon v-if="row.column.is_nullable" color="#22c55e" :size="15"><CheckmarkOutline /></n-icon>
                  <n-icon v-else color="#ef4444" :size="15"><CloseOutline /></n-icon>
                </td>
                <td>
                  <!-- SKIP 行：数据库自动填充，禁用 -->
                  <n-tag v-if="row.strategy === 'SKIP'" size="small" type="default">数据库自动填充</n-tag>
                  <n-select
                    v-else
                    :value="row.strategy"
                    :options="getStrategyOptions(row.column)"
                    size="small"
                    @update:value="(v: StrategyCode) => changeStrategy(row, v)"
                  />
                </td>
                <td>
                  <StrategyParams
                    v-if="row.strategy !== 'SKIP'"
                    :strategy="row.strategy"
                    :column="row.column"
                    v-model="row.params"
                  />
                  <span v-else class="dim">—</span>
                </td>
                <td>
                  <div class="assoc-tags">
                    <n-tag
                      v-for="a in assocsOf(row.column.column_name)"
                      :key="`${a.target_table}.${a.target_column}`"
                      size="small"
                      closable
                      @close="removeAssoc(a)"
                    >
                      {{ a.target_table }}.{{ a.target_column }}
                    </n-tag>
                    <span v-if="assocsOf(row.column.column_name).length === 0" class="dim">-</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </n-spin>

    <!-- 关联管理抽屉（PRD 4.4.6） -->
    <n-drawer v-model:show="assocDrawerShow" :width="520" placement="right">
      <n-drawer-content title="关联管理" closable>
        <p class="dim assoc-tip">执行造数时，源字段与所有关联目标字段插入完全相同的值（保证外键一致性）。</p>
        <!-- 已配置关联列表 -->
        <div class="assoc-list">
          <div v-for="(a, i) in associations" :key="i" class="assoc-item">
            <span class="assoc-source">{{ a.source_table || tableName }}.{{ a.source_column }}</span>
            <span class="dim">→</span>
            <span class="assoc-target">{{ a.target_table }}.{{ a.target_column }}</span>
            <n-button text size="tiny" type="error" @click="associations.splice(i, 1)">删除</n-button>
          </div>
          <EmptyState v-if="associations.length === 0" description="暂无关联配置" :size="70" />
        </div>
        <!-- 关联链路实时预览（多级关联拓扑图） -->
        <div v-if="associations.length > 0" class="assoc-graph-preview">
          <h4 class="assoc-add-title">关联链路预览</h4>
          <AssocGraph :main-table="tableName" :associations="associations" />
        </div>
        <!-- 添加关联（支持多级：源表可以是主表或任一已关联的表） -->
        <div class="assoc-add">
          <h4 class="assoc-add-title">添加关联（支持多级）</h4>
          <n-form label-placement="top" size="small">
            <n-form-item label="源表">
              <n-select
                v-model:value="assocForm.sourceTable"
                :options="sourceTableOptions"
                placeholder="选择源表（主表或已关联的表）"
                @update:value="onSourceTableChange"
              />
            </n-form-item>
            <n-form-item label="源字段">
              <n-select
                v-model:value="assocForm.sourceColumn"
                :options="sourceColumnOptions"
                filterable
                placeholder="选择源字段"
                :disabled="!assocForm.sourceTable"
                :loading="sourceColumnsLoading"
              />
            </n-form-item>
            <n-form-item label="目标表">
              <n-select
                v-model:value="assocForm.targetTable"
                :options="targetTableOptions"
                filterable
                placeholder="选择目标表"
                @update:value="loadTargetColumns"
              />
            </n-form-item>
            <n-form-item label="目标字段">
              <n-select
                v-model:value="assocForm.targetColumn"
                :options="targetColumnOptions"
                filterable
                placeholder="选择兼容类型的字段"
                :disabled="!assocForm.targetTable"
              />
            </n-form-item>
            <n-button class="gradient-btn" block size="small" :disabled="!assocForm.targetColumn" @click="addAssoc">
              确认添加
            </n-button>
          </n-form>
        </div>
      </n-drawer-content>
    </n-drawer>

    <!-- Case 命名弹窗（仅保存） -->
    <n-modal v-model:show="saveModalShow" preset="card" title="保存 Case" style="width: 420px">
      <n-input v-model:value="saveCaseName" placeholder="请输入 Case 名称" />
      <template #footer>
        <div class="modal-actions">
          <n-button @click="saveModalShow = false">取消</n-button>
          <n-button class="gradient-btn" :loading="saving" @click="handleSaveOnly">保存</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 创建并执行弹窗（普通 / 遍历两种形态） -->
    <ExecuteModal
      v-model:show="executeModalShow"
      :main-table="tableName"
      :related-tables="relatedTables"
      :iterate-info="iterateInfo"
      :auto-increment-column="autoIncrementColumn"
      :initial-name="defaultCaseName"
      :submitting="executing"
      @confirm="handleExecute"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowBackOutline, CheckmarkOutline, CloseOutline, SearchOutline } from '@vicons/ionicons5'
import { engineApi } from '@/api/engine'
import { casesApi } from '@/api/cases'
import type {
  Association,
  ColumnInfo,
  FieldStrategyConfig,
  IndexInfo,
  StrategyCode,
  TableInfo,
} from '@/api/types'
import StrategyParams from '@/components/business/StrategyParams.vue'
import ExecuteModal from '@/components/business/ExecuteModal.vue'
import AssocGraph from '@/components/business/AssocGraph.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { useTaskProgress } from '@/composables/useTaskProgress'
import { formatNumber, formatDateTime } from '@/utils/formatter'
import {
  columnTypeColor,
  getStrategyOptions,
  inferDefaultStrategy,
  isAutoIncrement,
  typesCompatible,
  validateStrategyParams,
} from '@/utils/strategy'

interface FieldRow {
  column: ColumnInfo
  strategy: StrategyCode
  params: Record<string, unknown>
}

const route = useRoute()
const router = useRouter()
const { hasPermission } = useAuth()
const { trackTask } = useTaskProgress()

const tableName = route.params.tableName as string
const datasourceId = Number(route.query.datasource_id)
const caseId = route.query.case_id ? Number(route.query.case_id) : null
const isEdit = !!caseId

const pageLoading = ref(true)
const tableInfo = ref<(TableInfo & { engine?: string; charset?: string }) | null>(null)
const fieldRows = ref<FieldRow[]>([])
const indexes = ref<IndexInfo[]>([])
const associations = ref<Association[]>([])
const outdatedFields = ref<string[]>([])
const fieldKeyword = ref('')
const dirty = ref(false)
const existingCaseName = ref('')

const filteredRows = computed(() => {
  const kw = fieldKeyword.value.trim().toLowerCase()
  if (!kw) return fieldRows.value
  return fieldRows.value.filter(
    (r) => r.column.column_name.toLowerCase().includes(kw) || r.column.column_type.toLowerCase().includes(kw),
  )
})

function isRequired(c: ColumnInfo): boolean {
  return !c.is_nullable && c.column_default == null
}

// ---------------- 数据加载 ----------------
async function loadPage(): Promise<void> {
  pageLoading.value = true
  try {
    // 字段与索引接口均返回纯数组
    const [colRes, idxRes] = await Promise.all([
      engineApi.columns(datasourceId, tableName),
      engineApi.indexes(datasourceId, tableName),
    ])
    indexes.value = idxRes.data
    // 初始化策略：优先后端推断，其次前端推断
    fieldRows.value = colRes.data.map((c) => {
      const inferred =
        c.suggested_strategy != null
          ? { strategy: c.suggested_strategy as StrategyCode, params: (c.suggested_params ?? {}) as Record<string, unknown> }
          : inferDefaultStrategy(c)
      return { column: c, strategy: inferred.strategy, params: { ...inferred.params } }
    })
    // 编辑模式：回显已保存配置
    if (caseId) {
      const detail = await casesApi.detail(caseId)
      existingCaseName.value = detail.data.case_name
      const cfg = detail.data.config
      const cfgMap = new Map(cfg.field_configs.map((f) => [f.column_name, f]))
      const existingNames = new Set(colRes.data.map((c) => c.column_name))
      outdatedFields.value = cfg.field_configs.filter((f) => !existingNames.has(f.column_name)).map((f) => f.column_name)
      fieldRows.value.forEach((row) => {
        const saved = cfgMap.get(row.column.column_name)
        if (saved) {
          row.strategy = saved.strategy
          row.params = { ...(saved.strategy_params ?? {}) }
        }
      })
      associations.value = [...cfg.associations]
      dirty.value = false
    }
  } finally {
    pageLoading.value = false
  }
}

// ---------------- 策略操作 ----------------
function changeStrategy(row: FieldRow, v: StrategyCode): void {
  row.strategy = v
  row.params = {}
  dirty.value = true
  // ITERATE_LIST 唯一性校验
  if (v === 'ITERATE_LIST') {
    const count = fieldRows.value.filter((r) => r.strategy === 'ITERATE_LIST').length
    if (count > 1) {
      window.$message.error('一个 Case 只允许一个字段使用按序遍历插入策略')
      row.strategy = 'DEFAULT'
    }
  }
}

/** 校验全部字段配置，返回是否通过 */
function validateAll(): boolean {
  for (const row of fieldRows.value) {
    const err = validateStrategyParams(row.column, row.strategy, row.params)
    if (err) {
      window.$message.error(`字段「${row.column.column_name}」：${err}`)
      return false
    }
  }
  return true
}

function buildFieldConfigs(): FieldStrategyConfig[] {
  return fieldRows.value.map((r) => ({
    column_name: r.column.column_name,
    data_type: r.column.data_type,
    column_type: r.column.column_type,
    is_nullable: !!r.column.is_nullable,
    is_primary_key: !!r.column.is_primary_key,
    strategy: r.strategy,
    strategy_params: r.params,
  }))
}

// ---------------- 关联管理 ----------------
const assocDrawerShow = ref(false)
const assocForm = reactive({
  sourceTable: tableName as string, // 默认主表
  sourceColumn: null as string | null,
  targetTable: null as string | null,
  targetColumn: null as string | null,
})
const targetTables = ref<TableInfo[]>([])
const targetColumns = ref<ColumnInfo[]>([])
const sourceColumns = ref<ColumnInfo[]>([]) // 关联表作为源时的字段缓存
const sourceColumnsLoading = ref(false)

// 源表选项：主表 + 已纳入关联的表（多级链式扩展：先 A→B，B 才可作为源去关联 C）
const sourceTableOptions = computed(() => {
  const tables: string[] = [tableName]
  for (const a of associations.value) {
    if (!tables.includes(a.target_table)) tables.push(a.target_table)
    const st = a.source_table
    if (st && !tables.includes(st)) tables.push(st)
  }
  return tables.map((t) => ({ label: t === tableName ? `${t}（主表）` : t, value: t }))
})

// 源字段选项：主表用已配置字段（非 SKIP），关联表用加载的字段（排除自增列）
const sourceColumnOptions = computed(() => {
  if (!assocForm.sourceTable || assocForm.sourceTable === tableName) {
    return fieldRows.value
      .filter((r) => r.strategy !== 'SKIP') // SKIP 字段不能设为关联源/目标
      .map((r) => ({
        label: `${r.column.column_name}（${r.column.column_type}）`,
        value: r.column.column_name,
      }))
  }
  return sourceColumns.value
    .filter((c) => !isAutoIncrement(c))
    .map((c) => ({ label: `${c.column_name}（${c.column_type}）`, value: c.column_name }))
})

// 源表变化：切到关联表时需加载该表字段
async function onSourceTableChange(table: string): Promise<void> {
  assocForm.sourceColumn = null
  if (!table || table === tableName) {
    sourceColumns.value = []
    return
  }
  sourceColumnsLoading.value = true
  try {
    const res = await engineApi.columns(datasourceId, table)
    sourceColumns.value = res.data
  } finally {
    sourceColumnsLoading.value = false
  }
}

const targetTableOptions = computed(() =>
  targetTables.value.map((t) => ({ label: `${t.table_name}${t.table_comment ? `（${t.table_comment}）` : ''}`, value: t.table_name })),
)

// 目标字段：仅显示类型兼容的字段（源字段按当前选中的源表取）
const targetColumnOptions = computed(() => {
  let source: ColumnInfo | undefined
  if (!assocForm.sourceTable || assocForm.sourceTable === tableName) {
    source = fieldRows.value.find((r) => r.column.column_name === assocForm.sourceColumn)?.column
  } else {
    source = sourceColumns.value.find((c) => c.column_name === assocForm.sourceColumn)
  }
  return targetColumns.value
    .filter((c) => !isAutoIncrement(c))
    .filter((c) => !source || typesCompatible(source, c))
    .map((c) => ({ label: `${c.column_name}（${c.column_type}）`, value: c.column_name }))
})

function assocsOf(columnName: string): Association[] {
  // 字段表格"关联字段"列：只显示以主表该字段为源发起的关联（多级关联中其他表为源的不在此列展示）
  return associations.value.filter((a) => (a.source_table || tableName) === tableName && a.source_column === columnName)
}

function removeAssoc(a: Association): void {
  associations.value = associations.value.filter((x) => x !== a)
  dirty.value = true
}

async function loadTargetColumns(): Promise<void> {
  assocForm.targetColumn = null
  targetColumns.value = []
  if (!assocForm.targetTable) return
  const res = await engineApi.columns(datasourceId, assocForm.targetTable)
  targetColumns.value = res.data
}

/** 关联环检测（表级有向图 DFS）：源表缺省为主表 */
function hasAssocCycle(edges: Association[]): boolean {
  const graph = new Map<string, string[]>()
  for (const e of edges) {
    const from = e.source_table || tableName
    const to = e.target_table
    graph.set(from, [...(graph.get(from) ?? []), to])
  }
  const visiting = new Set<string>()
  const done = new Set<string>()
  function dfs(node: string): boolean {
    if (visiting.has(node)) return true
    if (done.has(node)) return false
    visiting.add(node)
    for (const next of graph.get(node) ?? []) {
      if (dfs(next)) return true
    }
    visiting.delete(node)
    done.add(node)
    return false
  }
  return [...graph.keys()].some((k) => dfs(k))
}

function addAssoc(): void {
  if (!assocForm.sourceTable || !assocForm.sourceColumn || !assocForm.targetTable || !assocForm.targetColumn) return
  // 表级自关联校验
  if (assocForm.sourceTable === assocForm.targetTable) {
    window.$message.error('不允许表内自关联（源表与目标表相同）')
    return
  }
  // 重复校验（含源表维度）
  const dup = associations.value.some(
    (a) =>
      (a.source_table || tableName) === assocForm.sourceTable &&
      a.source_column === assocForm.sourceColumn &&
      a.target_table === assocForm.targetTable &&
      a.target_column === assocForm.targetColumn,
  )
  if (dup) {
    window.$message.warning('该关联已存在')
    return
  }
  const next = [
    ...associations.value,
    {
      source_table: assocForm.sourceTable === tableName ? null : assocForm.sourceTable, // 主表省略，保持简洁兼容
      source_column: assocForm.sourceColumn,
      target_table: assocForm.targetTable,
      target_column: assocForm.targetColumn,
    },
  ]
  // 循环关联校验（表级）
  if (hasAssocCycle(next)) {
    window.$message.error('检测到循环关联，请检查关联配置')
    return
  }
  associations.value = next
  dirty.value = true
  assocForm.sourceColumn = null
  assocForm.targetColumn = null
  window.$message.success('关联已添加')
}

// ---------------- 保存 / 执行 ----------------
const saveModalShow = ref(false)
const saveCaseName = ref('')
const saving = ref(false)
const executeModalShow = ref(false)
const executing = ref(false)

const relatedTables = computed(() => [...new Set(associations.value.map((a) => a.target_table))])

// 遍历模式信息（存在 ITERATE_LIST 字段时）
const iterateInfo = computed(() => {
  const row = fieldRows.value.find((r) => r.strategy === 'ITERATE_LIST')
  if (!row) return null
  const values = String(row.params.list ?? '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  if (!values.length) return null
  return {
    field: `${tableName}.${row.column.column_name}`,
    values,
    rowsPerValue: Number(row.params.rows_per_value ?? 1),
  }
})

const autoIncrementColumn = computed(() => {
  const col = fieldRows.value.find((r) => r.column.is_primary_key && isAutoIncrement(r.column))
  return col?.column.column_name ?? null
})

const defaultCaseName = computed(() => existingCaseName.value || `${tableName}_造数Case`)

function openSaveModal(): void {
  if (!validateAll()) return
  saveCaseName.value = defaultCaseName.value
  saveModalShow.value = true
}

/** 仅保存 Case（新建 → engine/save；编辑 → cases PUT） */
async function handleSaveOnly(): Promise<void> {
  const name = saveCaseName.value.trim()
  if (!name) {
    window.$message.error('Case 名称不能为空')
    return
  }
  saving.value = true
  try {
    if (isEdit && caseId) {
      await casesApi.update(caseId, {
        case_name: name,
        config: { version: '1.0', main_table: tableName, field_configs: buildFieldConfigs(), associations: associations.value },
      })
    } else {
      await engineApi.save({
        case_name: name,
        datasource_id: datasourceId,
        config: { version: '1.0', main_table: tableName, field_configs: buildFieldConfigs(), associations: associations.value },
      })
    }
    window.$message.success('Case 已保存')
    dirty.value = false
    saveModalShow.value = false
    router.push('/cases')
  } finally {
    saving.value = false
  }
}

function openExecuteModal(): void {
  if (!validateAll()) return
  executeModalShow.value = true
}

/** 创建并执行：保存 Case 并立即执行，成功后打开进度面板 */
async function handleExecute(payload: { caseName: string; targetCount: number }): Promise<void> {
  executing.value = true
  try {
    let taskNo: string
    if (isEdit && caseId) {
      // 编辑模式：先保存最新配置再执行
      await casesApi.update(caseId, {
        case_name: payload.caseName,
        config: { version: '1.0', main_table: tableName, field_configs: buildFieldConfigs(), associations: associations.value },
      })
      const res = await casesApi.execute(caseId, payload.targetCount)
      taskNo = res.data.task_no
    } else {
      const res = await engineApi.execute({
        case_name: payload.caseName,
        datasource_id: datasourceId,
        target_count: payload.targetCount,
        config: { version: '1.0', main_table: tableName, field_configs: buildFieldConfigs(), associations: associations.value },
      })
      taskNo = res.data.task_no
    }
    dirty.value = false
    executeModalShow.value = false
    trackTask(taskNo, payload.caseName)
  } finally {
    executing.value = false
  }
}

/** 取消：清空所有字段配置（恢复默认），二次确认 */
function handleReset(): void {
  window.$dialog.warning({
    title: '确认取消',
    content: '将清空所有字段配置并恢复默认推断策略，是否继续？',
    positiveText: '确认',
    negativeText: '再想想',
    onPositiveClick: () => {
      fieldRows.value.forEach((row) => {
        const inferred = inferDefaultStrategy(row.column)
        row.strategy = inferred.strategy
        row.params = { ...inferred.params }
      })
      associations.value = []
      dirty.value = false
    },
  })
}

/** 返回：有未保存配置时弹确认框 */
function handleBack(): void {
  if (!dirty.value) {
    router.push('/engine')
    return
  }
  window.$dialog.warning({
    title: '有未保存的配置',
    content: '当前字段配置尚未保存，离开后将丢失，是否继续？',
    positiveText: '离开',
    negativeText: '留下',
    onPositiveClick: () => router.push('/engine'),
  })
}

onMounted(async () => {
  await loadPage()
  // 关联管理需要目标表列表；表基本信息改由表列表接口获取（columns 接口为纯数组）
  try {
    const res = await engineApi.tables(datasourceId)
    targetTables.value = res.data.filter((t) => t.table_name !== tableName)
    tableInfo.value = res.data.find((t) => t.table_name === tableName) ?? null
  } catch {
    // 目标表列表加载失败不阻塞主流程
  }
})
</script>

<style scoped>
.field-config-page {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  margin-bottom: 14px;
  position: sticky;
  top: 0;
  z-index: 10;
}
.action-bar-right {
  display: flex;
  gap: 10px;
}
.field-card {
  padding: 14px;
}
.field-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.field-table-wrap {
  overflow: auto;
  max-height: calc(100vh - 320px);
}
.field-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.field-table th {
  text-align: left;
  padding: 8px 10px;
  color: #94a3b8;
  font-weight: 500;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  position: sticky;
  top: 0;
  background: #1a1a2e;
  z-index: 1;
}
.field-table td {
  padding: 8px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  vertical-align: middle;
}
.field-name {
  font-weight: 600;
  color: #e2e8f0;
  cursor: default;
}
.required-star {
  color: #ef4444;
  margin-right: 2px;
  font-size: 11px;
}
.row-skip {
  opacity: 0.5;
  background: rgba(148, 163, 184, 0.04);
}
.dim {
  color: #64748b;
  font-size: 12px;
}
.assoc-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.index-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.index-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.index-name {
  color: #e2e8f0;
}
.assoc-tip {
  margin: 0 0 12px;
}
.assoc-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}
.assoc-item {
  position: relative;
  display: block;
  padding: 8px 48px 8px 12px; /* 右侧预留删除按钮空间 */
  border: 1px solid rgba(124, 58, 237, 0.2);
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere; /* 长表名/字段名任意断行，避免 flex 压缩成一字一行 */
}
.assoc-source {
  color: #a78bfa;
  font-weight: 600;
}
.assoc-target {
  color: #60a5fa;
}
.assoc-item .dim {
  padding: 0 4px;
}
.assoc-item :deep(.n-button) {
  position: absolute;
  right: 8px;
  top: 8px;
}
.assoc-add {
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  padding-top: 14px;
}
.assoc-add-title {
  margin: 0 0 10px;
  font-size: 13px;
  color: #a78bfa;
}
.assoc-graph-preview {
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  padding-top: 14px;
  margin-bottom: 14px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.mb-3 {
  margin-bottom: 12px;
}
</style>
