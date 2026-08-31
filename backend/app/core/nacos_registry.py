"""Nacos 服务注册与注销（架构文档 8.6）。

API 实例启动后向 Nacos 注册自身（临时实例，进程退出后自动摘除），
优雅退出时注销。全部容错降级：注册失败仅记录 WARNING，不阻断启动。
"""

import asyncio
import socket
from typing import Any

import structlog

from app.config import settings

logger = structlog.get_logger()

SERVICE_NAME = "dataforge-api"
SERVICE_PORT = 8000

_client: Any = None
_client_init_failed: bool = False


def _get_client() -> Any:
    """惰性创建 Nacos 客户端（避免模块导入时即连接）。"""
    global _client, _client_init_failed
    if _client is None and not _client_init_failed:
        try:
            import nacos

            _client = nacos.NacosClient(
                server_addresses=settings.NACOS_SERVER,
                namespace=settings.NACOS_NAMESPACE,
                username=settings.NACOS_USERNAME,
                password=settings.NACOS_PASSWORD,
            )
        except Exception as e:
            _client_init_failed = True
            logger.warning("nacos_registry_init_failed", error=str(e))
    return _client


async def register_service_instance() -> None:
    """API 启动时注册到 Nacos 服务列表（容错，失败不阻断启动）。"""
    client = _get_client()
    if client is None:
        return
    try:
        ip = socket.gethostbyname(socket.gethostname())  # 容器内 IP
        # nacos SDK 为同步调用，放入线程执行避免阻塞事件循环
        await asyncio.to_thread(
            client.add_naming_instance,
            service_name=SERVICE_NAME,
            ip=ip,
            port=SERVICE_PORT,
            cluster_name="DEFAULT",
            weight=1.0,
            metadata={
                "version": settings.APP_VERSION,
                "env": settings.ENV,
            },
            healthy=True,
            ephemeral=True,  # 临时实例：进程退出后 Nacos 自动摘除
        )
        logger.info(
            "nacos_service_registered", service=SERVICE_NAME, ip=ip, port=SERVICE_PORT
        )
    except Exception as e:
        logger.warning("nacos_service_register_failed", error=str(e))


async def deregister_service_instance() -> None:
    """API 优雅退出时注销（容错）。"""
    client = _get_client()
    if client is None:
        return
    try:
        ip = socket.gethostbyname(socket.gethostname())
        await asyncio.to_thread(
            client.remove_naming_instance, SERVICE_NAME, ip, SERVICE_PORT
        )
        logger.info("nacos_service_deregistered", service=SERVICE_NAME)
    except Exception as e:
        logger.warning("nacos_service_deregister_failed", error=str(e))
