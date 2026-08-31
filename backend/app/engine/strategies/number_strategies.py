"""数字类策略：INCR_FROM（指定值自增）

多线程安全方案（架构文档 6.4）：
- 每个自增字段对应一个 Redis 原子计数器：df:incr:{task_id}:{table}:{column}
- 线程不是每次 INCR 1，而是按批次一次性 INCRBY batch_size 预取一段连续区间，
  批内行通过 range_start + index 映射取值，减少 Redis 请求次数
"""
from __future__ import annotations

from typing import Any

from app.engine.strategies.base import BaseStrategy

# Redis Key 模板（文档 5.1）：df:incr:{task_id}:{table}:{column}
INCR_KEY_TEMPLATE = "df:incr:{task_id}:{table}:{column}"


def incr_counter_key(task_id: int, table: str, column: str) -> str:
    """自增计数器 Redis Key"""
    return INCR_KEY_TEMPLATE.format(task_id=task_id, table=table, column=column)


def init_incr_counter(redis_client, task_id: int, table: str, column: str, start: int) -> None:
    """初始化自增计数器起始值

    使用 NX 语义：断点重试时保留已有计数，保证自增值连续不重复。
    """
    redis_client.set(incr_counter_key(task_id, table, column), int(start), nx=True)


def prefetch_incr_range(redis_client, task_id: int, table: str, column: str, count: int) -> int:
    """批量预取 count 个连续自增值，返回本批起始值（含）

    Redis INCRBY 原子语义：返回累加后的终值 end，
    本批可用区间为 [end - count, end - 1]，故起始值 = end - count。
    """
    end_value = redis_client.incrby(incr_counter_key(task_id, table, column), count)
    return int(end_value) - count


class IncrFromStrategy(BaseStrategy):
    """INCR_FROM：指定起始值自增（参数 start，正整数）"""

    strategy_code = "INCR_FROM"

    def validate(self, column_meta: dict, params: dict) -> None:
        start = params.get("start", params.get("start_value"))
        if not isinstance(start, int) or isinstance(start, bool) or start < 1:
            raise ValueError("起始值必须为正整数")

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        # range_start 由数据生成器在批前通过 Redis 批量预取注入（文档 6.4）；
        # 无预取场景（单独调用）退化为 start + index
        range_start = params.get("range_start")
        if range_start is None:
            range_start = int(params.get("start", params.get("start_value", 1)))
        return int(range_start) + index
