# DataForge 造数工厂 — 架构设计文档

**版本：** V1.1（一期）

**更新日期：** 2026-09

**变更记录：**

| 版本 | 日期      | 变更内容                                                                                                                                                                            |
|------|---------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| V1.0 | 2026-08 | 初稿,分析系统代码生成                                                                                                                                                                     |
| V1.1 | 2026-09 | 4.2 config_json 新增 `related_field_configs`（关联表字段策略覆盖）与 `associations[].source_table`（多级关联）；6.3 策略注册表新增 DERIVED/TOOL_GEN 并补充 Worker 重启注意事项；新增 6.10 多级关联执行与关联表字段策略覆盖（含表操作量 Top10 统计口径） |

---

## 目录

1. [整体架构概览](#1-整体架构概览)
2. [后端技术栈（Python）](#2-后端技术栈python)
3. [前端技术栈](#3-前端技术栈)
4. [数据库设计](#4-数据库设计)
5. [Redis 缓存设计](#5-redis-缓存设计)
6. [关键技术方案](#6-关键技术方案)
7. [部署架构（Docker）](#7-部署架构docker)
8. [Nacos 集成方案](#8-nacos-集成方案)
9. [目录结构](#9-目录结构)
10. [API 路由清单](#10-api-路由清单)
11. [数据库索引策略与查询优化](#11-数据库索引策略与查询优化)
12. [连接数规划与资源预算](#12-连接数规划与资源预算)
13. [数据库迁移策略（Alembic）](#13-数据库迁移策略alembic)
14. [密钥管理与 AES 密钥轮换](#14-密钥管理与-aes-密钥轮换)

---

## 1. 整体架构概览

### 1.1 系统分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          客户端层                                     │
│              Vue 3 + TypeScript（浏览器 SPA）                         │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTPS（HTTP 轮询，无 WebSocket）
┌───────────────────────────▼─────────────────────────────────────────┐
│                          网关层                                       │
│                    Nginx（反向代理 + 静态资源）                         │
└──────────────┬────────────────────────────┬────────────────────────┘
               │ /api/*                      │ /api/v1/ai/*
┌──────────────▼──────────────┐  ┌──────────▼────────────────────────┐
│       业务 API 服务           │  │        AI 对外接口服务              │
│   FastAPI（Python 3.11+）    │  │   FastAPI AI Router（同进程）       │
│   JWT 认证 + RBAC 权限        │  │   API Key 认证                    │
└──────────────┬──────────────┘  └──────────┬────────────────────────┘
               │                             │
┌──────────────▼─────────────────────────────▼────────────────────────┐
│                         服务层（Service）                              │
│  用户服务 | 数据源服务 | 造数引擎服务 | Case服务 | 场景服务 | 总览服务 | 工具服务 │
└──────┬──────────┬──────────┬──────────────┬──────────────┬──────────┘
       │          │          │              │              │
┌──────▼──┐ ┌────▼────┐ ┌───▼──────┐ ┌────▼────┐ ┌───────▼──────────┐
│  MySQL  │ │  Redis  │ │  Celery  │ │动态连接池│ │  本地缓存DB表      │
│（系统DB）│ │（缓存）  │ │（异步任务）│ │（目标DB）│ │(df_table_cache等)│
└─────────┘ └─────────┘ └──────────┘ └─────────┘ └──────────────────┘
```

### 1.2 核心组件职责

| 组件 | 技术选型 | 职责 |
|------|----------|------|
| API 服务 | FastAPI | 处理所有 HTTP 请求，JWT 认证，业务逻辑编排 |
| 异步任务 | Celery + Redis Broker | 造数执行、数据源同步、心跳检测、消息生成 |
| 任务调度 | Celery Beat | 定时同步数据源（凌晨02:00）、心跳检测（30s）、消息清理（凌晨03:00） |
| 系统数据库 | MySQL 8.0 | 存储用户、Case、执行记录、表结构缓存、消息通知等系统数据 |
| 缓存 | Redis 7.x | 表结构缓存、任务进度、会话黑名单、分布式锁、消息未读计数 |
| 动态连接池 | SQLAlchemy | 按需创建并管理各目标数据源的连接池 |
| 前端 | Vue 3 + Vite | SPA，通过 Nginx 托管静态资源；进度监控采用 HTTP 轮询（非 WebSocket） |
| 反向代理 | Nginx | 静态资源服务 + API 反向代理 + HTTPS 终止 |
| 配置中心 | Nacos | 集中管理业务参数配置，支持热更新；服务注册与健康感知 |

> **进度监控方案说明（A5 澄清）：** 一期任务进度监控统一采用 HTTP 轮询（前端每 2 秒调用 `GET /api/v1/tasks/{task_no}/progress`），不引入 WebSocket。选择轮询的原因：①实现简单，运维无额外负担；②造数任务时效性要求为秒级，2 秒延迟可接受；③轮询在负载均衡多副本场景下无状态亲和性问题。若二期需要毫秒级推送，可引入 SSE（Server-Sent Events）替代，成本低于 WebSocket。

### 1.3 请求链路示意（以执行造数为例）

```
前端点击「创建并执行」
    │
    ▼
POST /api/v1/engine/execute  →  FastAPI Router
    │
    ▼
AuthMiddleware（验证 JWT + 检查 ENGINE:EXECUTE 权限）
    │
    ▼
EngineService.create_and_execute(config, user)
    ├── 参数校验
    ├── 保存 df_case（MySQL）
    ├── 创建 df_exec_task（MySQL，status=待执行）
    └── celery_app.send_task('execute_data_gen', task_id)
            │
            ▼  （异步，立即返回 task_no 给前端）
    Celery Worker
    ├── 构建插入依赖图
    ├── 初始化 Redis 自增计数器
    ├── ThreadPoolExecutor 并发执行批次
    │       └── 每批：生成数据 → bulk INSERT → 更新 Redis 进度
    │               ├── HINCRBY df:task:progress:{task_no} success_total +batch_size
    │               ├── HSET df:task:table_progress:{task_no} {table} {...新进度...}
    │               ├── RPUSH df:task:rate:{task_no}:{table} "{timestamp}:{batch_size}"
    │               └── HSET df:task:progress:{task_no} updated_at {now}
    └── 完成后更新 MySQL 任务状态

前端轮询 GET /api/v1/tasks/{task_no}/progress
    └── 读 Redis:
        ├── df:task:progress:{task_no}              → 整体进度
        ├── df:task:table_progress:{task_no}        → 各表进度
        └── df:task:rate:{task_no}:{table_name}     → 各表插入速率（滑动窗口）
    └── 聚合计算 预计剩余时间 = 剩余条数 / 整体速率
    └── 返回完整进度 JSON 给前端（前端每 2 秒轮询一次）
```

---

## 2. 后端技术栈（Python）

### 2.1 技术选型总表

| 分类 | 技术 | 版本 | 选型理由 |
|------|------|------|----------|
| Web 框架 | **FastAPI** | 0.111+ | 原生异步、自动 OpenAPI 文档、类型系统完善、性能优秀 |
| Python 运行时 | CPython | 3.11+ | 性能提升（比3.9快25%）、更好的错误信息 |
| ORM | **SQLAlchemy 2.x** | 2.0+ | 异步支持（async session）、类型安全、连接池管理 |
| DB 驱动 | **aiomysql** | 0.2+ | 纯异步 MySQL 驱动，配合 SQLAlchemy async |
| 数据校验 | **Pydantic v2** | 2.x | FastAPI 原生集成，比 v1 性能提升 5-50x |
| 异步任务 | **Celery** | 5.3+ | 成熟稳定，支持任务重试、优先级队列、监控 |
| 任务 Broker | **Redis** | 7.x | 同时作为 Broker 和 Result Backend，减少中间件 |
| 任务调度 | **Celery Beat** | 内置 | 定时任务，与 Celery 无缝集成 |
| 缓存客户端 | **redis-py** (async) | 5.x | 官方异步客户端，连接池管理 |
| 认证 | **python-jose** | 3.x | JWT 生成与校验 |
| 密码哈希 | **passlib[bcrypt]** | 1.7+ | bcrypt 算法，安全可靠 |
| 加密 | **cryptography** | 42+ | AES-256 加密数据库密码 |
| HTTP 客户端 | **httpx** | 0.27+ | 异步 HTTP，用于心跳检测等 |
| 日志 | **structlog** | 24+ | 结构化 JSON 日志，比 logging 更灵活 |
| 配置管理 | **pydantic-settings** | 2.x | 环境变量管理，类型安全 |
| 数据库迁移 | **Alembic** | 1.13+ | SQLAlchemy 官方迁移工具 |
| 依赖注入 | FastAPI 内置 DI | — | 无需额外框架 |
| API 文档 | Swagger UI / ReDoc | 内置 | FastAPI 自动生成 |
| 测试框架 | **pytest + pytest-asyncio** | — | 异步测试支持 |
| 代码规范 | **ruff** | 0.4+ | 极速 linter + formatter（替代 flake8+black） |
| 类型检查 | **mypy** | 1.x | 静态类型检查 |

### 2.2 FastAPI 应用结构设计

#### 2.2.1 应用工厂模式

```python
# app/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：初始化 DB 连接池、Redis 连接池、Celery 检查
    await startup()
    yield
    # 关闭时：优雅释放资源
    await shutdown()

def create_app() -> FastAPI:
    app = FastAPI(
        title="DataForge API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )
    # 注册中间件
    app.add_middleware(CORSMiddleware, ...)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(TraceIDMiddleware)   # 注入 trace_id
    # 注册路由
    app.include_router(auth_router,       prefix="/api/v1/auth")
    app.include_router(user_router,       prefix="/api/v1/users")
    app.include_router(datasource_router, prefix="/api/v1/datasources")
    app.include_router(engine_router,     prefix="/api/v1/engine")
    app.include_router(case_router,       prefix="/api/v1/cases")
    app.include_router(scene_router,      prefix="/api/v1/scenes")    # 场景管理
    app.include_router(task_router,       prefix="/api/v1/tasks")
    app.include_router(tool_router,       prefix="/api/v1/tools")
    app.include_router(overview_router,   prefix="/api/v1/overview")
    app.include_router(ai_router,         prefix="/api/v1/ai")   # AI 预留
    return app
```

#### 2.2.2 统一响应格式

```python
# app/schemas/response.py
from pydantic import BaseModel
from typing import TypeVar, Generic, Optional

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    code: int = 0             # 0=成功，非0=失败
    message: str = "success"
    data: Optional[T] = None
    trace_id: Optional[str] = None

class PageData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
```

#### 2.2.3 权限控制依赖

```python
# app/dependencies/auth.py
from fastapi import Depends, HTTPException
from app.core.security import verify_jwt

def require_permission(permission: str):
    """权限装饰器工厂"""
    async def _check(current_user = Depends(get_current_user)):
        if not current_user.has_permission(permission):
            raise HTTPException(status_code=403, detail="无操作权限")
        return current_user
    return _check

# 使用示例
@router.post("/execute")
async def execute_case(
    body: ExecuteRequest,
    user = Depends(require_permission("ENGINE:EXECUTE"))
):
    ...
```

### 2.3 Celery 任务设计

#### 2.3.1 任务队列规划

```python
# 三个优先级队列
CELERY_TASK_ROUTES = {
    "tasks.execute_data_gen":   {"queue": "high"},     # 造数执行，高优先
    "tasks.sync_datasource":    {"queue": "normal"},   # 数据源同步
    "tasks.heartbeat_check":    {"queue": "low"},      # 心跳检测
    "tasks.scheduled_sync":     {"queue": "low"},      # 定时同步
}
```

#### 2.3.2 造数执行任务核心逻辑

```python
# tasks/execute_task.py
@celery_app.task(
    bind=True,
    max_retries=0,           # 任务级不重试，内部批次级重试
    acks_late=True,          # 消费后再 ack，防止 Worker 崩溃丢任务
    track_started=True,
)
def execute_data_gen(self, task_id: int):
    task = db.get(ExecTask, task_id)
    config = parse_case_config(task.case_snapshot)

    # 1. 分析关联依赖，拓扑排序确定插入顺序
    insert_order = topological_sort(config.associations)

    # 2. 初始化 Redis 自增计数器（INCR_FROM 策略用）
    init_incr_counters(task_id, config)

    # 3. 计算批次
    batch_size = calc_batch_size(task.target_count)  # 动态批次大小
    batches = list(range(0, task.target_count, batch_size))

    # 4. 多线程并发执行
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(execute_batch, task_id, batch_no, config, offset)
            for batch_no, offset in enumerate(batches)
        ]
        for future in as_completed(futures):
            result = future.result()
            # 更新 Redis 实时进度
            update_redis_progress(task_id, result)

    finalize_task(task_id)
```

#### 2.3.3 Celery Beat 定时任务

```python
# tasks/scheduled.py
CELERYBEAT_SCHEDULE = {
    # 每天凌晨 02:00 同步所有数据源表结构
    "sync-all-datasources": {
        "task": "tasks.scheduled_sync_all",
        "schedule": crontab(hour=2, minute=0),
    },
    # 每 30 秒心跳检测所有数据源连接状态
    "heartbeat-check": {
        "task": "tasks.heartbeat_check",
        "schedule": 30.0,
    },
}
```

### 2.4 动态多数据源连接池管理

这是本系统最关键的技术点之一：

```python
# app/core/dynamic_pool.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from cryptography.fernet import Fernet

class DynamicConnectionPool:
    """按需创建、缓存、管理各目标数据源的连接池"""

    _engines: dict[int, AsyncEngine] = {}
    _lock = asyncio.Lock()

    async def get_engine(self, datasource_id: int) -> AsyncEngine:
        if datasource_id not in self._engines:
            async with self._lock:
                # double-check
                if datasource_id not in self._engines:
                    ds = await get_datasource(datasource_id)
                    password = decrypt_aes(ds.password)
                    url = f"mysql+aiomysql://{ds.username}:{password}@{ds.host}:{ds.port}/{ds.database_name}"
                    engine = create_async_engine(
                        url,
                        pool_size=5,
                        max_overflow=10,
                        pool_timeout=30,
                        pool_recycle=3600,
                        echo=False,
                    )
                    self._engines[datasource_id] = engine
        return self._engines[datasource_id]

    async def remove_engine(self, datasource_id: int):
        """数据源删除或连接失败时移除"""
        if datasource_id in self._engines:
            await self._engines[datasource_id].dispose()
            del self._engines[datasource_id]

pool_manager = DynamicConnectionPool()
```

### 2.5 结构化日志配置

```python
# app/core/logging.py
import structlog

def configure_logging(env: str):
    processors = [
        structlog.contextvars.merge_contextvars,     # 注入 trace_id/user_id
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    if env == "production":
        processors.append(structlog.processors.JSONRenderer())  # JSON 格式
    else:
        processors.append(structlog.dev.ConsoleRenderer())      # 彩色可读格式

    structlog.configure(processors=processors, ...)

# 使用示例
logger = structlog.get_logger()
logger.info("exec_task_start",
    task_no=task.task_no,
    datasource=ds.name,
    target_count=task.target_count,
    user_id=user.id)
```



---

## 3. 前端技术栈

### 3.1 技术选型总表

| 分类 | 技术 | 版本 | 选型理由 |
|------|------|------|----------|
| 核心框架 | **Vue 3** | 3.4+ | Composition API、性能优秀、生态成熟 |
| 开发语言 | **TypeScript** | 5.x | 类型安全，与后端 Pydantic schema 对应 |
| 构建工具 | **Vite** | 5.x | 极速 HMR，构建速度远超 webpack |
| 状态管理 | **Pinia** | 2.x | Vue 官方推荐，比 Vuex 更简洁 |
| 路由 | **Vue Router** | 4.x | 支持懒加载、导航守卫（权限控制） |
| UI 组件库 | **Naive UI** | 2.x | 暗色主题支持完善、风格简洁、TypeScript 原生 |
| 图表库 | **ECharts 5** | 5.x | 功能强大，折线/柱状/饼图全覆盖 |
| HTTP 请求 | **Axios** | 1.x | 拦截器统一处理 Token / 错误 |
| 动画库 | **GSAP** | 3.x | 猫咪装饰动画、页面过渡动效 |
| 图标库 | **@vicons/ionicons5** | — | Naive UI 配套图标 |
| CSS 方案 | **UnoCSS** | 0.60+ | 原子化 CSS，按需生成，极小体积 |
| 代码规范 | **ESLint + Prettier** | — | 统一代码风格 |
| 测试 | **Vitest** | 1.x | Vite 原生测试框架 |

### 3.2 前端架构设计

#### 3.2.1 目录结构

```
frontend/
├── src/
│   ├── api/                    # API 请求层（按模块分文件）
│   │   ├── auth.ts
│   │   ├── datasource.ts
│   │   ├── engine.ts
│   │   ├── cases.ts
│   │   ├── tasks.ts
│   │   └── overview.ts
│   ├── assets/                 # 静态资源
│   │   ├── cat/                # 猫咪 SVG 插画资源
│   │   └── fonts/
│   ├── components/             # 公共组件
│   │   ├── common/             # 通用：AppLogo, CatLoader, EmptyState
│   │   ├── layout/             # 布局：AppLayout, Sidebar, TopBar
│   │   └── business/           # 业务：FieldStrategyPicker, AssocTag
│   ├── composables/            # 组合式函数（hooks）
│   │   ├── useAuth.ts
│   │   ├── useTaskProgress.ts  # 轮询任务进度
│   │   └── useDatasource.ts
│   ├── router/
│   │   └── index.ts            # 路由配置 + 权限导航守卫
│   ├── stores/                 # Pinia stores
│   │   ├── auth.ts             # 用户信息、权限列表
│   │   ├── datasource.ts       # 当前选中数据源
│   │   └── taskProgress.ts     # 执行中任务进度
│   ├── views/                  # 页面组件
│   │   ├── login/
│   │   ├── overview/
│   │   ├── engine/
│   │   │   ├── TableList.vue
│   │   │   └── FieldConfig.vue
│   │   ├── cases/
│   │   ├── tools/
│   │   ├── datasource/
│   │   └── admin/              # 用户管理（仅管理员可见）
│   ├── utils/
│   │   ├── request.ts          # Axios 封装
│   │   ├── permission.ts       # 权限判断工具函数
│   │   └── formatter.ts        # 数字/日期格式化
│   ├── styles/
│   │   ├── theme.ts            # Naive UI 主题变量（暗色）
│   │   └── global.css
│   ├── App.vue
│   └── main.ts
├── public/
├── index.html
├── vite.config.ts
└── tsconfig.json
```

#### 3.2.2 权限路由守卫

```typescript
// router/index.ts
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  // 白名单：登录页、注册页不需要认证
  if (to.meta.public) return next()

  // 未登录 → 跳转登录页
  if (!authStore.isLoggedIn) return next('/login')

  // 检查菜单权限
  const requiredPermission = to.meta.permission as string
  if (requiredPermission && !authStore.hasPermission(requiredPermission)) {
    return next('/403')
  }

  next()
})
```

#### 3.2.3 Axios 请求封装

```typescript
// utils/request.ts
const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
})

// 请求拦截：注入 JWT Token
request.interceptors.request.use(config => {
  const token = useAuthStore().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截：统一错误处理
request.interceptors.response.use(
  res => res.data,
  error => {
    if (error.response?.status === 401) {
      useAuthStore().logout()
      router.push('/login')
    }
    const msg = error.response?.data?.message || '网络请求失败'
    window.$message.error(msg)   // Naive UI 全局消息
    return Promise.reject(error)
  }
)
```

#### 3.2.4 任务进度轮询 composable

```typescript
// composables/useTaskProgress.ts
export function useTaskProgress(taskNo: string) {
  const progress = ref<TaskProgress | null>(null)
  let timer: ReturnType<typeof setInterval>

  const startPolling = () => {
    timer = setInterval(async () => {
      const res = await getTaskProgress(taskNo)
      progress.value = res.data
      if (['success', 'failed', 'partial_success'].includes(res.data.status)) {
        clearInterval(timer)   // 终态停止轮询
      }
    }, 2000)  // 每 2 秒轮询一次
  }

  onUnmounted(() => clearInterval(timer))
  return { progress, startPolling }
}
```

### 3.3 主题设计规范

```typescript
// styles/theme.ts — Naive UI 暗色主题覆盖
export const darkThemeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#7c3aed',           // 主色：紫色
    primaryColorHover: '#8b5cf6',
    primaryColorPressed: '#6d28d9',
    bodyColor: '#0d0d0d',              // 页面背景：极深黑
    cardColor: '#1a1a2e',              // 卡片背景
    borderColor: 'rgba(124,58,237,0.3)', // 边框：紫色半透明
    textColorBase: '#e2e8f0',
    textColor1: '#f1f5f9',
    textColor2: '#94a3b8',
    textColor3: '#64748b',
    fontFamily: '"Inter", "PingFang SC", "Microsoft YaHei", sans-serif',
  },
  Button: {
    // 主按钮：渐变效果通过 CSS 额外处理
    colorPrimary: 'linear-gradient(135deg, #7c3aed 0%, #2563eb 100%)',
  },
}
```

### 3.4 多任务并发进度 Store 设计

PRD 要求「支持同时存在多个执行任务，悬浮球显示进行中任务数量角标」，需要管理多个并发任务的进度状态。

#### 3.4.1 taskProgressStore（单 Case 任务）

```typescript
// stores/taskProgress.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { TaskProgressData } from '@/api/tasks'

export interface TaskProgressEntry {
  taskNo: string
  caseName: string
  status: 'submitted' | 'running' | 'success' | 'failed' | 'partial_success' | 'aborted'
  progressPercent: number       // 0~100
  insertRate: number            // 条/秒
  estimatedRemainSeconds: number | null
  data: TaskProgressData | null
  panelVisible: boolean         // 进度面板是否展开
  pollingTimer: ReturnType<typeof setInterval> | null
}

export const useTaskProgressStore = defineStore('taskProgress', () => {
  // Map<taskNo, TaskProgressEntry>
  const tasks = ref<Map<string, TaskProgressEntry>>(new Map())

  // 所有进行中的任务（running / submitted）
  const activeTasks = computed(() =>
    [...tasks.value.values()].filter(t => ['submitted', 'running'].includes(t.status))
  )

  // 悬浮球显示数量
  const activeCount = computed(() => activeTasks.value.length)

  // 悬浮球显示进度（最新提交任务的进度）
  const latestProgress = computed(() => {
    const sorted = activeTasks.value.sort((a, b) =>
      b.taskNo.localeCompare(a.taskNo)  // 雪花ID字典序越大越新
    )
    return sorted[0]?.progressPercent ?? 0
  })

  // 最后活跃的任务 taskNo（点击悬浮球展开用）
  const lastActiveTaskNo = ref<string | null>(null)

  function addTask(taskNo: string, caseName: string) {
    tasks.value.set(taskNo, {
      taskNo, caseName,
      status: 'submitted',
      progressPercent: 0,
      insertRate: 0,
      estimatedRemainSeconds: null,
      data: null,
      panelVisible: true,      // 新任务默认展开面板
      pollingTimer: null,
    })
    lastActiveTaskNo.value = taskNo
  }

  function updateTask(taskNo: string, patch: Partial<TaskProgressEntry>) {
    const entry = tasks.value.get(taskNo)
    if (entry) tasks.value.set(taskNo, { ...entry, ...patch })
  }

  function stopPolling(taskNo: string) {
    const entry = tasks.value.get(taskNo)
    if (entry?.pollingTimer) {
      clearInterval(entry.pollingTimer)
      updateTask(taskNo, { pollingTimer: null })
    }
  }

  // 终态任务 5 分钟后自动从 Map 中清除
  function scheduleCleanup(taskNo: string) {
    setTimeout(() => tasks.value.delete(taskNo), 5 * 60 * 1000)
  }

  return { tasks, activeTasks, activeCount, latestProgress, lastActiveTaskNo,
           addTask, updateTask, stopPolling, scheduleCleanup }
})
```

#### 3.4.2 sceneProgressStore（场景任务）

场景任务与单 Case 任务分开管理，结构相同但字段扩展了场景层级进度：

```typescript
// stores/sceneProgress.ts
export interface SceneProgressEntry {
  sceneExecNo: string
  sceneName: string
  status: string
  nodeCount: number
  completedNodes: number
  overallPercent: number
  data: SceneProgressData | null
  panelVisible: boolean
  pollingTimer: ReturnType<typeof setInterval> | null
}

export const useSceneProgressStore = defineStore('sceneProgress', () => {
  const scenes = ref<Map<string, SceneProgressEntry>>(new Map())
  // ... 结构与 taskProgressStore 对称
})
```

#### 3.4.3 悬浮球组件逻辑

```typescript
// components/common/TaskFloatBall.vue
const taskStore = useTaskProgressStore()
const sceneStore = useSceneProgressStore()

// 所有进行中任务总数（Case + 场景）
const totalActive = computed(() =>
  taskStore.activeCount + sceneStore.activeCount
)

// 悬浮球显示进度：优先展示最新任务（无论 Case 还是场景）
const displayProgress = computed(() => {
  if (taskStore.activeCount > 0) return taskStore.latestProgress
  if (sceneStore.activeCount > 0) return sceneStore.latestProgress
  return 0
})
```

---

> 系统自身使用一个独立 MySQL 实例（`dataforge_db`），所有表以 `df_` 前缀区分。

### 4.1 完整建表 DDL

```sql
-- ================================================================
-- 用户与权限体系
-- ================================================================

CREATE TABLE df_user (
    id                    BIGINT       PRIMARY KEY AUTO_INCREMENT,
    username              VARCHAR(50)  NOT NULL UNIQUE COMMENT '登录账号',
    password              VARCHAR(255) NOT NULL COMMENT 'bcrypt哈希',
    real_name             VARCHAR(50)  COMMENT '真实姓名',
    group_type            TINYINT      NOT NULL COMMENT '1=销项组 2=申报组 99=管理员',
    status                TINYINT      NOT NULL DEFAULT 0 COMMENT '0=待审批 1=正常 2=禁用 3=已拒绝',
    apply_reason          VARCHAR(500) COMMENT '申请理由',
    reject_reason         VARCHAR(500) COMMENT '拒绝原因',
    default_datasource_id BIGINT       COMMENT '默认数据源ID',
    avatar_index          TINYINT      DEFAULT 1 COMMENT '猫咪头像序号1-10',
    last_login_at         DATETIME     COMMENT '最后登录时间',
    last_login_ip         VARCHAR(50)  COMMENT '最后登录IP',
    created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_group_status (group_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

CREATE TABLE df_menu (
    id          BIGINT      PRIMARY KEY AUTO_INCREMENT,
    menu_code   VARCHAR(50) NOT NULL UNIQUE COMMENT '权限编码，如ENGINE:EXECUTE',
    menu_name   VARCHAR(100) NOT NULL COMMENT '菜单名称',
    parent_code VARCHAR(50) COMMENT '父菜单编码',
    sort_order  INT         NOT NULL DEFAULT 0 COMMENT '排序',
    icon        VARCHAR(100) COMMENT '图标名称'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='菜单权限表';

CREATE TABLE df_user_menu (
    user_id  BIGINT NOT NULL,
    menu_id  BIGINT NOT NULL,
    PRIMARY KEY (user_id, menu_id),
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户菜单关联表';

CREATE TABLE df_ai_api_key (
    id          BIGINT       PRIMARY KEY AUTO_INCREMENT,
    key_name    VARCHAR(100) NOT NULL COMMENT 'Key名称',
    api_key     VARCHAR(64)  NOT NULL UNIQUE COMMENT 'df_ai_前缀+32位hex',
    permissions JSON         COMMENT '允许的接口权限范围',
    rate_limit  INT          DEFAULT 100 COMMENT '每分钟请求限制',
    expire_at   DATETIME     COMMENT '过期时间，NULL=永不过期',
    status      TINYINT      DEFAULT 1 COMMENT '1=启用 0=禁用',
    created_by  BIGINT       NOT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_api_key (api_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI接口API Key表';

-- ================================================================
-- 数据源与表结构缓存
-- ================================================================

CREATE TABLE df_datasource (
    id            BIGINT       PRIMARY KEY AUTO_INCREMENT,
    name          VARCHAR(100) NOT NULL UNIQUE COMMENT '数据源名称',
    db_type       VARCHAR(20)  NOT NULL DEFAULT 'MySQL',
    host          VARCHAR(255) NOT NULL,
    port          INT          NOT NULL DEFAULT 3306,
    database_name VARCHAR(100) NOT NULL,
    username      VARCHAR(100) NOT NULL,
    password      VARCHAR(500) NOT NULL COMMENT 'AES-256加密',
    group_type    TINYINT      NOT NULL COMMENT '1=销项组 2=申报组',
    status        TINYINT      NOT NULL DEFAULT 0 COMMENT '0=未初始化 1=正常 2=异常 3=同步中',
    remark        VARCHAR(500),
    table_count   INT          DEFAULT 0 COMMENT '已缓存表数量',
    last_sync_at  DATETIME     COMMENT '最后表结构同步时间',
    created_by    BIGINT       NOT NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_group (group_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据源配置表';

CREATE TABLE df_table_cache (
    id             BIGINT       PRIMARY KEY AUTO_INCREMENT,
    datasource_id  BIGINT       NOT NULL,
    table_name     VARCHAR(200) NOT NULL COMMENT '表名',
    table_comment  VARCHAR(500) COMMENT '表备注',
    table_rows     BIGINT       DEFAULT 0 COMMENT '估算行数(information_schema)',
    data_length    BIGINT       DEFAULT 0 COMMENT '数据大小(bytes)',
    engine         VARCHAR(50)  COMMENT '存储引擎',
    charset        VARCHAR(50)  COMMENT '字符集',
    create_time    DATETIME     COMMENT '表创建时间',
    column_count   INT          DEFAULT 0 COMMENT '字段数量',
    pk_type        VARCHAR(20)  DEFAULT 'none' COMMENT 'none/single/composite',
    unique_index_count INT      DEFAULT 0,
    synced_at      DATETIME     NOT NULL COMMENT '缓存同步时间',
    UNIQUE KEY uk_ds_table (datasource_id, table_name),
    INDEX idx_datasource (datasource_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据源表信息缓存';

CREATE TABLE df_column_cache (
    id               BIGINT       PRIMARY KEY AUTO_INCREMENT,
    datasource_id    BIGINT       NOT NULL,
    table_name       VARCHAR(200) NOT NULL,
    column_name      VARCHAR(200) NOT NULL,
    column_comment   VARCHAR(500) COMMENT '字段备注',
    data_type        VARCHAR(100) NOT NULL COMMENT '基础类型: varchar/int/datetime等',
    column_type      VARCHAR(200) NOT NULL COMMENT '完整类型: varchar(255)/int(11)等',
    is_nullable      TINYINT      NOT NULL DEFAULT 1 COMMENT '0=NOT NULL 1=NULL',
    is_primary_key   TINYINT      NOT NULL DEFAULT 0,
    is_unique        TINYINT      NOT NULL DEFAULT 0,
    column_default   VARCHAR(500) COMMENT '默认值',
    char_max_length  INT          COMMENT 'varchar最大长度',
    numeric_precision INT         COMMENT '数字精度',
    numeric_scale    INT          COMMENT '小数位数',
    ordinal_position INT          NOT NULL COMMENT '字段顺序',
    extra            VARCHAR(100) COMMENT 'auto_increment等',
    synced_at        DATETIME     NOT NULL,
    UNIQUE KEY uk_ds_table_col (datasource_id, table_name, column_name),
    INDEX idx_ds_table (datasource_id, table_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据源字段信息缓存';

CREATE TABLE df_index_cache (
    id            BIGINT       PRIMARY KEY AUTO_INCREMENT,
    datasource_id BIGINT       NOT NULL,
    table_name    VARCHAR(200) NOT NULL,
    index_name    VARCHAR(200) NOT NULL,
    is_unique     TINYINT      NOT NULL DEFAULT 0,
    is_primary    TINYINT      NOT NULL DEFAULT 0,
    column_names  VARCHAR(500) NOT NULL COMMENT 'JSON数组，字段名列表',
    seq_in_index  INT          COMMENT '联合索引中的位置',
    synced_at     DATETIME     NOT NULL,
    INDEX idx_ds_table (datasource_id, table_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据源索引信息缓存';

-- ================================================================
-- 造数 Case
-- ================================================================

CREATE TABLE df_case (
    id               BIGINT        PRIMARY KEY AUTO_INCREMENT,
    case_name        VARCHAR(200)  NOT NULL COMMENT 'Case名称',
    datasource_id    BIGINT        NOT NULL,
    datasource_name  VARCHAR(100)  NOT NULL COMMENT '冗余，防数据源改名后显示异常',
    main_table       VARCHAR(200)  NOT NULL COMMENT '主操作表',
    related_tables   VARCHAR(1000) COMMENT '关联表名JSON数组',
    related_count    INT           DEFAULT 0 COMMENT '关联表数量',
    config_json      MEDIUMTEXT    NOT NULL COMMENT '完整配置JSON（字段策略+关联关系）',
    group_type       TINYINT       NOT NULL,
    is_deleted       TINYINT       NOT NULL DEFAULT 0,
    last_exec_at     DATETIME      COMMENT '最后执行时间',
    last_exec_status TINYINT       COMMENT '0=未执行 1=成功 2=失败 3=部分成功',
    exec_count       INT           NOT NULL DEFAULT 0 COMMENT '历史执行次数',
    created_by       BIGINT        NOT NULL,
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_group_ds (group_type, datasource_id),
    INDEX idx_creator (created_by),
    INDEX idx_main_table (datasource_id, main_table)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='造数Case表';

-- ================================================================
-- 执行任务与日志
-- ================================================================

CREATE TABLE df_exec_task (
    id             BIGINT        PRIMARY KEY AUTO_INCREMENT,
    task_no        VARCHAR(64)   NOT NULL UNIQUE COMMENT '任务编号（雪花ID）',
    case_id        BIGINT        NOT NULL,
    case_name      VARCHAR(200)  NOT NULL COMMENT '冗余Case名',
    case_snapshot  MEDIUMTEXT    NOT NULL COMMENT '执行时Case配置快照',
    datasource_id  BIGINT        NOT NULL,
    datasource_name VARCHAR(100) NOT NULL,
    main_table     VARCHAR(200)  NOT NULL,
    related_tables VARCHAR(1000) COMMENT 'JSON数组',
    target_count   BIGINT        NOT NULL COMMENT '目标造数条数',
    success_count  BIGINT        NOT NULL DEFAULT 0,
    fail_count     BIGINT        NOT NULL DEFAULT 0,
    retry_count    TINYINT       NOT NULL DEFAULT 0,
    celery_task_id VARCHAR(100)  COMMENT 'Celery任务ID，用于发送revoke强制停止',
    status         TINYINT       NOT NULL DEFAULT 0
        COMMENT '0=待执行 1=执行中 2=成功 3=失败 4=重试中 5=部分成功 6=已中止',
    error_msg      TEXT          COMMENT '失败时的错误摘要',
    start_at       DATETIME,
    finish_at      DATETIME,
    duration_ms    BIGINT        COMMENT '总耗时毫秒',
    group_type     TINYINT       NOT NULL,
    created_by     BIGINT        NOT NULL,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_case (case_id),
    INDEX idx_task_no (task_no),
    INDEX idx_group_status (group_type, status),
    INDEX idx_group_created (group_type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='造数执行任务表';

CREATE TABLE df_exec_batch_log (
    id          BIGINT   PRIMARY KEY AUTO_INCREMENT,
    task_id     BIGINT   NOT NULL,
    table_name  VARCHAR(200) NOT NULL COMMENT '插入的目标表',
    batch_no    INT      NOT NULL COMMENT '批次序号（从0开始）',
    batch_size  INT      NOT NULL COMMENT '本批条数',
    status      TINYINT  NOT NULL DEFAULT 0 COMMENT '0=待执行 1=成功 2=失败',
    retry_times TINYINT  NOT NULL DEFAULT 0,
    error_msg   TEXT,
    start_at    DATETIME,
    finish_at   DATETIME,
    duration_ms INT,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_task (task_id),
    INDEX idx_task_table (task_id, table_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='执行批次日志（断点续传依据）';

CREATE TABLE df_audit_log (
    id          BIGINT       PRIMARY KEY AUTO_INCREMENT,
    user_id     BIGINT       NOT NULL,
    username    VARCHAR(50)  NOT NULL,
    action      VARCHAR(100) NOT NULL
        COMMENT 'LOGIN/LOGOUT/CREATE_CASE/EXEC_TASK/DELETE_CASE/ADD_DS/DEL_DS/APPROVE_USER等',
    resource    VARCHAR(100) COMMENT '操作对象类型',
    resource_id VARCHAR(50)  COMMENT '操作对象ID',
    detail      TEXT         COMMENT '操作详情JSON',
    ip          VARCHAR(50),
    user_agent  VARCHAR(500),
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_action (action),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='操作审计日志（不可删除）';

-- ================================================================
-- 场景管理
-- ================================================================

CREATE TABLE df_scene (
    id               BIGINT        PRIMARY KEY AUTO_INCREMENT,
    scene_name       VARCHAR(200)  NOT NULL COMMENT '场景名称',
    description      VARCHAR(500)  COMMENT '场景描述',
    -- nodes_json 存储节点列表，exec_mode 由后端计算后冗余存储
    nodes_json       MEDIUMTEXT    NOT NULL COMMENT '节点配置JSON数组，见下方格式规范',
    edges_json       MEDIUMTEXT    NOT NULL DEFAULT '[]' COMMENT '连线关系JSON数组',
    node_count       INT           NOT NULL DEFAULT 0 COMMENT '节点总数',
    exec_mode        VARCHAR(20)   NOT NULL DEFAULT 'serial'
        COMMENT 'serial=纯串行 parallel=纯并行 mixed=混合',
    group_type       TINYINT       NOT NULL COMMENT '1=销项组 2=申报组',
    is_deleted       TINYINT       NOT NULL DEFAULT 0,
    last_exec_at     DATETIME      COMMENT '最后执行时间',
    last_exec_status TINYINT       COMMENT '0=未执行 1=成功 2=失败 3=部分成功 4=已中止',
    exec_count       INT           NOT NULL DEFAULT 0,
    created_by       BIGINT        NOT NULL,
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_group (group_type, is_deleted),
    INDEX idx_creator (created_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='场景表';

CREATE TABLE df_scene_exec (
    id               BIGINT        PRIMARY KEY AUTO_INCREMENT,
    scene_exec_no    VARCHAR(64)   NOT NULL UNIQUE COMMENT '场景执行编号（雪花ID，SC前缀）',
    scene_id         BIGINT        NOT NULL,
    scene_name       VARCHAR(200)  NOT NULL COMMENT '冗余场景名',
    scene_snapshot   MEDIUMTEXT    NOT NULL COMMENT '执行时场景配置快照（nodes+edges）',
    node_count       INT           NOT NULL COMMENT '本次执行节点总数',
    success_count    INT           NOT NULL DEFAULT 0 COMMENT '成功节点数',
    fail_count       INT           NOT NULL DEFAULT 0 COMMENT '失败/已取消节点数',
    total_rows       BIGINT        NOT NULL DEFAULT 0 COMMENT '所有节点成功插入条数之和',
    status           TINYINT       NOT NULL DEFAULT 0
        COMMENT '0=待执行 1=执行中 2=成功 3=失败 4=部分成功 5=已中止',
    error_msg        TEXT          COMMENT '失败摘要',
    start_at         DATETIME,
    finish_at        DATETIME,
    duration_ms      BIGINT        COMMENT '总耗时毫秒',
    group_type       TINYINT       NOT NULL,
    created_by       BIGINT        NOT NULL,
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_scene (scene_id),
    INDEX idx_scene_exec_no (scene_exec_no),
    INDEX idx_group_created (group_type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='场景执行记录表';

CREATE TABLE df_scene_node_exec (
    id               BIGINT        PRIMARY KEY AUTO_INCREMENT,
    scene_exec_id    BIGINT        NOT NULL COMMENT '关联 df_scene_exec.id',
    node_id          VARCHAR(64)   NOT NULL COMMENT '节点唯一ID（前端生成UUID，用于关联edges）',
    case_id          BIGINT        NOT NULL,
    case_name        VARCHAR(200)  NOT NULL COMMENT '冗余Case名',
    layer_no         INT           NOT NULL COMMENT '拓扑分层序号（0=第一批）',
    target_count     BIGINT        NOT NULL COMMENT '本节点造数目标条数',
    success_count    BIGINT        NOT NULL DEFAULT 0,
    fail_count       BIGINT        NOT NULL DEFAULT 0,
    exec_task_id     BIGINT        COMMENT '关联 df_exec_task.id（节点实际执行的任务）',
    exec_task_no     VARCHAR(64)   COMMENT '冗余 task_no，方便查询',
    fail_strategy    VARCHAR(20)   NOT NULL DEFAULT 'continue'
        COMMENT 'continue=继续执行 abort=终止场景',
    status           TINYINT       NOT NULL DEFAULT 0
        COMMENT '0=待执行 1=执行中 2=成功 3=失败 4=已取消（前置终止）',
    error_msg        TEXT,
    start_at         DATETIME,
    finish_at        DATETIME,
    duration_ms      BIGINT,
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_scene_exec (scene_exec_id),
    INDEX idx_case (case_id),
    INDEX idx_exec_task (exec_task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='场景节点执行明细表';


-- ================================================================
-- 消息通知
-- ================================================================

CREATE TABLE df_notification (
    id            BIGINT        PRIMARY KEY AUTO_INCREMENT,
    user_id       BIGINT        NOT NULL COMMENT '接收用户ID',
    msg_type      VARCHAR(50)   NOT NULL
        COMMENT '消息类型：USER_APPLY/APPLY_APPROVED/APPLY_REJECTED/EXEC_SUCCESS/EXEC_FAILED/EXEC_PARTIAL/SCENE_SUCCESS/SCENE_FAILED/SCENE_PARTIAL/DS_SYNC_DONE/DS_SYNC_FAILED/DS_OFFLINE/PERMISSION_CHANGED',
    priority      TINYINT       NOT NULL DEFAULT 2
        COMMENT '优先级：1=高(红) 2=中(黄) 3=普通(绿)',
    title         VARCHAR(200)  NOT NULL COMMENT '消息标题',
    content       VARCHAR(1000) NOT NULL COMMENT '消息正文',
    link_url      VARCHAR(500)  COMMENT '关联跳转路径（相对路径）',
    is_read       TINYINT       NOT NULL DEFAULT 0 COMMENT '0=未读 1=已读',
    read_at       DATETIME      COMMENT '阅读时间',
    is_deleted    TINYINT       NOT NULL DEFAULT 0,
    group_type    TINYINT       NOT NULL COMMENT '接收人所属分组，管理员填99',
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_read (user_id, is_read, is_deleted),
    INDEX idx_user_created (user_id, created_at),
    INDEX idx_group_type (group_type, msg_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统消息通知表';
```

### 4.2 config_json 字段格式规范

`df_case.config_json` 存储完整的造数配置，格式如下：

```json
{
  "version": "1.0",
  "main_table": "user_info",
  "field_configs": [
    {
      "column_name": "id",
      "data_type": "bigint",
      "column_type": "bigint(20)",
      "is_nullable": false,
      "is_primary_key": true,
      "strategy": "SNOWFLAKE",
      "strategy_params": {}
    },
    {
      "column_name": "phone",
      "data_type": "varchar",
      "column_type": "varchar(20)",
      "is_nullable": false,
      "is_primary_key": false,
      "strategy": "RANDOM_FIXED_LEN",
      "strategy_params": { "length": 11 }
    },
    {
      "column_name": "created_at",
      "data_type": "datetime",
      "column_type": "datetime",
      "is_nullable": true,
      "is_primary_key": false,
      "strategy": "NOW",
      "strategy_params": {}
    }
  ],
  "associations": [
    {
      "source_column": "user_id",
      "target_table": "order_info",
      "target_column": "buyer_id"
    },
    {
      "source_column": "user_id",
      "target_table": "log_info",
      "target_column": "operator_id"
    },
    {
      "source_table": "order_info",
      "source_column": "order_no",
      "target_table": "log_info",
      "target_column": "order_no"
    }
  ],
  "related_field_configs": {
    "order_info": [
      {
        "column_name": "amount",
        "data_type": "decimal",
        "column_type": "decimal(10,2)",
        "is_nullable": false,
        "is_primary_key": false,
        "strategy": "DERIVED",
        "strategy_params": { "source_column": "price", "operator": "multiply", "operand": 0.8 }
      }
    ]
  }
}
```

**字段补充说明：**

- `associations[].source_table`：可选，**多级关联**时指定源表（缺省为主表）。源表必须是主表或某个关联目标表，形成 A→B→C 链式。
- `related_field_configs`：可选，**关联表字段策略覆盖**，key 为关联目标表名，value 结构与 `field_configs` 相同。缺省的关联表由执行器按字段元数据自动推断策略兜底（`executor._infer_field_configs_from_cache`）。
- 被关联注入的目标列（如 `log_info.order_no`）即使在 `related_field_configs` 中配置了策略也不会生效——注入值优先覆盖（见 6.10）。

### 4.3 场景 nodes_json / edges_json 格式规范

**nodes_json** 存储画布中所有节点的配置：

```json
[
  {
    "node_id": "n_abc123",          // 前端生成的 UUID，全场景唯一
    "case_id": 42,
    "case_name": "用户信息Case",
    "target_count": 1000,           // 本节点造数条数
    "fail_strategy": "continue",    // continue | abort
    "position": { "x": 100, "y": 80 }  // 画布坐标，仅用于前端渲染
  },
  {
    "node_id": "n_def456",
    "case_id": 58,
    "case_name": "订单信息Case",
    "target_count": 2000,
    "fail_strategy": "abort",
    "position": { "x": 400, "y": 80 }
  }
]
```

**edges_json** 存储节点间的依赖连线：

```json
[
  {
    "edge_id": "e_001",
    "source": "n_abc123",   // 前置节点 node_id
    "target": "n_def456"    // 后置节点 node_id（等待 source 完成后才执行）
  }
]
```

**拓扑分层算法（Kahn's Algorithm）示例：**

```python
def build_layers(nodes: list[dict], edges: list[dict]) -> list[list[str]]:
    """
    输入：节点列表、有向边列表
    输出：分层结果，每层是一组可并行执行的 node_id 列表
    layer[0] 先执行，layer[-1] 最后执行
    """
    from collections import defaultdict, deque

    in_degree = {n["node_id"]: 0 for n in nodes}
    graph = defaultdict(list)   # source → [targets]

    for edge in edges:
        graph[edge["source"]].append(edge["target"])
        in_degree[edge["target"]] += 1

    queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
    layers = []

    while queue:
        layer = list(queue)      # 本层所有节点（入度=0，可并行执行）
        layers.append(layer)
        queue.clear()
        for nid in layer:
            for target in graph[nid]:
                in_degree[target] -= 1
                if in_degree[target] == 0:
                    queue.append(target)

    if sum(len(l) for l in layers) != len(nodes):
        raise ValueError("场景存在循环依赖，无法执行")

    return layers
```

---

## 5. Redis 缓存设计

### 5.1 Key 规范与完整清单

所有 Key 统一前缀 `df:`，格式：`df:{模块}:{标识}`

```
┌──────────────────────────────────────────────────────────────────────┐
│ Key                                          TTL      说明            │
├──────────────────────────────────────────────────────────────────────┤
│ df:tables:{datasource_id}                   12h      表列表JSON缓存   │
│ df:columns:{datasource_id}:{table_name}     12h      字段列表JSON缓存 │
│ df:indexes:{datasource_id}:{table_name}     12h      索引信息JSON缓存 │
├──────────────────────────────────────────────────────────────────────┤
│ df:ds:status:{datasource_id}                60s      连接状态心跳     │
│ df:lock:sync:{datasource_id}                5min     同步分布式锁     │
├──────────────────────────────────────────────────────────────────────┤
│ df:task:progress:{task_no}                  24h      任务整体实时进度  │
│ df:task:table_progress:{task_no}            24h      分表实时进度      │
│ df:task:rate:{task_no}:{table_name}         10s      各表插入速率窗口  │
│ df:incr:{task_id}:{table}:{column}          task生命周期 自增计数器   │
├──────────────────────────────────────────────────────────────────────┤
│ df:scene:progress:{scene_exec_no}           24h      场景整体实时进度  │
│ df:scene:node_progress:{scene_exec_no}      24h      各节点实时进度   │
├──────────────────────────────────────────────────────────────────────┤
│ df:token:blacklist:{jti}                    token剩余期 JWT黑名单     │
├──────────────────────────────────────────────────────────────────────┤
│ df:stats:{group_type}:daily                 5min     总览指标缓存     │
│ df:tool:history:{user_id}:{tool}            7d       工具使用历史     │
│ df:notify:unread:{user_id}                  永久(DB同步) 未读消息计数 │
└──────────────────────────────────────────────────────────────────────┘
```

### 5.2 核心 Key 数据结构详解

#### df:task:progress:{task_no} — Hash 结构（任务整体进度）

```
HSET df:task:progress:TK001
  status           "running"           # submitted/running/success/failed/partial_success/aborted
  target_total     "3000000"           # 所有表目标总条数之和（主表N + 关联表N × 表数）
  success_total    "1020000"           # 所有表当前成功总条数
  fail_total       "0"                 # 所有表失败总条数
  table_count      "3"                 # 涉及表数量
  batch_size       "5000"              # 本次执行批次大小
  concurrency      "8"                 # 并发线程数
  start_at         "1720406400"        # 任务开始时间戳
  updated_at       "1720406416"        # 最后更新时间戳
```

前端轮询 `GET /api/v1/tasks/{task_no}/progress` 读此 Key + 下方分表 Key，聚合后返回，避免每次查 MySQL。

#### df:task:table_progress:{task_no} — Hash 结构（分表进度）

每张表一个 field，field 名为表名，value 为 JSON 字符串：

```
HSET df:task:table_progress:TK001
  user_info   '{"target":1000000,"success":900000,"failed":0,"status":"running"}'
  order_info  '{"target":1000000,"success":520000,"failed":0,"status":"running"}'
  log_info    '{"target":1000000,"success":320000,"failed":0,"status":"running"}'
```

设计为单 Key 多 field 而非多 Key，原因：前端一次 `HGETALL` 即可取到所有表的进度，减少 RTT。

#### df:task:rate:{task_no}:{table_name} — List 结构（滑动窗口速率）

用于计算「最近 3 秒插入速率」，采用滑动时间窗口：

```python
# Celery Worker 每批次完成后写入
async def record_batch_rate(redis, task_no: str, table: str, count: int):
    key = f"df:task:rate:{task_no}:{table}"
    now = time.time()
    # 将 (时间戳, 条数) 序列化后 rpush 到列表
    await redis.rpush(key, f"{now}:{count}")
    await redis.expire(key, 10)   # 10s 后自动清理

# 查询速率时：取最近 3s 内的所有记录求和 / 3
async def get_insert_rate(redis, task_no: str, table: str) -> float:
    key = f"df:task:rate:{task_no}:{table}"
    records = await redis.lrange(key, 0, -1)
    now = time.time()
    window_start = now - 3.0
    recent_count = sum(
        int(r.split(":")[1])
        for r in records
        if float(r.split(":")[0]) >= window_start
    )
    return recent_count / 3.0   # 条/秒
```

TTL 设为 10s，任务结束后自动过期无需手动清理。

#### df:incr:{task_id}:{table}:{column} — String（原子计数器）

```python
# 多线程并发时安全自增
current = await redis.incrby(
    f"df:incr:{task_id}:{table}:{column}",
    batch_size   # 每个线程一次性取 batch_size 个连续值
)
# 该线程使用 (current - batch_size) ~ (current - 1) 的值
```

#### df:tables:{datasource_id} — String（JSON）

```json
[
  {
    "table_name": "user_info",
    "table_comment": "用户信息表",
    "table_rows": 50000,
    "column_count": 12,
    "pk_type": "single",
    "unique_index_count": 2,
    "synced_at": "2026-07-08 02:00:00"
  }
]
```

#### df:scene:progress:{scene_exec_no} — Hash 结构（场景整体进度）

```
HSET df:scene:progress:SC001
  status           "running"    # submitted/running/success/failed/partial_success/aborted
  node_count       "4"          # 节点总数
  success_count    "1"          # 已成功节点数
  fail_count       "0"          # 已失败/已取消节点数
  current_layer    "1"          # 当前执行层（0-indexed）
  total_layers     "3"          # 总层数
  target_rows      "4500"       # 所有节点目标行数之和
  success_rows     "1000"       # 已成功插入行数之和
  start_at         "1720406400"
  updated_at       "1720406428"
```

#### df:scene:node_progress:{scene_exec_no} — Hash 结构（各节点进度）

每个节点一个 field，field 名为 `node_id`，value 为 JSON 字符串：

```
HSET df:scene:node_progress:SC001
  n_abc123  '{"status":"success","target":1000,"success":1000,"task_no":"TK001","layer":0}'
  n_def456  '{"status":"running","target":500,"success":300,"task_no":"TK002","layer":1}'
  n_ghi789  '{"status":"running","target":1000,"success":200,"task_no":"TK003","layer":1}'
  n_jkl012  '{"status":"pending","target":2000,"success":0,"task_no":null,"layer":2}'
```

设计为单 Key 多 field，前端一次 `HGETALL` 获取全部节点状态，减少 RTT。



---

## 6. 关键技术方案

### 6.1 高性能批量插入方案

千万级数据插入是本系统核心挑战，采用以下分层优化策略：

#### 方案一：批量 VALUES 拼接（核心）

```python
# 不用 ORM 逐条 INSERT，改用原生批量 SQL
async def bulk_insert(engine, table_name: str, rows: list[dict]):
    if not rows:
        return

    columns = list(rows[0].keys())
    placeholders = ", ".join([f":{col}" for col in columns])
    col_names = ", ".join([f"`{col}`" for col in columns])
    sql = f"INSERT INTO `{table_name}` ({col_names}) VALUES ({placeholders})"

    async with engine.begin() as conn:
        await conn.execute(text(sql), rows)   # SQLAlchemy 批量执行
```

#### 方案二：动态批次大小

```python
def calc_batch_size(target_count: int) -> int:
    """根据目标量动态调整批次大小，平衡内存和性能"""
    if target_count <= 10_000:
        return 500
    elif target_count <= 100_000:
        return 1_000
    elif target_count <= 1_000_000:
        return 3_000
    else:
        return 5_000   # 超百万级：5000条/批
```

#### 方案三：多线程并发（IO 密集型适合）

```python
# 8 线程并发执行批次（数据库 IO 等待期间 GIL 释放）
# 实测：单线程 5000条/s → 8线程 约 35000条/s
MAX_WORKERS = 8  # 可配置，不超过 DB 连接池大小
```

#### 方案四：关联表并行插入

```python
# 分析依赖关系：无依赖的表可并行插入
# 有依赖的表需等待源表插入完成（获得实际值后再写入）
#
# 例：user_info(id) → order(user_id) → log(order_id)
# 执行顺序：user_info 完成 → order 并行 log 前置等待
#
# 实现：asyncio.gather 并发执行无依赖任务组
```

### 6.2 数据源表结构缓存策略

#### 三级缓存架构

```
请求到来
    │
    ▼
① 查 Redis（df:columns:{ds_id}:{table}）
    └── 命中 → 直接返回，< 10ms
    │
    ▼ 未命中
② 查本地 MySQL 缓存表（df_column_cache）
    └── 命中 → 异步回写 Redis → 返回，< 50ms
    │
    ▼ 未命中（首次或缓存失效）
③ 触发数据源同步任务
    └── 从目标数据源查 information_schema
    └── 写入 df_column_cache + Redis
    └── 返回结果，< 5s（大表可能更长）
```

#### 缓存一致性维护

| 场景 | 处理方式 |
|------|----------|
| 定时凌晨同步 | Celery Beat 凌晨 02:00 全量刷新 |
| 手动点击「立即同步」 | 触发增量同步（仅同步变更部分） |
| 数据源密码/地址变更 | 保存后强制触发全量重新初始化，清除旧缓存 |
| Redis 重启 | 首次查询时自动从 MySQL 缓存表回填 Redis |

### 6.3 造数数据生成策略引擎

采用策略模式（Strategy Pattern），每种策略为独立类：

```python
# app/engine/strategies/base.py
from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    @abstractmethod
    def generate(self, column_meta: ColumnMeta, params: dict, index: int) -> Any:
        """生成单个值
        Args:
            column_meta: 字段元数据（类型、长度等）
            params: 策略参数（用户配置）
            index: 当前行序号（自增策略需要）
        """
        ...

# app/engine/strategies/registry.py
STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "DEFAULT":           DefaultStrategy,
    "RANDOM_FIXED_LEN":  RandomFixedLenStrategy,
    "RANDOM_RANGE_LEN":  RandomRangeLenStrategy,
    "CUSTOM_VALUE":      CustomValueStrategy,
    "PICK_FROM_LIST":    PickFromListStrategy,
    "ITERATE_LIST":      IterateListStrategy,    # 遍历驱动策略
    "UUID":              UUIDStrategy,
    "SNOWFLAKE":         SnowflakeStrategy,
    "INCR_FROM":         IncrFromStrategy,
    "DERIVED":           DerivedStrategy,        # 字段运算派生（依赖同表源列，data_generator 整列计算）
    "TOOL_GEN":          ToolGenStrategy,        # 调用快捷工具生成器（身份证/手机号/姓名等）
    "NOW":               NowStrategy,
    "RANDOM_TIME_RANGE": RandomTimeRangeStrategy,
    "FIXED_TIME":        FixedTimeStrategy,
}

def get_strategy(strategy_code: str) -> BaseStrategy:
    cls = STRATEGY_REGISTRY.get(strategy_code)
    if not cls:
        raise ValueError(f"未知策略: {strategy_code}")
    return cls()
```

新增策略只需实现 `BaseStrategy` 并在 `STRATEGY_REGISTRY` 中注册，无需修改核心引擎。

> 注意：策略实例为**进程内单例**（模块加载即实例化，保证 SNOWFLAKE 等有状态策略并发取值唯一）。因此 **Celery Worker 对策略代码无热更新能力**——新增/修改策略后必须重启 Worker，否则执行报「未知策略」。

**DERIVED / TOOL_GEN 实现要点：**

```python
# app/engine/strategies/derived_strategies.py
class DerivedStrategy(BaseStrategy):
    """字段运算派生：目标值 = 源列值 运算符 操作数（逐行计算）"""
    strategy_code = "DERIVED"
    # params: {"source_column": "income", "operator": "multiply", "operand": 0.2}
    # 校验：源字段同表存在、数字类型、非 SKIP；除法操作数 ≠ 0
    # 执行：data_generator 生成完源列后整列计算，支持 add/subtract/multiply/divide

# app/engine/strategies/tool_strategies.py
class ToolGenStrategy(BaseStrategy):
    """快捷工具生成：复用快捷工具的生成器函数，按行独立随机生成"""
    strategy_code = "TOOL_GEN"
    # params: {"tool": "idcard" | "phone" | "name" | "address" | "bank_card" | ...}
    # 与 tools 模块共用同一生成器实现，保证身份证校验位等规则一致
```

### 6.4 分布式自增 ID 方案（Redis INCRBY）

```python
class IncrFromStrategy(BaseStrategy):
    """
    多线程安全的自增策略：
    线程不是每次 INCR 1，而是批量预取一段范围，
    减少 Redis 请求次数，提升并发性能。
    """
    async def init_counter(self, redis, key: str, start: int, batch_size: int) -> tuple[int, int]:
        """预取 batch_size 个连续 ID，返回 (start, end)"""
        end_value = await redis.incrby(key, batch_size)
        start_value = end_value - batch_size
        return start_value, end_value - 1

    def generate(self, col_meta, params, index):
        # index 直接映射到预取范围内的值
        return params["range_start"] + index
```

### 6.5 JWT 认证与会话管理

```python
# app/core/security.py

# Token 生成
def create_access_token(user_id: int, permissions: list[str]) -> str:
    jti = str(uuid4())  # JWT ID，用于黑名单
    payload = {
        "sub": str(user_id),
        "permissions": permissions,
        "jti": jti,
        "exp": datetime.utcnow() + timedelta(days=7),
        "iat": datetime.utcnow(),
    }
    return jose.jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

# 主动失效（登出）
async def invalidate_token(jti: str, ttl: int):
    await redis.setex(f"df:token:blacklist:{jti}", ttl, "1")

# 校验时检查黑名单
async def verify_token(token: str) -> dict:
    payload = jose.jwt.decode(token, settings.SECRET_KEY, ...)
    if await redis.exists(f"df:token:blacklist:{payload['jti']}"):
        raise HTTPException(401, "Token已失效")
    return payload
```

---

### 6.6 任务进度监控接口设计

#### 6.6.1 接口定义

```
GET /api/v1/tasks/{task_no}/progress
Authorization: Bearer {jwt}
```

#### 6.6.2 响应结构（完整）

```json
{
  "code": 0,
  "data": {
    "task_no": "TK20260708001",
    "status": "running",
    "start_at": "2026-07-08T10:30:00+08:00",
    "elapsed_seconds": 16,
    "batch_size": 5000,
    "concurrency": 8,

    "overall": {
      "target_total": 3000000,
      "success_total": 1740000,
      "fail_total": 0,
      "progress_percent": 58.0,
      "insert_rate": 42300,
      "estimated_remaining_seconds": 29
    },

    "tables": [
      {
        "table_name": "user_info",
        "role": "main",
        "target": 1000000,
        "success": 900000,
        "failed": 0,
        "progress_percent": 90.0,
        "insert_rate": 18200,
        "status": "running"
      },
      {
        "table_name": "order_info",
        "role": "related",
        "target": 1000000,
        "success": 520000,
        "failed": 0,
        "progress_percent": 52.0,
        "insert_rate": 15400,
        "status": "running"
      },
      {
        "table_name": "log_info",
        "role": "related",
        "target": 1000000,
        "success": 320000,
        "failed": 0,
        "progress_percent": 32.0,
        "insert_rate": 8700,
        "status": "running"
      }
    ]
  }
}
```

**status 枚举值：**

| 值 | 说明 |
|----|------|
| `submitted` | 已提交，Worker 尚未开始处理 |
| `running` | 执行中 |
| `success` | 全部成功 |
| `failed` | 全部失败 |
| `partial_success` | 部分成功（有失败批次） |
| `aborted` | 用户强制停止 |

**table.status 枚举值：**

| 值 | 说明 |
|----|------|
| `pending` | 等待中（依赖的前置表尚未完成） |
| `running` | 插入中 |
| `success` | 该表全部完成 |
| `failed` | 该表插入失败 |

#### 6.6.3 后端聚合逻辑

```python
# app/api/v1/tasks.py
@router.get("/{task_no}/progress")
async def get_task_progress(task_no: str, user=Depends(get_current_user)):
    # 1. 从 Redis 读取整体进度（HGETALL）
    overall_raw = await redis.hgetall(f"df:task:progress:{task_no}")
    if not overall_raw:
        # Redis 已过期，回退查 MySQL（任务已结束的历史数据）
        return await get_progress_from_db(task_no)

    # 2. 从 Redis 读取分表进度（HGETALL）
    table_raw = await redis.hgetall(f"df:task:table_progress:{task_no}")

    # 3. 计算各表实时速率（滑动窗口）
    tables = []
    total_rate = 0
    for table_name, progress_json in table_raw.items():
        progress = json.loads(progress_json)
        rate = await get_insert_rate(redis, task_no, table_name)
        total_rate += rate
        tables.append({
            **progress,
            "table_name": table_name,
            "insert_rate": round(rate),
            "progress_percent": round(progress["success"] / progress["target"] * 100, 1)
                                if progress["target"] > 0 else 0
        })

    # 4. 计算整体进度和预计剩余时间
    target_total = int(overall_raw["target_total"])
    success_total = int(overall_raw["success_total"])
    remaining = target_total - success_total
    estimated_remaining = round(remaining / total_rate) if total_rate > 0 else None

    return ApiResponse(data={
        "task_no": task_no,
        "status": overall_raw["status"],
        "elapsed_seconds": int(time.time()) - int(overall_raw["start_at"]),
        "batch_size": int(overall_raw["batch_size"]),
        "concurrency": int(overall_raw["concurrency"]),
        "overall": {
            "target_total": target_total,
            "success_total": success_total,
            "fail_total": int(overall_raw["fail_total"]),
            "progress_percent": round(success_total / target_total * 100, 1),
            "insert_rate": round(total_rate),
            "estimated_remaining_seconds": estimated_remaining,
        },
        "tables": sorted(tables, key=lambda x: x["table_name"])
    })
```

#### 6.6.4 前端轮询策略

```typescript
// composables/useTaskProgress.ts
export function useTaskProgress(taskNo: string) {
  const progress = ref<TaskProgressData | null>(null)
  let timer: ReturnType<typeof setInterval>
  let pollInterval = 2000   // 初始 2 秒

  const startPolling = () => {
    timer = setInterval(async () => {
      const res = await api.getTaskProgress(taskNo)
      progress.value = res.data

      const s = res.data.status
      if (['success', 'failed', 'partial_success', 'aborted'].includes(s)) {
        clearInterval(timer)   // 终态停止轮询
        return
      }

      // 动态调整轮询频率：进度越快轮询越频繁
      const rate = res.data.overall.insert_rate
      if (rate > 100_000) pollInterval = 1000      // 高速：1s
      else if (rate > 10_000) pollInterval = 2000  // 中速：2s
      else pollInterval = 3000                      // 低速：3s

    }, pollInterval)
  }

  const stopPolling = () => clearInterval(timer)
  onUnmounted(stopPolling)

  return { progress, startPolling, stopPolling }
}
```

#### 6.6.5 强制停止接口

```
POST /api/v1/tasks/{task_no}/abort
Authorization: Bearer {jwt}
```

后端实现：
```python
@router.post("/{task_no}/abort")
async def abort_task(task_no: str, user=Depends(get_current_user)):
    task = await get_task_by_no(task_no)
    # 权限校验：只能停止自己的任务
    if task.created_by != user.id and user.group_type != 99:
        raise HTTPException(403, "无权停止该任务")
    # 向 Celery 发送 revoke 信号（terminate=True 强制停止）
    celery_app.control.revoke(task.celery_task_id, terminate=True)
    # 更新任务状态
    await update_task_status(task.id, status="aborted")
    await redis.hset(f"df:task:progress:{task_no}", "status", "aborted")
    return ApiResponse(message="任务已停止")
```

### 6.7 ITERATE_LIST 遍历驱动策略实现

`ITERATE_LIST` 在执行引擎中是一个特殊的「驱动层」，在进入批次执行前被识别并改变整体执行模式：

```python
# app/engine/executor.py

def detect_iterate_driver(config: CaseConfig) -> IterateDriver | None:
    """识别 Case 中是否存在 ITERATE_LIST 驱动字段"""
    for fc in config.field_configs:
        if fc.strategy == "ITERATE_LIST":
            return IterateDriver(
                table=config.main_table,
                column=fc.column_name,
                drive_values=fc.strategy_params["values"],      # ["qwer","asdf","zxcv"]
                rows_per_value=fc.strategy_params["rows_per_value"],  # 10
            )
    return None


async def execute_iterate_mode(task_id: int, config: CaseConfig, driver: IterateDriver):
    """遍历驱动模式执行入口"""
    total_rounds = len(driver.drive_values)

    for round_idx, drive_value in enumerate(driver.drive_values):
        # 更新 Redis：当前轮次信息
        await redis.hset(f"df:task:progress:{task_no}", mapping={
            "current_round": round_idx + 1,
            "total_rounds": total_rounds,
            "current_drive_value": drive_value,
        })

        # 将当前 drive_value 注入到本轮的 config 中
        round_config = inject_drive_value(config, driver.column, drive_value)

        # 执行本轮（复用普通模式的批次执行器，仅修改驱动字段值为固定值）
        round_result = await execute_single_round(
            task_id=task_id,
            config=round_config,
            target_count=driver.rows_per_value,
            round_no=round_idx,
        )

        # 某轮失败不中止，记录后继续下一轮
        if round_result.status == "failed":
            await record_round_failure(task_id, round_idx, drive_value, round_result.error)
            continue

    await finalize_task(task_id)


def inject_drive_value(config: CaseConfig, column: str, value: str) -> CaseConfig:
    """将驱动字段的策略临时替换为 CUSTOM_VALUE（固定值），
    关联字段同步替换，保证本轮所有关联表都插入相同的 drive_value"""
    new_config = config.model_copy(deep=True)
    # 1. 主驱动字段改为固定值
    for fc in new_config.field_configs:
        if fc.column_name == column:
            fc.strategy = "CUSTOM_VALUE"
            fc.strategy_params = {"value": value}
    # 2. 所有关联字段也改为相同固定值
    for assoc in new_config.associations:
        if assoc.source_column == column:
            # 找到目标表配置中的对应字段，同样注入固定值
            new_config.related_overrides[assoc.target_table][assoc.target_column] = value
    return new_config
```

**df_exec_batch_log 的 round_no 字段扩展：**

遍历模式下，`df_exec_batch_log` 需记录当前轮次和 drive_value，便于「重试失败轮次」功能定位：

```sql
-- 在 df_exec_batch_log 表新增两列
ALTER TABLE df_exec_batch_log
    ADD COLUMN round_no      SMALLINT DEFAULT NULL COMMENT '遍历模式轮次序号（从0开始）',
    ADD COLUMN drive_value   VARCHAR(500) DEFAULT NULL COMMENT '遍历模式当前驱动值';
```

---

### 6.8 性能基准与参数建议

#### 6.8.1 目标场景定义

**用户核心性能需求：3 张表各插入 1000 万条数据（总计 3000 万条），期望在 1~2 小时内完成。**

---

#### 6.8.2 理论性能推算

**基准吞吐量（8 核服务器，目标 DB 同局域网，无多余索引）：**

| 配置 | 吞吐量 | 说明 |
|------|--------|------|
| 单线程，批次 1000 条 | ~5,000 条/s | 基准线 |
| 8 线程，批次 1000 条 | ~35,000 条/s | 默认配置 |
| 8 线程，批次 5000 条 | ~50,000 条/s | 千万级推荐配置 |
| 16 线程，批次 5000 条 | ~70,000 条/s | 上限，受 DB 连接池约束 |

**3000 万条在不同配置下的预计耗时：**

| 执行方式 | 吞吐量 | 3000万条耗时 | 是否满足 1~2h |
|----------|--------|-------------|---------------|
| 3 表串行，8 线程，批次 5000 | ~50,000/s | **约 10 分钟** | ✅ 远满足 |
| 3 表串行，8 线程，批次 1000 | ~35,000/s | **约 14 分钟** | ✅ 满足 |
| 3 表有依赖串行（最坏情况） | ~50,000/s | **约 20~30 分钟** | ✅ 满足 |
| 跨公网访问目标 DB | ~5,000/s | **约 100 分钟** | ⚠️ 边界，略有风险 |

> **结论：在局域网/同机房环境下，当前 8 线程架构可在 15~30 分钟内完成 3000 万条插入，远优于 1~2 小时目标。**
> 唯一风险场景是跨公网访问，该场景下可能逼近 1~2 小时上限，需结合实际网络情况调优。

---

#### 6.8.3 实际影响性能的关键因素

**① 目标表索引数量（影响最大）**

| 目标表索引数 | 实际吞吐量衰减 | 3000万条额外增加耗时 |
|-------------|---------------|---------------------|
| 0~1 个索引 | 无衰减（基准） | +0 分钟 |
| 2~3 个普通索引 | 衰减 30~50% | +10~20 分钟 |
| 5+ 个索引 | 衰减 60~70% | +20~40 分钟 |
| 含全文/空间索引 | 衰减 80%+ | +40~80 分钟 |

系统在进入字段配置页时检测索引数，执行弹窗展示动态预警：

```
⚠️ 检测到目标表含 5 个索引，大批量插入时索引维护会显著降低速度。
   建议：造数完成后重建索引，或提前与 DBA 确认是否可临时禁用非关键索引。
   预计实际速度：~15,000 条/s（较基准降低约 70%）
   重新预估耗时：约 33 分钟（原预估 10 分钟）
```

**② MySQL InnoDB 缓冲池（innodb_buffer_pool_size）**

| 目标表数据量 | 缓冲池建议 | 说明 |
|-------------|-----------|------|
| < 500 万条 | 默认即可 | 无影响 |
| 500 万~2000 万条 | 建议 ≥ 4GB | 后期速度下降 30~50% |
| 2000 万条以上 | 建议 ≥ 16GB | 必须调优，否则速度骤降 80% |

**③ 网络延迟**

| 网络环境 | 单批次 RTT | 速度影响 |
|----------|-----------|----------|
| 同机器（localhost） | < 0.1ms | 无影响 |
| 同局域网 | 1~5ms | 轻微 |
| 跨城市专线 | 5~30ms | 速度降低 30~60% |
| 公网访问 | 30~100ms | 速度降低 70~90% |

**④ 触发器 / 外键约束**

- 触发器：每行 INSERT 触发一次，速度降低 50~90%
- 外键约束：每次插入需验证父表，速度降低 20~50%

系统执行前通过 `information_schema` 检测触发器和外键，存在时在弹窗中明确警告。

---

#### 6.8.4 推荐执行参数（自动计算）

```python
def recommend_exec_params(target_per_table: int, table_count: int,
                           index_count: int, has_trigger: bool) -> ExecParams:
    total = target_per_table * table_count

    if total <= 100_000:
        batch_size, max_workers = 500, 4
    elif total <= 1_000_000:
        batch_size, max_workers = 1_000, 8
    elif total <= 10_000_000:
        batch_size, max_workers = 3_000, 8
    else:                          # 千万级以上
        batch_size, max_workers = 5_000, 16

    if index_count >= 5:           # 索引多时降并发，减少锁竞争
        max_workers = max(4, max_workers // 2)
        batch_size = min(batch_size, 2_000)

    if has_trigger:                # 有触发器强制单线程
        max_workers, batch_size = 1, 500

    return ExecParams(batch_size=batch_size, max_workers=max_workers)
```

执行弹窗底部展示推荐参数和预估耗时，用户可手动覆盖。

---

#### 6.8.5 千万级造数专项优化

**① 显式事务批量提交**（默认开启，减少 commit 次数）

```python
async with engine.begin() as conn:
    await conn.execute(text(bulk_insert_sql), rows)
```

**② 临时关闭索引检查**（可选，用户在执行弹窗勾选，默认关闭）

```python
await conn.execute(text("SET unique_checks=0; SET foreign_key_checks=0;"))
# ... 批量插入 ...
await conn.execute(text("SET unique_checks=1; SET foreign_key_checks=1;"))
```

> 提示文案：「关闭唯一索引检查可提速 30~50%，但若数据存在重复值将导致索引损坏，请确认数据无重复后再开启。」

**③ 超千万条自动任务分片**

单表超 1000 万条时，自动拆分为多个 500 万条子任务，由不同 Worker 并行处理：

```
总任务（1 张表 1000 万条）
    ├── 子任务 A：第 1~500 万条  → Worker-1
    └── 子任务 B：第 501~1000 万条 → Worker-2
```

父任务汇总子任务状态，进度面板展示子任务维度明细。

---

#### 6.8.6 各规模场景完整耗时预估表

> 假设：8 核服务器，局域网，目标表 2~3 个普通索引，无触发器，无外键

| 场景 | 每表条数 | 总条数 | 推荐配置 | 预计耗时 | 满足 1~2h |
|------|---------|--------|----------|----------|-----------|
| 小量 | 1,000 | 3,000 | 默认 | < 1s | ✅ |
| 中量 | 100,000 | 300,000 | 默认 | 约 15s | ✅ |
| 大量 | 1,000,000 | 3,000,000 | 8线程/批3000 | 约 3~5 分钟 | ✅ |
| **目标场景** | **10,000,000** | **30,000,000** | **16线程/批5000** | **约 15~30 分钟** | **✅** |
| 超大量 | 50,000,000 | 150,000,000 | 16线程/批5000 | 约 1.5~2.5 小时 | ⚠️ 边界 |
| 极大量 | 100,000,000 | 300,000,000 | 需分片+专项调优 | 约 3~6 小时 | ❌ |

**目标场景（3×1000万）关键变量影响：**

| 影响因素 | 乐观（局域网+少索引） | 悲观（公网+多索引） |
|----------|---------------------|-------------------|
| 预计耗时 | **15~20 分钟** | **60~120 分钟** |
| 结论 | ✅ 远满足 | ⚠️ 边界，需优化 |

> **最终结论：在局域网、索引 ≤ 3 个、缓冲池 ≥ 4GB 的标准配置下，3 张表各 1000 万条可在 15~30 分钟内完成，充分满足 1~2 小时目标。**
> 若目标 DB 在公网或存在大量索引，系统会在执行弹窗中自动预警并给出优化建议。

#### 6.8.7 性能调优参数汇总（系统配置项）

```python
class ExecutorSettings(BaseSettings):
    MAX_WORKERS: int = 8                    # 并发线程数（千万级建议 16）
    BATCH_SIZE_OVERRIDE: int | None = None  # None=自动计算
    BATCH_MAX_RETRY: int = 3                # 单批次最大重试次数
    FAIL_RATE_THRESHOLD: float = 0.5        # 失败率超过此值停止任务
    ITERATE_PARALLEL_ROUNDS: bool = False   # ITERATE_LIST 是否并发执行各轮
    AUTO_SPLIT_THRESHOLD: int = 10_000_000  # 超过此条数自动分片（条/表）
    DISABLE_UNIQUE_CHECKS: bool = False     # 是否临时关闭唯一索引检查
    DISABLE_FK_CHECKS: bool = False         # 是否临时关闭外键检查
```

### 6.9 场景执行技术方案

场景执行建立在单 Case 执行体系之上，引入 DAG 调度层。

#### 6.9.1 场景执行 Celery 任务设计

```python
# tasks/scene_task.py
@celery_app.task(
    bind=True,
    max_retries=0,
    acks_late=True,
    track_started=True,
)
def execute_scene(self, scene_exec_id: int):
    """场景执行主任务：负责 DAG 调度，不直接插入数据"""
    scene_exec = db.get(SceneExec, scene_exec_id)
    snapshot = json.loads(scene_exec.scene_snapshot)

    nodes = snapshot["nodes"]
    edges = snapshot["edges"]

    # 1. 拓扑分层
    layers = build_layers(nodes, edges)

    # 2. 初始化 Redis 场景进度
    await init_scene_progress(scene_exec.scene_exec_no, nodes, layers)

    # 3. 逐层执行
    for layer_no, layer_node_ids in enumerate(layers):
        layer_nodes = [n for n in nodes if n["node_id"] in layer_node_ids]

        # 3a. 并行提交本层所有节点（每个节点独立触发 execute_data_gen）
        node_exec_records = await submit_layer_nodes(
            scene_exec_id, scene_exec.scene_exec_no, layer_no, layer_nodes
        )

        # 3b. 轮询等待本层所有节点达到终态（每 2 秒检查一次 Redis）
        await wait_for_layer_completion(
            scene_exec.scene_exec_no, layer_node_ids, timeout=7200
        )

        # 3c. 检查失败策略：是否有 abort 节点失败
        should_abort = await check_abort_policy(
            scene_exec.scene_exec_no, layer_node_ids, node_exec_records
        )
        if should_abort:
            # 取消后续所有层的节点
            remaining_node_ids = [
                nid
                for future_layer in layers[layer_no + 1:]
                for nid in future_layer
            ]
            await cancel_remaining_nodes(
                scene_exec_id, scene_exec.scene_exec_no, remaining_node_ids
            )
            await finalize_scene(scene_exec_id, status="failed")
            return

    await finalize_scene(scene_exec_id, status=compute_final_status(scene_exec_id))
```

#### 6.9.2 节点提交与进度同步

```python
async def submit_layer_nodes(
    scene_exec_id: int,
    scene_exec_no: str,
    layer_no: int,
    layer_nodes: list[dict],
) -> list[SceneNodeExec]:
    """并行提交一层内的所有节点，每个节点对应一个独立的 df_exec_task"""
    records = []
    for node in layer_nodes:
        # 创建节点执行记录
        node_exec = SceneNodeExec(
            scene_exec_id=scene_exec_id,
            node_id=node["node_id"],
            case_id=node["case_id"],
            case_name=node["case_name"],
            layer_no=layer_no,
            target_count=node["target_count"],
            fail_strategy=node["fail_strategy"],
            status=0,  # 待执行
        )
        db.add(node_exec)
        await db.flush()

        # 为节点创建独立的 exec_task（复用现有 Case 执行体系）
        exec_task = await create_exec_task(
            case_id=node["case_id"],
            target_count=node["target_count"],
            created_by=scene_exec.created_by,
            scene_exec_id=scene_exec_id,    # 反向关联，用于进度归并
            scene_node_exec_id=node_exec.id,
        )

        # 提交 Celery 任务（复用 execute_data_gen，节点执行完毕后回调更新场景进度）
        celery_task = celery_app.send_task(
            "tasks.execute_data_gen",
            args=[exec_task.id],
            kwargs={"scene_exec_no": scene_exec_no, "node_id": node["node_id"]},
        )

        node_exec.exec_task_id = exec_task.id
        node_exec.exec_task_no = exec_task.task_no
        node_exec.status = 1  # 执行中

        # 更新 Redis 节点状态
        await redis.hset(
            f"df:scene:node_progress:{scene_exec_no}",
            node["node_id"],
            json.dumps({
                "status": "running",
                "target": node["target_count"],
                "success": 0,
                "task_no": exec_task.task_no,
                "layer": layer_no,
            }),
        )
        records.append(node_exec)

    await db.commit()
    return records
```

#### 6.9.3 场景进度查询接口

```
GET /api/v1/scenes/{scene_exec_no}/progress
Authorization: Bearer {jwt}
```

响应结构：

```json
{
  "code": 0,
  "data": {
    "scene_exec_no": "SC20260708001",
    "status": "running",
    "total_layers": 3,
    "current_layer": 1,
    "elapsed_seconds": 28,
    "overall": {
      "node_count": 4,
      "success_count": 1,
      "fail_count": 0,
      "pending_count": 1,
      "running_count": 2,
      "target_rows": 4500,
      "success_rows": 1300
    },
    "layers": [
      {
        "layer_no": 0,
        "status": "success",
        "nodes": [
          {
            "node_id": "n_abc123",
            "case_name": "用户信息Case",
            "status": "success",
            "target": 1000,
            "success": 1000,
            "task_no": "TK20260708001"
          }
        ]
      },
      {
        "layer_no": 1,
        "status": "running",
        "nodes": [
          {
            "node_id": "n_def456",
            "case_name": "商品信息Case",
            "status": "running",
            "target": 500,
            "success": 300,
            "task_no": "TK20260708002"
          },
          {
            "node_id": "n_ghi789",
            "case_name": "地址信息Case",
            "status": "running",
            "target": 1000,
            "success": 0,
            "task_no": "TK20260708003"
          }
        ]
      },
      {
        "layer_no": 2,
        "status": "pending",
        "nodes": [
          {
            "node_id": "n_jkl012",
            "case_name": "订单信息Case",
            "status": "pending",
            "target": 2000,
            "success": 0,
            "task_no": null
          }
        ]
      }
    ]
  }
}
```

后端读取 `df:scene:progress:{scene_exec_no}` + `df:scene:node_progress:{scene_exec_no}` 两个 Redis Key 聚合返回，前端每 2 秒轮询一次。

#### 6.9.4 Celery 任务队列补充

```python
CELERY_TASK_ROUTES = {
    "tasks.execute_data_gen":   {"queue": "high"},     # 造数执行，高优先
    "tasks.execute_scene":      {"queue": "high"},     # 场景调度，高优先
    "tasks.sync_datasource":    {"queue": "normal"},   # 数据源同步
    "tasks.heartbeat_check":    {"queue": "low"},      # 心跳检测
    "tasks.scheduled_sync":     {"queue": "low"},      # 定时同步
}
```

场景调度任务（`execute_scene`）本身消耗资源极少，主要是轮询等待和触发子任务，与 `execute_data_gen` 同队列避免调度延迟。

### 6.10 多级关联执行与关联表字段策略覆盖

#### 6.10.1 多级关联（A→B→C 链式）

关联配置 `associations[]` 支持 `source_table` 字段（缺省为主表），允许**关联表再作为源关联其他表**：

```
tax_change.id_card_no ──→ user.id_card_no ──→ salary.id_card_no
（主表 → 关联表，一级）     （关联表 → 关联表，多级）
```

执行链路（`executor.py`）：

```python
# 1. 拓扑排序确定插入顺序（dep_analyzer.build_insert_order，Kahn 算法）
ctx.insert_order = build_insert_order(ctx.main_table, ctx.associations)
# 结果示例：[tax_change, user, salary] —— 保证源表先于目标表插入

# 2. 每批次内按插入顺序逐表生成；目标表的关联列从本批已生成数据按行取值
def _source_values(source_table, source_column):
    if source_table in generated:   # 源表已在本批生成 → 按行对齐取值
        return [row.get(source_column) for row in generated[source_table]]
    return _sample_source_values(...)  # 断点重试场景：从目标库采样

# 3. 生成时注入覆盖：injected_columns 优先级高于一切策略
#    （data_generator.py：列在 injected_columns 中则直接使用注入值）
```

**行对齐保证：** 同一批次内各表行数一致（均为 batch_size），注入值列表与目标表行按索引一一对应，因此三表（或多表）的关联字段逐行一致。

**校验（`engine_service.validate_case_config` / `executor._validate_associations`）：**
- 源表必须在造数范围内（主表或某个关联目标表）
- 源字段存在且策略非 SKIP（自增主键不能作为关联源）
- 同一目标列只能被一个源字段关联
- 表级循环关联检测（Kahn 拓扑排序失败即存在环）

#### 6.10.2 关联表字段策略覆盖（related_field_configs）

```
df_case.config_json
├── field_configs            # 主表字段策略（前端主表 Tab 编辑）
├── associations             # 关联关系（含多级）
└── related_field_configs    # 关联表字段策略覆盖（前端关联表 Tab 编辑）
    └── {表名: [FieldConfig, ...]}
```

执行器构建各表字段配置的优先级（`_build_table_field_configs`）：

```
主表   → 快照 field_configs（必有）
关联表 → 快照 related_field_configs[table]（有则用）
       → 缓存字段元数据自动推断（_infer_field_configs_from_cache，兜底）
```

保存校验规则（`validate_case_config` 第 6 步）：
- `related_field_configs` 的表必须是关联目标表（未纳入造数范围的表配置无意义，报错）
- 关联表字段**禁止 ITERATE_LIST**（遍历驱动只能是主表字段，否则各表行数无法对齐）
- 策略合法性 + 参数校验与主表一致
- 表结构变更检测（1402）覆盖关联表已配置字段

前端交互（`FieldConfig.vue`）：字段表格顶部表 Tab 切换（主表 + 各关联表）；被关联注入的列禁用策略编辑并标记「关联注入」；删除关联后无关联的表配置随 Tab 移除。

#### 6.10.3 表操作量 Top10 统计口径

总览「表操作量 Top10」**按实际插入表聚合**，数据源为 `df_exec_batch_log`（每表每批次一条记录）：

```sql
SELECT l.table_name, t.datasource_name, SUM(l.batch_size) AS row_count, COUNT(DISTINCT t.case_id)
FROM df_exec_batch_log l JOIN df_exec_task t ON l.task_id = t.id
WHERE t.created_at >= :start AND l.status = 1  -- 仅成功批次
GROUP BY l.table_name, t.datasource_name
ORDER BY row_count DESC LIMIT 10
```

- 主表与关联表各自独立成项（`ExecTask.success_count` 为任务全表合计，无法按表拆分，故不用于此统计）
- 重试不双计：同批次先失败后重试成功产生两条日志，仅 status=1 的成功条参与求和

## 7. 部署架构（Docker）

### 7.1 容器化设计原则

DataForge 所有服务均以 Docker 容器方式运行，遵循以下原则：

| 原则 | 说明 |
|------|------|
| 一容器一进程 | 每个容器只运行一个主进程（API / Worker / Beat / Nginx 分别独立容器） |
| 镜像不含秘钥 | 密码、密钥全部通过环境变量或 Docker Secret 注入，不写入镜像 |
| 无状态服务横向扩展 | api / worker-high / worker-normal 均为无状态，直接 `--scale` 扩容 |
| 有状态服务挂载卷 | mysql / redis 数据目录挂载 Named Volume，容器重建不丢数据 |
| 统一健康检查 | 所有服务配置 `healthcheck`，Compose 依赖关系基于健康状态而非启动顺序 |

### 7.2 镜像规范

#### 7.2.1 后端 Dockerfile

```dockerfile
# backend/Dockerfile
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- 运行时镜像（精简层）----
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

WORKDIR /app
# 只复制依赖，不复制源码中的 .env / 秘钥文件
COPY --from=builder /install /usr/local
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini pyproject.toml ./

# 非 root 用户运行
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

#### 7.2.2 前端 Dockerfile（多阶段构建）

```dockerfile
# frontend/Dockerfile
FROM node:20-alpine AS builder

WORKDIR /build
COPY package*.json ./
RUN npm ci --frozen-lockfile
COPY . .
RUN npm run build       # 输出到 /build/dist

# ---- Nginx 运行时 ----
FROM nginx:alpine
COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### 7.3 完整 Docker Compose 配置

```yaml
# docker-compose.yml
version: '3.9'

# 公共环境变量锚点
x-api-env: &api-env
  DATABASE_URL: mysql+aiomysql://dataforge:${MYSQL_PASSWORD}@mysql:3306/dataforge_db
  REDIS_URL: redis://redis:6379/0
  NACOS_SERVER: nacos:8848          # Nacos 地址（见第 8 章）
  NACOS_NAMESPACE: ${NACOS_NS:-}    # 命名空间，默认 public
  NACOS_GROUP: DATAFORGE_GROUP
  SECRET_KEY: ${SECRET_KEY}
  AES_KEY: ${AES_KEY}
  LOG_LEVEL: ${LOG_LEVEL:-INFO}
  TZ: Asia/Shanghai

services:

  # ── 基础中间件 ──────────────────────────────────────────────────

  mysql:
    image: mysql:8.0
    restart: unless-stopped
    environment:
      MYSQL_DATABASE: dataforge_db
      MYSQL_USER: dataforge
      MYSQL_PASSWORD: ${MYSQL_PASSWORD}
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      TZ: Asia/Shanghai
    volumes:
      - mysql_data:/var/lib/mysql
      - ./sql/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    ports:
      - "3306:3306"       # 生产环境建议移除，仅内网访问
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "dataforge", "-p${MYSQL_PASSWORD}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    deploy:
      resources:
        limits:
          memory: 2g

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: >
      redis-server
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
      --save 60 1000
      --appendonly yes
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 640m

  nacos:
    image: nacos/nacos-server:v2.3.2
    restart: unless-stopped
    environment:
      MODE: standalone              # 单机模式（生产建议集群，见 8.2 节）
      SPRING_DATASOURCE_PLATFORM: mysql
      MYSQL_SERVICE_HOST: mysql
      MYSQL_SERVICE_PORT: 3306
      MYSQL_SERVICE_DB_NAME: nacos_db
      MYSQL_SERVICE_USER: dataforge
      MYSQL_SERVICE_PASSWORD: ${MYSQL_PASSWORD}
      NACOS_AUTH_ENABLE: "true"
      NACOS_AUTH_TOKEN: ${NACOS_AUTH_TOKEN}
      JVM_XMS: 256m
      JVM_XMX: 512m
      TZ: Asia/Shanghai
    volumes:
      - nacos_logs:/home/nacos/logs
    ports:
      - "8848:8848"
      - "9848:9848"     # gRPC 端口（Nacos 2.x 客户端通信）
    depends_on:
      mysql:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8848/nacos/v1/console/health/liveness"]
      interval: 15s
      timeout: 5s
      retries: 8
      start_period: 60s
    deploy:
      resources:
        limits:
          memory: 640m

  # ── 应用服务 ────────────────────────────────────────────────────

  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      <<: *api-env
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
      nacos:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 20s
    deploy:
      replicas: 2               # 默认 2 副本，可 --scale api=N 扩容
      resources:
        limits:
          memory: 1g

  worker-high:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: celery -A app.celery_app worker -Q high -c 8 --loglevel=info
    restart: unless-stopped
    environment:
      <<: *api-env
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "celery", "-A", "app.celery_app", "inspect", "ping", "-d", "celery@$$HOSTNAME"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    deploy:
      replicas: 2               # 造数压力大时可 --scale worker-high=N 扩容
      resources:
        limits:
          memory: 2g

  worker-normal:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: celery -A app.celery_app worker -Q normal,low -c 4 --loglevel=info
    restart: unless-stopped
    environment:
      <<: *api-env
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 1g

  beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: celery -A app.celery_app beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    restart: unless-stopped
    environment:
      <<: *api-env
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      replicas: 1               # Beat 必须单实例，禁止扩容
      resources:
        limits:
          memory: 256m

  nginx:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./ssl:/etc/nginx/ssl:ro  # HTTPS 证书（生产环境）
    depends_on:
      api:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 128m

volumes:
  mysql_data:
  redis_data:
  nacos_logs:
```

### 7.4 Nginx 配置

```nginx
# nginx.conf
upstream dataforge_api {
    # 多 api 副本时 Nginx 自动轮询负载均衡
    server api:8000;
}

server {
    listen 80;
    server_name _;

    # 前端静态资源（SPA）
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
        gzip on;
        gzip_types text/plain application/javascript text/css application/json;
        gzip_min_length 1024;
        expires 7d;                 # 静态资源缓存 7 天
        add_header Cache-Control "public, immutable";
    }

    # index.html 不缓存（保证发版后立即生效）
    location = /index.html {
        root /usr/share/nginx/html;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # API 反向代理
    location /api/ {
        proxy_pass http://dataforge_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;    # 造数任务提交
        proxy_connect_timeout 10s;
    }

    # Nacos 控制台代理（可选，方便内网访问）
    location /nacos/ {
        proxy_pass http://nacos:8848/nacos/;
        proxy_set_header Host $host;
    }
}
```

### 7.5 环境变量文件（.env 模板）

```dotenv
# .env.example  — 复制为 .env 并填写实际值，禁止提交到 Git

# MySQL
MYSQL_PASSWORD=your_strong_password
MYSQL_ROOT_PASSWORD=your_root_password

# 应用秘钥
SECRET_KEY=your_jwt_secret_key_at_least_32_chars
AES_KEY=your_aes_key_32bytes_base64encoded

# Nacos
NACOS_AUTH_TOKEN=your_nacos_auth_token_at_least_32_chars
NACOS_NS=                          # 留空=public 命名空间，或填写具体 namespace-id

# 日志级别（DEBUG/INFO/WARNING/ERROR）
LOG_LEVEL=INFO
```

### 7.6 常用运维命令

```bash
# 首次启动（含构建镜像）
docker compose up -d --build

# 查看所有容器状态
docker compose ps

# 扩容造数 Worker（临时扩到 4 个实例）
docker compose up -d --scale worker-high=4

# 仅重建并重启 API（发版）
docker compose up -d --build --no-deps api

# 查看 API 实时日志
docker compose logs -f api

# 查看 Worker 日志
docker compose logs -f worker-high worker-normal

# 执行数据库迁移
docker compose exec api alembic upgrade head

# 进入 MySQL 容器
docker compose exec mysql mysql -u dataforge -p dataforge_db

# 停止所有服务（保留数据卷）
docker compose stop

# 销毁所有容器（数据卷保留）
docker compose down

# 销毁所有容器 + 数据卷（⚠️ 数据不可恢复）
docker compose down -v
```

### 7.7 服务依赖关系与启动顺序

```
mysql ──┬──► nacos
        │
        └──► redis ──┬──► api ──────────► nginx
                     │
                     ├──► worker-high
                     ├──► worker-normal
                     └──► beat
```

健康检查机制保证依赖服务就绪后才启动下游服务，无需手动控制启动顺序。

### 7.8 扩容说明

| 服务 | 是否可横向扩容 | 扩容命令 | 注意事项 |
|------|-------------|---------|---------|
| api | ✅ | `--scale api=N` | Nginx upstream 自动感知新实例 |
| worker-high | ✅ | `--scale worker-high=N` | 注意 DB 连接池总数 = N × pool_size ≤ MySQL max_connections |
| worker-normal | ✅ | `--scale worker-normal=N` | 同上 |
| beat | ❌ 单实例 | 禁止 scale | 多实例会导致定时任务重复执行 |
| nginx | ✅（通常不需要） | `--scale nginx=N` + LB | 需上层 LB 配合 |
| mysql | ❌ 单机版 | 需改为主从/MGR | 超大规模时迁移到独立 MySQL 集群 |
| redis | ❌ 单机版 | 需改为 Redis Sentinel/Cluster | 高可用需求时迁移 |
| nacos | ❌ standalone | 需改为 3 节点集群 | 见 8.2 节 |

---

## 8. Nacos 集成方案

### 8.1 集成定位

DataForge 引入 Nacos 承担两个职责：

| 职责 | 说明 |
|------|------|
| **配置中心** | 将环境相关配置（DB 连接串、Redis 地址、Celery 参数、日志级别等）集中存储在 Nacos，服务启动时拉取，配置变更时热更新，无需重启容器 |
| **服务注册** | API 实例启动后向 Nacos 注册自身，Beat/Worker 通过 Nacos 感知 API 健康状态；后期扩展微服务时提供服务发现基础 |

### 8.2 Nacos 部署模式选择

| 模式 | 适用场景 | 说明 |
|------|---------|------|
| **standalone（单机）** | 开发 / 测试 / 小规模生产 | Docker Compose 默认，1 个容器，MySQL 持久化配置 |
| **cluster（3 节点集群）** | 生产高可用 | 3 个 Nacos 节点 + 共享 MySQL，需独立 docker-compose.cluster.yml |

本文档以单机模式描述，集群模式只需将 `MODE=standalone` 改为 `MODE=cluster` 并配置节点列表，应用侧代码无需改动。

### 8.3 Nacos 命名空间与配置分组规划

```
Nacos
└── Namespace: dataforge-prod（生产）/ dataforge-dev（开发）
    └── Group: DATAFORGE_GROUP
        ├── dataforge-common.yaml      # 公共配置（日志、跨域、分页默认值）
        ├── dataforge-db.yaml          # MySQL 数据库连接配置
        ├── dataforge-redis.yaml       # Redis 连接配置
        ├── dataforge-celery.yaml      # Celery 执行参数（批次大小、并发数等）
        ├── dataforge-security.yaml    # JWT 有效期、加密参数（不含明文秘钥）
        └── dataforge-datasync.yaml    # 数据源同步策略配置
```

> 敏感值（密码、私钥）不存入 Nacos，仍通过 Docker 环境变量注入；Nacos 存储的是可热更新的业务参数。

### 8.4 配置文件内容示例

#### dataforge-common.yaml

```yaml
app:
  name: DataForge
  version: "1.0"
  debug: false
  timezone: Asia/Shanghai

cors:
  origins:
    - "http://localhost:5173"
    - "https://your-production-domain.com"

pagination:
  default_page_size: 20
  max_page_size: 100

log:
  level: INFO
  structured: true        # true=JSON格式，false=可读格式
```

#### dataforge-db.yaml

```yaml
database:
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  pool_recycle: 3600
  echo: false             # 是否打印 SQL，生产 false
```

#### dataforge-celery.yaml

```yaml
celery:
  worker_high_concurrency: 8
  worker_normal_concurrency: 4
  task_soft_time_limit: 7200      # 单任务软超时（秒）
  task_time_limit: 7800           # 单任务硬超时（秒）

executor:
  default_batch_size: 3000
  max_workers: 8
  batch_max_retry: 3
  fail_rate_threshold: 0.5
  auto_split_threshold: 10000000
  disable_unique_checks: false
  disable_fk_checks: false
```

#### dataforge-datasync.yaml

```yaml
datasync:
  scheduled_hour: 2          # 凌晨 2 点定时同步
  scheduled_minute: 0
  heartbeat_interval: 30     # 心跳检测间隔（秒）
  cache_ttl_tables: 43200    # 表列表缓存 TTL（秒，12h）
  cache_ttl_columns: 43200
  sync_lock_ttl: 300         # 同步分布式锁 TTL（秒）
```

### 8.5 Python 客户端集成

依赖库选型：`nacos-sdk-python`（官方 SDK，支持配置监听和服务注册）

```python
# requirements.txt 新增
nacos-sdk-python==2.0.0
```

#### 8.5.1 Nacos 客户端封装

```python
# app/core/nacos_client.py
import nacos
import yaml
from typing import Any
from app.config import settings
import structlog

logger = structlog.get_logger()

class NacosConfigManager:
    """Nacos 配置中心客户端，支持启动拉取和热更新监听"""

    def __init__(self):
        self._client = nacos.NacosClient(
            server_addresses=settings.NACOS_SERVER,   # 如 "nacos:8848"
            namespace=settings.NACOS_NAMESPACE,
            username=settings.NACOS_USERNAME,
            password=settings.NACOS_PASSWORD,
        )
        self._config_cache: dict[str, dict] = {}
        self._group = settings.NACOS_GROUP             # "DATAFORGE_GROUP"

    def get_config(self, data_id: str) -> dict[str, Any]:
        """拉取配置，返回解析后的字典"""
        raw = self._client.get_config(data_id, self._group, timeout=5)
        if not raw:
            logger.warning("nacos_config_empty", data_id=data_id)
            return {}
        parsed = yaml.safe_load(raw)
        self._config_cache[data_id] = parsed
        return parsed

    def add_listener(self, data_id: str, callback):
        """注册配置变更监听（热更新）"""
        def _on_change(tenant, group, data_id, content):
            new_config = yaml.safe_load(content) if content else {}
            self._config_cache[data_id] = new_config
            logger.info("nacos_config_updated", data_id=data_id)
            callback(new_config)

        self._client.add_config_watcher(data_id, self._group, _on_change)

    def get_cached(self, data_id: str) -> dict[str, Any]:
        return self._config_cache.get(data_id, {})


nacos_config = NacosConfigManager()
```

#### 8.5.2 应用启动时拉取配置

```python
# app/core/config_loader.py
from app.core.nacos_client import nacos_config
from app.config import settings   # 基础配置（秘钥等仍读环境变量）
import structlog

logger = structlog.get_logger()

# 运行时动态配置对象（热更新会修改此对象的属性）
class RuntimeConfig:
    celery_batch_size: int = 3000
    celery_max_workers: int = 8
    log_level: str = "INFO"
    datasync_heartbeat_interval: int = 30
    # ... 其他可热更新参数

runtime_config = RuntimeConfig()


def load_nacos_configs():
    """应用启动时统一拉取所有 Nacos 配置"""
    _data_ids = [
        "dataforge-common.yaml",
        "dataforge-db.yaml",
        "dataforge-redis.yaml",
        "dataforge-celery.yaml",
        "dataforge-datasync.yaml",
    ]
    for data_id in _data_ids:
        try:
            nacos_config.get_config(data_id)
            logger.info("nacos_config_loaded", data_id=data_id)
        except Exception as e:
            # Nacos 不可用时降级使用环境变量默认值，不阻断启动
            logger.warning("nacos_config_load_failed", data_id=data_id, error=str(e))

    # 注册热更新监听
    nacos_config.add_listener("dataforge-celery.yaml", _on_celery_config_change)
    nacos_config.add_listener("dataforge-common.yaml", _on_common_config_change)


def _on_celery_config_change(new_config: dict):
    """Celery 参数热更新回调（无需重启 Worker）"""
    executor = new_config.get("executor", {})
    runtime_config.celery_batch_size = executor.get("default_batch_size", 3000)
    runtime_config.celery_max_workers = executor.get("max_workers", 8)
    logger.info("celery_config_hot_updated", new_config=executor)


def _on_common_config_change(new_config: dict):
    log_cfg = new_config.get("log", {})
    runtime_config.log_level = log_cfg.get("level", "INFO")
```

#### 8.5.3 与 FastAPI lifespan 集成

```python
# app/main.py（片段）
from app.core.config_loader import load_nacos_configs

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 拉取 Nacos 配置（Nacos 不可用时降级，不阻断启动）
    load_nacos_configs()

    # 2. 注册服务实例到 Nacos
    await register_service_instance()

    # 3. 初始化 DB / Redis 连接池
    await startup()

    yield

    # 关闭时注销服务实例
    await deregister_service_instance()
    await shutdown()
```

### 8.6 服务注册与健康检查

```python
# app/core/nacos_registry.py
import nacos
import socket
from app.config import settings
import structlog

logger = structlog.get_logger()

_client = nacos.NacosClient(
    server_addresses=settings.NACOS_SERVER,
    namespace=settings.NACOS_NAMESPACE,
    username=settings.NACOS_USERNAME,
    password=settings.NACOS_PASSWORD,
)

SERVICE_NAME = "dataforge-api"


async def register_service_instance():
    """API 启动时注册到 Nacos 服务列表"""
    ip = socket.gethostbyname(socket.gethostname())   # 容器内 IP
    try:
        _client.add_naming_instance(
            service_name=SERVICE_NAME,
            ip=ip,
            port=8000,
            cluster_name="DEFAULT",
            weight=1.0,
            metadata={
                "version": settings.APP_VERSION,
                "env": settings.ENV,
            },
            healthy=True,
            ephemeral=True,    # 临时实例：进程退出后 Nacos 自动摘除
        )
        logger.info("nacos_service_registered", service=SERVICE_NAME, ip=ip, port=8000)
    except Exception as e:
        logger.warning("nacos_service_register_failed", error=str(e))


async def deregister_service_instance():
    """API 优雅退出时注销"""
    ip = socket.gethostbyname(socket.gethostname())
    try:
        _client.remove_naming_instance(SERVICE_NAME, ip, 8000)
        logger.info("nacos_service_deregistered", service=SERVICE_NAME)
    except Exception as e:
        logger.warning("nacos_service_deregister_failed", error=str(e))
```

FastAPI 同时暴露健康检查端点供 Nacos 心跳探测：

```python
# app/api/v1/health.py
from fastapi import APIRouter
from app.db.session import check_db_health
from app.core.redis_client import check_redis_health

router = APIRouter()

@router.get("/api/health")
async def health_check():
    """Docker healthcheck + Nacos 心跳探测端点"""
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    status = "UP" if (db_ok and redis_ok) else "DEGRADED"
    return {
        "status": status,
        "db": "UP" if db_ok else "DOWN",
        "redis": "UP" if redis_ok else "DOWN",
    }
```

### 8.7 配置优先级与降级策略

```
优先级（高 → 低）：
  1. 环境变量（秘钥、连接串等不可热更新的敏感配置）
  2. Nacos 配置中心（可热更新的业务参数）
  3. 代码内默认值（Nacos 不可用时的最终兜底）
```

降级行为：
- Nacos 拉取失败 → 记录 WARNING 日志，使用代码默认值，**不阻断服务启动**
- Nacos 监听连接中断 → SDK 自动重连（指数退避），重连成功后恢复配置推送
- Nacos 服务不可用 → 已加载的配置缓存在内存中继续生效，不影响正在运行的任务

### 8.8 新增环境变量（.env 补充）

```dotenv
# Nacos 连接（追加到 .env）
NACOS_SERVER=nacos:8848
NACOS_NAMESPACE=               # 留空=public，生产建议填写专用 namespace-id
NACOS_GROUP=DATAFORGE_GROUP
NACOS_USERNAME=nacos
NACOS_PASSWORD=${NACOS_AUTH_TOKEN}
```

### 8.9 Nacos 控制台操作指引

| 操作 | 路径 | 说明 |
|------|------|------|
| 访问控制台 | `http://{host}:8848/nacos` | 默认账号 nacos/nacos，首次登录后修改 |
| 新建命名空间 | 命名空间 → 新建 | 建议 dev / test / prod 三套环境隔离 |
| 导入配置 | 配置管理 → 导入 | 将 `config/nacos/` 目录下的 yaml 文件批量导入 |
| 查看服务列表 | 服务管理 → 服务列表 | 可看到所有注册的 dataforge-api 实例及健康状态 |
| 手动下线实例 | 服务管理 → 实例列表 → 下线 | 滚动发版时手动摘流量 |

---

## 9. 目录结构

### 9.1 后端目录结构

```
backend/
├── app/
│   ├── main.py                 # 应用入口
│   ├── config.py               # 配置（pydantic-settings）
│   ├── celery_app.py           # Celery 实例
│   │
│   ├── api/                    # 路由层
│   │   ├── v1/
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── datasources.py
│   │   │   ├── engine.py
│   │   │   ├── cases.py
│   │   │   ├── scenes.py       # 场景管理路由（增删改查 + 执行 + 进度）
│   │   │   ├── tasks.py
│   │   │   ├── tools.py
│   │   │   ├── overview.py
│   │   │   └── ai.py           # AI 预留接口
│   │   └── deps.py             # 公共依赖（auth、pagination）
│   │
│   ├── services/               # 业务逻辑层
│   │   ├── user_service.py
│   │   ├── datasource_service.py
│   │   ├── engine_service.py
│   │   ├── case_service.py
│   │   ├── scene_service.py    # 场景CRUD、复制、执行触发、进度查询
│   │   ├── task_service.py
│   │   ├── overview_service.py
│   │   └── tool_service.py
│   │
│   ├── engine/                 # 造数引擎核心
│   │   ├── executor.py         # 执行器主逻辑（单Case执行）
│   │   ├── scene_executor.py   # 场景执行器（DAG调度层）
│   │   ├── data_generator.py   # 数据生成器
│   │   ├── dep_analyzer.py     # 依赖关系分析（拓扑排序，Case内+场景DAG共用）
│   │   └── strategies/         # 策略实现
│   │       ├── base.py
│   │       ├── registry.py
│   │       ├── string_strategies.py
│   │       ├── number_strategies.py
│   │       ├── time_strategies.py
│   │       └── pk_strategies.py
│   │
│   ├── models/                 # SQLAlchemy ORM 模型
│   │   ├── user.py
│   │   ├── datasource.py
│   │   ├── cache.py            # df_table_cache 等
│   │   ├── case.py
│   │   ├── scene.py            # df_scene / df_scene_exec / df_scene_node_exec
│   │   └── task.py
│   │
│   ├── schemas/                # Pydantic 请求/响应 Schema
│   │   ├── response.py         # 统一响应格式
│   │   ├── user.py
│   │   ├── datasource.py
│   │   ├── engine.py
│   │   ├── case.py
│   │   ├── scene.py            # SceneCreate/Update/Detail/ExecProgress
│   │   └── task.py
│   │
│   ├── core/
│   │   ├── security.py         # JWT、密码哈希、AES 加密
│   │   ├── logging.py          # structlog 配置
│   │   ├── dynamic_pool.py     # 动态数据源连接池
│   │   ├── redis_client.py     # Redis 连接池
│   │   ├── nacos_client.py     # Nacos 配置中心客户端
│   │   └── nacos_registry.py   # Nacos 服务注册与注销
│   │
│   ├── db/
│   │   ├── session.py          # 系统 DB Session 管理
│   │   └── base.py             # SQLAlchemy Base
│   │
│   └── tasks/                  # Celery 任务
│       ├── execute_task.py     # 造数执行任务（单Case）
│       ├── scene_task.py       # 场景执行任务（DAG调度）
│       ├── sync_task.py        # 数据源同步任务
│       └── scheduled.py        # 定时任务配置
│
├── alembic/                    # 数据库迁移
│   ├── versions/
│   └── env.py
├── tests/
├── Dockerfile
├── requirements.txt
└── pyproject.toml              # ruff + mypy 配置
```

### 9.2 前端目录结构（简版）

```
frontend/
├── src/
│   ├── api/          # 接口请求（按模块）
│   │   ├── auth.ts
│   │   ├── datasource.ts
│   │   ├── engine.ts
│   │   ├── cases.ts
│   │   ├── scenes.ts       # 场景管理接口（CRUD + 执行 + 进度轮询）
│   │   ├── tasks.ts
│   │   └── overview.ts
│   ├── assets/       # 静态资源（猫咪SVG等）
│   ├── components/   # 公共组件
│   │   ├── common/
│   │   ├── layout/
│   │   └── business/
│   │       ├── SceneCanvas.vue        # 场景编排画布（节点拖拽+连线）
│   │       ├── SceneNodeCard.vue      # 画布中的节点卡片
│   │       ├── SceneProgressPanel.vue # 场景执行进度面板
│   │       └── ...
│   ├── composables/  # Composition API hooks
│   │   ├── useAuth.ts
│   │   ├── useTaskProgress.ts         # 单Case任务进度轮询
│   │   ├── useSceneProgress.ts        # 场景执行进度轮询
│   │   └── useDatasource.ts
│   ├── router/       # 路由配置
│   ├── stores/       # Pinia 状态
│   │   ├── auth.ts
│   │   ├── datasource.ts
│   │   ├── taskProgress.ts            # 执行中的单Case任务列表
│   │   └── sceneProgress.ts           # 执行中的场景任务列表
│   ├── styles/       # 主题 + 全局样式
│   ├── utils/        # 工具函数
│   └── views/        # 页面组件
│       ├── login/
│       ├── overview/
│       ├── engine/
│       │   ├── TableList.vue
│       │   └── FieldConfig.vue
│       ├── cases/
│       ├── scenes/                    # 场景管理
│       │   ├── SceneList.vue          # 场景列表页
│       │   ├── SceneEditor.vue        # 场景编排页（含画布）
│       │   └── SceneDetail.vue        # 场景详情只读页
│       ├── tools/
│       ├── datasource/
│       └── admin/
├── public/
├── vite.config.ts
├── tsconfig.json
└── package.json
```

---

## 10. API 路由清单

> 前后端对接的权威参考，所有接口均以 `/api/v1/` 为前缀。认证方式：JWT Bearer Token（AI 接口除外）。

### 10.1 认证模块 `/api/v1/auth`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/auth/login` | 公开 | 用户登录，返回 JWT Token |
| POST | `/auth/register` | 公开 | 提交注册申请 |
| POST | `/auth/logout` | 已登录 | 主动登出，Token 加入黑名单 |
| GET  | `/auth/me` | 已登录 | 获取当前用户信息及权限列表 |

### 10.2 用户管理模块 `/api/v1/users`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET  | `/users/pending` | `USER:APPROVE` | 获取待审批用户列表 |
| POST | `/users/{id}/approve` | `USER:APPROVE` | 审批通过，分配权限 |
| POST | `/users/{id}/reject` | `USER:APPROVE` | 审批拒绝，填写原因 |
| GET  | `/users` | `USER:APPROVE` | 获取全部用户列表（分页） |
| PUT  | `/users/{id}/permissions` | `USER:PERMISSION` | 更新用户菜单权限 |
| POST | `/users/{id}/disable` | `USER:DISABLE` | 禁用用户 |
| POST | `/users/{id}/enable` | `USER:DISABLE` | 启用用户 |
| POST | `/users/{id}/reset-password` | `USER:DISABLE` | 重置密码（返回临时密码） |
| PUT  | `/users/me/password` | 已登录 | 修改自己密码 |
| PUT  | `/users/me/avatar` | 已登录 | 更新头像序号 |
| PUT  | `/users/me/default-datasource` | 已登录 | 设置默认数据源 |
| GET  | `/users/audit-logs` | 已登录 | 查询操作日志（普通用户看本组，管理员看全量） |

### 10.3 数据源模块 `/api/v1/datasources`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET  | `/datasources` | `DATASOURCE:VIEW` | 数据源列表（含连接状态） |
| POST | `/datasources` | `DATASOURCE:ADD` | 新增数据源 |
| PUT  | `/datasources/{id}` | `DATASOURCE:EDIT` | 编辑数据源 |
| DELETE | `/datasources/{id}` | `DATASOURCE:DELETE` | 删除数据源 |
| POST | `/datasources/test` | `DATASOURCE:ADD` | 测试连接（表单页按钮，不保存） |
| POST | `/datasources/{id}/sync` | `DATASOURCE:EDIT` | 手动触发表结构同步 |
| GET  | `/datasources/{id}/status` | `DATASOURCE:VIEW` | 获取数据源连接状态（心跳） |

### 10.4 造数引擎模块 `/api/v1/engine`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET  | `/engine/tables` | `ENGINE:VIEW` | 获取指定数据源的表列表（含字段数、主键类型等） |
| GET  | `/engine/tables/{table_name}/columns` | `ENGINE:VIEW` | 获取表字段详情（含自动推断策略） |
| GET  | `/engine/tables/{table_name}/indexes` | `ENGINE:VIEW` | 获取表索引信息 |
| POST | `/engine/execute` | `ENGINE:EXECUTE` | 创建 Case 并立即执行（返回 task_no） |
| POST | `/engine/save` | `ENGINE:CREATE` | 仅保存 Case，不执行 |

Query 参数：`/engine/tables?datasource_id={id}&keyword={kw}&sort=name|rows|columns`

### 10.5 Case 管理模块 `/api/v1/cases`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET  | `/cases` | `CASE:VIEW` | Case 列表（分页 + 筛选） |
| GET  | `/cases/{id}` | `CASE:VIEW` | Case 详情（含 config_json） |
| PUT  | `/cases/{id}` | `CASE:EDIT` | 修改 Case 配置 |
| DELETE | `/cases/{id}` | `CASE:DELETE` | 逻辑删除 Case |
| POST | `/cases/{id}/execute` | `CASE:EXECUTE` | 执行 Case（返回 task_no） |
| POST | `/cases/{id}/copy` | `CASE:COPY` | 复制 Case |
| GET  | `/cases/{id}/history` | `CASE:VIEW` | 查看 Case 执行历史 |
| POST | `/cases/batch-execute` | `CASE:EXECUTE` | 批量执行（多个 case_id + 各自条数） |

### 10.6 场景管理模块 `/api/v1/scenes`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET  | `/scenes` | `SCENE:VIEW` | 场景列表（分页 + 筛选） |
| GET  | `/scenes/{id}` | `SCENE:VIEW` | 场景详情（含 nodes_json + edges_json） |
| POST | `/scenes` | `SCENE:CREATE` | 新建场景 |
| PUT  | `/scenes/{id}` | `SCENE:EDIT` | 编辑场景 |
| DELETE | `/scenes/{id}` | `SCENE:DELETE` | 逻辑删除场景 |
| POST | `/scenes/{id}/execute` | `SCENE:EXECUTE` | 执行场景（返回 scene_exec_no） |
| POST | `/scenes/{id}/copy` | `SCENE:CREATE` | 复制场景 |
| GET  | `/scenes/{id}/history` | `SCENE:VIEW` | 场景执行历史列表 |
| GET  | `/scenes/exec/{scene_exec_no}/progress` | `SCENE:VIEW` | 场景执行实时进度 |
| POST | `/scenes/exec/{scene_exec_no}/abort` | `SCENE:EXECUTE` | 强制停止场景 |
| POST | `/scenes/exec/{scene_exec_no}/retry-nodes` | `SCENE:EXECUTE` | 重试失败节点 |

### 10.7 任务进度模块 `/api/v1/tasks`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET  | `/tasks/{task_no}/progress` | 已登录 | 获取任务实时进度（前端每 2s 轮询） |
| POST | `/tasks/{task_no}/abort` | 已登录 | 强制停止任务 |
| POST | `/tasks/{task_no}/retry-batches` | 已登录 | 重试失败批次（断点续传） |
| GET  | `/tasks/{task_no}/detail` | 已登录 | 任务详情（含分批次日志） |

### 10.8 造数总览模块 `/api/v1/overview`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET  | `/overview/metrics` | `OVERVIEW:VIEW` | 核心指标卡片数据（6 个指标） |
| GET  | `/overview/trend` | `OVERVIEW:VIEW` | 执行趋势折线图数据（近7/30/90天） |
| GET  | `/overview/status-dist` | `OVERVIEW:VIEW` | 执行状态分布饼图数据 |
| GET  | `/overview/table-top10` | `OVERVIEW:VIEW` | 表操作量 Top10 柱状图数据 |
| GET  | `/overview/member-rank` | `OVERVIEW:VIEW` | 成员贡献排行数据 |
| GET  | `/overview/exec-records` | `OVERVIEW:VIEW` | 执行记录明细表（分页 + 筛选） |

### 10.9 快捷工具模块 `/api/v1/tools`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/tools/idcard` | `TOOL:USE` | 生成身份证号 |
| POST | `/tools/phone` | `TOOL:USE` | 生成手机号 |
| POST | `/tools/bankcard` | `TOOL:USE` | 生成银行卡号 |
| POST | `/tools/name` | `TOOL:USE` | 生成随机姓名 |
| POST | `/tools/credit-code` | `TOOL:USE` | 生成统一社会信用代码 |
| POST | `/tools/taxpayer-id` | `TOOL:USE` | 生成纳税人识别号 |
| POST | `/tools/address` | `TOOL:USE` | 生成随机地址 |
| POST | `/tools/date` | `TOOL:USE` | 批量生成日期 |
| POST | `/tools/uuid` | `TOOL:USE` | 批量生成 UUID |
| POST | `/tools/snowflake` | `TOOL:USE` | 生成雪花 ID |

> 以上工具接口均为 POST，请求体包含生成参数，响应体包含生成结果列表。前端导出功能在本地完成，无需额外接口。

### 10.10 消息通知模块 `/api/v1/notifications`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET  | `/notifications/unread-count` | 已登录 | 获取未读消息数量（前端每 60s 轮询） |
| GET  | `/notifications` | 已登录 | 消息列表（分页，支持筛选已读/未读/优先级） |
| POST | `/notifications/{id}/read` | 已登录 | 标记单条消息为已读 |
| POST | `/notifications/read-all` | 已登录 | 全部标为已读 |

### 10.11 健康检查

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET  | `/api/health` | 公开 | 服务健康检查（Docker healthcheck + Nacos 心跳探测） |

---

## 11. 数据库索引策略与查询优化

### 11.1 高频查询分析

以下为系统运行时最常触发的查询，每条均需验证索引覆盖情况：

| 查询场景 | 涉及表 | SQL 关键条件 | 命中索引 |
|---------|--------|------------|---------|
| Case 列表（带分组过滤） | `df_case` | `group_type=? AND is_deleted=0 ORDER BY created_at DESC` | `idx_group_ds(group_type, datasource_id)` + 补充索引 |
| 执行记录列表（带时间范围） | `df_exec_task` | `group_type=? AND created_at BETWEEN ? AND ?` | `idx_group_created(group_type, created_at)` ✅ |
| 总览趋势聚合（近 30 天） | `df_exec_task` | `group_type=? AND created_at >= ? GROUP BY DATE(created_at)` | `idx_group_created` ✅ |
| 表结构缓存查询 | `df_column_cache` | `datasource_id=? AND table_name=?` | `uk_ds_table_col(datasource_id, table_name, column_name)` ✅ |
| 消息未读数查询 | `df_notification` | `user_id=? AND is_read=0 AND is_deleted=0` | `idx_user_read(user_id, is_read, is_deleted)` ✅ |
| 场景执行记录查询 | `df_scene_exec` | `group_type=? AND created_at >= ?` | `idx_group_created(group_type, created_at)` ✅ |
| 操作日志查询（本组） | `df_audit_log` | `user_id IN (本组用户列表)` OR `action=? AND created_at >=?` | `idx_action(action)` + `idx_created(created_at)` |

### 11.2 需补充的索引

原 DDL 中以下表缺少高频查询所需索引，需补充：

```sql
-- df_case：列表页按创建时间倒序 + 分组过滤
ALTER TABLE df_case
    ADD INDEX idx_group_created_at (group_type, is_deleted, created_at);

-- df_case：按主表名查询（总览 Top10 下钻）
-- idx_main_table 已存在，确认覆盖 (datasource_id, main_table) ✅

-- df_notification：按用户+时间查询（消息列表分页）
-- idx_user_created 已存在 ✅

-- df_audit_log：按用户+时间（个人日志）
ALTER TABLE df_audit_log
    ADD INDEX idx_user_created (user_id, created_at);

-- df_exec_batch_log：遍历模式按 round_no 重试查询
ALTER TABLE df_exec_batch_log
    ADD INDEX idx_task_round (task_id, round_no, status);
```

### 11.3 config_json 大字段性能评估

`df_case.config_json` 和 `df_scene.nodes_json` 类型为 `MEDIUMTEXT`，需注意：

| 场景 | 风险 | 缓解策略 |
|------|------|---------|
| Case 列表查询 | SELECT * 会加载大字段，影响内存和网络 | 列表接口**禁止** SELECT *，明确列出非 JSON 字段，config_json 仅在详情页单独查询 |
| Case 执行时读取 config | 单次读取约 1~50 KB，可接受 | Celery Worker 只在任务开始时读一次，不重复查询 |
| 大规模字段配置（100+ 字段） | config_json 可能达到 100 KB+ | 加压测试验证，必要时拆分为独立的 `df_case_field_config` 表（二期优化） |

### 11.4 慢查询监控配置建议

```sql
-- MySQL 开启慢查询日志（建议生产环境配置）
SET GLOBAL slow_query_log = ON;
SET GLOBAL long_query_time = 0.5;      -- 超过 500ms 记录
SET GLOBAL slow_query_log_file = '/var/log/mysql/slow.log';
```

Docker Compose 中通过 MySQL 配置文件挂载：

```ini
# mysql/conf.d/custom.cnf
[mysqld]
slow_query_log = ON
long_query_time = 0.5
slow_query_log_file = /var/log/mysql/slow.log
innodb_buffer_pool_size = 2G        # 生产环境建议 >= 2G
max_connections = 500               # 见第 12 章连接数规划
```

---

## 12. 连接数规划与资源预算

### 12.1 问题背景

MySQL 默认 `max_connections=151`，若各服务连接池配置不当，总连接数会超限导致 `Too many connections` 错误，直接影响造数任务执行。

### 12.2 各服务连接数计算

**系统 MySQL（dataforge_db）：**

| 服务 | 副本数 | 每副本连接池 pool_size | 最大溢出 max_overflow | 最大连接数 |
|------|--------|----------------------|----------------------|----------|
| api | 2 | 10 | 10 | 2 × (10+10) = **40** |
| worker-high | 2 | 5 | 5 | 2 × (5+5) = **20** |
| worker-normal | 1 | 5 | 5 | 1 × (5+5) = **10** |
| beat | 1 | 2 | 2 | 1 × (2+2) = **4** |
| **系统 DB 合计** | — | — | — | **≈ 74** |

**目标数据源 MySQL（用户业务库）：**

| 服务 | 副本数 | 每副本每数据源 pool_size | 数据源数量（估算） | 最大连接数 |
|------|--------|------------------------|-----------------|----------|
| worker-high（造数） | 2 | 5 | 最多 3 个并发 | 2 × 5 × 3 = **30** |

**Redis 连接数：**

| 服务 | 副本数 | Redis 连接池 | 合计 |
|------|--------|-------------|------|
| api | 2 | 20 | 40 |
| worker-high | 2 | 10 | 20 |
| worker-normal | 1 | 10 | 10 |
| **Redis 合计** | — | — | **≈ 70** |

### 12.3 MySQL 配置建议

```ini
# 系统 MySQL
max_connections = 200           # 留余量：74（业务）+ 20（管理连接）+ 缓冲
wait_timeout = 600
interactive_timeout = 600
```

```ini
# 目标数据源 MySQL（用户业务库，不由本系统管理，仅建议）
max_connections = 100           # 造数专用账号限制为 50 以内
```

### 12.4 连接池参数最终配置

```python
# app/config.py
class DatabaseSettings(BaseSettings):
    # 系统 DB（dataforge_db）
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # 目标数据源（动态连接池）
    TARGET_DS_POOL_SIZE: int = 5
    TARGET_DS_MAX_OVERFLOW: int = 5
    TARGET_DS_POOL_RECYCLE: int = 1800
```

### 12.5 扩容时的连接数约束

按第 7 章扩容说明，扩容 worker-high 时需同步评估连接数：

```
当 worker-high 扩容到 N 副本时：
  系统 DB 连接数 = 74 + (N-2) × 10
  目标 DB 连接数 = N × 5 × 并发数据源数

建议：worker-high 最多扩到 4 副本，系统 DB max_connections 保持 300 以内。
超过 4 副本时需同步调大目标数据源的 max_connections 并评估其服务器承载。
```

---

## 13. 数据库迁移策略（Alembic）

### 13.1 迁移文件规范

```
alembic/
├── env.py                          # Alembic 环境配置
├── script.py.mako                  # 迁移脚本模板
└── versions/
    ├── 001_init_schema.py          # 初始建表（所有 DDL）
    ├── 002_add_scene_tables.py     # 新增场景管理表
    ├── 003_add_notification.py     # 新增消息通知表
    └── 004_add_batch_log_round.py  # df_exec_batch_log 新增 round_no 列
```

命名规范：`{序号三位}_{功能描述}.py`，序号全局递增，禁止并行编号。

### 13.2 开发环境迁移流程

```bash
# 1. 新建迁移脚本（自动检测 ORM 模型变更）
docker compose exec api alembic revision --autogenerate -m "add_notification_table"

# 2. 检查生成的迁移脚本，确认 upgrade/downgrade 内容正确
# 3. 执行迁移
docker compose exec api alembic upgrade head

# 4. 查看当前版本
docker compose exec api alembic current

# 5. 回滚一个版本（仅限开发环境）
docker compose exec api alembic downgrade -1
```

### 13.3 生产环境变更流程

```
1. 开发环境验证迁移脚本（upgrade + downgrade 均测试）
2. 提交 PR，迁移脚本与代码变更在同一 PR
3. 部署时先执行迁移，再启动新版本 API：
      docker compose exec api alembic upgrade head
      docker compose up -d --no-deps api
4. 观察 API 健康状态 5 分钟，若异常执行回滚：
      docker compose exec api alembic downgrade -1
      docker compose up -d --no-deps api  # 回滚到旧版本镜像
```

### 13.4 自动执行迁移（可选）

在 API 容器启动命令中前置迁移（适合小团队，无需手动操作）：

```dockerfile
# backend/Dockerfile — 修改 CMD
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4"]
```

> **注意：** 多副本同时启动时可能产生并发迁移，需在 `env.py` 中加分布式锁（使用 `alembic_lock` 表或 Redis 锁）。若副本数 > 1，建议改为独立的 `migrate` 一次性容器：
> ```yaml
> migrate:
>   build: ./backend
>   command: alembic upgrade head
>   depends_on:
>     mysql:
>       condition: service_healthy
>   restart: "no"   # 执行完即退出
> ```

### 13.5 回滚策略

| 场景 | 操作 |
|------|------|
| 新增列（nullable） | 可前向兼容，回滚时 `DROP COLUMN` 即可 |
| 新增表 | 回滚时 `DROP TABLE`（确认无数据或数据可丢弃） |
| 修改列类型 | 高风险，生产环境**禁止直接 ALTER**，改用新增列 + 数据迁移 + 废弃旧列的方式 |
| 删除列 | 极高风险，至少保留一个版本的废弃期，确认代码不再引用后再删除 |

---

## 14. 密钥管理与 AES 密钥轮换

### 14.1 密钥体系概览

| 密钥 | 用途 | 存储位置 | 轮换影响 |
|------|------|---------|---------|
| `SECRET_KEY` | JWT 签名 | 环境变量 | 轮换后所有已签发 Token 立即失效，用户需重新登录 |
| `AES_KEY` | 数据源密码加密 | 环境变量 | 轮换后所有已加密密码需重新加密（见 14.3） |
| `NACOS_AUTH_TOKEN` | Nacos 接口认证 | 环境变量 | 轮换后重启服务即可 |

### 14.2 密钥存储规范

```bash
# .env 文件仅用于开发/测试环境
# 生产环境建议通过 Docker Secret 或密钥管理服务（如 Vault）注入

# SECRET_KEY 生成（32 字节随机）
python -c "import secrets; print(secrets.token_hex(32))"

# AES_KEY 生成（32 字节，Base64 编码）
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

### 14.3 AES_KEY 轮换操作手册

**一期不提供自动化轮换**，需 DBA 手动执行以下步骤：

```bash
# 步骤 1：生成新密钥
NEW_AES_KEY=$(python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())")

# 步骤 2：执行重加密脚本（将所有数据源密码用新密钥重新加密）
docker compose exec api python -m app.scripts.rotate_aes_key \
    --old-key "$OLD_AES_KEY" \
    --new-key "$NEW_AES_KEY"
# 脚本逻辑：读取所有 df_datasource.password → 旧密钥解密 → 新密钥加密 → 写回 DB

# 步骤 3：更新 .env 中的 AES_KEY 并重启服务
docker compose up -d --no-deps api worker-high worker-normal beat
```

重加密脚本需实现为幂等操作（脚本中断可重跑），保证数据安全。

### 14.4 SECRET_KEY 轮换

JWT 密钥轮换会导致所有在线用户被踢出，建议在低峰期操作：

```
操作步骤：
1. 生成新 SECRET_KEY
2. 更新 .env
3. 重启 api 服务（旧 Token 在新实例上校验失败，用户收到 1001 错误后跳转登录页重新登录）
4. Redis 中的 JWT 黑名单可清空（旧 Token 已全部失效，无需保留黑名单）
```

---
