import type { SceneEdge, SceneNode } from '@/api/types'

// ============================================================
// DAG 工具：拓扑分层（Kahn）、循环依赖检测、自动布局、执行模式识别
// ============================================================

export interface DagEdge {
  source: string
  target: string
}

/**
 * 拓扑分层（Kahn 算法）：返回每层可并行执行的 node_id 列表
 * 存在循环依赖时抛出 Error
 */
export function buildLayers(nodeIds: string[], edges: DagEdge[]): string[][] {
  const inDegree = new Map<string, number>(nodeIds.map((id) => [id, 0]))
  const graph = new Map<string, string[]>()
  for (const e of edges) {
    if (!inDegree.has(e.source) || !inDegree.has(e.target)) continue
    graph.set(e.source, [...(graph.get(e.source) ?? []), e.target])
    inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1)
  }
  let queue = nodeIds.filter((id) => (inDegree.get(id) ?? 0) === 0)
  const layers: string[][] = []
  while (queue.length > 0) {
    layers.push(queue)
    const next: string[] = []
    for (const id of queue) {
      for (const target of graph.get(id) ?? []) {
        const deg = (inDegree.get(target) ?? 0) - 1
        inDegree.set(target, deg)
        if (deg === 0) next.push(target)
      }
    }
    queue = next
  }
  if (layers.flat().length !== nodeIds.length) {
    throw new Error('检测到循环依赖，请检查连线')
  }
  return layers
}

/** 检测新增一条边后是否形成环（返回 true 表示安全可添加） */
export function canAddEdge(nodeIds: string[], edges: DagEdge[], source: string, target: string): boolean {
  if (source === target) return false
  try {
    buildLayers(nodeIds, [...edges, { source, target }])
    return true
  } catch {
    return false
  }
}

/**
 * 自动布局：按拓扑分层从左到右排列，层内垂直堆叠
 */
export function autoLayout(nodes: SceneNode[], edges: SceneEdge[]): Record<string, { x: number; y: number }> {
  const ids = nodes.map((n) => n.node_id)
  let layers: string[][]
  try {
    layers = buildLayers(ids, edges)
  } catch {
    // 有环时退化为网格布局
    layers = [ids]
  }
  const positions: Record<string, { x: number; y: number }> = {}
  layers.forEach((layer, li) => {
    layer.forEach((id, ni) => {
      positions[id] = { x: li * 300 + 40, y: ni * 170 + 40 }
    })
  })
  return positions
}

/**
 * 执行模式自动识别（PRD 6.3.3）
 */
export function detectExecMode(nodeCount: number, edges: DagEdge[]): { mode: 'serial' | 'parallel' | 'mixed'; text: string } {
  if (edges.length === 0) {
    return { mode: 'parallel', text: '并行模式：所有节点将同时执行' }
  }
  // 纯串行：每个节点最多一条入边一条出边，且分层后每层恰一个节点
  try {
    const layers = buildLayers(
      // 调用方保证 nodeId 唯一，这里用边推导
      Array.from(new Set(edges.flatMap((e) => [e.source, e.target]))),
      edges,
    )
    const involved = new Set(edges.flatMap((e) => [e.source, e.target]))
    if (involved.size === nodeCount && layers.every((l) => l.length === 1)) {
      return { mode: 'serial', text: '串行模式：节点将按顺序依次执行' }
    }
  } catch {
    // 有环时按混合处理（保存时会拦截）
  }
  return { mode: 'mixed', text: '混合模式：无前置依赖的节点并行，有依赖的节点等待前置完成后执行' }
}
