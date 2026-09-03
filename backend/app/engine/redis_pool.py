"""Redis 型数据源连接池（同步版，供 Celery Worker / 造数引擎使用）

设计要点（与 db_pool.py 对齐）
- 按 datasource_id 缓存 redis.Redis 客户端（内置连接池，线程安全）
- 连接信息读取 df_datasource 表：database_name 存 DB 索引（"0"~"15"），username 可空（ACL 用户）
- 密码使用 AES 解密（app.core.security.decrypt_aes），空密码按 None 处理（避免 AUTH 空串报错）

注意：本模块为同步实现，Celery 任务内禁止使用 asyncio。
"""
from __future__ import annotations

import threading

import redis
import structlog

from app.core.security import decrypt_aes
from app.db.session import SyncSessionLocal
from app.models import Datasource

logger = structlog.get_logger(__name__)

# datasource_id -> redis.Redis 缓存
_clients: dict[int, redis.Redis] = {}
_lock = threading.Lock()


def is_redis_datasource(ds: Datasource) -> bool:
    """判断数据源是否为 Redis 类型"""
    return (ds.db_type or "").strip().lower() == "redis"


def _build_client(datasource_id: int) -> redis.Redis:
    """读取数据源配置并创建同步 Redis 客户端"""
    session = SyncSessionLocal()
    try:
        ds = session.get(Datasource, datasource_id)
    finally:
        session.close()
    if ds is None:
        raise ValueError(f"数据源不存在: {datasource_id}")
    if not is_redis_datasource(ds):
        raise ValueError(f"数据源 {datasource_id} 不是 Redis 类型（{ds.db_type}）")
    password = decrypt_aes(ds.password) if ds.password else ""
    try:
        db_index = int(ds.database_name or 0)
    except ValueError as exc:
        raise ValueError(f"Redis 数据源 {datasource_id} 的 DB 索引非法: {ds.database_name!r}") from exc
    return redis.Redis(
        host=ds.host,
        port=ds.port,
        db=db_index,
        username=ds.username or None,
        password=password or None,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=10,
        max_connections=10,
    )


def get_sync_redis(datasource_id: int) -> redis.Redis:
    """获取指定 Redis 数据源的同步客户端（不存在则创建，线程安全 double-check）"""
    if datasource_id not in _clients:
        with _lock:
            if datasource_id not in _clients:
                _clients[datasource_id] = _build_client(datasource_id)
                logger.info("sync_redis_created", datasource_id=datasource_id)
    return _clients[datasource_id]


def remove_sync_redis(datasource_id: int) -> None:
    """移除并销毁指定 Redis 客户端（数据源删除/密码变更时调用）"""
    with _lock:
        client = _clients.pop(datasource_id, None)
    if client is not None:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
        logger.info("sync_redis_removed", datasource_id=datasource_id)


def dispose_all_redis() -> None:
    """销毁全部 Redis 客户端（Worker 停机时调用）"""
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
    logger.info("sync_redis_dispose_all", count=len(clients))
