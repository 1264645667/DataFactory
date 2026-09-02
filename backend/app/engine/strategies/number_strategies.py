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
    """INCR_FROM：指定起始值自增

    参数：
    - start: 起始值（正整数，必填）
    - prefix: 字符串前缀（可选，用于 varchar/char 等字符字段生成 test0001 这类带前缀序列）
    - pad_length: 数字部分补零位数（可选，如 4 → 0001；不填则不补零）

    不传 prefix/pad_length 时行为与旧版一致（纯数字自增），向后兼容。
    """

    strategy_code = "INCR_FROM"

    def validate(self, column_meta: dict, params: dict) -> None:
        start = params.get("start", params.get("start_value"))
        if not isinstance(start, int) or isinstance(start, bool) or start < 1:
            raise ValueError("起始值必须为正整数")
        prefix = params.get("prefix")
        if prefix is not None and not isinstance(prefix, str):
            raise ValueError("前缀必须为字符串")
        pad_length = params.get("pad_length")
        if pad_length is not None and pad_length != "":
            if not isinstance(pad_length, int) or isinstance(pad_length, bool) or pad_length < 0:
                raise ValueError("补零位数必须为非负整数")
        # 字符字段：预估最大长度校验（前缀 + 数字位）
        max_len = column_meta.get("char_max_length")
        if (prefix or pad_length) and max_len:
            estimated = len(prefix or "") + max(int(pad_length or 0), len(str(int(start))))
            if estimated > int(max_len):
                raise ValueError(f"前缀+数字长度约 {estimated}，超过字段最大长度 {max_len}")

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        # range_start 由数据生成器在批前通过 Redis 批量预取注入（文档 6.4）；
        # 无预取场景（单独调用）退化为 start + index
        range_start = params.get("range_start")
        if range_start is None:
            range_start = int(params.get("start", params.get("start_value", 1)))
        num = int(range_start) + index
        prefix = params.get("prefix") or ""
        pad_length = params.get("pad_length")
        # 带前缀或补零 → 生成字符串；否则保持纯数字（向后兼容）
        if prefix or pad_length:
            num_str = str(num).zfill(int(pad_length)) if pad_length else str(num)
            return f"{prefix}{num_str}"
        return num
