"""DataForge 造数引擎核心包

包含：动态连接池(db_pool)、策略引擎(strategies)、数据生成器(data_generator)、
依赖分析(dep_analyzer)、单 Case 执行器(executor)、场景 DAG 调度器(scene_executor)。

说明：各模块按需直接 import 子模块，此处不做顶层 re-export，
避免与 app.celery_app 产生 import 顺序耦合。
"""
