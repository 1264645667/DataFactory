"""Nacos 配置加载器（架构文档 8.5.2）。

应用启动时统一拉取所有 Nacos 配置并注册热更新监听；
Nacos 不可用时降级使用代码默认值，不阻断启动（文档 8.7）。
"""

import structlog

from app.config import settings
from app.core.nacos_client import nacos_config

logger = structlog.get_logger()


class RuntimeConfig:
    """运行时动态配置对象（Nacos 热更新会修改此对象的属性）。"""

    celery_batch_size: int = 3000
    celery_max_workers: int = 8
    log_level: str = "INFO"
    datasync_heartbeat_interval: int = 30
    # ... 其他可热更新参数按需扩展


# 全局运行时配置单例
runtime_config = RuntimeConfig()

# 启动时需拉取的配置项（统一单文件，与 Nacos 控制台 Data ID 对应）
_DATA_ID = settings.NACOS_DATA_ID  # popsicle_datafactory_config


def load_nacos_configs() -> None:
    """应用启动时统一拉取 Nacos 配置（降级不阻断）。"""
    try:
        cfg = nacos_config.get_config(_DATA_ID)
        logger.info("nacos_config_loaded", data_id=_DATA_ID)
    except Exception as e:
        # Nacos 不可用时降级使用环境变量/代码默认值，不阻断启动
        logger.warning("nacos_config_load_failed", data_id=_DATA_ID, error=str(e))
        cfg = {}

    # 将启动拉取的配置应用到运行时对象
    _on_config_change(cfg)

    # 注册热更新监听（容错）
    try:
        nacos_config.add_listener(_DATA_ID, _on_config_change)
    except Exception as e:
        logger.warning("nacos_listener_register_failed", error=str(e))


def _on_config_change(new_config: dict) -> None:
    """Nacos 配置统一热更新回调。"""
    if not new_config:
        return
    executor = new_config.get("executor", {})
    if executor:
        runtime_config.celery_batch_size = executor.get("default_batch_size", 3000)
        runtime_config.celery_max_workers = executor.get("max_workers", 8)
    log_cfg = new_config.get("log", {})
    if log_cfg:
        runtime_config.log_level = log_cfg.get("level", "INFO")
    datasync = new_config.get("datasync", {})
    if datasync:
        runtime_config.datasync_heartbeat_interval = datasync.get("heartbeat_interval", 30)
    logger.info("nacos_config_applied", config=new_config)
