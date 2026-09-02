"""依赖分析工具（拓扑排序）

- build_insert_order: Case 内关联依赖排序（源表先于目标表插入）
- build_layers: 场景 DAG 拓扑分层（Kahn 算法），层内节点可并行

循环依赖 / 自关联均抛 ValueError（中文提示）。
"""
from __future__ import annotations

from collections import defaultdict, deque


def build_insert_order(main_table: str, associations: list[dict] | None) -> list[str]:
    """Case 内表插入顺序（拓扑排序）

    关联语义：source 表先插入，target 表后插入（目标表需要源表生成的关联值）。
    关联的 source_table 缺省为主表。

    :param main_table: 主操作表
    :param associations: 关联配置列表 [{source_column, target_table, target_column, source_table?}]
    :return: 表名插入顺序（主表在前）
    :raises ValueError: 存在循环关联或表内自关联
    """
    associations = associations or []

    # 收集涉及的全部表（保持声明顺序，保证输出稳定）
    tables: list[str] = [main_table]
    edges: list[tuple[str, str]] = []
    for assoc in associations:
        source_table = assoc.get("source_table") or main_table
        target_table = assoc["target_table"]
        if source_table == target_table:
            raise ValueError(f"不允许表内自关联: {source_table}")
        edges.append((source_table, target_table))
        for table in (source_table, target_table):
            if table not in tables:
                tables.append(table)

    # Kahn 拓扑排序
    in_degree: dict[str, int] = {table: 0 for table in tables}
    graph: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        graph[source].append(target)
        in_degree[target] += 1

    queue = deque(sorted((t for t, d in in_degree.items() if d == 0), key=tables.index))
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for nxt in graph[node]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(tables):
        raise ValueError("关联关系存在循环依赖，无法执行")
    return order


def build_layers(nodes: list[dict], edges: list[dict] | None) -> list[list[str]]:
    """场景 DAG 拓扑分层（Kahn 算法）

    :param nodes: 节点列表 [{"node_id": ...}]
    :param edges: 有向边列表 [{"source": 前置node_id, "target": 后置node_id}]
    :return: 分层结果，每层是一组可并行执行的 node_id 列表；layer[0] 先执行
    :raises ValueError: 场景存在循环依赖
    """
    in_degree = {node["node_id"]: 0 for node in nodes}
    graph: dict[str, list[str]] = defaultdict(list)

    for edge in edges or []:
        graph[edge["source"]].append(edge["target"])
        in_degree[edge["target"]] += 1

    queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
    layers: list[list[str]] = []

    while queue:
        layer = list(queue)  # 本层所有节点（入度=0，可并行执行）
        layers.append(layer)
        queue.clear()
        for nid in layer:
            for target in graph[nid]:
                in_degree[target] -= 1
                if in_degree[target] == 0:
                    queue.append(target)

    if sum(len(layer) for layer in layers) != len(nodes):
        raise ValueError("场景存在循环依赖，无法执行")

    return layers
