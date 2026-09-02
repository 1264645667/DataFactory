"""系统数据库 Session 管理。

- async_engine / AsyncSessionLocal：异步引擎（aiomysql），FastAPI 请求链路使用
- sync_engine / SyncSessionLocal：同步引擎（pymysql），Celery 同步任务使用
"""

from collections.abc import AsyncGenerator

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# ── 异步引擎（FastAPI 请求链路）──────────────────────────────
async_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,  # 连接前探活，避免使用已被服务端回收的连接
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# ── 同步引擎（Celery 同步任务，pymysql 驱动）──────────────────
# Worker 副本连接数规划：pool_size=5, max_overflow=5
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    pool_size=5,
    max_overflow=5,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    echo=False,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：获取异步数据库 Session。"""
    async with AsyncSessionLocal() as session:
        yield session


async def check_db_health() -> bool:
    """数据库健康检查（/api/health 端点使用）。"""
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def close_db() -> None:
    """应用关闭时释放连接池。"""
    await async_engine.dispose()
    sync_engine.dispose()
