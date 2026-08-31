"""目标数据源动态连接池（同步版，供 Celery Worker / 造数引擎使用）

设计要点（架构文档 2.4 的同步实现）：
- 按 datasource_id 缓存 SQLAlchemy Engine（mysql+pymysql）
- pool_size=5 / max_overflow=5 / pool_recycle=1800
- 线程锁 double-check 保证并发场景下同一数据源只创建一个 Engine
- 连接信息读取 df_datasource 表，密码使用 AES 解密（app.core.security.decrypt_aes）

注意：本模块为同步实现，Celery 任务内禁止使用 asyncio。
"""
from __future__ import annotations

import threading
from urllib.parse import quote_plus

import structlog
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.security import decrypt_aes
from app.db.session import SyncSessionLocal
from app.models import Datasource

logger = structlog.get_logger(__name__)

# datasource_id -> Engine 缓存
_engines: dict[int, Engine] = {}
_lock = threading.Lock()


def _build_engine(datasource_id: int) -> Engine:
    """读取数据源配置并创建同步 Engine"""
    session = SyncSessionLocal()
    try:
        ds = session.get(Datasource, datasource_id)
    finally:
        session.close()
    if ds is None:
        raise ValueError(f"数据源不存在: {datasource_id}")
    password = decrypt_aes(ds.password)
    # 用户名/密码做 URL 编码，避免特殊字符破坏连接串
    url = (
        f"mysql+pymysql://{quote_plus(str(ds.username))}:{quote_plus(str(password))}"
        f"@{ds.host}:{ds.port}/{ds.database_name}"
        f"?charset=utf8mb4&connect_timeout=5"
    )
    return create_engine(
        url,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
        pool_timeout=30,
        pool_pre_ping=True,  # 取用前探活，规避连接被服务端回收后的 stale 连接
        echo=False,
    )


def get_sync_engine(datasource_id: int) -> Engine:
    """获取指定数据源的同步 Engine（不存在则创建，线程安全 double-check）"""
    if datasource_id not in _engines:
        with _lock:
            # double-check：等待锁期间可能已被其他线程创建
            if datasource_id not in _engines:
                engine = _build_engine(datasource_id)
                _engines[datasource_id] = engine
                logger.info("sync_engine_created", datasource_id=datasource_id)
    return _engines[datasource_id]


def remove_sync_engine(datasource_id: int) -> None:
    """移除并销毁指定数据源连接池（数据源删除/密码变更/持续连接失败时调用）"""
    with _lock:
        engine = _engines.pop(datasource_id, None)
    if engine is not None:
        engine.dispose()
        logger.info("sync_engine_removed", datasource_id=datasource_id)


def dispose_all() -> None:
    """销毁全部连接池（Worker 停机时调用）"""
    with _lock:
        engines = list(_engines.values())
        _engines.clear()
    for engine in engines:
        engine.dispose()
    logger.info("sync_engine_dispose_all", count=len(engines))
