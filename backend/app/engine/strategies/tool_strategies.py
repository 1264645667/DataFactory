"""工具生成策略：TOOL_GEN（调用快捷工具随机生成字段值）

需求场景：id_card_no / address / phone 等字段，直接复用「快捷工具」的生成器，
每行随机生成一条合规值（身份证含校验位、手机号真实号段、银行卡 BIN+Luhn 等）。

设计要点：
- 复用 tool_service 的纯内存生成函数，不在策略层重复造轮子
- 策略单例 + 线程锁 + 批量缓存（每批 200 条）：避免逐行调用工具的循环开销，多线程安全
- 缓存按 tool+参数 维度区分，同一字段配置的批次内连续取值
- 参数：tool（工具标识，必填）+ 各工具可选参数（province/gender 等，缺省用工具默认值）
"""
from __future__ import annotations

import json
import threading
from typing import Any

from app.engine.strategies.base import BaseStrategy, get_char_max_length
from app.services import tool_service

# 支持的工具标识
TOOL_IDCARD = "idcard"
TOOL_PHONE = "phone"
TOOL_BANKCARD = "bankcard"
TOOL_NAME = "name"
TOOL_CREDIT_CODE = "credit_code"
TOOL_TAXPAYER_ID = "taxpayer_id"
TOOL_ADDRESS = "address"

SUPPORTED_TOOLS = {
    TOOL_IDCARD,
    TOOL_PHONE,
    TOOL_BANKCARD,
    TOOL_NAME,
    TOOL_CREDIT_CODE,
    TOOL_TAXPAYER_ID,
    TOOL_ADDRESS,
}

# 各工具生成值的固定/典型长度（用于字符字段最大长度校验，None 表示长度可变不预校验）
_TOOL_TYPICAL_LEN: dict[str, int | None] = {
    TOOL_IDCARD: 18,
    TOOL_PHONE: 11,
    TOOL_BANKCARD: None,
    TOOL_NAME: None,
    TOOL_CREDIT_CODE: 18,
    TOOL_TAXPAYER_ID: 18,
    TOOL_ADDRESS: None,
}


class ToolGenStrategy(BaseStrategy):
    """TOOL_GEN：调用快捷工具随机生成（每行一条）"""

    strategy_code = "TOOL_GEN"

    # 批量预取条数（缓存队列长度）
    _BATCH_SIZE = 200

    def __init__(self) -> None:
        # cache_key -> 待取值队列（线程锁保护）
        self._cache: dict[str, list] = {}
        self._lock = threading.Lock()

    def validate(self, column_meta: dict, params: dict) -> None:
        tool = params.get("tool")
        if tool not in SUPPORTED_TOOLS:
            raise ValueError(f"未知工具类型：{tool}（支持 {sorted(SUPPORTED_TOOLS)}）")
        # 字符字段长度校验（仅对定长工具）
        max_len = get_char_max_length(column_meta)
        typical = _TOOL_TYPICAL_LEN.get(tool)
        if max_len and typical and typical > int(max_len):
            raise ValueError(f"工具[{tool}]生成值长度约 {typical}，超过字段最大长度 {max_len}")

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        tool = params["tool"]
        key = self._cache_key(tool, params)
        with self._lock:
            queue = self._cache.get(key)
            if not queue:
                queue = self._generate_batch(tool, params, self._BATCH_SIZE)
                self._cache[key] = queue
            return queue.pop(0)

    # ── 内部实现 ─────────────────────────────────────────────

    @staticmethod
    def _cache_key(tool: str, params: dict) -> str:
        """缓存维度：工具 + 除 tool 外的全部参数（同一字段配置共享一个队列）"""
        rest = {k: v for k, v in params.items() if k != "tool"}
        return f"{tool}|{json.dumps(rest, sort_keys=True, default=str)}"

    def _generate_batch(self, tool: str, params: dict, count: int) -> list:
        """按工具类型批量生成，并提取主值（身份证取 id_card，银行卡取 card_no，其余为纯字符串）"""
        if tool == TOOL_IDCARD:
            items = tool_service.generate_idcards(
                province=params.get("province") or None,
                gender=params.get("gender") or "random",
                birth_year_start=int(params.get("birth_year_start") or 1950),
                birth_year_end=int(params.get("birth_year_end") or 2010),
                count=count,
            )
            return [it["id_card"] for it in items]
        if tool == TOOL_PHONE:
            return tool_service.generate_phones(carrier=params.get("carrier") or "random", count=count)
        if tool == TOOL_BANKCARD:
            items = tool_service.generate_bankcards(
                bank=params.get("bank") or None,
                card_type=params.get("card_type") or "debit",
                count=count,
            )
            return [it["card_no"] for it in items]
        if tool == TOOL_NAME:
            return tool_service.generate_names(
                language=params.get("language") or "zh",
                gender=params.get("gender") or "random",
                count=count,
            )
        if tool == TOOL_CREDIT_CODE:
            return tool_service.generate_credit_codes(department=params.get("department") or None, count=count)
        if tool == TOOL_TAXPAYER_ID:
            return tool_service.generate_taxpayer_ids(
                taxpayer_type=params.get("taxpayer_type") or "enterprise", count=count
            )
        if tool == TOOL_ADDRESS:
            return tool_service.generate_addresses(
                province=params.get("province") or None,
                precision=params.get("precision") or "full",
                count=count,
            )
        raise ValueError(f"未知工具类型：{tool}")
