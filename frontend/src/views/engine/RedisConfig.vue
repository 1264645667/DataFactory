<template>
  <!-- Redis 造数配置页：Key 模板 + value 字段策略 + 写入模式 -->
  <div class="redis-config-page">
    <!-- 顶部操作栏 -->
    <div class="action-bar glass-card">
      <n-button size="small" quaternary @click="handleBack">
        <template #icon><n-icon><ArrowBackOutline /></n-icon></template>
        返回
      </n-button>
      <div class="action-bar-right">
        <n-button v-if="hasPermission('ENGINE:CREATE')" size="small" @click="openSaveModal">
          {{ isEdit ? '保存修改' : '创建 Case' }}
        </n-button>
        <n-button v-if="hasPermission('ENGINE:EXECUTE')" size="small" class="gradient-btn" @click="openExecuteModal">
          创建并执行
        </n-button>
      </div>
    </div>

    <n-spin :show="pageLoading">
      <!-- Key 模板与写入配置 -->
      <div class="config-card gradient-border-card">
        <h3 class="card-title">Key 配置</h3>
        <n-alert type="info" :show-icon="false" class="mb-3">
          模板占位符：{字段名} 引用下方字段生成值；{incr}/{incr:100} 全局递增；{uuid}/{uuid:8}；{rand:6} N位随机数字；{i} 批内序号；{ts}/{ts_ms} 时间戳；{task_no} 任务编号。
        </n-alert>
        <n-form label-placement="top" size="small">
          <div class="form-row">
            <n-form-item label="写入模式" class="form-col">
              <n-radio-group v-model:value="form.writeMode" size="small">
                <n-radio-button value="per_row">每行一个 Key</n-radio-button>
                <n-radio-button value="single_key">聚合单 Key</n-radio-button>
              </n-radio-group>
              <template #feedback>
                <span class="dim">
                  {{ form.writeMode === 'per_row' ? '执行 N 条 → 生成 N 个 Key（Key 模板须含行级占位符）' : '执行 N 条 → 1 个 Key 聚合 N 个成员' }}
                </span>
              </template>
            </n-form-item>
            <n-form-item label="数据类型" class="form-col">
              <n-select v-model:value="form.dataType" :options="dataTypeOptions" />
            </n-form-item>
            <n-form-item label="TTL（秒，0=不过期）" class="form-col">
              <n-input-number v-model:value="form.ttlSeconds" :min="0" size="small" style="width: 160px" />
            </n-form-item>
          </div>
          <n-form-item label="Key 模板">
            <n-input
              v-model:value="form.keyTemplate"
              :placeholder="form.writeMode === 'per_row' ? '如 user:profile:{incr} 或 user:{id}' : '如 case:{task_no}:users'"
            />
          </n-form-item>

          <!-- Key 引用字段（独立于 value 字段；同名时 Key 渲染优先取独立配置，实现解耦） -->
          <div v-if="keyRefs.length > 0 || keyFieldRows.length > 0" class="key-fields-block">
            <div class="key-fields-head">
              <span class="key-fields-title">Key 引用字段</span>
              <n-button size="tiny" @click="addFieldTo(keyFieldRows)">添加 Key 字段</n-button>
            </div>
            <div v-if="keyRefs.length > 0" class="key-refs">
              <template v-for="ref in keyRefs" :key="ref">
                <n-tag
                  size="small"
                  :type="keyRefSource(ref) === 'independent' ? 'warning' : keyRefSource(ref) === 'shared' ? 'default' : 'error'"
                >{{ ref }} · {{ keyRefSource(ref) === 'independent' ? 'Key 独立配置' : keyRefSource(ref) === 'shared' ? '共享 value 字段' : '未定义' }}</n-tag>
                <n-button
                  v-if="keyRefSource(ref) === 'shared'"
                  text
                  size="tiny"
                  type="primary"
                  @click="promoteToKeyField(ref)"
                >独立配置</n-button>
              </template>
            </div>
            <p class="dim key-fields-tip">未独立配置时，Key 占位符取同名 value 字段的值（共享）；独立配置后两者互不影响。</p>
            <table v-if="keyFieldRows.length > 0" class="field-table">
              <thead>
                <tr>
                  <th style="width: 180px">字段名</th>
                  <th style="width: 110px">类型</th>
                  <th style="width: 170px">造数策略</th>
                  <th>策略参数</th>
                  <th style="width: 60px">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in keyFieldRows" :key="i">
                  <td>
                    <n-input v-model:value="row.name" size="small" placeholder="占位符名" @update:value="dirty = true" />
                  </td>
                  <td>
                    <n-select
                      :value="row.kind"
                      :options="kindOptions"
                      size="small"
                      @update:value="(v: string) => changeKind(row, v)"
                    />
                  </td>
                  <td>
                    <n-select
                      :value="row.strategy"
                      :options="strategyOptionsFor(row)"
                      size="small"
                      @update:value="(v: StrategyCode) => changeStrategy(row, v)"
                    />
                  </td>
                  <td>
                    <StrategyParams
                      :strategy="row.strategy"
                      :column="syntheticColumn(row)"
                      :sibling-columns="[]"
                      v-model="row.params"
                    />
                  </td>
                  <td>
                    <n-button text size="tiny" type="error" @click="removeFieldFrom(keyFieldRows, i)">删除</n-button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <n-form-item v-if="form.dataType === 'zset'" label="分数字段（从下方字段中选择）">
            <n-select
              v-model:value="form.scoreField"
              :options="fieldNameOptions"
              placeholder="选择数值字段作为 score"
            />
          </n-form-item>
          <n-form-item label="value 模板（可选，覆盖默认组装）">
            <n-input
              v-model:value="form.valueTemplate"
              type="textarea"
              :rows="4"
              placeholder='留空按数据类型默认组装（json=全部字段 JSON 对象）；示例：{"name":"{name}","mobile":"{mobile}"}'
            />
            <template #feedback>
              <div class="tpl-actions">
                <n-button size="tiny" type="primary" secondary @click="parseTemplateFields">解析模板生成字段</n-button>
                <span class="dim">粘贴业务 JSON 后点击：自动识别字段名/类型/初始值（自定义输入策略），模板字面量替换为 {字段} 占位符</span>
              </div>
            </template>
          </n-form-item>
        </n-form>
      </div>

      <!-- value 字段配置 -->
      <div class="config-card gradient-border-card">
        <div class="field-head">
          <h3 class="card-title">value 字段（复用造数策略）</h3>
          <n-button size="small" @click="addFieldTo(fieldRows)">添加字段</n-button>
        </div>
        <div class="field-table-wrap">
          <table class="field-table">
            <thead>
              <tr>
                <th style="width: 180px">字段名</th>
                <th style="width: 110px">类型</th>
                <th style="width: 170px">造数策略</th>
                <th>策略参数</th>
                <th style="width: 60px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in fieldRows" :key="i">
                <td>
                  <n-input v-model:value="row.name" size="small" placeholder="字段名，如 name" @update:value="dirty = true" />
                </td>
                <td>
                  <n-select
                    :value="row.kind"
                    :options="kindOptions"
                    size="small"
                    @update:value="(v: string) => changeKind(row, v)"
                  />
                </td>
                <td>
                  <n-select
                    :value="row.strategy"
                    :options="strategyOptionsFor(row)"
                    size="small"
                    @update:value="(v: StrategyCode) => changeStrategy(row, v)"
                  />
                </td>
                <td>
                  <StrategyParams
                    :strategy="row.strategy"
                    :column="syntheticColumn(row)"
                    :sibling-columns="[]"
                    v-model="row.params"
                  />
                </td>
                <td>
                  <n-button text size="tiny" type="error" @click="removeFieldFrom(fieldRows, i)">删除</n-button>
                </td>
              </tr>
            </tbody>
          </table>
          <EmptyState v-if="fieldRows.length === 0" description="暂无字段，点击右上角「添加字段」" :size="70" />
        </div>
      </div>
    </n-spin>

    <!-- 保存弹窗 -->
    <n-modal v-model:show="saveModalShow" preset="card" title="保存 Case" style="width: 420px">
      <n-input v-model:value="caseName" placeholder="请输入 Case 名称" />
      <template #footer>
        <div class="modal-actions">
          <n-button @click="saveModalShow = false">取消</n-button>
          <n-button class="gradient-btn" :loading="submitting" @click="handleSaveOnly">保存</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 执行弹窗 -->
    <n-modal v-model:show="executeModalShow" preset="card" title="创建并执行" style="width: 420px">
      <n-form label-placement="top" size="small">
        <n-form-item label="Case 名称">
          <n-input v-model:value="caseName" placeholder="请输入 Case 名称" />
        </n-form-item>
        <n-form-item :label="form.writeMode === 'per_row' ? '造数条数（生成 Key 个数）' : '造数条数（聚合成员数）'">
          <n-input-number v-model:value="targetCount" :min="1" :max="100000000" style="width: 100%" />
        </n-form-item>
      </n-form>
      <template #footer>
        <div class="modal-actions">
          <n-button @click="executeModalShow = false">取消</n-button>
          <n-button class="gradient-btn" :loading="submitting" @click="handleExecute">执行</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowBackOutline } from '@vicons/ionicons5'
import { engineApi } from '@/api/engine'
import { casesApi } from '@/api/cases'
import type { CaseConfigJson, ColumnInfo, FieldStrategyConfig, RedisCaseConfig, StrategyCode } from '@/api/types'
import StrategyParams from '@/components/business/StrategyParams.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { useTaskProgress } from '@/composables/useTaskProgress'
import { parseJsonTemplate, extractFieldRefs, type ParsedTemplate } from '@/utils/jsonTemplate'
import { getStrategyOptions, validateStrategyParams } from '@/utils/strategy'

interface RedisFieldRow {
  name: string
  /** 字段类型（决定可用策略）：string/number/datetime */
  kind: string
  strategy: StrategyCode
  params: Record<string, unknown>
}

const route = useRoute()
const router = useRouter()
const { hasPermission } = useAuth()
const { trackTask } = useTaskProgress()

const datasourceId = Number(route.query.datasource_id)
const caseId = route.query.case_id ? Number(route.query.case_id) : null
const isEdit = !!caseId

const pageLoading = ref(false)
const dirty = ref(false)
const submitting = ref(false)
const saveModalShow = ref(false)
const executeModalShow = ref(false)
const caseName = ref('')
const targetCount = ref(1000)

const form = reactive({
  keyTemplate: '',
  writeMode: 'per_row' as 'per_row' | 'single_key',
  dataType: 'json' as RedisCaseConfig['data_type'],
  ttlSeconds: 0,
  valueTemplate: '',
  scoreField: null as string | null,
})

const fieldRows = ref<RedisFieldRow[]>([])
/** Key 引用字段（独立配置，与 value 字段解耦；同名时 Key 渲染优先取这里） */
const keyFieldRows = ref<RedisFieldRow[]>([])

/** Key 模板引用的字段占位符（排除内置占位符） */
const keyRefs = computed(() => extractFieldRefs(form.keyTemplate))
const keyFieldSet = computed(() => new Set(keyFieldRows.value.map((r) => r.name.trim()).filter(Boolean)))
const valueFieldSet = computed(() => new Set(fieldRows.value.map((r) => r.name.trim()).filter(Boolean)))

/** Key 占位符来源状态：independent=Key 独立配置 / shared=共享 value 字段 / missing=未定义 */
function keyRefSource(ref: string): 'independent' | 'shared' | 'missing' {
  if (keyFieldSet.value.has(ref)) return 'independent'
  if (valueFieldSet.value.has(ref)) return 'shared'
  return 'missing'
}

const kindOptions = [
  { label: '字符串', value: 'string' },
  { label: '数字', value: 'number' },
  { label: '时间', value: 'datetime' },
]

const dataTypeOptions = computed(() => {
  const all = [
    { label: 'json（JSON 对象）', value: 'json' },
    { label: 'string（字符串）', value: 'string' },
    { label: 'hash（哈希）', value: 'hash' },
    { label: 'list（列表，聚合）', value: 'list' },
    { label: 'set（集合，聚合）', value: 'set' },
    { label: 'zset（有序集合，聚合）', value: 'zset' },
  ]
  if (form.writeMode === 'per_row') return all.filter((o) => !['list', 'set', 'zset'].includes(o.value))
  return all
})

const fieldNameOptions = computed(() =>
  fieldRows.value.filter((r) => r.name.trim()).map((r) => ({ label: r.name, value: r.name })),
)

// 类型 → 合成 ColumnInfo（复用策略推断与参数组件）
const KIND_COLUMN: Record<string, { data_type: string; column_type: string; char_max_length: number | null }> = {
  string: { data_type: 'varchar', column_type: 'varchar(255)', char_max_length: 255 },
  number: { data_type: 'int', column_type: 'int(11)', char_max_length: null },
  datetime: { data_type: 'datetime', column_type: 'datetime', char_max_length: null },
}

function syntheticColumn(row: RedisFieldRow): ColumnInfo {
  const meta = KIND_COLUMN[row.kind] ?? KIND_COLUMN.string
  return {
    column_name: row.name || 'field',
    column_comment: null,
    data_type: meta.data_type,
    column_type: meta.column_type,
    is_nullable: 1,
    is_primary_key: 0,
    is_unique: 0,
    char_max_length: meta.char_max_length,
    column_default: null,
    extra: null,
  }
}

function strategyOptionsFor(row: RedisFieldRow) {
  // Redis value 字段不支持 SKIP / ITERATE_LIST
  return getStrategyOptions(syntheticColumn(row)).filter((o) => !['SKIP', 'ITERATE_LIST'].includes(o.value))
}

function changeKind(row: RedisFieldRow, v: string): void {
  row.kind = v
  row.strategy = 'DEFAULT'
  row.params = {}
  dirty.value = true
}

function changeStrategy(row: RedisFieldRow, v: StrategyCode): void {
  row.strategy = v
  row.params = {}
  dirty.value = true
}

function addFieldTo(rows: RedisFieldRow[]): void {
  rows.push({ name: '', kind: 'string', strategy: 'UUID', params: {} })
  dirty.value = true
}

function removeFieldFrom(rows: RedisFieldRow[], i: number): void {
  rows.splice(i, 1)
  dirty.value = true
}

/** 把 value 字段复制为 Key 独立字段（解耦：Key 渲染不再跟随 value 策略变化） */
function promoteToKeyField(name: string): void {
  const src = fieldRows.value.find((r) => r.name === name)
  keyFieldRows.value.push({
    name,
    kind: src?.kind ?? 'string',
    strategy: src?.strategy ?? 'CUSTOM_VALUE',
    params: { ...(src?.params ?? {}) },
  })
  dirty.value = true
}

/**
 * 从 value 模板解析 JSON：叶子标量提取为字段行（自定义输入策略 + 模板原值），
 * 模板中对应字面量替换为 {字段名} 占位符。
 */
function parseTemplateFields(): void {
  const raw = form.valueTemplate.trim()
  if (!raw) {
    window.$message.warning('请先粘贴 JSON value 模板')
    return
  }
  let parsed: ParsedTemplate
  try {
    parsed = parseJsonTemplate(raw)
  } catch (e) {
    window.$message.error(`JSON 解析失败：${(e as Error).message}`)
    return
  }
  if (!parsed.fields.length) {
    window.$message.warning('模板中没有可识别的标量字段（纯字面量/空结构）')
    return
  }

  const applyParse = (): void => {
    form.valueTemplate = parsed.template
    fieldRows.value = parsed.fields.map((f) => ({
      name: f.name,
      kind: f.kind,
      strategy: 'CUSTOM_VALUE',
      params: { value: f.value },
    }))
    dirty.value = true
    window.$message.success(`已识别 ${parsed.fields.length} 个字段，可在下方逐个调整策略和值`)
  }
  if (fieldRows.value.length > 0) {
    window.$dialog.warning({
      title: '覆盖现有字段',
      content: `将用模板解析出的 ${parsed.fields.length} 个字段覆盖当前 ${fieldRows.value.length} 个字段配置，是否继续？`,
      positiveText: '覆盖',
      negativeText: '取消',
      onPositiveClick: applyParse,
    })
  } else {
    applyParse()
  }
}

/** 校验全部配置，返回是否通过 */
function validateAll(): boolean {
  if (!form.keyTemplate.trim()) {
    window.$message.error('请填写 Key 模板')
    return false
  }
  const names = new Set<string>()
  for (const row of fieldRows.value) {
    if (!row.name.trim()) {
      window.$message.error('存在未命名的字段')
      return false
    }
    if (names.has(row.name.trim())) {
      window.$message.error(`字段名重复：${row.name}`)
      return false
    }
    names.add(row.name.trim())
    const err = validateStrategyParams(syntheticColumn(row), row.strategy, row.params)
    if (err) {
      window.$message.error(`字段「${row.name}」：${err}`)
      return false
    }
  }
  // Key 引用字段：名称为空/重名校验 + 策略参数校验
  const keyNames = new Set<string>()
  for (const row of keyFieldRows.value) {
    if (!row.name.trim()) {
      window.$message.error('存在未命名的 Key 字段')
      return false
    }
    if (keyNames.has(row.name.trim())) {
      window.$message.error(`Key 字段名重复：${row.name}`)
      return false
    }
    keyNames.add(row.name.trim())
    const err = validateStrategyParams(syntheticColumn(row), row.strategy, row.params)
    if (err) {
      window.$message.error(`Key 字段「${row.name}」：${err}`)
      return false
    }
  }
  // Key 模板引用了未定义字段（既非 Key 字段也非 value 字段）
  const missing = keyRefs.value.filter((r) => keyRefSource(r) === 'missing')
  if (missing.length) {
    window.$message.error(`Key 模板引用了未定义的字段：${missing.join('、')}（请添加为 value 字段或 Key 字段）`)
    return false
  }
  if (!fieldRows.value.length && !form.valueTemplate.trim()) {
    window.$message.error('至少配置一个 value 字段或填写 value 模板')
    return false
  }
  if (form.dataType === 'zset' && !form.scoreField) {
    window.$message.error('zset 类型必须选择分数字段')
    return false
  }
  if (form.writeMode === 'single_key') {
    const badToken = /\{([^{}]+)\}/.exec(form.keyTemplate)?.[1]
    if (badToken && badToken.trim() !== 'task_no') {
      window.$message.error('聚合单 Key 模式的 Key 模板仅支持 {task_no} 占位符（Key 须在任务内各批次保持稳定）')
      return false
    }
  }
  return true
}

function toFieldConfig(r: RedisFieldRow): FieldStrategyConfig {
  const col = syntheticColumn(r)
  return {
    column_name: r.name.trim(),
    data_type: col.data_type,
    column_type: col.column_type,
    is_nullable: true,
    is_primary_key: false,
    strategy: r.strategy,
    strategy_params: r.params,
  }
}

function buildConfig(): CaseConfigJson {
  const redisConfig: RedisCaseConfig = {
    key_template: form.keyTemplate.trim(),
    write_mode: form.writeMode,
    data_type: form.dataType,
    field_configs: fieldRows.value.map(toFieldConfig),
    key_fields: keyFieldRows.value.map(toFieldConfig),
    value_template: form.valueTemplate.trim() || null,
    score_field: form.scoreField,
    ttl_seconds: form.ttlSeconds || 0,
  }
  return {
    version: '1.0',
    case_type: 'redis',
    main_table: '',
    field_configs: [],
    associations: [],
    redis_config: redisConfig,
  }
}

function openSaveModal(): void {
  if (!validateAll()) return
  if (!caseName.value) caseName.value = `redis_${form.keyTemplate.slice(0, 24).replace(/[{}]/g, '')}_Case`
  saveModalShow.value = true
}

function openExecuteModal(): void {
  if (!validateAll()) return
  if (!caseName.value) caseName.value = `redis_${form.keyTemplate.slice(0, 24).replace(/[{}]/g, '')}_Case`
  executeModalShow.value = true
}

async function handleSaveOnly(): Promise<void> {
  if (!caseName.value.trim()) {
    window.$message.error('Case 名称不能为空')
    return
  }
  submitting.value = true
  try {
    if (isEdit && caseId) {
      await casesApi.update(caseId, { case_name: caseName.value.trim(), config: buildConfig() })
    } else {
      await engineApi.save({ case_name: caseName.value.trim(), datasource_id: datasourceId, config: buildConfig() })
    }
    window.$message.success('Case 已保存')
    dirty.value = false
    saveModalShow.value = false
    router.push('/cases')
  } finally {
    submitting.value = false
  }
}

async function handleExecute(): Promise<void> {
  if (!caseName.value.trim()) {
    window.$message.error('Case 名称不能为空')
    return
  }
  submitting.value = true
  try {
    let taskNo: string
    if (isEdit && caseId) {
      await casesApi.update(caseId, { case_name: caseName.value.trim(), config: buildConfig() })
      const res = await casesApi.execute(caseId, targetCount.value)
      taskNo = res.data.task_no
    } else {
      const res = await engineApi.execute({
        case_name: caseName.value.trim(),
        datasource_id: datasourceId,
        target_count: targetCount.value,
        config: buildConfig(),
      })
      taskNo = res.data.task_no
    }
    dirty.value = false
    executeModalShow.value = false
    trackTask(taskNo, caseName.value.trim())
  } finally {
    submitting.value = false
  }
}

/** 编辑模式：回显已保存配置 */
async function loadCase(): Promise<void> {
  if (!caseId) return
  pageLoading.value = true
  try {
    const res = await casesApi.detail(caseId)
    const cfg = res.data.config
    caseName.value = res.data.case_name
    if (cfg.redis_config) {
      form.keyTemplate = cfg.redis_config.key_template
      form.writeMode = cfg.redis_config.write_mode
      form.dataType = cfg.redis_config.data_type
      form.ttlSeconds = cfg.redis_config.ttl_seconds || 0
      form.valueTemplate = cfg.redis_config.value_template ?? ''
      form.scoreField = cfg.redis_config.score_field ?? null
      const toRow = (fc: FieldStrategyConfig): RedisFieldRow => ({
        name: fc.column_name,
        kind: fc.data_type === 'int' || fc.data_type === 'bigint' ? 'number' : fc.data_type === 'datetime' ? 'datetime' : 'string',
        strategy: fc.strategy,
        params: { ...(fc.strategy_params ?? {}) },
      })
      fieldRows.value = (cfg.redis_config.field_configs ?? []).map(toRow)
      keyFieldRows.value = (cfg.redis_config.key_fields ?? []).map(toRow)
    }
    dirty.value = false
  } finally {
    pageLoading.value = false
  }
}

function handleBack(): void {
  if (!dirty.value) {
    router.push('/engine')
    return
  }
  window.$dialog.warning({
    title: '有未保存的配置',
    content: '当前配置尚未保存，离开后将丢失，是否继续？',
    positiveText: '离开',
    negativeText: '留下',
    onPositiveClick: () => router.push('/engine'),
  })
}

onMounted(loadCase)
</script>

<style scoped>
.redis-config-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  position: sticky;
  top: 0;
  z-index: 10;
}
.action-bar-right {
  display: flex;
  gap: 10px;
}
.config-card {
  padding: 16px;
}
.card-title {
  margin: 0 0 12px;
  font-size: 14px;
  color: #a78bfa;
}
.form-row {
  display: flex;
  gap: 16px;
}
.form-col {
  flex: 1;
  min-width: 0;
}
.field-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.field-table-wrap {
  overflow: auto;
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
}
.field-table td {
  padding: 8px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  vertical-align: middle;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.mb-3 {
  margin-bottom: 12px;
}
.dim {
  color: #64748b;
  font-size: 12px;
}
.tpl-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.key-fields-block {
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.key-fields-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.key-fields-title {
  font-size: 13px;
  color: #f59e0b;
  font-weight: 600;
}
.key-refs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.key-fields-tip {
  margin: 8px 0;
}
</style>
