<template>
  <!-- 场景画布节点卡片Case 信息 + 造数条数 + 失败策略 + 移除 -->
  <div class="scene-node" :class="{ readonly }">
    <Handle type="target" :position="Position.Left" />
    <div class="node-head">
      <n-icon :size="14" color="#a78bfa"><FolderOpenOutline /></n-icon>
      <span class="node-name">{{ data.case_name }}</span>
    </div>
    <div class="node-meta">
      <span v-if="data.main_table">主表：{{ data.main_table }}</span>
      <span v-if="data.datasource_name">数据源：{{ data.datasource_name }}</span>
    </div>
    <div class="node-config">
      <div class="node-field" @mousedown.stop>
        <span class="node-field-label">造数条数</span>
        <n-input-number
          :value="data.target_count"
          size="tiny"
          :min="1"
          :disabled="readonly"
          placeholder="必填"
          style="width: 110px"
          @update:value="(v: number | null) => update('target_count', v)"
        />
      </div>
      <div class="node-field" @mousedown.stop>
        <span class="node-field-label">失败策略</span>
        <n-select
          :value="data.fail_strategy"
          size="tiny"
          :disabled="readonly"
          :options="failOptions"
          style="width: 110px"
          @update:value="(v: string) => update('fail_strategy', v)"
        />
      </div>
    </div>
    <div v-if="!readonly" class="node-remove" @mousedown.stop @click="emit('remove', id)">× 移除</div>
    <Handle type="source" :position="Position.Right" />
  </div>
</template>

<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'
import { FolderOpenOutline } from '@vicons/ionicons5'

// 自定义场景节点组件：通过 data 与画布双向同步节点参数
const props = withDefaults(
  defineProps<{
    id: string
    data: {
      case_name: string
      main_table?: string
      datasource_name?: string
      target_count: number | null
      fail_strategy: 'continue' | 'abort'
    }
    readonly?: boolean
  }>(),
  { readonly: false },
)

const emit = defineEmits<{
  (e: 'remove', id: string): void
  (e: 'update', id: string, key: string, value: unknown): void
}>()

const failOptions = [
  { label: '继续执行', value: 'continue' },
  { label: '终止场景', value: 'abort' },
]

function update(key: string, value: unknown): void {
  emit('update', props.id, key, value)
}
</script>

<style scoped>
.scene-node {
  width: 220px;
  background: rgba(26, 26, 46, 0.95);
  border: 1px solid rgba(124, 58, 237, 0.45);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 12px;
  color: #e2e8f0;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.4);
}
.node-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.node-name {
  font-weight: 600;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: #64748b;
  font-size: 11px;
  padding-bottom: 8px;
  border-bottom: 1px dashed rgba(148, 163, 184, 0.15);
}
.node-config {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 8px;
}
.node-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.node-field-label {
  color: #94a3b8;
  font-size: 11px;
}
.node-remove {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed rgba(148, 163, 184, 0.15);
  color: #f87171;
  font-size: 11px;
  cursor: pointer;
  text-align: right;
}
.node-remove:hover {
  color: #ef4444;
}
.scene-node.readonly .node-remove {
  display: none;
}
</style>
