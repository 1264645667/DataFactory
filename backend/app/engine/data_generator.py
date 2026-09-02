"""数据生成器：根据 field_configs 为单表批量生成行数据

规则（PRD 4.4 / 架构文档 4.2、6.3、6.4）：
- SKIP 策略（AUTO_INCREMENT 主键）字段不出现在生成列中，由数据库自动填充
- 关联值注入（injected_columns）：目标表关联列使用源表已生成行的同值，保证外键一致
- 固定值覆盖（value_overrides）：ITERATE_LIST 遍历模式下驱动列固定为当前轮值
- INCR_FROM 策略按批次通过 Redis INCRBY 批量预取连续区间（文档 6.4）

按列生成再组装为行（list[dict]），供原生批量 INSERT 使用。
"""
from __future__ import annotations

from typing import Any

from app.engine.strategies.derived_strategies import topo_order_derived
from app.engine.strategies.number_strategies import prefetch_incr_range
from app.engine.strategies.registry import get_strategy

# SKIP 策略编码（AUTO_INCREMENT 主键，数据库自动填充）
SKIP_STRATEGY = "SKIP"


def generate_rows(
    table_name: str,
    field_configs: list[dict],
    count: int,
    task_id: int,
    redis_client=None,
    injected_columns: dict[str, list] | None = None,
    value_overrides: dict[str, Any] | None = None,
) -> tuple[list[dict], list[str]]:
    """为单表批量生成 count 行数据

    :param table_name: 目标表名（INCR_FROM 计数器 Key 使用）
    :param field_configs: 字段配置列表（含 column_name/strategy/strategy_params 等）
    :param count: 生成行数
    :param task_id: 执行任务 ID（INCR_FROM 计数器 Key 使用）
    :param redis_client: 同步 Redis 客户端（INCR_FROM 必需）
    :param injected_columns: 关联注入值 {目标列名: [每行的值]}，长度必须等于 count
    :param value_overrides: 固定值覆盖 {列名: 值}（遍历模式 drive_value 注入）
    :return: (rows, columns) — 行数据列表与实际生成的列名列表
    :raises ValueError: 策略参数非法或注入值数量不匹配
    """
    injected_columns = injected_columns or {}
    value_overrides = value_overrides or {}

    column_values: dict[str, list] = {}
    for field_config in field_configs:
        column = field_config["column_name"]
        strategy_code = (field_config.get("strategy") or "DEFAULT").upper()

        # AUTO_INCREMENT 主键：完全不出现在 INSERT 列列表中（PRD 4.4.3-A）
        if strategy_code == SKIP_STRATEGY:
            continue

        # 固定值覆盖优先（遍历模式驱动列）
        if column in value_overrides:
            column_values[column] = [value_overrides[column]] * count
            continue

        # 关联值注入（目标列与源列同值）
        if column in injected_columns:
            values = list(injected_columns[column])
            if len(values) != count:
                raise ValueError(
                    f"关联注入值数量({len(values)})与批次条数({count})不一致: {table_name}.{column}"
                )
            column_values[column] = values
            continue

        # DERIVED 派生字段：依赖源列整列值，延迟到源列生成后统一计算
        if strategy_code == "DERIVED":
            continue

        # 按策略生成
        strategy = get_strategy(strategy_code)
        params = dict(field_config.get("strategy_params") or {})
        if strategy_code == "INCR_FROM":
            if redis_client is None:
                raise ValueError(f"INCR_FROM 策略需要 Redis 连接: {table_name}.{column}")
            # Redis 批量预取本批连续区间（文档 6.4）
            params["range_start"] = prefetch_incr_range(
                redis_client, task_id, table_name, column, count
            )
        # 每批生成前做一次参数校验（非法配置快速失败，抛中文 ValueError）
        strategy.validate(field_config, params)
        column_values[column] = [strategy.generate(field_config, params, i) for i in range(count)]

    # 第二遍：DERIVED 派生字段按拓扑顺序整列计算（源列须已生成，支持多级派生）
    for field_config in topo_order_derived(field_configs):
        column = field_config["column_name"]
        if column in column_values:  # 已被 override/关联注入填充则跳过
            continue
        params = dict(field_config.get("strategy_params") or {})
        strategy = get_strategy("DERIVED")
        strategy.validate(field_config, params)
        source_column = params["source_column"]
        if source_column not in column_values:
            raise ValueError(
                f"派生字段的源字段不存在或未生成（源字段不能是自增主键/未配置字段）: {source_column}"
            )
        column_values[column] = strategy.compute_column(field_config, params, column_values[source_column])

    columns = list(column_values.keys())
    if count <= 0 or not columns:
        return [], columns
    rows = [
        dict(zip(columns, values))
        for values in zip(*(column_values[column] for column in columns))
    ]
    return rows, columns
