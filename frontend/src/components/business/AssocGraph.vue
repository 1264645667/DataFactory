<template>
  <!-- 关联关系图（拓扑分层布局，支持多级关联）：主表在左，下游表按依赖层次向右展开 -->
  <div class="graph-wrap">
    <svg :width="graphWidth" :height="graphHeight" class="assoc-graph">
      <!-- 连线 + 字段映射块 -->
      <g v-for="(line, i) in graphLines" :key="`l-${i}`">
        <path :d="line.path" stroke="#7c3aed" stroke-width="1.6" fill="none" opacity="0.75" />
        <!-- 字段映射块：多行垂直堆叠，居中两节点之间；同名仅显示字段名，不同名显示 source → target -->
        <text :x="line.midX" :y="line.fieldsStartY" text-anchor="middle" fill="#94a3b8" class="assoc-field-label">
          <tspan v-for="(f, fi) in line.fields" :key="fi" :x="line.midX" :dy="fi === 0 ? 0 : 15">
            {{ f.text }}<title v-if="f.full">{{ f.full }}</title>
          </tspan>
        </text>
      </g>
      <!-- 节点（按拓扑层次从左到右：主表 → 各级关联表） -->
      <g v-for="node in layoutNodes" :key="node.name">
        <!-- 悬停显示完整表名（表名可能因超长被截断） -->
        <title>{{ node.name }}</title>
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
          class="assoc-node-name"
          :font-weight="node.isMain ? 600 : 400"
          text-anchor="middle"
        >{{ node.displayName }}</text>
        <text
          v-if="node.isMain"
          :x="node.x + nodeW / 2"
          :y="node.y + nodeH / 2 + 13"
          fill="#64748b"
          class="assoc-node-sub"
          text-anchor="middle"
        >主表</text>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Association } from '@/api/types'
import { buildLayers } from '@/utils/dag'

const props = defineProps<{ mainTable: string; associations: Association[] }>()

const nodeH = 46
const gapY = 80
const MIN_NODE_W = 150
const MAX_NODE_W = 260
const NODE_CHAR_W = 6.8   // 节点表名（13px）单字符宽度估算
const LABEL_CHAR_W = 5.8  // 字段标签（11px）单字符宽度估算
const LABEL_LINE_H = 15   // 字段标签行高

// 表级节点与边（多级关联：source_table 缺省为主表）
const tableGraph = computed(() => {
  const nodeSet = new Set<string>([props.mainTable])
  const edges: Array<{ source: string; target: string }> = []
  for (const a of props.associations) {
    const src = a.source_table || props.mainTable
    nodeSet.add(src)
    nodeSet.add(a.target_table)
    edges.push({ source: src, target: a.target_table })
  }
  return { nodes: [...nodeSet], edges }
})

// 字段标签文本：同名仅显示字段名，不同名显示 source → target
function fieldLabel(a: Association): string {
  return a.source_column === a.target_column ? a.source_column : `${a.source_column} → ${a.target_column}`
}

// 节点宽度：自适应最长表名（下限 150 / 上限 260，超出截断）
const nodeW = computed(() => {
  const maxLen = Math.max(...tableGraph.value.nodes.map((n) => n.length), 8)
  return Math.min(MAX_NODE_W, Math.max(MIN_NODE_W, Math.ceil(maxLen * NODE_CHAR_W) + 24))
})

// 节点内表名可放下的最大字符数，超出截断（hover 用 <title> 显示全名）
const maxNameChars = computed(() => Math.floor((nodeW.value - 20) / NODE_CHAR_W))
function displayName(name: string): string {
  return name.length > maxNameChars.value ? `${name.slice(0, maxNameChars.value - 1)}…` : name
}

// 节点水平间距：节点宽 + 最长字段标签宽 + 余量，保证标签不压节点
const gapX = computed(() => {
  let maxLabel = 0
  for (const a of props.associations) {
    maxLabel = Math.max(maxLabel, fieldLabel(a).length * LABEL_CHAR_W)
  }
  return nodeW.value + Math.max(90, Math.ceil(maxLabel) + 40)
})

// 同一对表之间字段关联的最大条数（决定字段映射块高度与节点垂直留白）
const maxPairFields = computed(() => {
  const counts = new Map<string, number>()
  for (const a of props.associations) {
    const src = a.source_table || props.mainTable
    const key = `${src}⟩${a.target_table}`
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return counts.size ? Math.max(...counts.values()) : 0
})
// 字段映射块（多行文本）所需的一半高度，用于节点顶部留白，保证标签不超出画布
const nodeTopPad = computed(() => Math.max(24, (maxPairFields.value * LABEL_LINE_H) / 2))

interface GraphNode {
  name: string
  displayName: string
  x: number
  y: number
  isMain: boolean
}

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
      result.push({
        name,
        displayName: displayName(name),
        x: 30 + li * gapX.value,
        y: nodeTopPad.value + ni * gapY,
        isMain: name === props.mainTable,
      })
    })
  })
  return result
})

const graphWidth = computed(() => {
  const xs = layoutNodes.value.map((n) => n.x)
  return Math.max(620, (xs.length ? Math.max(...xs) : 30) + nodeW.value + 40)
})
const graphHeight = computed(() => {
  const ys = layoutNodes.value.map((n) => n.y)
  return Math.max(140, (ys.length ? Math.max(...ys) : 30) + nodeH + nodeTopPad.value)
})

interface FieldLabel {
  text: string
  full: string | null // 截断时的完整文本（tooltip）
}
interface GraphLine {
  path: string
  fields: FieldLabel[]
  midX: number
  fieldsStartY: number
}

// 同一对表的多条字段关联：合并为一条连线 + 垂直堆叠的多行字段映射块（居中两节点之间，不重叠）
const graphLines = computed<GraphLine[]>(() => {
  const posMap = new Map(layoutNodes.value.map((n) => [n.name, n]))
  const groups = new Map<string, Association[]>()
  for (const a of props.associations) {
    const src = a.source_table || props.mainTable
    const key = `${src}⟩${a.target_table}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(a)
  }
  const lines: GraphLine[] = []
  for (const assocs of groups.values()) {
    const a0 = assocs[0]
    const src = a0.source_table || props.mainTable
    const srcNode = posMap.get(src)
    const tgtNode = posMap.get(a0.target_table)
    if (!srcNode || !tgtNode) continue
    const sx = srcNode.x + nodeW.value
    const sy = srcNode.y + nodeH / 2
    const tx = tgtNode.x
    const ty = tgtNode.y + nodeH / 2
    const midX = (sx + tx) / 2
    const midY = (sy + ty) / 2
    const n = assocs.length
    lines.push({
      path: `M ${sx} ${sy} C ${midX} ${sy}, ${midX} ${ty}, ${tx} ${ty}`,
      fields: assocs.map((a) => {
        const full = a.source_column === a.target_column
          ? `${src}.${a.source_column} → ${a.target_table}.${a.target_column}`
          : null
        return { text: fieldLabel(a), full }
      }),
      midX,
      fieldsStartY: midY - ((n - 1) * LABEL_LINE_H) / 2 + 4, // 多行垂直居中
    })
  }
  return lines
})
</script>

<style scoped>
.graph-wrap {
  overflow-x: auto;
}
.assoc-graph {
  display: block;
  margin: 0 auto;
}
/* 注意：SVG 文字大小必须用 CSS 类设置，不能用 font-size HTML 属性——
   UnoCSS attributify 会把 font-size="11" 劫持解析为 2.75rem(44px)，导致文字巨大重叠 */
.assoc-graph text {
  font-size: 11px;
}
.assoc-graph .assoc-node-name {
  font-size: 13px;
}
</style>
