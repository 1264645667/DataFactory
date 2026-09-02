"""Redis 客户端管理

- redis_client：redis.asyncio 异步客户端（FastAPI 请求链路）
- sync_redis_client：同步 redis.Redis 客户端（Celery 同步任务）
"""

import redis.asyncio as aioredis
import redis as sync_redis
from redis.asyncio import Redis as AsyncRedis

from app.config import settings

# 异步客户端（API 服务，decode_responses=True 直接返回 str）
redis_client: AsyncRedis = aioredis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=20,
)

# 同步客户端（Celery Worker 同步任务使用）
sync_redis_client: sync_redis.Redis = sync_redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=10,
)


async def get_redis() -> AsyncRedis:
    """FastAPI 依赖：获取异步 Redis 客户端。"""
    return redis_client


async def check_redis_health() -> bool:
    """Redis 健康检查（/api/health 端点使用）。"""
    try:
        return bool(await redis_client.ping())
    except Exception:
        return False


async def close_redis() -> None:
    """应用关闭时释放连接池。"""
    await redis_client.aclose()
    sync_redis_client.close()
