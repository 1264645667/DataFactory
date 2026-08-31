"""数据源同步与心跳检测 Celery 任务（PRD 8.4/8.5/8.6）

- sync_datasource: Redis 分布式锁 → information_schema 批量采集 →
  UPSERT df_table_cache/df_column_cache/df_index_cache → 刷新 Redis 缓存（12h TTL）→
  更新数据源状态 → 释放锁
- heartbeat_check: 每 30s 对所有数据源 SELECT 1，写 df:ds:status:{id}（60s TTL），
  连续 3 次失败写 DS_OFFLINE 通知（失败计数用 Redis）
- scheduled_sync_all: 每天 02:00 全量数据源逐个同步（status=正常）

所有 SQL 均参数化；缓存表写入使用原生 SQL（仅依赖 DDL 表结构，与 ORM 字段命名解耦）。
"""
from __future__ import annotations

import json
import time
from datetime import datetime

import structlog
from sqlalchemy import text

from app.celery_app import celery_app
from app.core.redis_client import sync_redis_client
from app.db.session import SyncSessionLocal
from app.engine.db_pool import get_sync_engine, remove_sync_engine
from app.models import Datasource, User
from app.tasks.notify_helper import create_notification

logger = structlog.get_logger(__name__)

# ---------------- Redis Key（文档 5.1） ----------------
TABLES_CACHE_KEY = "df:tables:{ds_id}"
COLUMNS_CACHE_KEY = "df:columns:{ds_id}:{table}"
INDEXES_CACHE_KEY = "df:indexes:{ds_id}:{table}"
DS_STATUS_KEY = "df:ds:status:{ds_id}"
SYNC_LOCK_KEY = "df:lock:sync:{ds_id}"
SCHEMA_CACHE_TTL = 12 * 3600        # 表结构缓存 12h
DS_STATUS_TTL = 60                  # 心跳状态 60s
SYNC_LOCK_TTL = 5 * 60              # 同步分布式锁 5min
# 以下为内部辅助 Key（文档未列出，心跳计数/防重复通知用）
DS_FAIL_COUNT_KEY = "df:ds:fail_count:{ds_id}"
DS_OFFLINE_NOTIFIED_KEY = "df:ds:offline_notified:{ds_id}"
HEARTBEAT_LOCK_KEY = "df:lock:heartbeat"

# 数据源状态（df_datasource.status）
DS_STATUS_NORMAL = 1
DS_STATUS_ERROR = 2
DS_STATUS_SYNCING = 3

# 心跳连续失败阈值（PRD 11.3：≥3 次触发 DS_OFFLINE）
HEARTBEAT_FAIL_THRESHOLD = 3


# ------------------------------------------------------------------
# information_schema 采集 SQL（参数化）
# ------------------------------------------------------------------

_SQL_TABLES = text(
    "SELECT TABLE_NAME, TABLE_COMMENT, TABLE_ROWS, DATA_LENGTH, ENGINE, TABLE_COLLATION, CREATE_TIME "
    "FROM information_schema.TABLES WHERE TABLE_SCHEMA = :schema ORDER BY TABLE_NAME"
)
_SQL_COLUMNS = text(
    "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_COMMENT, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, "
    "COLUMN_KEY, COLUMN_DEFAULT, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, "
    "ORDINAL_POSITION, EXTRA "
    "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = :schema ORDER BY TABLE_NAME, ORDINAL_POSITION"
)
_SQL_STATISTICS = text(
    "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, COLUMN_NAME, SEQ_IN_INDEX "
    "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = :schema "
    "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX"
)

# 本地缓存表写入 SQL（参数化）
_SQL_UPSERT_TABLE = text(
    "INSERT INTO df_table_cache (datasource_id, table_name, table_comment, table_rows, data_length, "
    "engine, charset, create_time, column_count, pk_type, unique_index_count, synced_at) "
    "VALUES (:datasource_id, :table_name, :table_comment, :table_rows, :data_length, "
    ":engine, :charset, :create_time, :column_count, :pk_type, :unique_index_count, :synced_at) "
    "ON DUPLICATE KEY UPDATE "
    "table_comment=VALUES(table_comment), table_rows=VALUES(table_rows), data_length=VALUES(data_length), "
    "engine=VALUES(engine), charset=VALUES(charset), create_time=VALUES(create_time), "
    "column_count=VALUES(column_count), pk_type=VALUES(pk_type), "
    "unique_index_count=VALUES(unique_index_count), synced_at=VALUES(synced_at)"
)
_SQL_DELETE_COLUMNS = text(
    "DELETE FROM df_column_cache WHERE datasource_id = :ds_id AND table_name = :table_name"
)
_SQL_INSERT_COLUMN = text(
    "INSERT INTO df_column_cache (datasource_id, table_name, column_name, column_comment, data_type, "
    "column_type, is_nullable, is_primary_key, is_unique, column_default, char_max_length, "
    "numeric_precision, numeric_scale, ordinal_position, extra, synced_at) "
    "VALUES (:datasource_id, :table_name, :column_name, :column_comment, :data_type, "
    ":column_type, :is_nullable, :is_primary_key, :is_unique, :column_default, :char_max_length, "
    ":numeric_precision, :numeric_scale, :ordinal_position, :extra, :synced_at)"
)
_SQL_DELETE_INDEXES = text(
    "DELETE FROM df_index_cache WHERE datasource_id = :ds_id AND table_name = :table_name"
)
_SQL_INSERT_INDEX = text(
    "INSERT INTO df_index_cache (datasource_id, table_name, index_name, is_unique, is_primary, "
    "column_names, seq_in_index, synced_at) "
    "VALUES (:datasource_id, :table_name, :index_name, :is_unique, :is_primary, "
    ":column_names, :seq_in_index, :synced_at)"
)
_SQL_DELETE_TABLE_CACHE = text(
    "DELETE FROM df_table_cache WHERE datasource_id = :ds_id AND table_name = :table_name"
)


def _decode(value):
    """Redis 返回值兼容 bytes/str"""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


# ------------------------------------------------------------------
# 数据源同步
# ------------------------------------------------------------------

def _collect_metadata(engine, database_name: str) -> tuple[list, dict, dict]:
    """从目标数据源采集表/字段/索引元数据

    :return: (表行列表, {表名: [字段行]}, {表名: {索引名: {"non_unique": int, "columns": [列名]}}})
    """
    with engine.connect() as conn:
        table_rows = conn.execute(_SQL_TABLES, {"schema": database_name}).fetchall()
        column_rows = conn.execute(_SQL_COLUMNS, {"schema": database_name}).fetchall()
        stat_rows = conn.execute(_SQL_STATISTICS, {"schema": database_name}).fetchall()

    columns_by_table: dict[str, list] = {}
    for row in column_rows:
        columns_by_table.setdefault(row[0], []).append(row)

    indexes_by_table: dict[str, dict] = {}
    for table_name, index_name, non_unique, column_name, seq_in_index in stat_rows:
        table_indexes = indexes_by_table.setdefault(table_name, {})
        index_info = table_indexes.setdefault(index_name, {"non_unique": int(non_unique), "columns": []})
        index_info["columns"].append(column_name)
    return table_rows, columns_by_table, indexes_by_table


def _persist_metadata(session, ds_id: int, table_rows, columns_by_table, indexes_by_table,
                      synced_at: datetime) -> dict:
    """批量 UPSERT 三类缓存表（单事务），并清理已删除表的缓存

    :return: 差异统计 {added, updated, removed}
    """
    # 差异对比（通知摘要：新增/更新/删除表数量）
    existing = session.execute(
        text("SELECT table_name FROM df_table_cache WHERE datasource_id = :ds_id"), {"ds_id": ds_id}
    ).fetchall()
    existing_names = {row[0] for row in existing}
    current_names = {row[0] for row in table_rows}
    added_names = current_names - existing_names
    removed_names = existing_names - current_names

    # 表缓存 UPSERT
    for row in table_rows:
        (table_name, table_comment, table_rows_est, data_length,
         engine_name, table_collation, create_time) = row
        columns = columns_by_table.get(table_name, [])
        pk_columns = [col for col in columns if col[6] == "PRI"]  # COLUMN_KEY='PRI'
        pk_type = "none" if not pk_columns else ("single" if len(pk_columns) == 1 else "composite")
        # 唯一索引数（排除主键）
        unique_index_count = sum(
            1 for index_name, info in (indexes_by_table.get(table_name) or {}).items()
            if info["non_unique"] == 0 and index_name != "PRIMARY"
        )
        session.execute(_SQL_UPSERT_TABLE, {
            "datasource_id": ds_id,
            "table_name": table_name,
            "table_comment": table_comment or None,
            "table_rows": int(table_rows_est or 0),
            "data_length": int(data_length or 0),
            "engine": engine_name,
            "charset": (table_collation or "").split("_")[0] or None,
            "create_time": create_time,
            "column_count": len(columns),
            "pk_type": pk_type,
            "unique_index_count": unique_index_count,
            "synced_at": synced_at,
        })

    # 字段/索引缓存：按表「先删后插」，天然处理字段/索引删除场景
    for table_name, columns in columns_by_table.items():
        session.execute(_SQL_DELETE_COLUMNS, {"ds_id": ds_id, "table_name": table_name})
        session.execute(_SQL_INSERT_COLUMN, [
            {
                "datasource_id": ds_id,
                "table_name": table_name,
                "column_name": col[1],
                "column_comment": col[2] or None,
                "data_type": col[3],
                "column_type": col[4],
                "is_nullable": 1 if col[5] == "YES" else 0,
                "is_primary_key": 1 if col[6] == "PRI" else 0,
                "is_unique": 1 if col[6] in ("PRI", "UNI") else 0,
                "column_default": None if col[7] is None else str(col[7])[:500],
                "char_max_length": int(col[8]) if col[8] is not None else None,
                "numeric_precision": int(col[9]) if col[9] is not None else None,
                "numeric_scale": int(col[10]) if col[10] is not None else None,
                "ordinal_position": int(col[11]),
                "extra": col[12] or None,
                "synced_at": synced_at,
            }
            for col in columns
        ])

    for table_name, indexes in indexes_by_table.items():
        session.execute(_SQL_DELETE_INDEXES, {"ds_id": ds_id, "table_name": table_name})
        if indexes:
            session.execute(_SQL_INSERT_INDEX, [
                {
                    "datasource_id": ds_id,
                    "table_name": table_name,
                    "index_name": index_name,
                    "is_unique": 0 if info["non_unique"] else 1,
                    "is_primary": 1 if index_name == "PRIMARY" else 0,
                    "column_names": json.dumps(info["columns"], ensure_ascii=False),
                    "seq_in_index": len(info["columns"]),
                    "synced_at": synced_at,
                }
                for index_name, info in indexes.items()
            ])

    # 清理已删除表的三类缓存
    for table_name in removed_names:
        params = {"ds_id": ds_id, "table_name": table_name}
        session.execute(_SQL_DELETE_TABLE_CACHE, params)
        session.execute(_SQL_DELETE_COLUMNS, params)
        session.execute(_SQL_DELETE_INDEXES, params)

    return {
        "added": len(added_names),
        "updated": len(current_names & existing_names),
        "removed": len(removed_names),
        "removed_names": sorted(removed_names),
    }


def _refresh_redis_cache(ds_id: int, table_rows, columns_by_table, indexes_by_table,
                         synced_at: datetime, removed_names: list[str]) -> None:
    """刷新 Redis 表结构缓存（df:tables / df:columns / df:indexes，12h TTL，文档 5.2）"""
    synced_str = synced_at.strftime("%Y-%m-%d %H:%M:%S")
    tables_payload = []
    for row in table_rows:
        table_name = row[0]
        columns = columns_by_table.get(table_name, [])
        pk_columns = [col for col in columns if col[6] == "PRI"]
        pk_type = "none" if not pk_columns else ("single" if len(pk_columns) == 1 else "composite")
        unique_index_count = sum(
            1 for index_name, info in (indexes_by_table.get(table_name) or {}).items()
            if info["non_unique"] == 0 and index_name != "PRIMARY"
        )
        tables_payload.append({
            "table_name": table_name,
            "table_comment": row[1] or "",
            "table_rows": int(row[2] or 0),
            "column_count": len(columns),
            "pk_type": pk_type,
            "unique_index_count": unique_index_count,
            "synced_at": synced_str,
        })

    pipe = sync_redis_client.pipeline()
    pipe.set(TABLES_CACHE_KEY.format(ds_id=ds_id), json.dumps(tables_payload, ensure_ascii=False),
             ex=SCHEMA_CACHE_TTL)

    for table_name, columns in columns_by_table.items():
        columns_payload = [
            {
                "column_name": col[1],
                "column_comment": col[2] or "",
                "data_type": col[3],
                "column_type": col[4],
                "is_nullable": 1 if col[5] == "YES" else 0,
                "is_primary_key": 1 if col[6] == "PRI" else 0,
                "is_unique": 1 if col[6] in ("PRI", "UNI") else 0,
                "column_default": None if col[7] is None else str(col[7])[:500],
                "char_max_length": int(col[8]) if col[8] is not None else None,
                "numeric_precision": int(col[9]) if col[9] is not None else None,
                "numeric_scale": int(col[10]) if col[10] is not None else None,
                "ordinal_position": int(col[11]),
                "extra": col[12] or "",
            }
            for col in columns
        ]
        pipe.set(COLUMNS_CACHE_KEY.format(ds_id=ds_id, table=table_name),
                 json.dumps(columns_payload, ensure_ascii=False), ex=SCHEMA_CACHE_TTL)

    for table_name, indexes in indexes_by_table.items():
        indexes_payload = [
            {
                "index_name": index_name,
                "is_unique": 0 if info["non_unique"] else 1,
                "is_primary": 1 if index_name == "PRIMARY" else 0,
                "column_names": info["columns"],
            }
            for index_name, info in indexes.items()
        ]
        pipe.set(INDEXES_CACHE_KEY.format(ds_id=ds_id, table=table_name),
                 json.dumps(indexes_payload, ensure_ascii=False), ex=SCHEMA_CACHE_TTL)

    # 清理已删除表的 Redis 缓存
    for table_name in removed_names:
        pipe.delete(COLUMNS_CACHE_KEY.format(ds_id=ds_id, table=table_name))
        pipe.delete(INDEXES_CACHE_KEY.format(ds_id=ds_id, table=table_name))

    pipe.execute()


def _notify_group(session, group_type: int, include_admins: bool, msg_type: str,
                  title: str, content: str, link_url: str, priority: int) -> None:
    """向指定分组全员（可选含管理员）发送通知（PRD 11.3 接收人规则）"""
    query = session.query(User).filter(User.status == 1)
    if include_admins:
        query = query.filter((User.group_type == group_type) | (User.group_type == 99))
    else:
        query = query.filter(User.group_type == group_type)
    for user in query.all():
        create_notification(
            session,
            user_id=user.id,
            msg_type=msg_type,
            title=title,
            content=content,
            link_url=link_url,
            priority=priority,
            group_type=user.group_type,
        )


def _do_sync(datasource_id: int) -> dict:
    """数据源同步核心逻辑（供 sync_datasource 与 scheduled_sync_all 复用）"""
    lock_key = SYNC_LOCK_KEY.format(ds_id=datasource_id)
    # Redis 分布式锁（SET NX EX 5min），已锁定则跳过
    if not sync_redis_client.set(lock_key, str(time.time()), nx=True, ex=SYNC_LOCK_TTL):
        logger.info("sync_locked_skip", datasource_id=datasource_id)
        return {"datasource_id": datasource_id, "status": "locked", "error": "同步任务正在进行中"}

    session = SyncSessionLocal()
    try:
        ds = session.get(Datasource, datasource_id)
        if ds is None:
            return {"datasource_id": datasource_id, "status": "failed", "error": "数据源不存在"}

        ds.status = DS_STATUS_SYNCING
        session.commit()
        log = logger.bind(datasource_id=datasource_id, datasource=ds.name)
        log.info("sync_datasource_start")

        try:
            engine = get_sync_engine(datasource_id)
            table_rows, columns_by_table, indexes_by_table = _collect_metadata(engine, ds.database_name)

            synced_at = datetime.now()
            diff = _persist_metadata(
                session, datasource_id, table_rows, columns_by_table, indexes_by_table, synced_at
            )
            # 更新数据源状态
            ds.status = DS_STATUS_NORMAL
            ds.last_sync_at = synced_at
            ds.table_count = len(table_rows)
            session.commit()

            # 刷新 Redis 缓存（失败不阻断，下次查询可回源 MySQL 缓存表）
            try:
                _refresh_redis_cache(
                    datasource_id, table_rows, columns_by_table, indexes_by_table,
                    synced_at, diff["removed_names"],
                )
            except Exception:  # noqa: BLE001
                log.warning("sync_redis_refresh_failed")

            # 同步完成通知（该数据源所属分组全员，PRD 11.3）
            _notify_group(
                session, ds.group_type, False,
                "DS_SYNC_DONE", "数据源同步完成",
                f"数据源「{ds.name}」同步完成：新增 {diff['added']} 张表，"
                f"更新 {diff['updated']} 张表，删除 {diff['removed']} 张表，"
                f"共缓存 {len(table_rows)} 张表。",
                "/datasources", 3,
            )
            session.commit()
            log.info("sync_datasource_done", tables=len(table_rows), **{k: diff[k] for k in ("added", "updated", "removed")})
            return {"datasource_id": datasource_id, "status": "success", "table_count": len(table_rows),
                    "added": diff["added"], "updated": diff["updated"], "removed": diff["removed"]}
        except Exception as exc:  # noqa: BLE001 — 同步失败需兜底记录并通知
            log.exception("sync_datasource_failed")
            session.rollback()
            # 更新数据源状态为异常
            ds = session.get(Datasource, datasource_id)
            if ds is not None:
                ds.status = DS_STATUS_ERROR
                session.commit()
                # 同步失败通知（分组全员 + 管理员，高优先级，PRD 11.3）
                _notify_group(
                    session, ds.group_type, True,
                    "DS_SYNC_FAILED", "数据源同步失败",
                    f"数据源「{ds.name}」同步失败：{str(exc)[:300]}",
                    "/datasources", 1,
                )
                session.commit()
            # 丢弃可能失效的连接池（密码变更/网络异常等）
            remove_sync_engine(datasource_id)
            return {"datasource_id": datasource_id, "status": "failed", "error": str(exc)[:500]}
    finally:
        session.close()
        # 释放分布式锁
        try:
            sync_redis_client.delete(lock_key)
        except Exception:  # noqa: BLE001
            logger.warning("sync_lock_release_failed", datasource_id=datasource_id)


@celery_app.task(bind=True, max_retries=0, acks_late=True, name="tasks.sync_datasource")
def sync_datasource(self, datasource_id: int) -> dict:
    """单个数据源表结构同步（手动「立即同步」/ 新增编辑后触发）"""
    logger.info("sync_datasource_task_start", datasource_id=datasource_id, celery_task_id=self.request.id)
    return _do_sync(datasource_id)


@celery_app.task(bind=True, max_retries=0, name="tasks.scheduled_sync_all")
def scheduled_sync_all(self) -> dict:
    """全量数据源定时同步（每天 02:00，范围：status=正常 的数据源，PRD 8.5）"""
    session = SyncSessionLocal()
    try:
        ids = [
            row[0] for row in session.query(Datasource.id)
            .filter(Datasource.status == DS_STATUS_NORMAL)
            .all()
        ]
    finally:
        session.close()
    logger.info("scheduled_sync_all_start", datasource_count=len(ids))
    results = [_do_sync(ds_id) for ds_id in ids]
    success = sum(1 for r in results if r.get("status") == "success")
    return {"total": len(ids), "success": success, "failed": len(ids) - success}


# ------------------------------------------------------------------
# 心跳检测
# ------------------------------------------------------------------

def _ping_datasource(datasource_id: int) -> bool:
    """对目标数据源执行轻量 SELECT 1 探活"""
    try:
        engine = get_sync_engine(datasource_id)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — 探活失败即离线
        return False


@celery_app.task(bind=True, max_retries=0, name="tasks.heartbeat_check")
def heartbeat_check(self) -> dict:
    """所有数据源连接状态心跳检测（每 30s，PRD 8.6）

    - 结果写 df:ds:status:{id}（online/offline，TTL 60s）
    - 连续 3 次失败写 DS_OFFLINE 通知（计数用 Redis，1 小时内不重复通知）
    - 互斥锁防止上一轮未结束时任务叠加
    """
    if not sync_redis_client.set(HEARTBEAT_LOCK_KEY, "1", nx=True, ex=60):
        return {"status": "skipped", "error": "上一轮心跳检测尚未结束"}
    try:
        session = SyncSessionLocal()
        try:
            datasources = session.query(Datasource).all()
        finally:
            session.close()

        online = offline = 0
        for ds in datasources:
            ok = _ping_datasource(ds.id)
            status_key = DS_STATUS_KEY.format(ds_id=ds.id)
            fail_count_key = DS_FAIL_COUNT_KEY.format(ds_id=ds.id)
            if ok:
                online += 1
                sync_redis_client.set(status_key, "online", ex=DS_STATUS_TTL)
                # 成功即清零失败计数与通知标记（恢复后允许再次通知）
                sync_redis_client.delete(fail_count_key)
                sync_redis_client.delete(DS_OFFLINE_NOTIFIED_KEY.format(ds_id=ds.id))
                continue

            offline += 1
            sync_redis_client.set(status_key, "offline", ex=DS_STATUS_TTL)
            fails = int(sync_redis_client.incr(fail_count_key))
            sync_redis_client.expire(fail_count_key, 300)
            logger.warning("heartbeat_failed", datasource_id=ds.id, datasource=ds.name, fails=fails)

            if fails >= HEARTBEAT_FAIL_THRESHOLD:
                # SET NX：1 小时内只通知一次，避免每 30s 重复告警
                notified = sync_redis_client.set(
                    DS_OFFLINE_NOTIFIED_KEY.format(ds_id=ds.id), "1", nx=True, ex=3600
                )
                if notified:
                    # 丢弃失效连接池，避免后续任务排队等待超时
                    remove_sync_engine(ds.id)
                    session = SyncSessionLocal()
                    try:
                        _notify_group(
                            session, ds.group_type, True,
                            "DS_OFFLINE", "数据源连接异常",
                            f"数据源「{ds.name}」已连续 {HEARTBEAT_FAIL_THRESHOLD} 次心跳检测失败，"
                            f"请检查数据库服务状态。",
                            "/datasources", 1,
                        )
                        session.commit()
                    finally:
                        session.close()
                    logger.error("ds_offline_notified", datasource_id=ds.id, datasource=ds.name)
        return {"status": "success", "online": online, "offline": offline}
    finally:
        sync_redis_client.delete(HEARTBEAT_LOCK_KEY)
