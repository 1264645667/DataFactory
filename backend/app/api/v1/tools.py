"""快捷工具模块路由（API 清单 10.9，前缀 /api/v1/tools）。

全部为 POST，请求体为生成参数，响应为生成结果列表（数量上限见各 Schema，PRD 7.3）。
"""

from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.models.user import User
from app.schemas.response import ApiResponse
from app.schemas.tool import (
    AddressGenerateRequest,
    BankCardGenerateRequest,
    BankCardItem,
    CreditCodeGenerateRequest,
    DateGenerateRequest,
    IdCardGenerateRequest,
    IdCardItem,
    NameGenerateRequest,
    PhoneGenerateRequest,
    SnowflakeGenerateRequest,
    SnowflakeItem,
    TaxpayerIdGenerateRequest,
    ToolResultResponse,
    UuidGenerateRequest,
)
from app.services import tool_service

router = APIRouter()

# 所有工具统一要求 TOOL:USE 权限（PRD 2.3）
_DEP = Depends(require_permission("TOOL:USE"))


@router.post("/idcard", summary="生成身份证号（GB/T 11643 校验位）")
async def gen_idcard(
    body: IdCardGenerateRequest,
    current_user: User = _DEP,
) -> ApiResponse[ToolResultResponse[IdCardItem]]:
    items = tool_service.generate_idcards(
        province=body.province, gender=body.gender,
        birth_year_start=body.birth_year_start, birth_year_end=body.birth_year_end,
        count=body.count,
    )
    return ApiResponse(data=ToolResultResponse(
        count=len(items), results=[IdCardItem(**item) for item in items]
    ))


@router.post("/phone", summary="生成手机号（真实号段）")
async def gen_phone(
    body: PhoneGenerateRequest,
    current_user: User = _DEP,
) -> ApiResponse[ToolResultResponse[str]]:
    items = tool_service.generate_phones(carrier=body.carrier, count=body.count)
    return ApiResponse(data=ToolResultResponse(count=len(items), results=items))


@router.post("/bankcard", summary="生成银行卡号（BIN + Luhn）")
async def gen_bankcard(
    body: BankCardGenerateRequest,
    current_user: User = _DEP,
) -> ApiResponse[ToolResultResponse[BankCardItem]]:
    items = tool_service.generate_bankcards(bank=body.bank, card_type=body.card_type, count=body.count)
    return ApiResponse(data=ToolResultResponse(
        count=len(items), results=[BankCardItem(**item) for item in items]
    ))


@router.post("/name", summary="生成随机姓名（中英文）")
async def gen_name(
    body: NameGenerateRequest,
    current_user: User = _DEP,
) -> ApiResponse[ToolResultResponse[str]]:
    items = tool_service.generate_names(language=body.language, gender=body.gender, count=body.count)
    return ApiResponse(data=ToolResultResponse(count=len(items), results=items))


@router.post("/credit-code", summary="生成统一社会信用代码（GB 32100 校验位）")
async def gen_credit_code(
    body: CreditCodeGenerateRequest,
    current_user: User = _DEP,
) -> ApiResponse[ToolResultResponse[str]]:
    items = tool_service.generate_credit_codes(department=body.department, count=body.count)
    return ApiResponse(data=ToolResultResponse(count=len(items), results=items))


@router.post("/taxpayer-id", summary="生成纳税人识别号")
async def gen_taxpayer_id(
    body: TaxpayerIdGenerateRequest,
    current_user: User = _DEP,
) -> ApiResponse[ToolResultResponse[str]]:
    items = tool_service.generate_taxpayer_ids(taxpayer_type=body.taxpayer_type, count=body.count)
    return ApiResponse(data=ToolResultResponse(count=len(items), results=items))


@router.post("/address", summary="生成随机地址（内置省市数据）")
async def gen_address(
    body: AddressGenerateRequest,
    current_user: User = _DEP,
) -> ApiResponse[ToolResultResponse[str]]:
    items = tool_service.generate_addresses(
        province=body.province, precision=body.precision, count=body.count
    )
    return ApiResponse(data=ToolResultResponse(count=len(items), results=items))


@router.post("/date", summary="批量生成日期")
async def gen_date(
    body: DateGenerateRequest,
    current_user: User = _DEP,
) -> ApiResponse[ToolResultResponse]:
    items = tool_service.generate_dates(
        start_date=body.start_date, end_date=body.end_date,
        fmt=body.fmt, dedup=body.dedup, count=body.count,
    )
    return ApiResponse(data=ToolResultResponse(count=len(items), results=items))


@router.post("/uuid", summary="批量生成 UUID")
async def gen_uuid(
    body: UuidGenerateRequest,
    current_user: User = _DEP,
) -> ApiResponse[ToolResultResponse[str]]:
    items = tool_service.generate_uuids(fmt=body.fmt, count=body.count)
    return ApiResponse(data=ToolResultResponse(count=len(items), results=items))


@router.post("/snowflake", summary="生成雪花 ID（含解析信息）")
async def gen_snowflake(
    body: SnowflakeGenerateRequest,
    current_user: User = _DEP,
) -> ApiResponse[ToolResultResponse[SnowflakeItem]]:
    items = tool_service.generate_snowflakes(
        machine_id=body.machine_id, datacenter_id=body.datacenter_id, count=body.count
    )
    return ApiResponse(data=ToolResultResponse(
        count=len(items), results=[SnowflakeItem(**item) for item in items]
    ))
