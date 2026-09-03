"""临时清理：E2E 测试残留（e2e- 前缀的 Case/任务/日志/数据源 + db10 的 e2e Key）"""
import sys
sys.path.insert(0, ".")

import redis
from sqlalchemy import create_engine, text

from app.config import settings

e = create_engine(settings.SYNC_DATABASE_URL)
with e.begin() as c:
    tids = [r[0] for r in c.execute(
        text("SELECT id FROM df_exec_task WHERE case_name LIKE 'e2e-%'")
    ).all()]
    for tid in tids:
        c.execute(text("DELETE FROM df_exec_rollback_log WHERE task_id = :t"), {"t": tid})
        c.execute(text("DELETE FROM df_exec_batch_log WHERE task_id = :t"), {"t": tid})
    c.execute(text("DELETE FROM df_exec_task WHERE case_name LIKE 'e2e-%'"))
    c.execute(text("DELETE FROM df_case WHERE case_name LIKE 'e2e-%'"))
    dsids = [r[0] for r in c.execute(
        text("SELECT id FROM df_datasource WHERE name LIKE 'e2e-%'")
    ).all()]
    for d in dsids:
        for t in ("df_table_cache", "df_column_cache", "df_index_cache"):
            c.execute(text(f"DELETE FROM {t} WHERE datasource_id = :d"), {"d": d})
    c.execute(text("DELETE FROM df_datasource WHERE name LIKE 'e2e-%'"))
    print("cleaned tasks:", len(tids), "datasources:", dsids)

r = redis.Redis(host="172.28.31.239", port=6379, password="baiwang", db=10, decode_responses=True)
left = list(r.scan_iter("e2e:*"))
if left:
    r.delete(*left)
print("redis db10 e2e keys cleaned:", len(left))
