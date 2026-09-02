<template>
  <!-- 创建并执行弹窗普通模式 / 遍历模式两种形态 -->
  <n-modal :show="show" preset="card" :title="modalTitle" style="width: 560px" @update:show="close">
    <n-form label-placement="left" label-width="90px">
      <n-form-item label="Case 名称" required :feedback="nameError" :validation-status="nameError ? 'error' : undefined">
        <n-input v-model:value="caseName" :disabled="nameReadonly" placeholder="请输入 Case 名称" />
      </n-form-item>
      <!-- 形态 A：普通模式输入造数条数 -->
      <n-form-item v-if="!iterateInfo" label="造数条数" required :feedback="countError" :validation-status="countError ? 'error' : undefined">
        <n-input-number v-model:value="targetCount" :min="1" style="width: 220px" placeholder="条" />
      </n-form-item>
    </n-form>

    <!-- 执行摘要预览 -->
    <div class="exec-summary">
      <div class="summary-title">{{ iterateInfo ? '遍历执行预览' : '执行摘要预览' }}</div>
      <template v-if="!iterateInfo">
        <div class="summary-row">
          <span>主表：{{ mainTable }}</span>
          <span class="dim">预计插入 {{ formatNumber(targetCount) }} 条</span>
        </div>
        <div v-for="t in relatedTables" :key="t" class="summary-row">
          <span>关联：{{ t }}</span>
          <span class="dim">预计插入 {{ formatNumber(targetCount) }} 条</span>
        </div>
        <div class="summary-total">
          总计：{{ relatedTables.length + 1 }} 张表，共 {{ formatNumber((relatedTables.length + 1) * (targetCount ?? 0)) }} 条数据
        </div>
      </template>
      <template v-else>
        <div class="summary-row"><span>遍历字段：{{ iterateInfo.field }}</span></div>
        <div class="summary-row">
          <span>遍历值列表：{{ iterateInfo.values.slice(0, 6).join(' / ') }}{{ iterateInfo.values.length > 6 ? ' …' : '' }}（共 {{ iterateInfo.values.length }} 个）</span>
        </div>
        <div class="summary-row"><span>每值插入条数：{{ iterateInfo.rowsPerValue }} 条</span></div>
        <div class="summary-rounds">
          <div v-for="(v, i) in iterateInfo.values.slice(0, 5)" :key="i" class="summary-row dim">
            第 {{ i + 1 }} 轮 {{ iterateInfo.field.split('.').pop() }}="{{ v }}"：各表插入 {{ iterateInfo.rowsPerValue }} 条
          </div>
          <div v-if="iterateInfo.values.length > 5" class="summary-row dim">… 共 {{ iterateInfo.values.length }} 轮</div>
        </div>
        <div class="summary-total">
          总计：{{ iterateInfo.values.length }} 轮 × {{ relatedTables.length + 1 }} 张表 × {{ iterateInfo.rowsPerValue }} 条
          = {{ formatNumber(iterateInfo.values.length * (relatedTables.length + 1) * iterateInfo.rowsPerValue) }} 条
        </div>
      </template>
    </div>

    <!-- AUTO_INCREMENT 预检提示 -->
    <n-alert v-if="autoIncrementColumn" type="warning" class="mt-3" :show-icon="false">
      检测到主键 {{ autoIncrementColumn }} 为 AUTO_INCREMENT，造数时将由数据库自动填充。
    </n-alert>

    <n-alert type="info" class="mt-3" :show-icon="false">注意：操作不可逆，请确认目标数据源和条数</n-alert>

    <template #footer>
      <div class="modal-actions">
        <n-button @click="close">取消</n-button>
        <n-button class="gradient-btn" :loading="submitting" @click="handleConfirm">确认执行</n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { formatNumber } from '@/utils/formatter'

// 遍历模式信息
interface IterateInfo {
  field: string
  values: string[]
  rowsPerValue: number
}

const props = withDefaults(
  defineProps<{
    show: boolean
    mainTable: string
    relatedTables: string[]
    iterateInfo?: IterateInfo | null
    autoIncrementColumn?: string | null
    initialName?: string
    nameReadonly?: boolean
    submitting?: boolean
  }>(),
  {
    iterateInfo: null,
    autoIncrementColumn: null,
    initialName: '',
    nameReadonly: false,
    submitting: false,
  },
)

const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'confirm', payload: { caseName: string; targetCount: number }): void
}>()

const caseName = ref(props.initialName)
const targetCount = ref<number | null>(1000)
const nameError = ref('')
const countError = ref('')

watch(
  () => props.show,
  (v) => {
    if (v) {
      caseName.value = props.initialName
      nameError.value = ''
      countError.value = ''
    }
  },
)

const modalTitle = computed(() => (props.iterateInfo ? '准备造数（遍历模式）' : '准备造数'))

function close(): void {
  emit('update:show', false)
}

function handleConfirm(): void {
  nameError.value = caseName.value.trim() ? '' : 'Case 名称不能为空'
  countError.value = ''
  if (!props.iterateInfo && (!targetCount.value || targetCount.value < 1)) {
    countError.value = '造数条数必须 ≥ 1'
  }
  if (nameError.value || countError.value) return
  emit('confirm', {
    caseName: caseName.value.trim(),
    targetCount: props.iterateInfo
      ? props.iterateInfo.values.length * props.iterateInfo.rowsPerValue
      : targetCount.value!,
  })
}
</script>

<style scoped>
.exec-summary {
  border: 1px solid rgba(124, 58, 237, 0.25);
  border-radius: 8px;
  padding: 12px 14px;
  background: rgba(124, 58, 237, 0.05);
  font-size: 13px;
}
.summary-title {
  font-weight: 600;
  color: #a78bfa;
  margin-bottom: 8px;
}
.summary-row {
  display: flex;
  justify-content: space-between;
  padding: 2px 0;
}
.summary-total {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed rgba(148, 163, 184, 0.2);
  font-weight: 600;
  color: #c4b5fd;
}
.dim {
  color: #64748b;
  font-size: 12px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
