"""DataForge API 应用入口（应用工厂模式，架构文档 2.2.1）。

lifespan 启动流程：
1. 加载 Nacos 配置（降级不阻断）
2. 注册服务实例到 Nacos（容错）
3. 初始化 DB / Redis 连接池并健康检查
4. 执行首次数据初始化（app/scripts/init_data.py，幂等）
关闭流程：注销 Nacos 实例，释放动态连接池 / DB / Redis 资源。
"""

import importlib
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.core.config_loader import load_nacos_configs
from app.core.dynamic_pool import pool_manager
from app.core.logging import configure_logging
from app.core.nacos_registry import (
    deregister_service_instance,
    register_service_instance,
)
from app.core.redis_client import check_redis_health, close_redis
from app.db.session import check_db_health, close_db
from app.schemas.errors import INTERNAL_ERROR, PARAM_INVALID, BizException
from app.schemas.response import ApiResponse

# 初始化结构化日志（早于其他模块输出日志）
configure_logging()
logger = structlog.get_logger()


# ── 中间件 ──────────────────────────────────────────────────


class TraceIDMiddleware(BaseHTTPMiddleware):
    """注入 trace_id：写入 request.state 与 structlog contextvars，并回写响应头。"""

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or uuid4().hex
        request.state.trace_id = trace_id
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("trace_id")
        response.headers["X-Trace-Id"] = trace_id
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件：记录方法、路径、状态码、耗时。"""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            client_ip=request.client.host if request.client else None,
        )
        return response


# ── 路由注册（路由模块由其他模块负责实现，缺失时跳过不阻断启动）─────

# (模块路径, router 属性名, 前缀, tags)
_ROUTER_SPECS = [
    ("app.api.v1.auth", "router", "/api/v1/auth", ["认证"]),
    ("app.api.v1.users", "router", "/api/v1/users", ["用户管理"]),
    ("app.api.v1.datasources", "router", "/api/v1/datasources", ["数据源"]),
    ("app.api.v1.engine", "router", "/api/v1/engine", ["造数引擎"]),
    ("app.api.v1.cases", "router", "/api/v1/cases", ["Case 管理"]),
    ("app.api.v1.scenes", "router", "/api/v1/scenes", ["场景管理"]),
    ("app.api.v1.tasks", "router", "/api/v1/tasks", ["任务进度"]),
    ("app.api.v1.tools", "router", "/api/v1/tools", ["快捷工具"]),
    ("app.api.v1.overview", "router", "/api/v1/overview", ["造数总览"]),
    # 注意：架构文档 2.2.1 示例遗漏了 notifications，此处按文档 10.10 补上
    ("app.api.v1.notifications", "router", "/api/v1/notifications", ["消息通知"]),
    ("app.api.v1.ai", "router", "/api/v1/ai", ["AI 预留"]),
]


def _include_routers(app: FastAPI) -> None:
    """注册业务路由。模块尚未实现时记录 WARNING 并跳过（不阻断启动）。"""
    for module_path, attr, prefix, tags in _ROUTER_SPECS:
        try:
            module = importlib.import_module(module_path)
            router = getattr(module, attr)
            app.include_router(router, prefix=prefix, tags=tags)
        except (ImportError, AttributeError) as e:
            logger.warning("router_not_registered", module=module_path, error=str(e))


# ── 生命周期 ────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # 1. 加载 Nacos 配置（Nacos 不可用时降级，不阻断启动）
    load_nacos_configs()

    # 2. 注册服务实例到 Nacos（容错，失败仅告警）
    await register_service_instance()

    # 3. 初始化 DB / Redis（引擎在模块导入时已创建，此处做连通性检查）
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    if not db_ok:
        logger.error("startup_db_unhealthy")
    if not redis_ok:
        logger.error("startup_redis_unhealthy")

    # 4. 执行首次数据初始化（幂等；DB 不可用时跳过并告警，不阻断启动）
    if db_ok:
        try:
            from app.scripts.init_data import init_first_data

            await init_first_data()
        except Exception as e:
            logger.error("init_first_data_failed", error=str(e))

    logger.info("startup_complete", db=db_ok, redis=redis_ok)
    yield

    # ── 关闭流程：优雅释放资源 ──
    await deregister_service_instance()
    await pool_manager.dispose_all()
    await close_db()
    await close_redis()
    logger.info("shutdown_complete")


# ── 全局异常处理 ──────────────────────────────────────────────


def _get_trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _biz_http_status(code: int) -> int:
    """业务错误码到 HTTP 状态码的映射（body 中仍携带统一 ApiResponse）。"""
    if code in (1001, 1006):  # 未登录 / Token 已失效
        return 401
    if code in (1002, 1205):  # 无权限
        return 403
    if code >= 9000:  # 系统级错误
        return 500
    return 400


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizException)
    async def biz_exception_handler(request: Request, exc: BizException) -> JSONResponse:
        body = ApiResponse(
            code=exc.code, message=exc.message, trace_id=_get_trace_id(request)
        )
        return JSONResponse(
            status_code=_biz_http_status(exc.code), content=body.model_dump()
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        body = ApiResponse(
            code=PARAM_INVALID,
            message="请求参数不合法",
            data={"errors": exc.errors()},
            trace_id=_get_trace_id(request),
        )
        return JSONResponse(status_code=400, content=body.model_dump())

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error("unhandled_exception", error=str(exc), exc_info=True)
        body = ApiResponse(
            code=INTERNAL_ERROR,
            message="服务内部错误，请联系管理员",
            trace_id=_get_trace_id(request),
        )
        return JSONResponse(status_code=500, content=body.model_dump())


# ── 应用工厂 ────────────────────────────────────────────────


def create_app() -> FastAPI:
    app = FastAPI(
        title="DataForge API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    # 注册中间件（注意：后注册的先执行，TraceID 最外层）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(TraceIDMiddleware)  # 注入 trace_id

    # 注册路由
    _include_routers(app)

    # 注册全局异常处理器
    _register_exception_handlers(app)

    # 健康检查端点（Docker healthcheck + Nacos 心跳探测，文档 8.6）
    @app.get("/api/health")
    async def health_check() -> dict:
        db_ok = await check_db_health()
        redis_ok = await check_redis_health()
        status = "UP" if (db_ok and redis_ok) else "DEGRADED"
        return {
            "status": status,
            "db": "UP" if db_ok else "DOWN",
            "redis": "UP" if redis_ok else "DOWN",
        }

    return app


app = create_app()
