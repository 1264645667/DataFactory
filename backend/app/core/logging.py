"""结构化日志配置

- 开发环境：彩色可读格式
- 生产环境：JSON 格式
- 通过 structlog.contextvars 注入 trace_id / user_id
"""

import logging
import sys

import structlog

from app.config import settings


def configure_logging(env: str | None = None) -> None:
    """初始化 structlog 与标准 logging。"""
    env = env or settings.ENV
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    processors: list = [
        structlog.contextvars.merge_contextvars,  # 注入 trace_id / user_id
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if env == "production":
        processors.append(structlog.processors.JSONRenderer())  # JSON 格式
    else:
        processors.append(structlog.dev.ConsoleRenderer())  # 彩色可读格式

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    # 同步配置标准 logging（uvicorn / sqlalchemy 等第三方库走同一级别）
    logging.basicConfig(level=log_level, stream=sys.stdout, format="%(message)s")


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    """获取结构化 logger。

    使用示例：
        logger = get_logger()
        logger.info("exec_task_start", task_no=task.task_no, target_count=1000)
    """
    if name:
        return structlog.get_logger(name)
    return structlog.get_logger()
