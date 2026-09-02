<template>
  <!-- 场景编排页（PRD 6.3）：左 Case 面板 260px + 右 VueFlow 画布 + 底部操作栏 -->
  <div class="scene-editor">
    <!-- 左侧 Case 选择面板 -->
    <div class="case-panel glass-card">
      <div class="panel-title">Case 选择</div>
      <n-input v-model:value="caseKeyword" size="small" clearable placeholder="搜索 Case" class="mb-2">
        <template #prefix><n-icon><SearchOutline /></n-icon></template>
      </n-input>
      <n-select v-model:value="caseDsFilter" :options="dsOptions" clearable size="small" placeholder="数据源过滤" class="mb-2" />
      <n-scrollbar class="case-list">
        <div
          v-for="c in filteredCases"
          :key="c.id"
          class="case-card"
          @pointerdown="onCardPointerDown($event, c)"
        >
          <div class="case-card-name">{{ c.case_name }}</div>
          <div class="case-card-meta">主表：{{ c.main_table }}</div>
          <div class="case-card-meta">数据源：{{ c.datasource_name }}</div>
        </div>
        <EmptyState v-if="filteredCases.length === 0" description="没有可用的 Case" :size="64" />
      </n-scrollbar>
      <div class="panel-tip">拖拽 Case 卡片到右侧画布添加节点，同一 Case 可多次拖入</div>
    </div>

    <!-- 右侧画布区域 -->
    <div class="canvas-area">
      <div ref="canvasWrapRef" class="canvas-wrap gradient-border-card" :class="{ 'drop-target-active': dragGhost && isOverCanvas }">
        <VueFlow
          v-model:nodes="flowNodes"
          v-model:edges="flowEdges"
          class="scene-flow"
          :delete-key-code="['Backspace', 'Delete']"
          :min-zoom="0.3"
          :max-zoom="2"
          fit-view-on-init
          @connect="onConnect"
        >
          <Background pattern-color="#2a2a4a" :gap="22" />
          <Controls position="top-right" />
          <!-- 自定义 Case 节点 -->
          <template #node-case="props">
            <SceneCaseNode v-bind="props" @remove="removeNode" @update="updateNodeData" />
          </template>
          <!-- 画布工具栏 -->
          <div class="canvas-toolbar">
            <n-button size="tiny" quaternary @click="handleAutoLayout" title="自动布局">
              <template #icon><n-icon><GridOutline /></n-icon></template>
              自动布局
            </n-button>
            <n-button size="tiny" quaternary @click="handleClear" title="清空画布">
              <template #icon><n-icon><TrashOutline /></n-icon></template>
              清空画布
            </n-button>
          </div>
          <!-- 空画布引导 -->
          <div v-if="flowNodes.length === 0" class="canvas-guide">
            <CatMascot pose="sit" :size="90" style="color: #4c3a75" />
            <p>拖拽左侧 Case 到此区域进行可视化编排</p>
          </div>
        </VueFlow>
      </div>
      <!-- 执行模式提示区 -->
      <div class="mode-hint" :class="`mode-${execMode.mode}`">
        <n-icon :size="15"><FlashOutline /></n-icon>
        <span>{{ execMode.text }}</span>
      </div>
      <!-- 底部操作栏 -->
      <div class="bottom-bar glass-card">
        <n-input v-model:value="sceneName" placeholder="请输入场景名称（必填）" style="width: 280px" size="small" />
        <div class="bottom-actions">
          <n-button size="small" @click="handleCancel">取消</n-button>
          <n-button v-if="canSave" size="small" :loading="saving" @click="handleSave(false)">保存</n-button>
          <n-button v-if="canExecute" size="small" class="gradient-btn" :loading="saving" @click="handleSave(true)">
            保存并执行
          </n-button>
        </div>
      </div>
    </div>
  </div>

  <!-- 拖拽跟随预览（Pointer Events 方案，绕开 Chrome 144+ HTML5 DnD 回归 bug） -->
  <Teleport to="body">
    <div v-if="dragGhost" class="drag-ghost" :style="{ left: dragGhost.x + 'px', top: dragGhost.y + 'px' }">
      <div class="case-card-name">{{ dragGhost.case_name }}</div>
      <div class="case-card-meta">主表：{{ dragGhost.main_table }}</div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { VueFlow, useVueFlow, type Connection, type Edge, type Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { FlashOutline, GridOutline, SearchOutline, TrashOutline } from '@vicons/ionicons5'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import { casesApi } from '@/api/cases'
import { scenesApi } from '@/api/scenes'
import { datasourceApi } from '@/api/datasource'
import type { CaseItem, SceneEdge, SceneNode } from '@/api/types'
import SceneCaseNode from './components/SceneCaseNode.vue'
import CatMascot from '@/components/common/CatMascot.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { useSceneProgress } from '@/composables/useSceneProgress'
import { autoLayout, buildLayers, canAddEdge, detectExecMode } from '@/utils/dag'

const route = useRoute()
const router = useRouter()
const { hasPermission } = useAuth()
const { trackScene } = useSceneProgress()

const sceneId = route.params.id ? Number(route.params.id) : null
const isEdit = !!sceneId

// 权限：新建需 SCENE:CREATE，编辑需 SCENE:EDIT，执行需 SCENE:EXECUTE
const canSave = computed(() => (isEdit ? hasPermission('SCENE:EDIT') : hasPermission('SCENE:CREATE')))
const canExecute = computed(() => canSave.value && hasPermission('SCENE:EXECUTE'))

// ---------------- 左侧 Case 面板 ----------------
const caseList = ref<CaseItem[]>([])
const caseKeyword = ref('')
const caseDsFilter = ref<number | null>(null)
const dsOptions = ref<Array<{ label: string; value: number }>>([])

const filteredCases = computed(() => {
  let data = caseList.value
  const kw = caseKeyword.value.trim().toLowerCase()
  if (kw) data = data.filter((c) => c.case_name.toLowerCase().includes(kw))
  if (caseDsFilter.value != null) data = data.filter((c) => c.datasource_id === caseDsFilter.value)
  return data
})

// ---------------- Vue Flow 画布 ----------------
const flowNodes = ref<Node[]>([])
const flowEdges = ref<Edge[]>([])
const sceneName = ref('')
const sceneDescription = ref<string | null>(null)
const saving = ref(false)
/** 画布容器引用（Pointer Events 拖拽判定落点用） */
const canvasWrapRef = ref<HTMLElement | null>(null)
/** 拖拽中的 Case 预览（含跟随坐标），null 表示未在拖拽 */
const dragGhost = ref<{ case_id: number; case_name: string; main_table: string; datasource_name: string; x: number; y: number } | null>(null)
/** 拖拽指针当前是否在画布上方（控制高亮） */
const isOverCanvas = ref(false)

const { screenToFlowCoordinate, fitView } = useVueFlow()

// 结构化访问辅助：规避 Vue Flow Node/Edge 深层泛型导致的 TS2589
interface SimpleFlowNode {
  id: string
  position: { x: number; y: number }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>
}
interface SimpleFlowEdge {
  id: string
  source: string
  target: string
}
function sn(): SimpleFlowNode[] {
  return flowNodes.value as unknown as SimpleFlowNode[]
}
function se(): SimpleFlowEdge[] {
  return flowEdges.value as unknown as SimpleFlowEdge[]
}

// 执行模式自动识别（画布底部提示）
const execMode = computed(() => {
  const simpleEdges = se().map((e) => ({ source: e.source, target: e.target }))
  return detectExecMode(flowNodes.value.length, simpleEdges)
})

function genNodeId(): string {
  return `n_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`
}

/** 在指定屏幕坐标处新增场景节点（拖放入画布时调用） */
function addCaseNode(c: { case_id: number; case_name: string; main_table: string; datasource_name: string }, clientX: number, clientY: number): void {
  const position = screenToFlowCoordinate({ x: clientX, y: clientY })
  flowNodes.value.push({
    id: genNodeId(),
    type: 'case',
    position,
    data: {
      case_id: c.case_id,
      case_name: c.case_name,
      main_table: c.main_table,
      datasource_name: c.datasource_name,
      target_count: 1000,
      fail_strategy: 'continue',
    },
  })
}

/** 判断屏幕坐标是否在画布区域内 */
function isPointInCanvas(x: number, y: number): boolean {
  const rect = canvasWrapRef.value?.getBoundingClientRect()
  return !!rect && x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom
}

/**
 * Case 卡片拖拽（Pointer Events 实现）。
 * 说明：Chrome 144+ 存在 HTML5 DnD 回归 bug（dragover preventDefault 后 drop 仍不派发），
 * 故改用 pointerdown/move/up 自实现拖拽，跨浏览器行为一致、不受该 bug 影响。
 */
function onCardPointerDown(e: PointerEvent, c: CaseItem): void {
  if (e.button !== 0) return // 仅响应左键
  const payload = { case_id: c.id, case_name: c.case_name, main_table: c.main_table, datasource_name: c.datasource_name }
  const startX = e.clientX
  const startY = e.clientY
  let started = false

  const onMove = (ev: PointerEvent): void => {
    // 移动超过阈值才算拖拽，避免误触（与点击区分）
    if (!started) {
      if (Math.hypot(ev.clientX - startX, ev.clientY - startY) < 6) return
      started = true
    }
    dragGhost.value = { ...payload, x: ev.clientX, y: ev.clientY }
    isOverCanvas.value = isPointInCanvas(ev.clientX, ev.clientY)
  }
  const onEnd = (ev: PointerEvent): void => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onEnd)
    window.removeEventListener('pointercancel', onEnd)
    if (started && dragGhost.value && isPointInCanvas(ev.clientX, ev.clientY)) {
      addCaseNode(payload, ev.clientX, ev.clientY)
    }
    dragGhost.value = null
    isOverCanvas.value = false
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onEnd)
  window.addEventListener('pointercancel', onEnd)
}

/** 连线：建立依赖关系，自动检测并禁止循环依赖 */
function onConnect(conn: Connection): void {
  const ids = sn().map((n) => n.id)
  const edges = se().map((e) => ({ source: e.source, target: e.target }))
  if (!canAddEdge(ids, edges, conn.source, conn.target)) {
    window.$message.error('检测到循环依赖，请检查连线')
    return
  }
  flowEdges.value.push({
    id: `e_${conn.source}_${conn.target}`,
    source: conn.source,
    target: conn.target,
    animated: true,
  })
}

function removeNode(id: string): void {
  flowNodes.value = sn().filter((n) => n.id !== id) as unknown as Node[]
  flowEdges.value = se().filter((e) => e.source !== id && e.target !== id) as unknown as Edge[]
}

/** 节点参数更新（造数条数 / 失败策略） */
function updateNodeData(id: string, key: string, value: unknown): void {
  const node = sn().find((n) => n.id === id)
  if (node) node.data = { ...node.data, [key]: value }
}

/** 自动布局：按拓扑分层整理节点位置 */
function handleAutoLayout(): void {
  const nodes = toSceneNodes()
  const edges = toSceneEdges()
  const positions = autoLayout(nodes, edges)
  sn().forEach((n) => {
    if (positions[n.id]) n.position = positions[n.id]
  })
  setTimeout(() => fitView({ padding: 0.2 }), 50)
}

/** 清空画布（二次确认） */
function handleClear(): void {
  if (flowNodes.value.length === 0) return
  window.$dialog.warning({
    title: '清空画布',
    content: '将移除画布上所有节点和连线，是否继续？',
    positiveText: '清空',
    negativeText: '取消',
    onPositiveClick: () => {
      flowNodes.value = []
      flowEdges.value = []
    },
  })
}

function handleCancel(): void {
  router.push('/scenes')
}

// ---------------- 保存 ----------------
function toSceneNodes(): SceneNode[] {
  return sn().map((n) => ({
    node_id: n.id,
    case_id: n.data.case_id,
    case_name: n.data.case_name,
    target_count: n.data.target_count ?? null,
    fail_strategy: n.data.fail_strategy ?? 'continue',
    position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
  }))
}

function toSceneEdges(): SceneEdge[] {
  return se().map((e, i) => ({ edge_id: e.id || `e_${i}`, source: e.source, target: e.target }))
}

/** 保存校验（PRD 6.3.4） */
function validateScene(): boolean {
  if (!sceneName.value.trim()) {
    window.$message.error('场景名称不能为空')
    return false
  }
  if (sceneName.value.trim().length > 100) {
    window.$message.error('场景名称不能超过 100 字')
    return false
  }
  if (flowNodes.value.length < 2) {
    window.$message.error('场景至少需要 2 个 Case 节点')
    return false
  }
  const missing = sn().find((n) => !n.data.target_count || n.data.target_count < 1)
  if (missing) {
    window.$message.error(`节点「${missing.data.case_name}」的造数条数未填写`)
    return false
  }
  try {
    buildLayers(
      sn().map((n) => n.id),
      se().map((e) => ({ source: e.source, target: e.target })),
    )
  } catch {
    window.$message.error('检测到循环依赖，请检查连线')
    return false
  }
  return true
}

/** 保存场景；execute=true 时保存后立即执行 */
async function handleSave(execute: boolean): Promise<void> {
  if (!validateScene()) return
  saving.value = true
  try {
    const payload = {
      scene_name: sceneName.value.trim(),
      description: sceneDescription.value,
      nodes: toSceneNodes(),
      edges: toSceneEdges(),
    }
    let id = sceneId
    if (isEdit && id) {
      await scenesApi.update(id, payload)
    } else {
      const res = await scenesApi.create(payload)
      id = res.data.scene_id
    }
    if (execute && id) {
      const res = await scenesApi.execute(id)
      trackScene(res.data.scene_exec_no, payload.scene_name)
      router.push('/scenes')
    } else {
      window.$message.success('场景已保存')
      router.push('/scenes')
    }
  } finally {
    saving.value = false
  }
}

// ---------------- 初始化 ----------------
onMounted(async () => {
  // 加载 Case 列表与数据源下拉
  try {
    const [caseRes, dsRes] = await Promise.all([
      casesApi.list({ page: 1, page_size: 100 }),
      datasourceApi.list().catch(() => null),
    ])
    caseList.value = caseRes.data.items ?? []
    if (dsRes) dsOptions.value = dsRes.data.map((d) => ({ label: d.name, value: d.id }))
  } catch {
    // Case 列表失败由拦截器提示
  }
  // 编辑模式：回显场景编排
  if (sceneId) {
    const res = await scenesApi.detail(sceneId)
    const d = res.data
    sceneName.value = d.scene_name
    sceneDescription.value = d.description
    flowNodes.value = d.nodes.map((n) => ({
      id: n.node_id,
      type: 'case',
      position: n.position,
      data: {
        case_id: n.case_id,
        case_name: n.case_name,
        target_count: n.target_count,
        fail_strategy: n.fail_strategy,
      },
    }))
    flowEdges.value = d.edges.map((e) => ({
      id: e.edge_id,
      source: e.source,
      target: e.target,
      animated: true,
    }))
  }
})
</script>

<style scoped>
.scene-editor {
  display: flex;
  gap: 14px;
  height: calc(100vh - 96px);
}
/* 左侧 Case 面板 */
.case-panel {
  width: 260px;
  flex-shrink: 0;
  padding: 14px;
  display: flex;
  flex-direction: column;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 10px;
}
.mb-2 {
  margin-bottom: 8px;
}
.case-list {
  flex: 1;
  min-height: 0;
}
.case-card {
  border: 1px solid rgba(124, 58, 237, 0.3);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: grab;
  background: rgba(124, 58, 237, 0.06);
  transition: border-color 0.15s ease;
}
.case-card:hover {
  border-color: rgba(124, 58, 237, 0.7);
}
.case-card:active {
  cursor: grabbing;
}
.case-card-name {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 4px;
}
.case-card-meta {
  font-size: 11px;
  color: #64748b;
}
.panel-tip {
  font-size: 11px;
  color: #4b5563;
  padding-top: 8px;
  border-top: 1px solid rgba(148, 163, 184, 0.1);
}
/* 右侧画布 */
.canvas-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
.canvas-wrap {
  flex: 1;
  overflow: hidden;
  position: relative;
  transition: outline-color 0.15s ease;
  outline: 2px dashed transparent;
  outline-offset: -2px;
  border-radius: 12px;
}
/* 拖拽 Case 经过画布上方时的高亮提示 */
.canvas-wrap.drop-target-active {
  outline-color: rgba(124, 58, 237, 0.6);
}
/* 拖拽跟随预览（fixed 定位，pointer-events:none 不拦截指针事件） */
.drag-ghost {
  position: fixed;
  z-index: 9999;
  pointer-events: none;
  transform: translate(12px, -50%);
  background: rgba(30, 30, 50, 0.92);
  border: 1px solid rgba(124, 58, 237, 0.6);
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  min-width: 180px;
}
.scene-flow {
  height: 100%;
  border-radius: 12px;
}
.canvas-toolbar {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
  display: flex;
  gap: 6px;
  background: rgba(26, 26, 46, 0.85);
  border: 1px solid rgba(124, 58, 237, 0.3);
  border-radius: 8px;
  padding: 4px 8px;
}
.canvas-guide {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #4b5563;
  font-size: 13px;
  pointer-events: none;
}
.mode-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 12px;
  background: rgba(124, 58, 237, 0.08);
  border: 1px solid rgba(124, 58, 237, 0.25);
  color: #c4b5fd;
}
.bottom-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
}
.bottom-actions {
  display: flex;
  gap: 10px;
}
</style>
