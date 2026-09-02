"""动态多数据源连接池管理

按需创建、缓存、管理各目标数据源的 SQLAlchemy 异步连接池：
- get_engine：按 datasource_id 获取（不存在则创建，双检锁防并发重复创建）
- remove_engine：数据源删除或连接失败时移除并释放
- dispose_all：应用关闭时释放全部连接
数据源密码使用 core.security.decrypt_aes 解密。
"""

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings
from app.core.security import decrypt_aes

logger = structlog.get_logger()


class DynamicConnectionPool:
    """按需创建、缓存、管理各目标数据源的连接池。"""

    def __init__(self) -> None:
        self._engines: dict[int, AsyncEngine] = {}
        self._lock = asyncio.Lock()

    async def get_engine(self, datasource_id: int) -> AsyncEngine:
        """获取指定数据源的连接引擎，不存在则创建。"""
        if datasource_id not in self._engines:
            async with self._lock:
                # double-check，防止并发下重复创建
                if datasource_id not in self._engines:
                    self._engines[datasource_id] = await self._create_engine(
                        datasource_id
                    )
        return self._engines[datasource_id]

    async def _create_engine(self, datasource_id: int) -> AsyncEngine:
        """读取数据源配置并创建异步引擎。"""
        # 延迟导入，避免模块级循环依赖
        from app.db.session import AsyncSessionLocal
        from app.models.datasource import Datasource

        async with AsyncSessionLocal() as session:
            ds = await session.get(Datasource, datasource_id)
        if ds is None:
            raise ValueError(f"数据源不存在: {datasource_id}")

        password = decrypt_aes(ds.password)
        url = (
            f"mysql+aiomysql://{ds.username}:{password}"
            f"@{ds.host}:{ds.port}/{ds.database_name}"
        )
        engine = create_async_engine(
            url,
            pool_size=settings.TARGET_DS_POOL_SIZE,
            max_overflow=settings.TARGET_DS_MAX_OVERFLOW,
            pool_timeout=settings.TARGET_DS_POOL_TIMEOUT,
            pool_recycle=settings.TARGET_DS_POOL_RECYCLE,
            echo=False,
        )
        logger.info(
            "dynamic_pool_engine_created",
            datasource_id=datasource_id,
            host=ds.host,
            port=ds.port,
            database=ds.database_name,
        )
        return engine

    async def remove_engine(self, datasource_id: int) -> None:
        """数据源删除或连接失败时移除并释放连接。"""
        engine = self._engines.pop(datasource_id, None)
        if engine is not None:
            await engine.dispose()
            logger.info("dynamic_pool_engine_removed", datasource_id=datasource_id)

    async def dispose_all(self) -> None:
        """应用关闭时释放全部连接引擎。"""
        for datasource_id in list(self._engines):
            await self.remove_engine(datasource_id)


# 全局连接池管理器单例
pool_manager = DynamicConnectionPool()
