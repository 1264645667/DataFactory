"""数据源模块请求/响应 Schema。"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


def _is_redis(db_type: str) -> bool:
    return (db_type or "").strip().lower() == "redis"


class DatasourceCreateRequest(BaseModel):
    """新增数据源（MySQL / Redis）。

    Redis 约定：database_name 填 DB 索引（"0"~"15"），username 可空（ACL 用户），password 可空。
    """

    name: str = Field(min_length=1, max_length=50, description="全局唯一，不含特殊字符")
    db_type: str = Field(default="MySQL", description="MySQL / Redis")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=100)
    username: str = Field(default="", max_length=100)
    password: str = Field(default="", max_length=128, description="明文，后端 AES-256 加密存储")
    group_type: int = Field(description="1=销项组 2=申报组")
    remark: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check_by_type(self):
        if _is_redis(self.db_type):
            if not self.database_name.isdigit() or not 0 <= int(self.database_name) <= 15:
                raise ValueError("Redis 数据源的 database_name 须为 DB 索引（0~15）")
        else:
            if not self.username:
                raise ValueError("MySQL 数据源必须填写用户名")
            if not self.password:
                raise ValueError("MySQL 数据源必须填写密码")
        return self


class DatasourceUpdateRequest(BaseModel):
    """编辑数据源（密码不填则保持原密码）。"""

    name: str = Field(min_length=1, max_length=50)
    db_type: str = Field(default="MySQL")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=100)
    username: str = Field(default="", max_length=100)
    password: str | None = Field(default=None, max_length=128, description="留空表示不修改")
    group_type: int
    remark: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check_by_type(self):
        if _is_redis(self.db_type):
            if not self.database_name.isdigit() or not 0 <= int(self.database_name) <= 15:
                raise ValueError("Redis 数据源的 database_name 须为 DB 索引（0~15）")
        elif not self.username:
            raise ValueError("MySQL 数据源必须填写用户名")
        return self


class DatasourceTestRequest(BaseModel):
    """测试连接（表单页按钮，不保存）。"""

    db_type: str = Field(default="MySQL")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=100)
    username: str = Field(default="", max_length=100)
    password: str = Field(default="", max_length=128)


class DatasourceTestResponse(BaseModel):
    """测试连接结果。"""

    success: bool
    message: str
    db_version: str | None = Field(default=None, description="如 MySQL 8.0.x")


class DatasourceItem(BaseModel):
    """数据源列表项。"""

    id: int
    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    group_type: int
    status: int = Field(description="缓存状态：0=未初始化 1=正常 2=异常 3=同步中")
    online: bool | None = Field(default=None, description="连接状态（30s 心跳）")
    remark: str | None = None
    table_count: int | None = 0
    last_sync_at: datetime | None = None
    is_default: bool = Field(default=False, description="是否当前用户默认数据源")
    created_at: datetime


class DatasourceStatusResponse(BaseModel):
    """数据源连接状态（心跳）。"""

    datasource_id: int
    online: bool
    latency_ms: float | None = None
    error: str | None = None
    checked_at: datetime


class DatasourceSyncResponse(BaseModel):
    """手动触发表结构同步响应。"""

    datasource_id: int
    triggered: bool = Field(description="是否成功触发同步任务")
    message: str
