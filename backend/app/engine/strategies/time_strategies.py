"""时间类策略：NOW / RANDOM_TIME_RANGE / FIXED_TIME

参数约定：
- RANDOM_TIME_RANGE: {"start_time": "yyyy-MM-dd HH:mm:ss", "end_time": "yyyy-MM-dd HH:mm:ss"}
  （date 字段使用 "yyyy-MM-dd"）
- FIXED_TIME: {"time": "yyyy-MM-dd HH:mm:ss"}（date 字段使用 "yyyy-MM-dd"）
"""
from __future__ import annotations

import random
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from app.engine.strategies.base import BaseStrategy, get_data_type

_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
_DATE_FMT = "%Y-%m-%d"


def _is_date_type(column_meta: dict) -> bool:
    return get_data_type(column_meta) == "date"


@lru_cache(maxsize=1024)
def _parse_time_value(data_type: str, raw: str) -> datetime | date:
    """按字段类型解析时间字符串（带缓存，避免百万行重复 strptime）"""
    if data_type == "date":
        try:
            return datetime.strptime(raw, _DATE_FMT).date()
        except ValueError:
            raise ValueError("日期格式不正确") from None
    try:
        return datetime.strptime(raw, _DATETIME_FMT)
    except ValueError:
        raise ValueError("时间格式不正确") from None


def _to_timestamp(value: datetime | date) -> float:
    """统一转时间戳（date 按当天 00:00:00 处理）"""
    if isinstance(value, datetime):
        return value.timestamp()
    return datetime(value.year, value.month, value.day).timestamp()


class NowStrategy(BaseStrategy):
    """NOW：当前时间（datetime/timestamp 返回当前时间，date 返回当前日期）"""

    strategy_code = "NOW"

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        if _is_date_type(column_meta):
            return date.today()
        return datetime.now().replace(microsecond=0)


class RandomTimeRangeStrategy(BaseStrategy):
    """RANDOM_TIME_RANGE：在指定时间范围内均匀随机"""

    strategy_code = "RANDOM_TIME_RANGE"

    def validate(self, column_meta: dict, params: dict) -> None:
        start_raw = params.get("start_time")
        end_raw = params.get("end_time")
        if not start_raw or not end_raw:
            raise ValueError("随机时间段必须配置起始与结束时间")
        data_type = get_data_type(column_meta)
        start = _parse_time_value(data_type, str(start_raw).strip())
        end = _parse_time_value(data_type, str(end_raw).strip())
        if _to_timestamp(start) >= _to_timestamp(end):
            raise ValueError("开始时间必须早于结束时间")

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        data_type = get_data_type(column_meta)
        start = _parse_time_value(data_type, str(params["start_time"]).strip())
        end = _parse_time_value(data_type, str(params["end_time"]).strip())
        start_ts, end_ts = _to_timestamp(start), _to_timestamp(end)
        random_ts = start_ts + random.random() * (end_ts - start_ts)
        result = datetime.fromtimestamp(random_ts).replace(microsecond=0)
        return result.date() if data_type == "date" else result


class FixedTimeStrategy(BaseStrategy):
    """FIXED_TIME：固定时间，所有行插入相同时间"""

    strategy_code = "FIXED_TIME"

    def validate(self, column_meta: dict, params: dict) -> None:
        raw = params.get("time", params.get("value"))
        if not raw:
            raise ValueError("固定时间不能为空")
        _parse_time_value(get_data_type(column_meta), str(raw).strip())

    def generate(self, column_meta: dict, params: dict, index: int) -> Any:
        raw = params.get("time", params.get("value"))
        return _parse_time_value(get_data_type(column_meta), str(raw).strip())
