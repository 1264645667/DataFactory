"""数据源业务服务。

覆盖：列表（含心跳状态）、新增（名称查重 + AES 加密 + 异步初始化）、编辑（密码保持原值 + 重同步）、
删除（硬校验 + 级联清理）、测试连接、手动同步（分布式锁）、连接状态查询。
"""

import time
from datetime import datetime
from urllib.parse import quote_plus

import structlog
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.deps import ensure_group_visible, group_filter_value
from app.celery_app import celery_app
from app.core.dynamic_pool import pool_manager
from app.core.redis_client import redis_client
from app.core.security import encrypt_aes
from app.models.cache import ColumnCache, IndexCache, TableCache
from app.models.case import Case
from app.models.datasource import Datasource
from app.models.task import ExecTask
from app.models.user import User
from app.schemas.datasource import (
    DatasourceCreateRequest,
    DatasourceItem,
    DatasourceStatusResponse,
    DatasourceSyncResponse,
    DatasourceTestRequest,
    DatasourceTestResponse,
    DatasourceUpdateRequest,
)
from app.schemas.errors import (
    CELERY_SUBMIT_FAILED,
    DS_HAS_ACTIVE_CASES,
    DS_NAME_TAKEN,
    DS_NOT_FOUND,
    DS_SYNC_LOCKED,
    FORBIDDEN,
    BizException,
)
from app.services.notification_service import audit

logger = structlog.get_logger(__name__)

# Redis Key
DS_STATUS_KEY = "df:ds:status:{ds_id}"
SYNC_LOCK_KEY = "df:lock:sync:{ds_id}"
TABLES_CACHE_KEY = "df:tables:{ds_id}"
COLUMNS_CACHE_PATTERN = "df:columns:{ds_id}:*"
INDEXES_CACHE_PATTERN = "df:indexes:{ds_id}:*"

# 执行中任务状态（0=待执行 1=执行中 4=重试中）
RUNNING_TASK_STATUS = (0, 1, 4)


def _remove_sync_engine_safe(datasource_id: int) -> None:
    """移除 Worker 侧同步连接池（MySQL Engine + Redis 客户端，防御性延迟导入）。"""
    try:
        from app.engine.db_pool import remove_sync_engine

        remove_sync_engine(datasource_id)
    except Exception:
        logger.warning("remove_sync_engine_failed", datasource_id=datasource_id)
    try:
        from app.engine.redis_pool import remove_sync_redis

        remove_sync_redis(datasource_id)
    except Exception:
        logger.warning("remove_sync_redis_failed", datasource_id=datasource_id)


async def get_datasource_or_404(db: AsyncSession, datasource_id: int) -> Datasource:
    """按 ID 获取数据源，不存在抛 1200。"""
    ds = await db.get(Datasource, datasource_id)
    if ds is None:
        raise BizException(DS_NOT_FOUND)
    return ds


async def get_datasource_checked(db: AsyncSession, current_user: User, datasource_id: int) -> Datasource:
    """获取数据源并校验分组数据权限（跨组按 1205 拒绝）。"""
    ds = await get_datasource_or_404(db, datasource_id)
    ensure_group_visible(current_user, ds.group_type, DS_NOT_FOUND)
    return ds


async def list_datasources(
    db: AsyncSession, *, current_user: User, keyword: str | None = None
) -> list[DatasourceItem]:
    """数据源列表（分组隔离 + Redis 心跳状态 + 默认标记）。"""
    conditions = []
    group_type = group_filter_value(current_user)
    if group_type is not None:
        conditions.append(Datasource.group_type == group_type)
    if keyword:
        conditions.append(Datasource.name.like(f"%{keyword}%"))

    result = await db.execute(
        select(Datasource).where(*conditions).order_by(Datasource.created_at.desc(), Datasource.id.desc())
    )
    datasources = list(result.scalars().all())

    # 批量读取心跳状态（df:ds:status:{id}，TTL 60s）
    online_map: dict[int, bool | None] = {}
    if datasources:
        try:
            values = await redis_client.mget(
                [DS_STATUS_KEY.format(ds_id=ds.id) for ds in datasources]
            )
            for ds, value in zip(datasources, values):
                if value == "online":
                    online_map[ds.id] = True
                elif value == "offline":
                    online_map[ds.id] = False
                else:
                    online_map[ds.id] = None  # 暂无心跳数据
        except Exception:
            logger.warning("ds_status_mget_failed")

    return [
        DatasourceItem(
            id=ds.id,
            name=ds.name,
            db_type=ds.db_type,
            host=ds.host,
            port=ds.port,
            database_name=ds.database_name,
            username=ds.username,
            group_type=ds.group_type,
            status=ds.status,
            online=online_map.get(ds.id),
            remark=ds.remark,
            table_count=ds.table_count,
            last_sync_at=ds.last_sync_at,
            is_default=(current_user.default_datasource_id == ds.id),
            created_at=ds.created_at,
        )
        for ds in datasources
    ]


async def _check_name_unique(
    db: AsyncSession, name: str, exclude_id: int | None = None
) -> None:
    """数据源名称全局唯一校验（1201）。"""
    stmt = select(Datasource.id).where(Datasource.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Datasource.id != exclude_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise BizException(DS_NAME_TAKEN)


def _check_group_assignable(current_user: User, group_type: int) -> None:
    """非管理员只能将数据源分配到本组（数据隔离）。"""
    if current_user.group_type != 99 and group_type != current_user.group_type:
        raise BizException(FORBIDDEN, "只能将数据源分配到本组")


def _trigger_sync_task(datasource_id: int) -> None:
    """异步触发 tasks.sync_datasource（提交失败抛 9003）。"""
    try:
        celery_app.send_task("tasks.sync_datasource", args=[datasource_id])
    except Exception as e:
        logger.error("celery_submit_failed", task="tasks.sync_datasource", datasource_id=datasource_id)
        raise BizException(CELERY_SUBMIT_FAILED) from e


async def create_datasource(
    db: AsyncSession, *, current_user: User, req: DatasourceCreateRequest, ip: str | None
) -> DatasourceItem:
    """新增数据源名称查重 → AES 加密存储 → 触发异步初始化。"""
    _check_group_assignable(current_user, req.group_type)
    await _check_name_unique(db, req.name)

    ds = Datasource(
        name=req.name,
        db_type=req.db_type,
        host=req.host,
        port=req.port,
        database_name=req.database_name,
        username=req.username,
        password=encrypt_aes(req.password),  # AES-256 加密存储
        group_type=req.group_type,
        status=0,  # 未初始化
        remark=req.remark,
        table_count=0,
        created_by=current_user.id,
    )
    db.add(ds)
    await db.flush()
    # 刷新以加载 server_default 列（created_at/updated_at），避免提交后懒加载触发 MissingGreenlet
    await db.refresh(ds)
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="ADD_DS",
        resource="datasource", resource_id=ds.id,
        detail=f"{req.name} {req.host}:{req.port}/{req.database_name}", ip=ip,
    )
    await db.commit()

    # 异步触发表结构初始化（失败仅告警：定时任务与手动同步可补偿）
    try:
        _trigger_sync_task(ds.id)
    except BizException:
        logger.warning("datasource_init_sync_trigger_failed", datasource_id=ds.id)
    logger.info("datasource_created", datasource_id=ds.id, name=req.name, operator=current_user.username)

    return DatasourceItem(
        id=ds.id,
        name=ds.name,
        db_type=ds.db_type,
        host=ds.host,
        port=ds.port,
        database_name=ds.database_name,
        username=ds.username,
        group_type=ds.group_type,
        status=ds.status,
        online=None,
        remark=ds.remark,
        table_count=0,
        last_sync_at=None,
        is_default=False,
        created_at=ds.created_at,
    )


async def update_datasource(
    db: AsyncSession,
    *,
    current_user: User,
    datasource_id: int,
    req: DatasourceUpdateRequest,
    ip: str | None,
) -> None:
    """编辑数据源密码不填保持原值；连接信息变更后清除连接池并重同步。"""
    ds = await get_datasource_checked(db, current_user, datasource_id)
    _check_group_assignable(current_user, req.group_type)
    await _check_name_unique(db, req.name, exclude_id=datasource_id)

    # 判断连接信息是否变更（决定是否需要重建连接池 + 重同步）
    conn_changed = any(
        [
            ds.host != req.host,
            ds.port != req.port,
            ds.database_name != req.database_name,
            ds.username != req.username,
            bool(req.password),  # 填了新密码
        ]
    )

    ds.name = req.name
    ds.db_type = req.db_type
    ds.host = req.host
    ds.port = req.port
    ds.database_name = req.database_name
    ds.username = req.username
    if req.password:
        ds.password = encrypt_aes(req.password)
    ds.group_type = req.group_type
    ds.remark = req.remark

    await audit(
        db, user_id=current_user.id, username=current_user.username, action="EDIT_DS",
        resource="datasource", resource_id=ds.id,
        detail=f"连接信息变更：{conn_changed}", ip=ip,
    )
    await db.commit()

    # 连接信息变更：丢弃旧连接池（异步池 + Worker 同步池），重新触发表结构同步
    if conn_changed:
        await pool_manager.remove_engine(datasource_id)
        _remove_sync_engine_safe(datasource_id)
    try:
        _trigger_sync_task(datasource_id)
    except BizException:
        logger.warning("datasource_resync_trigger_failed", datasource_id=datasource_id)
    logger.info("datasource_updated", datasource_id=datasource_id, operator=current_user.username)


async def delete_datasource(
    db: AsyncSession, *, current_user: User, datasource_id: int, ip: str | None
) -> None:
    """删除数据源。

    硬校验：存在未删除 Case → 1206；存在执行中任务 → 拦截。
    级联清理：三类缓存表 / Redis Key / 连接池 / 用户默认数据源置 NULL，最后物理删除记录。
    """
    ds = await get_datasource_checked(db, current_user, datasource_id)

    # 1. 未删除 Case 硬拦截（提示前 5 个 Case 名）
    case_result = await db.execute(
        select(Case.id, Case.case_name).where(
            Case.datasource_id == datasource_id, Case.is_deleted == 0
        )
    )
    active_cases = case_result.all()
    if active_cases:
        names = "、".join(f"「{name}」" for _, name in active_cases[:5])
        raise BizException(
            DS_HAS_ACTIVE_CASES,
            f"该数据源下还有 {len(active_cases)} 个 Case（{names}），请先删除或迁移后再操作",
        )

    # 2. 执行中任务硬拦截
    running_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ExecTask)
                .where(
                    ExecTask.datasource_id == datasource_id,
                    ExecTask.status.in_(RUNNING_TASK_STATUS),
                )
            )
        ).scalar_one()
    )
    if running_count > 0:
        raise BizException(
            DS_HAS_ACTIVE_CASES,
            f"该数据源下有 {running_count} 个任务正在执行，请等待执行完成或强制停止后再删除",
        )

    # 3. 级联清理（二次确认由前端完成）
    await db.execute(sql_delete(TableCache).where(TableCache.datasource_id == datasource_id))
    await db.execute(sql_delete(ColumnCache).where(ColumnCache.datasource_id == datasource_id))
    await db.execute(sql_delete(IndexCache).where(IndexCache.datasource_id == datasource_id))
    # 默认数据源引用置 NULL
    await db.execute(
        update(User)
        .where(User.default_datasource_id == datasource_id)
        .values(default_datasource_id=None)
    )
    await db.delete(ds)
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="DEL_DS",
        resource="datasource", resource_id=datasource_id,
        detail=f"删除数据源「{ds.name}」，级联清理缓存/连接池/默认引用", ip=ip,
    )
    await db.commit()

    # 4. 清理 Redis 缓存键（表结构缓存 + 心跳状态 + 同步锁）
    try:
        keys_to_delete = [TABLES_CACHE_KEY.format(ds_id=datasource_id), DS_STATUS_KEY.format(ds_id=datasource_id)]
        for pattern in (COLUMNS_CACHE_PATTERN, INDEXES_CACHE_PATTERN):
            async for key in redis_client.scan_iter(pattern.format(ds_id=datasource_id)):
                keys_to_delete.append(key)
        if keys_to_delete:
            await redis_client.delete(*keys_to_delete)
    except Exception:
        logger.warning("datasource_redis_cleanup_failed", datasource_id=datasource_id)

    # 5. 移除连接池（API 异步池 + Worker 同步池）
    await pool_manager.remove_engine(datasource_id)
    _remove_sync_engine_safe(datasource_id)
    logger.info("datasource_deleted", datasource_id=datasource_id, operator=current_user.username)


async def test_connection(req: DatasourceTestRequest) -> DatasourceTestResponse:
    """测试连接（表单页按钮，不保存）。MySQL：SELECT VERSION()；Redis：PING。"""
    if (req.db_type or "").strip().lower() == "redis":
        return await _test_redis_connection(req)
    engine = create_async_engine(
        f"mysql+aiomysql://{quote_plus(req.username)}:{quote_plus(req.password)}"
        f"@{req.host}:{req.port}/{req.database_name}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=5,
        echo=False,
    )
    start = time.perf_counter()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT VERSION()"))
            version = result.scalar_one()
        latency = round((time.perf_counter() - start) * 1000, 1)
        logger.info("datasource_test_success", host=req.host, port=req.port, latency_ms=latency)
        return DatasourceTestResponse(
            success=True, message=f"连接成功，数据库版本：MySQL {version}", db_version=str(version)
        )
    except Exception as e:
        logger.warning("datasource_test_failed", host=req.host, port=req.port, error=str(e))
        return DatasourceTestResponse(success=False, message=f"连接失败：{str(e)[:300]}")
    finally:
        await engine.dispose()


async def _test_redis_connection(req: DatasourceTestRequest) -> DatasourceTestResponse:
    """Redis 数据源测试连接：PING + INFO server 取版本。"""
    import redis.asyncio as aioredis

    try:
        db_index = int(req.database_name or 0)
    except ValueError:
        return DatasourceTestResponse(success=False, message="连接失败：DB 索引须为 0~15 的整数")
    client = aioredis.Redis(
        host=req.host, port=req.port, db=db_index,
        username=req.username or None, password=req.password or None,
        socket_connect_timeout=5, socket_timeout=5, decode_responses=True,
    )
    start = time.perf_counter()
    try:
        await client.ping()
        info = await client.info(section="server")
        version = info.get("redis_version", "unknown")
        dbsize = await client.dbsize()
        latency = round((time.perf_counter() - start) * 1000, 1)
        logger.info("redis_test_success", host=req.host, port=req.port, db=db_index, latency_ms=latency)
        return DatasourceTestResponse(
            success=True,
            message=f"连接成功，Redis {version}（db{db_index} 现有 {dbsize} 个 Key）",
            db_version=str(version),
        )
    except Exception as e:
        logger.warning("redis_test_failed", host=req.host, port=req.port, error=str(e))
        return DatasourceTestResponse(success=False, message=f"连接失败：{str(e)[:300]}")
    finally:
        await client.aclose()


async def trigger_sync(
    db: AsyncSession, *, current_user: User, datasource_id: int, ip: str | None
) -> DatasourceSyncResponse:
    """手动触发表结构同步分布式锁被占返回 1203。"""
    await get_datasource_checked(db, current_user, datasource_id)

    # 分布式锁占用检查（Worker 侧同步任务持有同一把锁）
    try:
        locked = bool(await redis_client.exists(SYNC_LOCK_KEY.format(ds_id=datasource_id)))
    except Exception:
        locked = False
    if locked:
        raise BizException(DS_SYNC_LOCKED)

    _trigger_sync_task(datasource_id)
    await audit(
        db, user_id=current_user.id, username=current_user.username, action="SYNC_DS",
        resource="datasource", resource_id=datasource_id, ip=ip,
    )
    await db.commit()
    logger.info("datasource_sync_triggered", datasource_id=datasource_id, operator=current_user.username)
    return DatasourceSyncResponse(
        datasource_id=datasource_id, triggered=True, message="同步任务已提交，请稍后刷新查看"
    )


async def get_datasource_status(
    db: AsyncSession, *, current_user: User, datasource_id: int
) -> DatasourceStatusResponse:
    """获取数据源连接状态（读取心跳结果 df:ds:status:{id}）。"""
    await get_datasource_checked(db, current_user, datasource_id)
    online = False
    error: str | None = None
    try:
        value = await redis_client.get(DS_STATUS_KEY.format(ds_id=datasource_id))
    except Exception:
        value = None
    if value == "online":
        online = True
    elif value == "offline":
        error = "心跳检测失败，数据源连接异常"
    else:
        error = "暂无心跳数据（检测每 30 秒执行一次）"
    return DatasourceStatusResponse(
        datasource_id=datasource_id, online=online, latency_ms=None, error=error,
        checked_at=datetime.now(),
    )
