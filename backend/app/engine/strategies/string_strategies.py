"""字符类与通用策略实现

包含：DEFAULT（兜底）、RANDOM_FIXED_LEN、
RANDOM_RANGE_LEN、CUSTOM_VALUE、PICK_FROM_LIST、ITERATE_LIST。

所有策略的参数校验失败均抛 ValueError
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.engine.strategies.base import (
    DECIMAL_TYPES,
    INT_TYPES,
    TEXT_TYPES,
    BaseStrategy,
    get_char_max_length,
    get_data_type,
    get_numeric_precision_scale,
    parse_column_type,
    parse_enum_first_value,
)

_ALPHANUM = string.ascii_letters + string.digits
_DIGITS = string.digits

# Lorem 文本素材（text 类字段 DEFAULT 生成用）
_LOREM_WORDS = (
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua enim ad minim veniam quis nostrud "
    "exercitation ullamco laboris nisi aliquip ex ea commodo consequat"
).split()


def _random_text(min_len: int, max_len: int) -> str:
    """生成 min_len~max_len 字符的随机 Lorem 文本"""
    length = random.randint(min_len, max_len)
    words: list[str] = []
    total = 0
    while total < length:
        word = random.choice(_LOREM_WORDS)
        words.append(word)
        total += len(word) + 1
    return " ".join(words)[:length]


def _random_digits(length: int) -> str:
    """生成指定位数的数字字符串（首位非零，保证位数语义）"""
    if length <= 0:
        return ""
    return random.choice("123456789") + "".join(random.choices(_DIGITS, k=length - 1))


class DefaultStrategy(BaseStrategy):
    """DEFAULT 兜底策略 """

    strategy_code = "DEFAULT"

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        data_type = get_data_type(column_meta)

        if data_type == "varchar":
            # 随机字母数字字符串，长度 min(10, N)
            max_len = get_char_max_length(column_meta) or 255
            return "".join(random.choices(_ALPHANUM, k=min(10, max_len)))
        if data_type == "char":
            # 固定 N 位随机字符串
            max_len = get_char_max_length(column_meta) or 1
            return "".join(random.choices(_ALPHANUM, k=max_len))
        if data_type in TEXT_TYPES:
            # 随机 100~500 字符的 Lorem 文本
            return _random_text(100, 500)
        if data_type == "tinyint":
            # tinyint(1) 视为布尔随机 0/1；其余取小整数
            _, nums = parse_column_type(column_meta.get("column_type") or "")
            if nums == [1]:
                return random.choice([0, 1])
            return random.randint(0, 127)
        if data_type == "smallint":
            return random.randint(1, 32767)
        if data_type == "mediumint":
            return random.randint(1, 8388607)
        if data_type in ("int", "integer"):
            return random.randint(1, 2147483647)
        if data_type == "bigint":
            return random.randint(1, 9223372036854775807)
        if data_type in DECIMAL_TYPES:
            # 随机生成符合精度的小数
            precision, scale = get_numeric_precision_scale(column_meta)
            precision = precision or 10
            scale = scale or 0
            int_digits = max(1, precision - scale)
            int_part = random.randint(0, 10 ** int_digits - 1)
            if scale <= 0:
                return Decimal(int_part)
            frac_part = random.randint(0, 10 ** scale - 1)
            value = Decimal(int_part) + (Decimal(frac_part) / Decimal(10 ** scale))
            return value.quantize(Decimal(1).scaleb(-scale))
        if data_type in ("datetime", "timestamp"):
            return datetime.now().replace(microsecond=0)
        if data_type == "date":
            return date.today()
        if data_type == "time":
            return datetime.now().time().replace(microsecond=0)
        if data_type == "year":
            return datetime.now().year
        if data_type in ("bool", "boolean", "bit"):
            return random.choice([0, 1])
        if data_type == "json":
            return "{}"
        if data_type in ("enum", "set"):
            # 取枚举第一个可选值，避免 strict 模式下插入非法值
            return parse_enum_first_value(column_meta)
        # 未知类型兜底：10 位随机字母数字
        return "".join(random.choices(_ALPHANUM, k=10))


class RandomFixedLenStrategy(BaseStrategy):
    """RANDOM_FIXED_LEN：随机 X 位生成（参数 length）"""

    strategy_code = "RANDOM_FIXED_LEN"

    def validate(self, column_meta: dict, params: dict) -> None:
        length = params.get("length")
        if not isinstance(length, int) or isinstance(length, bool) or length < 1:
            raise ValueError("位数必须 ≥ 1")
        max_len = get_char_max_length(column_meta)
        if max_len is not None and length > max_len:
            raise ValueError(f"位数不能超过字段最大长度 {max_len}")

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        length = int(params["length"])
        data_type = get_data_type(column_meta)
        if data_type in INT_TYPES:
            return int(_random_digits(length))
        return "".join(random.choices(_ALPHANUM, k=length))


class RandomRangeLenStrategy(BaseStrategy):
    """RANDOM_RANGE_LEN：随机 X~Y 位生成（参数 min_length/max_length）"""

    strategy_code = "RANDOM_RANGE_LEN"

    def validate(self, column_meta: dict, params: dict) -> None:
        min_len = params.get("min_length")
        max_len_param = params.get("max_length")
        for name, value in (("最小位数", min_len), ("最大位数", max_len_param)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name}必须 ≥ 1")
        if min_len >= max_len_param:
            raise ValueError("最小位数必须小于最大位数")
        col_max = get_char_max_length(column_meta)
        if col_max is not None and max_len_param > col_max:
            raise ValueError(f"位数不能超过字段最大长度 {col_max}")

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        length = random.randint(int(params["min_length"]), int(params["max_length"]))
        data_type = get_data_type(column_meta)
        if data_type in INT_TYPES:
            return int(_random_digits(length))
        return "".join(random.choices(_ALPHANUM, k=length))


def convert_custom_value(column_meta: dict, value: Any) -> Any:
    """ CUSTOM_VALUE / 列表类策略共用：将用户输入值按字段类型转换并校验 """
    if value is None:
        return None
    data_type = get_data_type(column_meta)

    if data_type in INT_TYPES:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError("该字段为数字类型，请输入整数") from None
    if data_type in DECIMAL_TYPES:
        text_value = str(value).strip()
        try:
            decimal_value = Decimal(text_value)
        except (InvalidOperation, ValueError):
            raise ValueError("该字段为数字类型，请输入数字") from None
        precision, scale = get_numeric_precision_scale(column_meta)
        if precision:
            # 拆分整数位/小数位校验精度（对应提示「不超过 M 位且小数点后不超过 D 位」）
            normalized = text_value.lstrip("+-")
            int_raw, _, frac_raw = normalized.partition(".")
            int_digits = len(int_raw.lstrip("0")) or (1 if int_raw else 0)
            frac_digits = len(frac_raw)
            if int_digits + frac_digits > precision or frac_digits > (scale or 0):
                raise ValueError(
                    f"请输入不超过 {precision} 位且小数点后不超过 {scale or 0} 位的数字"
                )
        return decimal_value
    if data_type in ("datetime", "timestamp"):
        if isinstance(value, datetime):
            return value
        try:
            return datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            raise ValueError("时间格式不正确") from None
    if data_type == "date":
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise ValueError("日期格式不正确") from None
    if data_type == "time":
        try:
            return datetime.strptime(str(value).strip(), "%H:%M:%S").time()
        except (TypeError, ValueError):
            raise ValueError("时间格式不正确") from None
    if data_type == "year":
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError("该字段为数字类型，请输入整数") from None

    # 字符类及其他类型：按字符串处理并校验长度
    text_value = str(value)
    max_len = get_char_max_length(column_meta)
    if max_len is not None and len(text_value) > max_len:
        raise ValueError("输入内容超过字段最大长度")
    return text_value


class CustomValueStrategy(BaseStrategy):
    """CUSTOM_VALUE：自定义固定值（参数 value）"""

    strategy_code = "CUSTOM_VALUE"

    def validate(self, column_meta: dict, params: dict) -> None:
        if "value" not in params:
            raise ValueError("自定义值不能为空")
        convert_custom_value(column_meta, params.get("value"))

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        return convert_custom_value(column_meta, params.get("value"))


def normalize_list_values(params: dict) -> list[Any]:
    """列表参数归一化：支持 list 或换行分隔字符串"""
    values = params.get("values")
    if isinstance(values, str):
        values = [line.strip() for line in values.splitlines() if line.strip()]
    return list(values or [])


def validate_list_values(column_meta: dict, values: list[Any]) -> None:
    """列表值校验：非空 + 每个值与字段类型兼容/长度合法"""
    if not values:
        raise ValueError("列表不能为空")
    for i, item in enumerate(values, 1):
        try:
            convert_custom_value(column_meta, item)
        except ValueError:
            raise ValueError(f"第 {i} 行值与字段类型不兼容") from None


class PickFromListStrategy(BaseStrategy):
    """PICK_FROM_LIST：从列表随机选取（参数 values）"""

    strategy_code = "PICK_FROM_LIST"

    def validate(self, column_meta: dict, params: dict) -> None:
        validate_list_values(column_meta, normalize_list_values(params))

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        values = normalize_list_values(params)
        return convert_custom_value(column_meta, random.choice(values))


class IterateListStrategy(BaseStrategy):
    """ITERATE_LIST：按序遍历插入（参数 values + rows_per_value）

    遍历驱动逻辑由执行器（executor.execute_iterate_mode）完成：
    每轮将本字段注入为固定 CUSTOM_VALUE。直接调用 generate 时按下标顺序循环取值。
    """

    strategy_code = "ITERATE_LIST"

    def validate(self, column_meta: dict, params: dict) -> None:
        values = normalize_list_values(params)
        validate_list_values(column_meta, values)
        rows_per_value = params.get("rows_per_value")
        if not isinstance(rows_per_value, int) or isinstance(rows_per_value, bool) or rows_per_value < 1:
            raise ValueError("每值条数必须 ≥ 1")

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        values = normalize_list_values(params)
        return convert_custom_value(column_meta, values[index % len(values)])
