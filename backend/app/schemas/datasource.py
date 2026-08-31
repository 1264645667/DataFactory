"""数据源模块请求/响应 Schema（API 清单 10.3 + PRD 第 8 章）。"""

from datetime import datetime

from pydantic import BaseModel, Field


class DatasourceCreateRequest(BaseModel):
    """新增数据源（PRD 8.3 表单校验规则）。"""

    name: str = Field(min_length=1, max_length=50, description="全局唯一，不含特殊字符")
    db_type: str = Field(default="MySQL", description="一期仅支持 MySQL")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128, description="明文，后端 AES-256 加密存储")
    group_type: int = Field(description="1=销项组 2=申报组")
    remark: str | None = Field(default=None, max_length=500)


class DatasourceUpdateRequest(BaseModel):
    """编辑数据源（密码不填则保持原密码）。"""

    name: str = Field(min_length=1, max_length=50)
    db_type: str = Field(default="MySQL")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=100)
    password: str | None = Field(default=None, max_length=128, description="留空表示不修改")
    group_type: int
    remark: str | None = Field(default=None, max_length=500)


class DatasourceTestRequest(BaseModel):
    """测试连接（表单页按钮，不保存）。"""

    db_type: str = Field(default="MySQL")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)


class DatasourceTestResponse(BaseModel):
    """测试连接结果。"""

    success: bool
    message: str
    db_version: str | None = Field(default=None, description="如 MySQL 8.0.x")


class DatasourceItem(BaseModel):
    """数据源列表项（PRD 8.2.1 表格列）。"""

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
