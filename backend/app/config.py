"""应用配置（pydantic-settings）。

配置优先级
1. 环境变量（秘钥、连接串等不可热更新的敏感配置）
2. Nacos 配置中心（可热更新的业务参数，见 app/core/config_loader.py）
3. 代码内默认值（最终兜底）
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置单例。所有字段均可通过同名环境变量覆盖。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 应用基础 ─────────────────────────────────────────────
    APP_NAME: str = "DataForge"
    APP_VERSION: str = "1.0.0"
    ENV: str = "development"  # development / production
    LOG_LEVEL: str = "INFO"
    TZ: str = "Asia/Shanghai"

    # ── 系统数据库（异步驱动 aiomysql，FastAPI 请求链路）────────
    # 生产/联调环境默认指向公司 MySQL，可用 DATABASE_URL 环境变量覆盖
    # 注意：MySQL 密码 QY20Lsf%!PLfM25Ts! 含特殊字符，需 URL 编码（quote_plus）后才能放入连接串
    DATABASE_URL: str = "mysql+aiomysql://popsicle:QY20Lsf%25%21PLfM25Ts%21@172.28.30.59:3306/data_factory"

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Celery 同步任务 / Alembic 迁移使用的同步连接串（pymysql 驱动）。"""
        return self.DATABASE_URL.replace("+aiomysql", "+pymysql")

    # ── Redis ────────────────────────────────────────────────
    REDIS_URL: str = "redis://:baiwang@172.28.31.239:6379/3"

    # ── 密钥（生产环境必须通过环境变量注入）─────────
    # JWT 签名密钥，至少 32 位随机字符串
    SECRET_KEY: str = "dataforge-dev-secret-key-change-me-in-production"
    # AES-256 密钥：base64 编码的 32 字节（数据源密码加密用）
    AES_KEY: str = ""

    # ── JWT（7 天有效，支持主动失效）─────────────────
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 7

    # ── 登录失败锁定（同一用户名连续失败 5 次锁定 10 分钟）─
    LOGIN_FAIL_MAX_TIMES: int = 5
    LOGIN_FAIL_LOCK_SECONDS: int = 600  # 10 分钟

    # ── Nacos──────────────────────────────────
    NACOS_SERVER: str = "localhost:8848"
    NACOS_NAMESPACE: str = ""  # 留空 = public 命名空间
    NACOS_GROUP: str = "datafactory_group"  # 配置分组，与控制台创建的 Group 保持一致
    NACOS_USERNAME: str = "nacos"
    NACOS_PASSWORD: str = "nacos"
    # Nacos 中统一的业务配置 Data ID
    NACOS_DATA_ID: str = "popsicle_datafactory_config"

    # ── 系统 DB 连接池────────────────────────────
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # ── 目标数据源动态连接池───────────────────────
    TARGET_DS_POOL_SIZE: int = 5
    TARGET_DS_MAX_OVERFLOW: int = 5
    TARGET_DS_POOL_TIMEOUT: int = 30
    TARGET_DS_POOL_RECYCLE: int = 1800

    # ── 造数执行器参数────────────
    MAX_WORKERS: int = 8  # 并发线程数（千万级建议 16）
    BATCH_SIZE_OVERRIDE: int | None = None  # None = 自动计算
    BATCH_MAX_RETRY: int = 3  # 单批次最大重试次数
    FAIL_RATE_THRESHOLD: float = 0.5  # 失败率超过此值停止任务
    ITERATE_PARALLEL_ROUNDS: bool = False  # ITERATE_LIST 是否并发执行各轮
    AUTO_SPLIT_THRESHOLD: int = 10_000_000  # 超过此条数自动分片（条/表）
    DISABLE_UNIQUE_CHECKS: bool = False  # 是否临时关闭唯一索引检查
    DISABLE_FK_CHECKS: bool = False  # 是否临时关闭外键检查

    # ── CORS（默认值见 dataforge-common.yaml，启动时注册不可热更新）─
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        """逗号分隔的 CORS 白名单转列表。"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


# 全局配置单例
settings = Settings()
