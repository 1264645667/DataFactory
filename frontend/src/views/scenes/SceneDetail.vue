<template>
  <!-- 场景详情页（PRD 6.5.4）：只读画布 + 最近 5 次执行记录 -->
  <div class="scene-detail-page">
    <n-spin :show="loading">
      <template v-if="detail">
        <!-- 基本信息 -->
        <div class="gradient-border-card info-card">
          <div class="info-head">
            <div>
              <h3 class="info-title">{{ detail.name }}</h3>
              <span class="info-meta">
                {{ detail.node_count }} 个节点 · {{ EXEC_MODE_TEXT[detail.exec_mode] ?? detail.exec_mode }} ·
                创建人 {{ detail.created_by_name }} · {{ formatDateTime(detail.created_at) }}
              </span>
            </div>
            <div class="info-actions">
              <n-button v-if="hasPermission('SCENE:EDIT')" size="small" @click="router.push(`/scenes/editor/${detail.id}`)">编辑</n-button>
              <n-button v-if="hasPermission('SCENE:EXECUTE')" size="small" class="gradient-btn" @click="handleExecute" :loading="executing">执行</n-button>
              <n-button v-if="hasPermission('SCENE:CREATE')" size="small" @click="copyShow = true">复制</n-button>
            </div>
          </div>
        </div>

        <!-- 只读画布 -->
        <div class="gradient-border-card canvas-card">
          <VueFlow
            v-model:nodes="flowNodes"
            v-model:edges="flowEdges"
            class="readonly-flow"
            :nodes-draggable="false"
            :nodes-connectable="false"
            :elements-selectable="false"
            :zoom-on-scroll="true"
            :pan-on-drag="true"
            fit-view-on-init
          >
            <Background pattern-color="#2a2a4a" :gap="22" />
            <Controls position="top-right" :show-interactive="false" />
            <template #node-case="props">
              <SceneCaseNode v-bind="props" readonly />
            </template>
          </VueFlow>
        </div>

        <!-- 最近 5 次执行记录 -->
        <div class="gradient-border-card history-card">
          <h4 class="section-title">最近执行记录</h4>
          <n-data-table :columns="historyColumns" :data="historyList" size="small" :pagination="false" />
          <EmptyState v-if="historyList.length === 0" description="还没有执行记录" :size="70" />
        </div>
      </template>
    </n-spin>

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
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { VueFlow, type Edge, type Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import { NTag, type DataTableColumns } from 'naive-ui'
import { scenesApi } from '@/api/scenes'
import type { SceneDetail, SceneHistoryItem } from '@/api/types'
import SceneCaseNode from './components/SceneCaseNode.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { useSceneProgress } from '@/composables/useSceneProgress'
import { formatDateTime, formatDateTimeMin, formatDuration, formatNumber } from '@/utils/formatter'

const route = useRoute()
const router = useRouter()
const { hasPermission } = useAuth()
const { trackScene } = useSceneProgress()

const sceneId = Number(route.params.id)
const loading = ref(true)
const detail = ref<SceneDetail | null>(null)
const flowNodes = ref<Node[]>([])
const flowEdges = ref<Edge[]>([])
const historyList = ref<SceneHistoryItem[]>([])
const executing = ref(false)

const EXEC_MODE_TEXT: Record<string, string> = { serial: '纯串行', parallel: '含并行', mixed: '混合' }

const historyColumns: DataTableColumns<SceneHistoryItem> = [
  { title: '执行编号', key: 'scene_exec_no', width: 160 },
  { title: '执行时间', key: 'started_at', width: 140, render: (r) => formatDateTimeMin(r.started_at) },
  { title: '节点数', key: 'node_count', width: 70 },
  { title: '总造数条数', key: 'total_rows', width: 110, render: (r) => formatNumber(r.total_rows) },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (r) => {
      const type = r.status === 'success' ? 'success' : r.status === 'partial_success' ? 'warning' : 'error'
      const textMap: Record<string, string> = { success: '成功', failed: '失败', partial_success: '部分成功', aborted: '已中止', running: '执行中', submitted: '已提交' }
      const text = textMap[r.status] ?? r.status
      return h(NTag, { size: 'small', type: type as 'success' | 'warning' | 'error' }, () => text)
    },
  },
  { title: '耗时', key: 'duration_seconds', width: 90, render: (r) => formatDuration(r.duration_seconds) },
  { title: '操作人', key: 'created_by_name', width: 80 },
]

async function handleExecute(): Promise<void> {
  if (!detail.value) return
  executing.value = true
  try {
    const res = await scenesApi.execute(detail.value.id)
    trackScene(res.data.scene_exec_no, detail.value.name)
  } finally {
    executing.value = false
  }
}

// ---------------- 复制 ----------------
const copyShow = ref(false)
const copying = ref(false)
const copyName = ref('')

async function handleCopy(): Promise<void> {
  if (!detail.value || !copyName.value.trim()) return
  copying.value = true
  try {
    const res = await scenesApi.copy(detail.value.id, copyName.value.trim())
    copyShow.value = false
    window.$message.success('复制成功')
    router.push(`/scenes/${res.data.scene_id}`)
  } finally {
    copying.value = false
  }
}

onMounted(async () => {
  try {
    const res = await scenesApi.detail(sceneId)
    detail.value = res.data
    copyName.value = `${res.data.name}_copy`
    // 还原只读画布
    flowNodes.value = res.data.nodes_json.map((n) => ({
      id: n.node_id,
      type: 'case',
      position: n.position,
      data: { case_name: n.case_name, target_count: n.target_count, fail_strategy: n.fail_strategy },
    }))
    flowEdges.value = res.data.edges_json.map((e) => ({
      id: e.edge_id,
      source: e.source,
      target: e.target,
      animated: true,
    }))
    // 最近 5 次执行记录
    const hist = await scenesApi.history(sceneId, { page: 1, page_size: 5 })
    historyList.value = hist.data.list
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.scene-detail-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: calc(100vh - 96px);
}
.info-card {
  padding: 18px;
}
.info-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.info-title {
  margin: 0 0 6px;
  font-size: 17px;
  color: #f1f5f9;
}
.info-meta {
  font-size: 12px;
  color: #64748b;
}
.info-actions {
  display: flex;
  gap: 10px;
}
.canvas-card {
  flex: 1;
  min-height: 320px;
  overflow: hidden;
}
.readonly-flow {
  height: 100%;
  border-radius: 12px;
}
.history-card {
  padding: 18px;
}
.section-title {
  margin: 0 0 12px;
  font-size: 14px;
  color: #a78bfa;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
