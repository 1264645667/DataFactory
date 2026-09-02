"""Nacos 配置中心客户端封装

支持启动拉取和热更新监听。全部操作容错降级：
Nacos 不可用时记录 WARNING 日志并返回空配置，不阻断服务启动
"""

from typing import Any, Callable

import structlog
import yaml

from app.config import settings

logger = structlog.get_logger()


class NacosConfigManager:
    """Nacos 配置中心客户端，支持启动拉取和热更新监听。"""

    def __init__(self) -> None:
        self._client: Any = None
        self._config_cache: dict[str, dict] = {}
        self._group = settings.NACOS_GROUP  # "datafactory_group"
        try:
            import nacos

            self._client = nacos.NacosClient(
                server_addresses=settings.NACOS_SERVER,
                namespace=settings.NACOS_NAMESPACE,
                username=settings.NACOS_USERNAME,
                password=settings.NACOS_PASSWORD,
            )
        except Exception as e:
            # SDK 初始化失败（如依赖未安装、参数错误）不阻断启动
            logger.warning("nacos_client_init_failed", error=str(e))

    def get_config(self, data_id: str) -> dict[str, Any]:
        """拉取配置，返回解析后的字典；失败返回空字典（降级）。"""
        if self._client is None:
            return {}
        try:
            raw = self._client.get_config(data_id, self._group, timeout=5)
        except Exception as e:
            logger.warning("nacos_config_pull_failed", data_id=data_id, error=str(e))
            return {}
        if not raw:
            logger.warning("nacos_config_empty", data_id=data_id)
            return {}
        parsed = yaml.safe_load(raw) or {}
        self._config_cache[data_id] = parsed
        return parsed

    def add_listener(self, data_id: str, callback: Callable[[dict], None]) -> None:
        """注册配置变更监听（热更新）；注册失败仅告警。"""
        if self._client is None:
            return

        def _on_change(tenant: str, group: str, data_id: str, content: str) -> None:
            try:
                new_config = yaml.safe_load(content) if content else {}
                self._config_cache[data_id] = new_config
                logger.info("nacos_config_updated", data_id=data_id)
                callback(new_config)
            except Exception as e:
                logger.warning(
                    "nacos_config_watch_failed", data_id=data_id, error=str(e)
                )

        try:
            self._client.add_config_watcher(data_id, self._group, _on_change)
        except Exception as e:
            logger.warning("nacos_add_watcher_failed", data_id=data_id, error=str(e))

    def get_cached(self, data_id: str) -> dict[str, Any]:
        """获取本地缓存的配置副本。"""
        return self._config_cache.get(data_id, {})


# 全局配置管理器单例
nacos_config = NacosConfigManager()
