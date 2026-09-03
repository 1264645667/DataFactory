"""E2E 验证脚本：Redis 数据源 + 纯 Redis 造数 + MySQL 联动 + 跨数据源关联 + 一键回滚

直接走 service 层（AsyncSession）+ 真实 Celery Worker 执行，验证：
1. Redis 数据源创建与连接测试
2. 纯 Redis Case 造数（per_row + single_key 两种模式）
3. MySQL Case Redis 联动（per_row 每行一个 Key）
4. 跨数据源 MySQL 关联（两个数据源条目指向同一物理库，验证 engine 分派）
5. 一键回滚（Redis Key + MySQL 行）

运行：.venv\Scripts\python.exe scripts\e2e_redis_multids.py
"""
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")  # backend/

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name} {detail}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def wait_task_done(task_no: str, timeout: int = 120) -> dict:
    """轮询 Redis 进度直到终态"""
    from app.core.redis_client import sync_redis_client
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = sync_redis_client.hgetall(f"df:task:progress:{task_no}")
        if raw and raw.get("status") in ("success", "failed", "partial_success", "aborted"):
            return raw
        time.sleep(1)
    raise TimeoutError(f"任务 {task_no} 超时未结束")


# 目标 Redis（db10，e2e 专用数据源指向）
import redis  # noqa: E402
target_redis = redis.Redis(host="172.28.31.239", port=6379, password="baiwang", db=10, decode_responses=True)


async def main() -> None:
    from app.schemas.datasource import DatasourceCreateRequest, DatasourceTestRequest
    from app.schemas.engine import (
        AssociationConfig, CaseConfig, EngineExecuteRequest, FieldConfig, RedisCaseConfig,
        RedisSyncConfig,
    )
    from app.services import datasource_service, engine_service, task_service
    from app.core.redis_client import sync_redis_client
    from sqlalchemy import text

    admin = User(id=1, username="popsicle", group_type=99, status=1)

    # 清理上次运行的残留（e2e 前缀 Key + 同名 Case，保证脚本幂等可重跑）
    old_keys = list(target_redis.scan_iter("e2e:*"))
    if old_keys:
        target_redis.delete(*old_keys)
    async with AsyncSessionLocal() as db0:
        await db0.execute(text("DELETE FROM df_case WHERE case_name LIKE 'e2e-%'"))
        await db0.commit()

    async with AsyncSessionLocal() as db:
        # ── 1. Redis 数据源 ──
        print("\n== 1. Redis 数据源创建 ==")
        from sqlalchemy import select
        from app.models.datasource import Datasource
        exist = (await db.execute(select(Datasource).where(Datasource.name == "e2e-redis"))).scalar_one_or_none()
        if exist:
            redis_ds_id = exist.id
        else:
            ds = await datasource_service.create_datasource(
                db, current_user=admin,
                req=DatasourceCreateRequest(
                    name="e2e-redis", db_type="Redis", host="172.28.31.239", port=6379,
                    database_name="10", username="", password="baiwang", group_type=1,
                ),
                ip=None,
            )
            redis_ds_id = ds.id
        check("redis 数据源创建", True, f"id={redis_ds_id}")

        test = await datasource_service.test_connection(DatasourceTestRequest(
            db_type="Redis", host="172.28.31.239", port=6379, database_name="10",
            username="", password="baiwang",
        ))
        check("redis 连接测试", test.success, test.message)

        # ── 2. 纯 Redis 造数（per_row：10 行 → 10 个 Key） ──
        print("\n== 2. 纯 Redis 造数 per_row ==")
        cfg = CaseConfig(
            case_type="redis",
            redis_config=RedisCaseConfig(
                key_template="e2e:user:{incr:1}",
                write_mode="per_row", data_type="json",
                field_configs=[
                    FieldConfig(column_name="id", data_type="varchar", column_type="varchar(64)",
                                strategy="UUID", strategy_params={}),
                    FieldConfig(column_name="score", data_type="int", column_type="int(11)",
                                strategy="INCR_FROM", strategy_params={"start": 1}),
                ],
                ttl_seconds=3600,
            ),
        )
        res = await engine_service.execute_case_config(
            db, current_user=admin,
            req=EngineExecuteRequest(case_name="e2e-redis-perrow", datasource_id=redis_ds_id,
                                     target_count=10, config=cfg),
            ip=None,
        )
        prog = wait_task_done(res.task_no)
        keys = [f"e2e:user:{i}" for i in range(1, 11)]
        vals = [target_redis.get(k) for k in keys]
        ok = prog.get("status") == "success" and all(vals) and len(set(vals)) == 10
        check("per_row 10行→10Key", ok, f"status={prog.get('status')} 命中={sum(1 for v in vals if v)}/10")

        # ── 3. 纯 Redis 造数（single_key：10 行 → 1 Key 10 成员） ──
        print("\n== 3. 纯 Redis 造数 single_key ==")
        cfg2 = CaseConfig(
            case_type="redis",
            redis_config=RedisCaseConfig(
                key_template="e2e:users:{task_no}",
                write_mode="single_key", data_type="list",
                field_configs=[
                    FieldConfig(column_name="name", data_type="varchar", column_type="varchar(32)",
                                strategy="RANDOM_FIXED_LEN", strategy_params={"length": 6}),
                ],
            ),
        )
        res2 = await engine_service.execute_case_config(
            db, current_user=admin,
            req=EngineExecuteRequest(case_name="e2e-redis-singlekey", datasource_id=redis_ds_id,
                                     target_count=10, config=cfg2),
            ip=None,
        )
        prog2 = wait_task_done(res2.task_no)
        agg_key = f"e2e:users:{res2.task_no}"
        members = []
        for _ in range(10):  # 可见性轮询（高延迟网络下进度与数据可见性可能有秒级差）
            members = target_redis.lrange(agg_key, 0, -1)
            if members:
                break
            time.sleep(1)
        check("single_key 10行→1Key10成员", prog2.get("status") == "success" and len(members) == 10,
              f"status={prog2.get('status')} 成员={len(members)}")

        # ── 4. 回滚纯 Redis Case（per_row 任务） ──
        print("\n== 4. 回滚 Redis 任务 ==")
        await task_service.rollback_task(db, current_user=admin, task_no=res.task_no, ip=None)
        deadline = time.time() + 120
        from app.models.task import ExecTask
        t = None
        while time.time() < deadline:
            await db.rollback()
            t = (await db.execute(select(ExecTask).where(ExecTask.task_no == res.task_no))).scalar_one()
            if t.rollback_status in (2, 3):
                break
            time.sleep(2)
        left = [k for k in keys if target_redis.exists(k)]
        check("redis 任务回滚", bool(t and t.rollback_status == 2) and not left,
              f"rollback_status={t.rollback_status if t else '?'} 残留Key={len(left)}")

        # ── 5. 跨数据源关联 + MySQL→Redis 联动 ──
        print("\n== 5. 跨数据源关联 + Redis 联动 ==")
        # 注册第二个指向同一物理库的数据源（验证多 engine 分派）
        exist2 = (await db.execute(select(Datasource).where(Datasource.name == "e2e-mysql-dup"))).scalar_one_or_none()
        if exist2:
            ds2_id = exist2.id
        else:
            src = await db.get(Datasource, 1)
            ds2 = Datasource(
                name="e2e-mysql-dup", db_type="MySQL", host=src.host, port=src.port,
                database_name=src.database_name, username=src.username, password=src.password,
                group_type=src.group_type, status=1, table_count=0, created_by=1,
            )
            db.add(ds2)
            await db.flush()
            ds2_id = ds2.id
            # 复制表结构缓存到 ds2（跨数据源取列依赖缓存）
            await db.execute(text(
                "INSERT INTO df_table_cache (datasource_id, table_name, table_comment, table_rows,"
                " column_count, pk_type, unique_index_count, synced_at)"
                " SELECT :new_ds, table_name, table_comment, table_rows, column_count, pk_type,"
                " unique_index_count, synced_at FROM df_table_cache WHERE datasource_id = 1"
            ), {"new_ds": ds2_id})
            await db.execute(text(
                "INSERT INTO df_column_cache (datasource_id, table_name, column_name, column_comment,"
                " data_type, column_type, is_nullable, is_primary_key, is_unique, column_default,"
                " char_max_length, numeric_precision, numeric_scale, ordinal_position, extra, synced_at)"
                " SELECT :new_ds, table_name, column_name, column_comment, data_type, column_type,"
                " is_nullable, is_primary_key, is_unique, column_default, char_max_length,"
                " numeric_precision, numeric_scale, ordinal_position, extra, synced_at"
                " FROM df_column_cache WHERE datasource_id = 1"
            ), {"new_ds": ds2_id})
            await db.commit()

        # 选两张已同步的表做主从关联（主表 ds1，关联表 ds2）
        tables = (await db.execute(text(
            "SELECT table_name FROM df_table_cache WHERE datasource_id = 1 ORDER BY table_name LIMIT 5"
        ))).scalars().all()
        print("  可用表:", tables)
        assert len(tables) >= 2, "数据源1至少需要2张已同步表"
        t_main, t_rel = tables[0], tables[1]

        # 用后端推断策略构建主表字段配置（与前端一致，避免 DEFAULT 策略填错类型）
        from app.services.engine_service import get_table_columns
        cols_main_info = await get_table_columns(db, current_user=admin, datasource_id=1, table_name=t_main)
        cols_rel_info = await get_table_columns(db, current_user=admin, datasource_id=ds2_id, table_name=t_rel)

        # 关联列：主表选 varchar 非自增非唯一列，目标表选同类型非自增非唯一列（保证 5 行同值不冲突）
        src_c = next((c for c in cols_main_info
                      if c.data_type in ("varchar", "char") and not c.is_unique
                      and "auto_increment" not in (c.extra or "")), None)
        tgt_c = next((c for c in cols_rel_info
                      if c.data_type in ("varchar", "char") and not c.is_unique
                      and "auto_increment" not in (c.extra or "")), None)
        assert src_c and tgt_c, "找不到兼容关联列"
        print(f"  关联: {t_main}.{src_c.column_name}(ds1) -> {t_rel}.{tgt_c.column_name}(ds2)")

        main_fields = [
            FieldConfig(
                column_name=c.column_name, data_type=c.data_type, column_type=c.column_type,
                is_nullable=bool(c.is_nullable), is_primary_key=bool(c.is_primary_key),
                strategy=("CUSTOM_VALUE" if c.column_name == src_c.column_name
                          else (c.suggested_strategy or "DEFAULT")),
                strategy_params=({"value": "E2E-LINK-001"} if c.column_name == src_c.column_name
                                 else (c.suggested_params or {})),
            )
            for c in cols_main_info
        ]
        cfg3 = CaseConfig(
            main_table=t_main,
            field_configs=main_fields,
            associations=[AssociationConfig(source_column=src_c.column_name, target_table=t_rel,
                                            target_column=tgt_c.column_name)],
            table_datasources={t_rel: ds2_id},
            redis_syncs=[RedisSyncConfig(
                name="e2e联动", datasource_id=redis_ds_id,
                key_template=f"e2e:link:{t_main}:{{{t_main}.{src_c.column_name}}}:{{incr}}",
                write_mode="per_row", data_type="string",
                fields=[f"{t_main}.{src_c.column_name}"],
                ttl_seconds=600,
            )],
        )
        res3 = await engine_service.execute_case_config(
            db, current_user=admin,
            req=EngineExecuteRequest(case_name="e2e-multids-link", datasource_id=1,
                                     target_count=5, config=cfg3),
            ip=None,
        )
        prog3 = wait_task_done(res3.task_no)
        # 校验：关联表行数 +5（经 ds2 引擎写入）；redis 联动 5 个 Key
        from app.engine.db_pool import get_sync_engine
        eng2 = get_sync_engine(ds2_id)
        with eng2.connect() as conn:
            rel_cnt = conn.execute(
                text(f"SELECT COUNT(*) FROM `{t_rel}` WHERE `{tgt_c.column_name}` = 'E2E-LINK-001'")
            ).scalar()
        # 等联动最终可见（写 Redis 在批次成功后同步执行，进度终态略早于可见性轮询）
        link_keys = []
        for _ in range(10):
            link_keys = [k for k in target_redis.scan_iter(f"e2e:link:{t_main}:*")]
            if link_keys:
                break
            time.sleep(1)
        check("跨数据源关联写入", prog3.get("status") == "success" and rel_cnt == 5,
              f"status={prog3.get('status')} 关联表新增行数={rel_cnt}")
        check("MySQL→Redis 联动", len(link_keys) == 5, f"联动Key数={len(link_keys)}")

        # ── 6. 回滚 MySQL 跨数据源任务（含联动 Key） ──
        print("\n== 6. 回滚 MySQL 任务（跨数据源 + 联动） ==")
        from app.models.task import ExecRollbackLog
        task3_id = (await db.execute(
            select(ExecTask.id).where(ExecTask.task_no == res3.task_no)
        )).scalar_one()
        rb_logs = (await db.execute(
            select(ExecRollbackLog).where(ExecRollbackLog.task_id == task3_id)
        )).scalars().all()
        print(f"  回滚日志: {[(l.target_type, l.table_name, l.row_count) for l in rb_logs]}")
        if rb_logs:
            await task_service.rollback_task(db, current_user=admin, task_no=res3.task_no, ip=None)
            deadline = time.time() + 120
            t3 = None
            while time.time() < deadline:
                await db.rollback()
                t3 = (await db.execute(select(ExecTask).where(ExecTask.task_no == res3.task_no))).scalar_one()
                if t3.rollback_status in (2, 3):
                    break
                time.sleep(2)
            left_keys = [k for k in target_redis.scan_iter(f"e2e:link:{t_main}:*")]
            with eng2.connect() as conn:
                rel_left = conn.execute(
                    text(f"SELECT COUNT(*) FROM `{t_rel}` WHERE `{tgt_c.column_name}` = 'E2E-LINK-001'")
                ).scalar()
            from app.engine.db_pool import get_sync_engine as _gse
            with _gse(1).connect() as conn:
                main_left = conn.execute(
                    text(f"SELECT COUNT(*) FROM `{t_main}` WHERE `{src_c.column_name}` = 'E2E-LINK-001'")
                ).scalar()
            ok = (t3 and t3.rollback_status == 2 and not left_keys and rel_left == 0 and main_left == 0)
            check("MySQL 任务回滚", bool(ok),
                  f"rollback_status={t3.rollback_status if t3 else '?'} 残留联动Key={len(left_keys)}"
                  f" 主表残留={main_left} 关联表残留={rel_left}")
        else:
            check("MySQL 任务回滚", False, "无回滚日志（主键采集失败）")

        # 清理聚合 Key
        target_redis.delete(agg_key)

    print(f"\n===== E2E 结果: PASS={PASS} FAIL={FAIL} =====")
    sys.exit(1 if FAIL else 0)


asyncio.run(main())
