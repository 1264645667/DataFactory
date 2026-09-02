"""策略注册表（架构文档 6.3，共 12 种策略）

新增策略只需实现 BaseStrategy 并登记到 STRATEGY_REGISTRY，无需修改核心引擎。

注意：get_strategy 返回进程内单例（模块加载时实例化），
保证 SNOWFLAKE 等带内部状态的策略在多线程并发下取值唯一。
"""
from __future__ import annotations

from app.engine.strategies.base import BaseStrategy
from app.engine.strategies.derived_strategies import DerivedStrategy
from app.engine.strategies.number_strategies import IncrFromStrategy
from app.engine.strategies.pk_strategies import SnowflakeStrategy, UUIDStrategy
from app.engine.strategies.string_strategies import (
    CustomValueStrategy,
    DefaultStrategy,
    IterateListStrategy,
    PickFromListStrategy,
    RandomFixedLenStrategy,
    RandomRangeLenStrategy,
)
from app.engine.strategies.time_strategies import (
    FixedTimeStrategy,
    NowStrategy,
    RandomTimeRangeStrategy,
)
from app.engine.strategies.tool_strategies import ToolGenStrategy

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "DEFAULT": DefaultStrategy,
    "RANDOM_FIXED_LEN": RandomFixedLenStrategy,
    "RANDOM_RANGE_LEN": RandomRangeLenStrategy,
    "CUSTOM_VALUE": CustomValueStrategy,
    "PICK_FROM_LIST": PickFromListStrategy,
    "ITERATE_LIST": IterateListStrategy,  # 遍历驱动策略
    "UUID": UUIDStrategy,
    "SNOWFLAKE": SnowflakeStrategy,
    "INCR_FROM": IncrFromStrategy,
    "DERIVED": DerivedStrategy,  # 字段运算派生（依赖源列，data_generator 整列计算）
    "TOOL_GEN": ToolGenStrategy,  # 调用快捷工具随机生成（身份证/手机号/地址等）
    "NOW": NowStrategy,
    "RANDOM_TIME_RANGE": RandomTimeRangeStrategy,
    "FIXED_TIME": FixedTimeStrategy,
}

# 进程内单例缓存（模块加载即实例化，避免并发下重复实例化有状态策略）
_STRATEGY_INSTANCES: dict[str, BaseStrategy] = {
    code: cls() for code, cls in STRATEGY_REGISTRY.items()
}


def get_strategy(strategy_code: str) -> BaseStrategy:
    """按策略编码获取策略实例

    :raises ValueError: 未知策略编码
    """
    code = (strategy_code or "").upper()
    instance = _STRATEGY_INSTANCES.get(code)
    if instance is None:
        raise ValueError(f"未知策略: {strategy_code}")
    return instance
