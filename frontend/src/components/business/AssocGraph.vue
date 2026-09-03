<template>
  <!-- 关联关系图（dagre 分层布局，支持多级/复杂关联）：主表在左，下游表按依赖层次向右展开，
       边自动绕行节点、层内自动排序减少交叉，字段映射标签由布局器分配独立空间 -->
  <div class="graph-wrap">
    <svg :width="graphWidth" :height="graphHeight" class="assoc-graph">
      <defs>
        <marker
          id="assoc-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 0 1 L 9 5 L 0 9 z" fill="#7c3aed" opacity="0.85" />
        </marker>
      </defs>
      <!-- 连线（dagre 计算绕行折点） + 字段映射标签块 -->
      <g v-for="(line, i) in graphLines" :key="`l-${i}`">
        <path
          :d="line.path"
          stroke="#7c3aed"
          stroke-width="1.6"
          fill="none"
          opacity="0.75"
          marker-end="url(#assoc-arrow)"
        />
        <!-- 标签底色块：避免连线/其他标签与文字交叠 -->
        <rect
          :x="line.labelX - line.labelW / 2"
          :y="line.labelY - line.labelH / 2"
          :width="line.labelW"
          :height="line.labelH"
          rx="4"
          fill="rgba(26, 26, 46, 0.92)"
          stroke="rgba(124, 58, 237, 0.25)"
          stroke-width="0.6"
        />
        <!-- 字段映射块：多行垂直堆叠；同名仅显示字段名，不同名显示 source → target -->
        <text
          :x="line.labelX"
          :y="line.labelY - ((line.fields.length - 1) * LABEL_LINE_H) / 2 + 4"
          text-anchor="middle"
          fill="#94a3b8"
          class="assoc-field-label"
        >
          <tspan v-for="(f, fi) in line.fields" :key="fi" :x="line.labelX" :dy="fi === 0 ? 0 : LABEL_LINE_H">
            {{ f.text }}<title v-if="f.full">{{ f.full }}</title>
          </tspan>
        </text>
      </g>
      <!-- 节点（dagre 分层：主表 → 各级关联表；外来表显示 @数据源 副标题） -->
      <g v-for="node in layoutNodes" :key="node.name">
        <!-- 悬停显示完整表名（表名可能因超长被截断） -->
        <title>{{ fullTitle(node) }}</title>
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
          :y="hasSubtitle(node) ? node.y + nodeH / 2 - 4 : node.y + nodeH / 2 + 4"
          fill="#e2e8f0"
          class="assoc-node-name"
          :font-weight="node.isMain ? 600 : 400"
          text-anchor="middle"
        >{{ node.displayName }}</text>
        <text
          v-if="hasSubtitle(node)"
          :x="node.x + nodeW / 2"
          :y="node.y + nodeH / 2 + 13"
          :fill="node.isMain ? '#64748b' : '#f59e0b'"
          class="assoc-node-sub"
          text-anchor="middle"
        >{{ subtitleOf(node) }}</text>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import dagre from '@dagrejs/dagre'
import type { Association } from '@/api/types'
import { buildLayers } from '@/utils/dag'

const props = defineProps<{
  mainTable: string
  associations: Association[]
  /** 表名 → 数据源名（跨数据源 Case 传入，外来表节点显示 @数据源 副标题） */
  tableDs?: Record<string, string>
}>()

const nodeH = 46
const LABEL_LINE_H = 15   // 字段标签行高
const LABEL_MAX_W = 240   // 字段标签块最大宽度（超出截断，hover 显示全名）
const MIN_NODE_W = 150
const MAX_NODE_W = 260
const NODE_CHAR_W = 6.8   // 节点表名（13px）单字符宽度估算
const LABEL_CHAR_W = 5.8  // 字段标签（11px）单字符宽度估算

interface FieldLabel {
  text: string
  full: string | null // 截断时的完整文本（tooltip）
}

// 表级节点与「表对」分组（多级关联：source_table 缺省为主表；同表对多字段合并为一条边）
const tableGraph = computed(() => {
  const nodeSet = new Set<string>([props.mainTable])
  const pairMap = new Map<string, { source: string; target: string; fields: FieldLabel[] }>()
  for (const a of props.associations) {
    const src = a.source_table || props.mainTable
    nodeSet.add(src)
    nodeSet.add(a.target_table)
    const key = `${src}⟩${a.target_table}`
    if (!pairMap.has(key)) pairMap.set(key, { source: src, target: a.target_table, fields: [] })
    const same = a.source_column === a.target_column
    const text = same ? a.source_column : `${a.source_column} → ${a.target_column}`
    const maxChars = Math.floor((LABEL_MAX_W - 14) / LABEL_CHAR_W)
    pairMap.get(key)!.fields.push({
      text: text.length > maxChars ? `${text.slice(0, maxChars - 1)}…` : text,
      full: text.length > maxChars ? `${src}.${a.source_column} → ${a.target_table}.${a.target_column}` : null,
    })
  }
  return { nodes: [...nodeSet], pairs: [...pairMap.values()] }
})

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

interface GraphNode {
  name: string
  displayName: string
  x: number
  y: number
  isMain: boolean
  /** 外来表的数据源名（主数据源表为 undefined，保持节点简洁） */
  dsName?: string
}

/** 节点是否有副标题行（主表=「主表」，外来表=@数据源） */
function hasSubtitle(node: GraphNode): boolean {
  return node.isMain || !!node.dsName
}

/** 数据源名过长时截断（节点宽度有限） */
function truncateDs(name: string): string {
  return name.length > 12 ? `${name.slice(0, 11)}…` : name
}

/** 节点悬停标题：表名 + 数据源（如有） */
function fullTitle(node: GraphNode): string {
  return node.dsName ? `${node.name}（数据源：${node.dsName}）` : node.name
}

/** 节点副标题：主表=「主表」，外来表=@数据源名（截断） */
function subtitleOf(node: GraphNode): string {
  return node.isMain ? '主表' : `@${truncateDs(node.dsName!)}`
}
interface GraphLine {
  path: string
  fields: FieldLabel[]
  labelX: number
  labelY: number
  labelW: number
  labelH: number
}

// dagre 布局：自动分层 + 层内排序减少交叉 + 边折点绕行节点 + 标签占位
const layout = computed<{ nodes: GraphNode[]; lines: GraphLine[]; width: number; height: number }>(() => {
  const { nodes, pairs } = tableGraph.value
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 46, ranksep: 70, edgesep: 18, marginx: 24, marginy: 24 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const name of nodes) {
    g.setNode(name, { width: nodeW.value, height: nodeH })
  }
  const labelSize = new Map<string, { w: number; h: number }>()
  for (const pair of pairs) {
    const maxText = Math.max(...pair.fields.map((f) => f.text.length), 4)
    const w = Math.min(LABEL_MAX_W, Math.ceil(maxText * LABEL_CHAR_W) + 14)
    const h = pair.fields.length * LABEL_LINE_H + 10
    labelSize.set(`${pair.source}⟩${pair.target}`, { w, h })
    // 标签尺寸交给 dagre，布局器会为标签分配独立空间避免重叠
    g.setEdge(pair.source, pair.target, { width: w, height: h, labelpos: 'c' })
  }

  let laidOut = true
  try {
    dagre.layout(g)
  } catch {
    laidOut = false // 理论不会发生（保存时已环检测），兜底走简易布局
  }

  if (laidOut) {
    const graph = g.graph()
    const laidNodes: GraphNode[] = nodes.map((name) => {
      const n = g.node(name)
      return {
        name,
        displayName: displayName(name),
        x: n.x - nodeW.value / 2,
        y: n.y - nodeH / 2,
        isMain: name === props.mainTable,
        dsName: name === props.mainTable ? undefined : props.tableDs?.[name],
      }
    })
    const lines: GraphLine[] = pairs.map((pair) => {
      const e = g.edge(pair.source, pair.target)
      const size = labelSize.get(`${pair.source}⟩${pair.target}`)!
      return {
        path: smoothPath(e.points),
        fields: pair.fields,
        labelX: e.x ?? 0,
        labelY: e.y ?? 0,
        labelW: size.w,
        labelH: size.h,
      }
    })
    return {
      nodes: laidNodes,
      lines,
      width: Math.max(320, Math.ceil(graph.width ?? 320)),
      height: Math.max(140, Math.ceil(graph.height ?? 140)),
    }
  }
  return fallbackLayout(nodes, pairs)
})

// 兜底布局（dagre 异常时）：Kahn 拓扑分层 + 层内垂直堆叠 + 贝塞尔曲线
function fallbackLayout(
  nodes: string[],
  pairs: { source: string; target: string; fields: FieldLabel[] }[],
): { nodes: GraphNode[]; lines: GraphLine[]; width: number; height: number } {
  let layers: string[][]
  try {
    layers = buildLayers(nodes, pairs.map((p) => ({ source: p.source, target: p.target })))
  } catch {
    layers = [nodes]
  }
  const gapX = nodeW.value + 160
  const gapY = 90
  const laidNodes: GraphNode[] = []
  layers.forEach((layer, li) => {
    layer.forEach((name, ni) => {
      laidNodes.push({
        name,
        displayName: displayName(name),
        x: 30 + li * gapX,
        y: 40 + ni * gapY,
        isMain: name === props.mainTable,
        dsName: name === props.mainTable ? undefined : props.tableDs?.[name],
      })
    })
  })
  const posMap = new Map(laidNodes.map((n) => [n.name, n]))
  const lines: GraphLine[] = []
  for (const pair of pairs) {
    const s = posMap.get(pair.source)
    const t = posMap.get(pair.target)
    if (!s || !t) continue
    const sx = s.x + nodeW.value
    const sy = s.y + nodeH / 2
    const tx = t.x
    const ty = t.y + nodeH / 2
    const midX = (sx + tx) / 2
    const size = labelSizeOf(pair.fields)
    lines.push({
      path: `M ${sx} ${sy} C ${midX} ${sy}, ${midX} ${ty}, ${tx} ${ty}`,
      fields: pair.fields,
      labelX: midX,
      labelY: (sy + ty) / 2,
      labelW: size.w,
      labelH: size.h,
    })
  }
  const maxX = Math.max(...laidNodes.map((n) => n.x), 30) + nodeW.value + 40
  const maxY = Math.max(...laidNodes.map((n) => n.y), 30) + nodeH + 40
  return { nodes: laidNodes, lines, width: Math.max(320, maxX), height: Math.max(140, maxY) }
}

function labelSizeOf(fields: FieldLabel[]): { w: number; h: number } {
  const maxText = Math.max(...fields.map((f) => f.text.length), 4)
  return {
    w: Math.min(LABEL_MAX_W, Math.ceil(maxText * LABEL_CHAR_W) + 14),
    h: fields.length * LABEL_LINE_H + 10,
  }
}

// 折点平滑：dagre 给出的折线点转二次贝塞尔平滑路径
function smoothPath(points: Array<{ x: number; y: number }>): string {
  if (points.length === 0) return ''
  if (points.length < 3) {
    return `M ${points[0].x} ${points[0].y} L ${points[points.length - 1].x} ${points[points.length - 1].y}`
  }
  let d = `M ${points[0].x} ${points[0].y}`
  for (let i = 1; i < points.length - 1; i++) {
    const midX = (points[i].x + points[i + 1].x) / 2
    const midY = (points[i].y + points[i + 1].y) / 2
    d += ` Q ${points[i].x} ${points[i].y} ${midX} ${midY}`
  }
  const last = points[points.length - 1]
  d += ` L ${last.x} ${last.y}`
  return d
}

const layoutNodes = computed(() => layout.value.nodes)
const graphLines = computed(() => layout.value.lines)
const graphWidth = computed(() => layout.value.width)
const graphHeight = computed(() => layout.value.height)
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
