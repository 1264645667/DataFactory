"""Case 管理模块路由（API 清单 10.5，前缀 /api/v1/cases）。

GET    /                   Case 列表（分页 + 筛选）
GET    /{case_id}          Case 详情（含 config_json）
PUT    /{case_id}          修改 Case 配置（覆盖式）
DELETE /{case_id}          逻辑删除 Case
POST   /{case_id}/execute  执行 Case（返回 task_no）
POST   /{case_id}/copy     复制 Case
GET    /{case_id}/history  Case 执行历史
POST   /batch-execute      批量执行（静态路径须先于 /{case_id} 声明）
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PageParams, require_permission
from app.db.session import get_db
from app.models.user import User
from app.schemas.case import (
    CaseBatchExecuteRequest,
    CaseBatchExecuteResponse,
    CaseCopyRequest,
    CaseCopyResponse,
    CaseDetail,
    CaseExecuteRequest,
    CaseExecuteResponse,
    CaseListItem,
    CaseUpdateRequest,
)
from app.schemas.response import ApiResponse, PageData
from app.services import case_service

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", summary="Case 列表（分页 + 筛选）")
async def list_cases(
    page_params: PageParams = Depends(),
    datasource_id: int | None = Query(default=None),
    name: str | None = Query(default=None, description="Case 名称模糊搜索"),
    created_by: int | None = Query(default=None),
    last_exec_status: list[int] | None = Query(default=None, description="最后执行状态多选"),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    main_table: str | None = Query(default=None),
    current_user: User = Depends(require_permission("CASE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PageData[CaseListItem]]:
    data = await case_service.list_cases(
        db, current_user=current_user,
        page=page_params.page, page_size=page_params.page_size,
        datasource_id=datasource_id, name=name, created_by=created_by,
        last_exec_status=last_exec_status, start_time=start_time, end_time=end_time,
        main_table=main_table,
    )
    return ApiResponse(data=data)


@router.post("/batch-execute", summary="批量执行（每个 Case 独立条数，串行提交）")
async def batch_execute(
    body: CaseBatchExecuteRequest,
    request: Request,
    current_user: User = Depends(require_permission("CASE:EXECUTE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CaseBatchExecuteResponse]:
    task_nos = await case_service.batch_execute_cases(
        db, current_user=current_user, req=body, ip=_ip(request)
    )
    return ApiResponse(data=CaseBatchExecuteResponse(task_nos=task_nos), message="批量任务已提交")


@router.get("/{case_id}", summary="Case 详情（含 config_json）")
async def get_case(
    case_id: int,
    current_user: User = Depends(require_permission("CASE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CaseDetail]:
    data = await case_service.get_case_detail(db, current_user=current_user, case_id=case_id)
    return ApiResponse(data=data)


@router.put("/{case_id}", summary="修改 Case 配置（覆盖式更新）")
async def update_case(
    case_id: int,
    body: CaseUpdateRequest,
    request: Request,
    current_user: User = Depends(require_permission("CASE:EDIT")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    result = await case_service.update_case(
        db, current_user=current_user, case_id=case_id, req=body, ip=_ip(request)
    )
    message = "Case 已保存"
    if result["schema_outdated"]:
        # PRD 5.3.2：表结构变更提示（保存仍生效）
        message = (
            "检测到表结构已更新，以下字段配置可能失效："
            + "、".join(result["outdated_fields"])
        )
    return ApiResponse(data=result, message=message)


@router.delete("/{case_id}", summary="逻辑删除 Case")
async def delete_case(
    case_id: int,
    request: Request,
    current_user: User = Depends(require_permission("CASE:DELETE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await case_service.delete_case(db, current_user=current_user, case_id=case_id, ip=_ip(request))
    return ApiResponse(message="Case 已删除，历史执行记录保留")


@router.post("/{case_id}/execute", summary="执行 Case（返回 task_no）")
async def execute_case(
    case_id: int,
    body: CaseExecuteRequest,
    request: Request,
    current_user: User = Depends(require_permission("CASE:EXECUTE")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CaseExecuteResponse]:
    task_no = await case_service.execute_case(
        db, current_user=current_user, case_id=case_id,
        target_count=body.target_count, batch_size=body.batch_size,
        max_workers=body.max_workers,
        disable_unique_checks=body.disable_unique_checks,
        disable_fk_checks=body.disable_fk_checks,
        ip=_ip(request),
    )
    return ApiResponse(data=CaseExecuteResponse(task_no=task_no), message="任务已提交")


@router.post("/{case_id}/copy", summary="复制 Case（默认名 xxx_copy）")
async def copy_case(
    case_id: int,
    body: CaseCopyRequest,
    request: Request,
    current_user: User = Depends(require_permission("CASE:COPY")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CaseCopyResponse]:
    new_case = await case_service.copy_case(
        db, current_user=current_user, case_id=case_id,
        case_name=body.case_name, ip=_ip(request),
    )
    return ApiResponse(
        data=CaseCopyResponse(case_id=new_case.id, case_name=new_case.case_name),
        message="复制成功",
    )


@router.get("/{case_id}/history", summary="查看 Case 执行历史")
async def case_history(
    case_id: int,
    current_user: User = Depends(require_permission("CASE:VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    data = await case_service.get_case_history(db, current_user=current_user, case_id=case_id)
    return ApiResponse(data=data)
