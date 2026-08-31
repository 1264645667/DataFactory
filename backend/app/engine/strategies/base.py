"""造数策略抽象基类与字段类型解析工具（架构文档 6.3）"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

# 字段类型分组（data_type 小写）
INT_TYPES = {"tinyint", "smallint", "mediumint", "int", "integer", "bigint"}
DECIMAL_TYPES = {"decimal", "numeric", "float", "double", "real"}
CHAR_TYPES = {"char", "varchar", "tinytext", "text", "mediumtext", "longtext"}
TEXT_TYPES = {"tinytext", "text", "mediumtext", "longtext"}
TIME_TYPES = {"datetime", "timestamp", "date", "time", "year"}
DATETIME_TYPES = {"datetime", "timestamp"}


class BaseStrategy(ABC):
    """造数策略抽象基类"""

    strategy_code: str = ""

    def validate(self, column_meta: dict, params: dict) -> None:
        """参数校验，不合法抛 ValueError（中文提示，对应 PRD 4.4.5）

        在执行前的配置校验与每批数据生成前各调用一次。
        """

    @abstractmethod
    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        """生成单个值

        :param column_meta: 字段元数据（data_type/column_type/char_max_length/numeric_precision 等）
        :param params: 策略参数（用户配置）
        :param index: 当前行序号（自增/遍历策略需要）
        """


# ------------------------------------------------------------------
# 字段类型解析工具
# ------------------------------------------------------------------

_TYPE_RE = re.compile(r"^(\w+)(?:\(([^)]*)\))?")


def parse_column_type(column_type: str) -> tuple[str, list[int]]:
    """解析完整字段类型，如 ``decimal(10,2) unsigned`` -> ('decimal', [10, 2])"""
    match = _TYPE_RE.match((column_type or "").strip())
    if not match:
        return "", []
    base = match.group(1).lower()
    nums: list[int] = []
    if match.group(2):
        for part in match.group(2).split(","):
            part = part.strip()
            if part.isdigit():
                nums.append(int(part))
    return base, nums


def get_data_type(column_meta: dict) -> str:
    """取基础类型：优先 data_type 字段，缺失时从 column_type 解析"""
    data_type = (column_meta.get("data_type") or "").lower()
    if data_type:
        return data_type
    base, _ = parse_column_type(column_meta.get("column_type") or "")
    return base


def get_char_max_length(column_meta: dict) -> int | None:
    """取字符最大长度：优先 char_max_length，缺失时从 column_type 解析（如 varchar(20)）"""
    length = column_meta.get("char_max_length")
    if length:
        return int(length)
    base, nums = parse_column_type(column_meta.get("column_type") or "")
    if base in ("char", "varchar", "binary", "varbinary") and nums:
        return nums[0]
    return None


def get_numeric_precision_scale(column_meta: dict) -> tuple[int | None, int | None]:
    """取数字精度与小数位：优先 numeric_precision/numeric_scale，缺失时从 column_type 解析"""
    precision = column_meta.get("numeric_precision")
    scale = column_meta.get("numeric_scale")
    if precision is not None:
        return int(precision), int(scale or 0)
    base, nums = parse_column_type(column_meta.get("column_type") or "")
    if base in ("decimal", "numeric") and nums:
        return nums[0], (nums[1] if len(nums) > 1 else 0)
    return None, None


def is_unsigned(column_meta: dict) -> bool:
    """判断字段是否 unsigned"""
    return "unsigned" in (column_meta.get("column_type") or "").lower()


def parse_enum_first_value(column_meta: dict) -> str:
    """解析 enum/set 类型的第一个可选值（DEFAULT 策略兜底用）"""
    column_type = column_meta.get("column_type") or ""
    match = re.search(r"\((.*)\)", column_type)
    if not match:
        return ""
    inner = match.group(1)
    first = inner.split(",", 1)[0].strip().strip("'").strip('"')
    return first
