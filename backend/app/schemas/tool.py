"""造数快捷工具模块请求/响应 Schema。"""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ToolResultResponse(BaseModel, Generic[T]):
    """工具生成结果通用响应。"""

    count: int
    results: list[T]


# ── 7.3.1 身份证号生成器 ──────────────────────────────────────


class IdCardGenerateRequest(BaseModel):
    province: str | None = Field(default=None, description="省份，为空=不限")
    gender: Literal["male", "female", "random"] = "random"
    birth_year_start: int = Field(default=1950, ge=1950, le=2010)
    birth_year_end: int = Field(default=2010, ge=1950, le=2010)
    count: int = Field(default=1, ge=1, le=1000)


class IdCardItem(BaseModel):
    id_card: str
    province: str
    birth_date: str
    gender: str
    check_digit: str = Field(description="校验位")


# ── 7.3.2 手机号生成器 ────────────────────────────────────────


class PhoneGenerateRequest(BaseModel):
    carrier: Literal["mobile", "unicom", "telecom", "random"] = Field(
        default="random", description="移动/联通/电信/随机"
    )
    count: int = Field(default=1, ge=1, le=1000)


# ── 7.3.3 银行卡号生成器 ──────────────────────────────────────


class BankCardGenerateRequest(BaseModel):
    bank: str | None = Field(default=None, description="银行名称，为空=随机")
    card_type: Literal["debit", "credit"] = "debit"
    count: int = Field(default=1, ge=1, le=100)


class BankCardItem(BaseModel):
    card_no: str
    bank: str
    card_type: str


# ── 7.3.4 随机姓名生成器 ──────────────────────────────────────


class NameGenerateRequest(BaseModel):
    language: Literal["zh", "en"] = "zh"
    gender: Literal["male", "female", "random"] = "random"
    count: int = Field(default=1, ge=1, le=1000)


# ── 7.3.5 统一社会信用代码生成器 ────────────────────────────────


class CreditCodeGenerateRequest(BaseModel):
    department: str | None = Field(default=None, description="登记管理部门，为空=全部")
    count: int = Field(default=1, ge=1, le=100)


# ── 7.3.6 纳税人识别号生成器 ────────────────────────────────────


class TaxpayerIdGenerateRequest(BaseModel):
    taxpayer_type: Literal["enterprise", "personal"] = "enterprise"
    count: int = Field(default=1, ge=1, le=100)


# ── 7.3.7 随机地址生成器 ──────────────────────────────────────


class AddressGenerateRequest(BaseModel):
    province: str | None = None
    precision: Literal["province_city", "province_city_district", "full"] = Field(
        default="full", description="省市 / 省市区 / 省市区街道+门牌号"
    )
    count: int = Field(default=1, ge=1, le=500)


# ── 7.3.8 日期批量生成器 ──────────────────────────────────────


class DateGenerateRequest(BaseModel):
    start_date: str = Field(description="起始日期 yyyy-MM-dd")
    end_date: str = Field(description="结束日期 yyyy-MM-dd")
    fmt: Literal["yyyy-MM-dd", "yyyy/MM/dd", "yyyyMMdd", "timestamp"] = "yyyy-MM-dd"
    dedup: bool = False
    count: int = Field(default=1, ge=1, le=10000)


# ── 7.3.9 UUID 批量生成器 ──────────────────────────────────────


class UuidGenerateRequest(BaseModel):
    fmt: Literal["hyphen", "plain", "upper", "lower"] = Field(
        default="hyphen", description="含连字符/不含连字符/大写/小写"
    )
    count: int = Field(default=1, ge=1, le=10000)


# ── 7.3.10 雪花 ID 生成器 ──────────────────────────────────────


class SnowflakeGenerateRequest(BaseModel):
    machine_id: int = Field(default=0, ge=0, le=31)
    datacenter_id: int = Field(default=0, ge=0, le=31)
    count: int = Field(default=1, ge=1, le=1000)


class SnowflakeItem(BaseModel):
    """雪花 ID 及解析信息。id 用字符串承载，避免 64 位整数在 JS 中精度丢失。"""

    id: str
    timestamp: int
    machine_id: int
    datacenter_id: int
    sequence: int
