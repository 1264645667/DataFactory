"""派生字段策略：DERIVED（基于同表另一数字字段做四则运算）

设计要点：
- 派生字段本身不随机生成，而是对源字段同批整列值逐元素运算
- 列式生成模型下需保证源列先生成：data_generator 内做字段级拓扑排序（支持多级派生）
- 仅数字类型字段可作为派生字段/源字段；结果按目标字段类型取整（int）或保留小数（decimal）
- 参数：source_column（源字段）+ operator（multiply/divide/add/subtract）+ operand（数字常量）
"""
from __future__ import annotations

from typing import Any

from app.engine.strategies.base import (
    DECIMAL_TYPES,
    INT_TYPES,
    BaseStrategy,
    get_data_type,
    get_numeric_precision_scale,
)

# 支持的运算符（四则运算）
OPERATOR_MULTIPLY = "multiply"
OPERATOR_DIVIDE = "divide"
OPERATOR_ADD = "add"
OPERATOR_SUBTRACT = "subtract"
ALLOWED_OPERATORS = {OPERATOR_MULTIPLY, OPERATOR_DIVIDE, OPERATOR_ADD, OPERATOR_SUBTRACT}


class DerivedStrategy(BaseStrategy):
    """DERIVED：字段运算派生（源字段值 ± × ÷ 常量）

    注意：逐行 generate 不适用（派生依赖源列整列值），
    实际计算由 data_generator 调用 compute_column 整列完成。
    """

    strategy_code = "DERIVED"

    def validate(self, column_meta: dict, params: dict) -> None:
        source = params.get("source_column")
        if not source or not isinstance(source, str):
            raise ValueError("派生字段必须指定源字段（source_column）")
        operator = params.get("operator")
        if operator not in ALLOWED_OPERATORS:
            raise ValueError("运算符必须是 multiply/divide/add/subtract 之一")
        operand = params.get("operand")
        if not isinstance(operand, (int, float)) or isinstance(operand, bool):
            raise ValueError("操作数必须为数字")
        if operator == OPERATOR_DIVIDE and operand == 0:
            raise ValueError("除法运算的除数不能为 0")
        # 派生字段必须是数字类型
        dt = get_data_type(column_meta)
        if dt not in INT_TYPES and dt not in DECIMAL_TYPES:
            raise ValueError("派生字段必须是数字类型（int/decimal/float 等）")

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        # 逐行生成不适用（需源列整列值），由 data_generator 走 compute_column
        raise NotImplementedError("DERIVED 策略由 data_generator 整列计算，不支持逐行 generate")

    def compute_column(self, column_meta: dict, params: dict, source_values: list) -> list:
        """整列计算派生值

        :param column_meta: 派生字段元数据（决定结果取整方式）
        :param params: 策略参数（operator/operand）
        :param source_values: 源字段同批整列值
        :return: 派生字段整列值
        """
        operator = params["operator"]
        operand = params["operand"]
        dt = get_data_type(column_meta)

        results: list = []
        for v in source_values:
            num = self._to_number(v)
            if num is None:
                results.append(None)
                continue
            if operator == OPERATOR_MULTIPLY:
                r = num * operand
            elif operator == OPERATOR_DIVIDE:
                r = num / operand
            elif operator == OPERATOR_ADD:
                r = num + operand
            else:  # subtract
                r = num - operand
            results.append(self._cast(r, dt, column_meta))
        return results

    @staticmethod
    def _to_number(v: Any) -> float | None:
        """源值转数字（None 透传，无法转换抛错）"""
        if v is None:
            return None
        try:
            return float(v) if isinstance(v, str) else (float(v) if not isinstance(v, (int, float)) else v)
        except (TypeError, ValueError) as e:
            raise ValueError(f"派生字段的源值不是数字: {v}") from e

    @staticmethod
    def _cast(value: float, data_type: str, column_meta: dict) -> Any:
        """按目标字段类型收敛结果：int 取整，decimal 按 scale 保留小数"""
        if data_type in INT_TYPES:
            return int(round(value))
        if data_type in DECIMAL_TYPES:
            _, scale = get_numeric_precision_scale(column_meta)
            return round(value, scale) if scale is not None else value
        return value


def topo_order_derived(field_configs: list[dict]) -> list[dict]:
    """派生字段（DERIVED）计算顺序：源字段先于派生字段（支持多级派生）

    仅处理 DERIVED 字段之间的依赖；源字段若是普通策略列则直接可引用。
    :raises ValueError: 派生字段间存在循环依赖
    """
    derived = [
        fc for fc in field_configs
        if (fc.get("strategy") or "").upper() == DerivedStrategy.strategy_code
    ]
    name_to_field = {fc["column_name"]: fc for fc in derived}
    ordered: list[dict] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"派生字段存在循环依赖: {name}")
        visiting.add(name)
        fc = name_to_field.get(name)
        if fc is not None:
            src = (fc.get("strategy_params") or {}).get("source_column")
            if src in name_to_field:
                visit(src)
            visiting.discard(name)
            visited.add(name)
            ordered.append(fc)
        else:
            visiting.discard(name)
            visited.add(name)

    for fc in derived:
        visit(fc["column_name"])
    return ordered
