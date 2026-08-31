"""统一响应格式（架构文档 2.2.2）。

code=0 表示成功；非 0 表示失败（错误码见 schemas/errors.py）。
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应体。"""

    code: int = 0  # 0=成功，非0=失败
    message: str = "success"
    data: T | None = None
    trace_id: str | None = None


class PageData(BaseModel, Generic[T]):
    """分页数据。"""

    items: list[T]
    total: int
    page: int
    page_size: int
