"""主键策略：UUID / SNOWFLAKE

SNOWFLAKE 为自实现雪花算法（64 位，兼容 bigint 主键）：
    1 位符号(固定0) + 41 位毫秒时间戳(自定义纪元起) + 5 位数据中心位 + 5 位机器位 + 12 位序列号
- 每毫秒单机最多 4096 个 ID，序列耗尽时自旋等待下一毫秒
- 发生时钟回拨时等待时钟追平，保证 ID 单调递增
- 机器位默认由 进程PID + 主机名 派生，可通过 settings.SNOWFLAKE_MACHINE_ID /
  settings.SNOWFLAKE_DATACENTER_ID 显式指定
"""
from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from typing import Any

from app.config import settings
from app.engine.strategies.base import (
    BaseStrategy,
    get_char_max_length,
    get_data_type,
)


class UUIDStrategy(BaseStrategy):
    """UUID：随机 UUID v4（默认去连字符 32 位，参数 with_dash 可保留连字符）"""

    strategy_code = "UUID"

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        with_dash = bool((params or {}).get("with_dash"))
        value = str(uuid.uuid4()) if with_dash else uuid.uuid4().hex
        max_len = get_char_max_length(column_meta)
        if max_len is not None and len(value) > max_len:
            raise ValueError(
                f"字段最大长度 {max_len} 小于 UUID 长度 {len(value)}，请调整字段长度或更换策略"
            )
        return value


class SnowflakeIdGenerator:
    """雪花 ID 生成器（线程安全单例使用）"""

    # 自定义纪元：2024-01-01 00:00:00 UTC（41 位毫秒约可用 69 年）
    EPOCH = 1704038400000

    DATACENTER_BITS = 5
    MACHINE_BITS = 5
    SEQUENCE_BITS = 12

    MAX_DATACENTER = (1 << DATACENTER_BITS) - 1   # 31
    MAX_MACHINE = (1 << MACHINE_BITS) - 1         # 31
    MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1       # 4095

    MACHINE_SHIFT = SEQUENCE_BITS                              # 12
    DATACENTER_SHIFT = SEQUENCE_BITS + MACHINE_BITS            # 17
    TIMESTAMP_SHIFT = SEQUENCE_BITS + MACHINE_BITS + DATACENTER_BITS  # 22

    def __init__(self, datacenter_id: int = 0, machine_id: int = 0) -> None:
        self.datacenter_id = datacenter_id & self.MAX_DATACENTER
        self.machine_id = machine_id & self.MAX_MACHINE
        self._lock = threading.Lock()
        self._last_timestamp = -1
        self._sequence = 0

    @staticmethod
    def _current_ms() -> int:
        return int(time.time() * 1000)

    def _wait_next_ms(self, last_timestamp: int) -> int:
        """自旋等待进入下一毫秒（序列耗尽或时钟回拨时使用）"""
        timestamp = self._current_ms()
        while timestamp <= last_timestamp:
            time.sleep(0.0001)
            timestamp = self._current_ms()
        return timestamp

    def next_id(self) -> int:
        """生成下一个雪花 ID"""
        with self._lock:
            timestamp = self._current_ms()
            if timestamp < self._last_timestamp:
                # 时钟回拨：等待追平上次时间戳，避免产生重复 ID
                timestamp = self._wait_next_ms(self._last_timestamp)
            if timestamp == self._last_timestamp:
                self._sequence = (self._sequence + 1) & self.MAX_SEQUENCE
                if self._sequence == 0:
                    # 本毫秒序列耗尽，等待下一毫秒
                    timestamp = self._wait_next_ms(timestamp)
            else:
                self._sequence = 0
            self._last_timestamp = timestamp
            return (
                ((timestamp - self.EPOCH) << self.TIMESTAMP_SHIFT)
                | (self.datacenter_id << self.DATACENTER_SHIFT)
                | (self.machine_id << self.MACHINE_SHIFT)
                | self._sequence
            )


def _derive_machine_id() -> int:
    """由进程 PID + 主机名派生机器位（0~31），保证多 Worker 实例间不冲突"""
    hostname_sum = sum(socket.gethostname().encode("utf-8", errors="ignore"))
    return (os.getpid() + hostname_sum) & SnowflakeIdGenerator.MAX_MACHINE


# 进程级共享生成器（必须单例：多实例同毫秒同机器位会产生重复序列）
_default_generator = SnowflakeIdGenerator(
    datacenter_id=int(getattr(settings, "SNOWFLAKE_DATACENTER_ID", 0) or 0),
    machine_id=int(getattr(settings, "SNOWFLAKE_MACHINE_ID", _derive_machine_id()) or 0),
)


def next_snowflake_id() -> int:
    """生成全局唯一雪花 ID（task_no 编号等场景复用）"""
    return _default_generator.next_id()


class SnowflakeStrategy(BaseStrategy):
    """SNOWFLAKE：雪花 ID，适合 bigint 主键（字符类型字段自动转字符串）"""

    strategy_code = "SNOWFLAKE"

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        value = _default_generator.next_id()
        data_type = get_data_type(column_meta)
        if data_type in ("char", "varchar"):
            return str(value)
        return value
