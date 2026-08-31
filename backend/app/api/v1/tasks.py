"""任务进度模块路由（API 清单 10.7，前缀 /api/v1/tasks）。

GET  /{task_no}/progress       任务实时进度（前端每 2s 轮询，文档 6.6.2）
POST /{task_no}/abort          强制停止任务（仅本人或管理员）
POST /{task_no}/retry-batches  重试失败批次（断点续传）
GET  /{task_no}/detail         任务详情（含分批次日志）
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.response import ApiResponse
from app.schemas.task import RetryBatchesRequest, TaskDetailResponse, TaskProgressResponse
from app.services import task_service

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/{task_no}/progress", summary="获取任务实时进度")
async def get_progress(
    task_no: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskProgressResponse]:
    data = await task_service.get_task_progress(db, current_user=current_user, task_no=task_no)
    return ApiResponse(data=data)


@router.post("/{task_no}/abort", summary="强制停止任务")
async def abort_task(
    task_no: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await task_service.abort_task(db, current_user=current_user, task_no=task_no, ip=_ip(request))
    return ApiResponse(message="任务已停止")


@router.post("/{task_no}/retry-batches", summary="重试失败批次（断点续传）")
async def retry_batches(
    task_no: str,
    body: RetryBatchesRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await task_service.retry_failed_batches(
        db, current_user=current_user, task_no=task_no, ip=_ip(request)
    )
    return ApiResponse(message="重试已提交，请通过进度接口查看执行状态")


@router.get("/{task_no}/detail", summary="任务详情（含分批次日志）")
async def get_detail(
    task_no: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskDetailResponse]:
    data = await task_service.get_task_detail(db, current_user=current_user, task_no=task_no)
    return ApiResponse(data=data)
