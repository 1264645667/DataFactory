# DataForge 造数工厂

面向测试/开发团队的自动化测试数据生成平台。支持 MySQL 数据源的可视化造数配置、千万级高性能批量插入、Case 模板管理、多 Case 场景编排（DAG 串并行调度）、分组数据权限隔离、14 个内置造数工具，并预留 AI 调用接口。

本文档包含：**目录结构与职责 → 全部配置项说明 → 本地从 0 到前后端联调运行 → 服务器从 0 到生产运行 → 功能验收清单 → 常见问题**。

---

## 1. 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.x(async+sync) / Celery 5 / Redis 7 / MySQL 8 / Alembic / Nacos(可选) |
| 前端 | Vue 3.4 / TypeScript 5 / Vite 5 / Naive UI(暗色) / Pinia / ECharts 5 / @vue-flow/core / UnoCSS |
| 部署 | Docker Compose（mysql / redis / nacos / api×2 / worker-high×2 / worker-normal / beat / nginx） |

默认管理员账号：`popsicle` / `Avaritia14589`（后端首次启动时自动创建，幂等）。

---

## 2. 目录结构与职责

```
DataFactory/
├── docker-compose.yml          # 生产编排：8 个服务一键启动
├── .env.example                # 环境变量模板（docker-compose 用），复制为 .env 后填写
├── README.md                   # 本文档
├── docs/                       # 产品需求(PRD)与架构设计原始文档
│
├── sql/
│   └── init.sql                # MySQL 首次初始化：建库(dataforge_db/nacos_db)、16 张表、补充索引
├── mysql/
│   └── conf.d/custom.cnf       # MySQL 配置：慢查询日志、缓冲池 2G、max_connections=500、utf8mb4
│
├── backend/                    # FastAPI 后端（Python）
│   ├── Dockerfile              # 后端镜像（python:3.11-slim 多阶段）
│   ├── requirements.txt        # 锁定版本依赖
│   ├── pyproject.toml          # ruff + mypy 配置
│   ├── alembic.ini + alembic/  # 数据库迁移（001_init_schema 基于 ORM metadata 建表）
│   └── app/
│       ├── main.py             # 应用工厂：中间件/路由注册/全局异常/生命周期/健康检查 GET /api/health
│       ├── config.py           # Settings 单例（pydantic-settings，读 backend/.env 与环境变量）
│       ├── celery_app.py       # Celery 实例：high/normal/low 三队列、Beat 调度表
│       ├── api/
│       │   ├── deps.py         # 公共依赖：JWT 解析、require_permission 权限工厂、分页、分组过滤
│       │   └── v1/             # 12 个路由模块（共 75 条接口）
│       │       ├── auth.py         # 登录/注册/登出/我的信息（含登录失败 5 次锁定 10 分钟）
│       │       ├── users.py        # 用户审批/权限分配/禁用/重置密码/操作日志
│       │       ├── datasources.py  # 数据源 CRUD/测试连接/同步/心跳状态
│       │       ├── engine.py       # 表列表/字段(含策略自动推断)/索引/创建并执行
│       │       ├── cases.py        # Case CRUD/执行/复制/历史/批量执行
│       │       ├── scenes.py       # 场景 CRUD/执行/进度/中止/重试失败节点
│       │       ├── tasks.py        # 任务进度轮询/强制停止/断点续传/详情
│       │       ├── overview.py     # 总览大屏 6 组统计接口
│       │       ├── tools.py        # 10 个服务端造数工具
│       │       ├── notifications.py# 消息中心（未读数/列表/已读）
│       │       └── ai.py           # AI 预留接口（X-DataForge-AI-Key 独立认证+限流）
│       ├── services/           # 业务逻辑层（路由只做参数/权限，逻辑全部下沉到这里）
│       ├── engine/             # 造数引擎核心（Celery Worker 内运行，全同步实现）
│       │   ├── strategies/         # 14 种造数策略（注册表模式，可插拔扩展；含 DERIVED 运算派生、TOOL_GEN 工具生成）
│       │   ├── executor.py         # 单 Case 执行器：多线程批量 INSERT/重试/断点续传/ITERATE 遍历模式
│       │   ├── scene_executor.py   # 场景 DAG 调度器：拓扑分层/并行提交/失败策略
│       │   ├── data_generator.py   # 批量数据生成（列式生成，SKIP 自增列处理）
│       │   ├── dep_analyzer.py     # 依赖拓扑排序（Case 内 + 场景 DAG 共用 Kahn 算法）
│       │   └── db_pool.py          # 目标数据源同步连接池（mysql+pymysql）
│       ├── tasks/              # Celery 任务入口
│       │   ├── execute_task.py     # tasks.execute_data_gen（造数）+ 完成通知
│       │   ├── scene_task.py       # tasks.execute_scene（场景调度）
│       │   ├── sync_task.py        # 表结构同步 / 30s 心跳检测 / 定时全量同步
│       │   ├── scheduled.py        # Beat 调度表（02:00 同步、30s 心跳、03:00 消息清理）
│       │   └── notify_helper.py    # 站内消息写入封装
│       ├── models/             # SQLAlchemy ORM（16 张 df_ 前缀表）
│       ├── schemas/            # Pydantic 请求/响应模型 + errors.py(41 个业务错误码+BizException)
│       ├── core/
│       │   ├── security.py         # bcrypt/JWT(7天+黑名单)/AES-256-CBC 加解密
│       │   ├── dynamic_pool.py     # 目标数据源异步连接池（API 链路用）
│       │   ├── redis_client.py     # 异步+同步双 Redis 客户端
│       │   ├── config_loader.py    # Nacos 配置拉取与热更新（降级不阻断）
│       │   ├── nacos_client.py / nacos_registry.py  # Nacos 客户端封装/服务注册
│       │   └── logging.py          # structlog 结构化日志
│       ├── db/                 # Base + 异步(aiomysql)/同步(pymysql) 双 Session
│       └── scripts/init_data.py# 首启幂等初始化：内置管理员 + 28 条菜单权限数据
│
└── frontend/                   # Vue3 前端
    ├── Dockerfile              # node:20-alpine 构建 → nginx:alpine 运行
    ├── nginx.conf              # 静态资源托管 + /api 反代到 api:8000
    ├── vite.config.ts          # dev 端口 5173，/api 代理到 localhost:8000
    └── src/
        ├── api/                # 11 个接口模块 + types.ts（与后端 Schema 对应的 TS 类型）
        ├── stores/             # auth/datasource/taskProgress(多任务)/sceneProgress
        ├── router/             # 路由 + meta.permission 权限守卫（白名单 /login /register）
        ├── composables/        # useTaskProgress(2s轮询)/useSceneProgress/useDatasource 等
        ├── utils/              # request.ts(Axios封装+1001重登)/errorCode/permission/strategy/dag
        ├── styles/             # Naive UI 暗色主题变量 + 玻璃态/渐变工具类
        ├── components/
        │   ├── layout/             # AppLayout/SideBar(220px可折叠)/TopBar/NotificationBell
        │   ├── common/             # 猫咪SVG/加载/空状态/任务进度面板/悬浮球/重登Modal
        │   └── business/           # 执行确认弹窗/策略参数动态控件
        └── views/              # 18 个页面
            ├── login/ register/    # 登录（左插画右玻璃卡片）/ 注册申请
            ├── overview/           # 造数总览大屏（指标卡+4图表+明细表）
            ├── engine/             # 表列表 + 字段配置页（核心造数界面）
            ├── cases/ scenes/      # Case 管理 / 场景列表+VueFlow 编排画布
            ├── tools/              # 14 个工具卡片（10 个调后端，4 个纯前端本地）
            ├── datasource/         # 数据源管理
            ├── admin/              # 用户管理（仅 ADMIN 可见）
            ├── profile/ notifications/ error/
```

---

## 3. 配置项说明

### 3.1 .env 文件（根目录与后端共用）

| 场景 | 文件 | 读取方 |
|---|---|---|
| 本地开发 + Docker 部署 | 项目根目录 `.env`（由 `.env.example` 复制） | `config.py`（`env_file=".env"`）和 docker-compose 共用 |

### 3.2 全部环境变量

| 变量 | 默认值（代码硬编码） | 说明 |
|---|---|---|
| `DATABASE_URL` | `mysql+aiomysql://popsicle:QY20Lsf%25%21PLfM25Ts%21@172.28.30.59:3306/data_factory` | 系统库连接串（密码已 URL 编码）；本地调试时若要连公司外部实例无需修改 |
| `REDIS_URL` | `redis://:baiwang@172.28.31.239:6379/3` | 外部 Redis；本地无需改 |
| `SECRET_KEY` | `dataforge-dev-secret-key-change-me-in-production` | JWT 签名密钥；**上线前必须换成随机 32 位 hex** |
| `AES_KEY` | 空字符串 | 数据源密码 AES-256 加密密钥（base64 32 字节）；**必须设置，否则数据源保存时报错** |
| `NACOS_SERVER` | `localhost:8848` | Nacos 地址；线上通过环境变量覆盖 |
| `NACOS_NAMESPACE` | 空 | 命名空间 ID，留空 = public |
| `NACOS_GROUP` | `datafactory_group` | 配置分组（控制台创建） |
| `NACOS_DATA_ID` | `popsicle_datafactory_config` | 业务配置 Data ID |
| `NACOS_USERNAME` | `nacos` | Nacos 登录账号 |
| `NACOS_PASSWORD` | `nacos` | Nacos 登录密码 |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |

> **密钥生成命令：**
> ```bash
> python -c "import secrets; print(secrets.token_hex(32))"                           # SECRET_KEY
> python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"  # AES_KEY
> ```
> **AES_KEY 一旦用于加密数据源密码后不可随意更换**，否则已有数据源密码无法解密。

### 3.3 覆盖方式

**方式 A（推荐，本地）**：直接在项目根目录创建 `.env`，填入要覆盖的变量即可（pydantic-settings 自动读取）。示例：

```dotenv
SECRET_KEY=xxx
AES_KEY=xxx
LOG_LEVEL=DEBUG
```

**方式 B（Docker 部署）**：docker-compose.yml 从 `.env` 读取，运行时通过环境变量注入覆盖代码默认值。

**方式 C（Nacos 热更新）**：在控制台创建配置后，Celery 执行参数、日志级别、同步策略等可实时热更新，无需重启服务。

其余常用默认值（都在 `config.py`，可用同名环境变量覆盖）：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 10 / 10 | 系统库连接池 |
| `MAX_WORKERS` | 8 | 造数并发线程数（千万级建议 16） |
| `BATCH_SIZE_OVERRIDE` | None | None=按目标量自动算批次(500~5000) |
| `BATCH_MAX_RETRY` | 3 | 单批次失败重试次数 |
| `FAIL_RATE_THRESHOLD` | 0.5 | 失败率超此值任务整体判失败 |
| `LOGIN_FAIL_MAX_TIMES` / `LOGIN_FAIL_LOCK_SECONDS` | 5 / 600 | 登录失败锁定策略 |
| `CORS_ORIGINS` | `http://localhost:5173,...` | 前端开发服务器来源白名单 |
| `NACOS_*` | localhost:8848 | 本地无 Nacos 时启动会有 WARNING 日志，**属正常降级，不影响运行** |

### 3.4 其他配置文件

| 文件 | 作用 |
|---|---|
| `mysql/conf.d/custom.cnf` | MySQL 运行参数：慢查询阈值 0.5s、`innodb_buffer_pool_size=2G`、`max_connections=500`、utf8mb4 |
| `sql/init.sql` | 建库建表脚本。**仅在 MySQL 数据卷为空时执行一次**（Docker）；本地需手动执行，详见 4.2 |
| `frontend/vite.config.ts` | dev 端口 5173；`/api` 代理到 `http://localhost:8000`；构建分包策略 |
| `frontend/nginx.conf` | 生产前端容器配置：SPA 路由回退、静态资源缓存 7 天、`/api` 反代 upstream `api:8000` |
| `backend/app/celery_app.py` | 队列路由（造数→high、同步→normal、心跳→low）、Beat 定时表 |
| `docker-compose.yml` | 8 服务编排；api 2 副本、worker-high 2 副本（可 `--scale` 扩容）、beat 必须单副本 |

---

## 4. 本地开发调试（从 0 开始）

> 目标：MySQL + Redis + 后端(8000) + Celery Worker + Beat + 前端(5173) 全部跑通，浏览器可登录并造数。
> 以下命令以 Windows PowerShell 为例，macOS/Linux 对应替换即可。

### 4.1 准备运行环境

| 软件 | 版本要求 | 安装方式（任选） |
|---|---|---|
| Python | **3.11 或 3.12**（推荐；锁定依赖均有预编译包。3.13+ 需自行升级 bcrypt/cryptography 等版本） | python.org 官方安装包 |
| Node.js | ≥ 20 | nodejs.org 或 nvm |
| MySQL | 8.0+ | 公司外部实例：`172.28.30.59:3306`（已配置，无需本地安装） |
| Redis | 5+ | 公司外部实例：`172.28.31.239:6379`（已配置，无需本地安装） |
| Nacos | 2.x | 本地 8848（可选，不装也能跑；需热更新时再启动） |

### 4.2 初始化数据库（首次执行）

联系 DBA 在 `172.28.30.59:3306` 创建数据库 `data_factory`，然后执行项目根目录的 `sql/init.sql`（已适配）：

```sql
-- 用 mysql 客户端连接公司库，root 或有 DDL 权限的账号执行
mysql -h 172.28.30.59 -u root -p < sql/init.sql
```

脚本内容：建 `data_factory` 库、16 张表、补充索引、授权 popsicle 账号。**管理员账号 popsicle 不在 SQL 中，由后端首次启动自动创建。**

### 4.3 验证 Redis 连通性

Redis 已配置为公司外部实例 `172.28.31.239:6379 db=3`，无需本地启动。

```powershell
# 若本机有 redis-cli 可验证：
redis-cli -h 172.28.31.239 -p 6379 -a baiwang -n 3 ping   # 返回 PONG
```

### 4.4 配置并启动后端 API

```powershell
cd D:\working_file\DataFactory\backend

# 1) 创建虚拟环境并安装依赖
py -3.11 -m venv .venv            # 或 python -m venv .venv
.\.venv\Scripts\Activate.ps1      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 2) 创建本地配置（内容见 3.3 节，至少填 DATABASE_URL / AES_KEY）
notepad .env

# 3) 启动 API（开发模式，改代码自动重载）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**启动成功的标志**（控制台日志）：
- `startup_complete db=True redis=True`
- Nacos 相关 `WARNING`（如 `nacos_config_load_failed`）属正常降级，忽略即可。

**立即验证：**
- 健康检查：浏览器访问 `http://localhost:8000/api/health` → `{"status":"UP",...}`
- 接口文档：`http://localhost:8000/api/docs`（Swagger UI，75 条接口）
- 首次启动后，`df_user` 表应自动出现 popsicle 账号、`df_menu` 表有 28 条权限数据。

### 4.5 启动 Celery Worker 和 Beat（各开一个终端）

```powershell
cd D:\working_file\DataFactory\backend

# 终端 2：Worker（消费造数/同步/心跳任务）
# Windows 必须加 --pool=solo！默认 prefork 在 Windows 不可用，
# --pool=threads 在部分 Windows 环境会报 PermissionError，实测 solo 最稳定
.\.venv\Scripts\python -m celery -A app.celery_app worker -Q high,normal,low --pool=solo --loglevel=info

# 终端 3：Beat（定时调度：02:00 同步、30s 心跳、03:00 消息清理）
.\.venv\Scripts\python -m celery -A app.celery_app beat --loglevel=info
```

> Linux/macOS 可去掉 `--pool=solo` 使用默认 prefork。生产 Docker 镜像中使用 prefork，无需此参数。
> 仅调页面不接造数时，Worker/Beat 可先不启动；涉及「造数执行、数据源同步、心跳状态」时必须启动 Worker。
> **确认 Worker 启动成功的标志**：日志中列出 `[tasks] . tasks.heartbeat_check . tasks.sync_datasource ...` 共 7 个任务。若列表为空，说明 `celery_app.py` 的 `include=["app.tasks"]` 未生效。

### 4.6 启动前端

```powershell
cd D:\working_file\DataFactory\frontend
npm install          # 首次约 1~2 分钟
npm run dev          # 启动于 http://localhost:5173
```

Vite 已配置 `/api → http://localhost:8000` 代理，前端请求自动转发到后端，无需额外配置。

### 4.6-A 局域网访问（可选）

前端 `vite.config.ts` 已配置 `server.host: '0.0.0.0'`，后端 uvicorn 按上文以 `--host 0.0.0.0` 启动即可：

1. `ipconfig` 查本机局域网 IPv4（如 `192.168.x.x`）
2. 局域网内其他机器访问 `http://<本机IP>:5173`
3. 首次监听 `0.0.0.0` 时 Windows 会弹防火墙授权，勾选「专用网络」允许；未弹窗则在「Windows Defender 防火墙 → 入站规则」手动放行 5173 / 8000 端口

> API 无需改地址：前端请求走相对路径 `/api`，由被访问机器上的 Vite dev server 代理回其本机后端；Celery Worker / Beat 不对外提供 HTTP，无需调整。

### 4.7 PyCharm 打断点调试（详细步骤）

> 目标：FastAPI、Celery Worker、Celery Beat 三个进程全部在 PyCharm 里以 Debug 模式运行，可随时打断点单步排查（如数据源同步卡住、心跳不执行等问题）。

#### 步骤 1：打开项目并配置解释器

1. PyCharm → `Open` → 选择项目根目录 `D:\working_file\DataFactory`（**不要只打开 backend**，否则前端文件看不到）。
2. `File → Settings → Project: DataFactory → Python Interpreter` → 右上角 `⚙ → Add Interpreter → Add Local Interpreter`。
3. 选 `Existing` → 路径填 `D:\working_file\DataFactory\backend\.venv\Scripts\python.exe` → OK。
   - 若还没有 `.venv`，先在 PowerShell 执行 4.4 节第 1 步创建并装依赖。
4. 应用后，Settings 里应能看到 fastapi / celery / sqlalchemy 等包列表，说明解释器识别成功。

#### 步骤 2：标记源码目录（重要，否则 import 报错）

左侧项目树右键 `backend` 文件夹 → `Mark Directory as` → `Sources Root`。
- 这样 `from app.xxx import ...` 才能被 PyCharm 正确解析。
- 若已标记可跳过（文件夹图标会变色）。

#### 步骤 3：创建 3 个运行配置（Run Configuration）

菜单 `Run → Edit Configurations → 左上角 + → Python`，分别创建以下 3 个配置：

**配置 A：FastAPI 后端**

| 字段 | 值 |
|---|---|
| Name | `FastAPI` |
| Module name（切换到 Module 模式，不要用 Script path） | `uvicorn` |
| Parameters | `app.main:app --host 127.0.0.1 --port 8000` |
| Working directory | `D:\working_file\DataFactory\backend` |
| Python interpreter | 步骤 1 配好的 `.venv` 解释器 |

> ⚠️ **调试时一定不要加 `--reload` 参数**，热重载会另起子进程，断点会失效。日常改代码想自动重载时，另建一个带 `--reload` 的配置用普通模式跑。

**配置 B：Celery Worker**

| 字段 | 值 |
|---|---|
| Name | `Celery Worker` |
| Module name | `celery` |
| Parameters | `-A app.celery_app worker -Q high,normal,low --pool=solo --loglevel=info` |
| Working directory | `D:\working_file\DataFactory\backend` |
| Python interpreter | 同上 |

**配置 C：Celery Beat（可选，不需要定时任务时可以不启）**

| 字段 | 值 |
|---|---|
| Name | `Celery Beat` |
| Module name | `celery` |
| Parameters | `-A app.celery_app beat --loglevel=info` |
| Working directory | `D:\working_file\DataFactory\backend` |
| Python interpreter | 同上 |

> **三个配置的 Working directory 都必须是 `backend`**：因为 `config.py` 按相对路径读 `.env`（即 `backend/.env`），工作目录错了会读不到 `AES_KEY` 等配置。
> 无需手动配置环境变量，`.env` 文件由 pydantic-settings 自动加载。

#### 步骤 4：以 Debug 模式启动并打断点

1. 右上角配置下拉框选中 `FastAPI` → 点旁边的 **🐞（Debug）按钮**（不要点 ▶ 普通运行）。
2. 同样方式用 Debug 启动 `Celery Worker`（需要排查异步任务时）。
3. 在代码行号左侧单击打红色断点，触发请求后 PyCharm 会自动停在断点处，可查看变量、单步（F8）、步入（F7）、求值表达式（Alt+F8）。

**各问题对应的推荐断点位置：**

| 排查问题 | 断点位置 |
|---|---|
| 登录失败/Token 问题 | [backend/app/services/auth_service.py](file:///d:/working_file/DataFactory/backend/app/services/auth_service.py) 登录函数入口 |
| 数据源保存报错 | [datasource_service.py](file:///d:/working_file/DataFactory/backend/app/services/datasource_service.py) `create_datasource` |
| 点"测试连接"无心跳数据 | [sync_task.py](file:///d:/working_file/DataFactory/backend/app/tasks/sync_task.py) `heartbeat_check`（Worker 进程内断点） |
| 同步卡住/无结果 | [sync_task.py](file:///d:/working_file/DataFactory/backend/app/tasks/sync_task.py) `_do_sync`（Worker 进程内断点） |
| 造数执行问题 | [execute_task.py](file:///d:/working_file/DataFactory/backend/app/tasks/execute_task.py) + [engine/executor.py](file:///d:/working_file/DataFactory/backend/app/engine/executor.py) |
| 接口返回结构不对 | [backend/app/api/v1/](file:///d:/working_file/DataFactory/backend/app/api/v1/) 对应路由函数 |

> 注意：**Celery 任务的断点必须打在 Worker 进程上**（配置 B 的 Debug 会话），打在 FastAPI 进程上不会触发——API 只是把任务丢进 Redis 队列，真正执行的是 Worker。

#### 步骤 5（可选）：一键同时启动三个配置

`Run → Edit Configurations → + → Compound` → 把 FastAPI / Celery Worker / Celery Beat 都加进去 → 之后选中这个 Compound 配置点 Debug，三个进程一起起。

#### 前端启动与调试

```powershell
cd D:\working_file\DataFactory\frontend
npm install          # 仅首次
npm run dev          # http://localhost:5173
```

- 也可以直接在 PyCharm 里打开 [frontend/package.json](file:///d:/working_file/DataFactory/frontend/package.json)，点 `scripts.dev` 左侧的 ▶ 图标启动。
- 前端断点：浏览器 F12 → Sources 面板找到 `src/` 下的 `.vue/.ts` 文件打断点（Vite 自带 sourcemap）；接口统一拦截点在 [src/utils/request.ts](file:///d:/working_file/DataFactory/frontend/src/utils/request.ts)，可在这里断点观察所有请求/响应。
- Vite 已配置 `/api → http://localhost:8000` 代理，前端直接调 `/api/...` 即可。

#### 手动触发任务辅助调试（不等 Beat 30s 周期）

调试 Worker 任务时，可在 PyCharm 的 Python Console（已加载项目解释器）里直接发任务，立即触发断点：

```python
from app.celery_app import celery_app
celery_app.send_task('tasks.heartbeat_check')          # 触发心跳检测
celery_app.send_task('tasks.sync_datasource', args=[1]) # 触发数据源 1 的表结构同步
```

查看 Redis 中的心跳/缓存结果：

```python
import redis
r = redis.from_url('redis://:baiwang@172.28.31.239:6379/3')
print(r.get('df:ds:status:1'))   # b'online' / b'offline' / None(暂无心跳)
print(r.keys('df:tables:*'))     # 表结构缓存
```

### 4.8 本地常见问题

| 现象 | 原因与解决 |
|---|---|
| `pip install` 报 bcrypt/cryptography 编译错误 | Python 版本过高（3.13+ 无旧版预编译包），换 3.11/3.12；或升级这两个包版本 |
| 启动日志一堆 Nacos WARNING | 本地没装 Nacos，**正常**，配置中心为可选组件 |
| 登录一直转圈/网络错误 | 后端 8000 未启动；或 `backend/.env` 的 DATABASE_URL 密码不对 |
| Celery 启动即报 `ValueError: not enough values to unpack` 或任务不执行 | Windows 没加 `--pool=solo` |
| Worker 启动了但 `[tasks]` 列表为空，任务全部不被消费 | `celery_app.py` 缺少 `include=["app.tasks"]`，任务模块未注册 |
| 数据源一直是「同步中」，列表显示暂无心跳数据 | 上一次同步任务中断导致 Redis 锁未释放。手动清锁：`redis-cli -h 172.28.31.239 -a baiwang -n 3 DEL df:lock:sync:{数据源id}`，并把 `df_datasource.status` 改回 2 后重新点「立即同步」 |
| 大库同步慢（如 1400+ 张表） | 正常现象，同步锁 TTL 已放宽到 30 分钟；期间数据源状态为「同步中」，完成后自动变为「已初始化」并写入表数量 |
| 数据源「测试连接」成功但执行造数没反应 | Worker 未启动，或 Worker 队列名不匹配（确认 `-Q high,normal,low`） |
| 前端 401 反复跳登录 | Token 过期（7 天）属正常；若一直跳，检查系统时间是否准确（JWT 校验时间戳） |
| `Access denied for user 'dataforge'` | 4.2 节用户未创建或密码与 backend/.env 不一致 |

---

## 5. 服务器部署（Docker，从 0 开始）

> 目标：在一台 Linux 服务器上用 Docker Compose 拉起全部服务，通过 `http://服务器IP` 访问。
> **数据库与 Redis 沿用现有公司实例**（MySQL 172.28.30.59:3306/data_factory、Redis 172.28.31.239:6379/db3），部署不新建这两者。
> 配置参考：2C4G 起步，建议 4C8G（Worker 吃内存）。

### 5.1 服务清单与配置项说明

Compose 编排包含 6 类服务（`docker-compose.yml`）：

| 服务 | 说明 | 副本 |
|---|---|---|
| migrate | 一次性容器：启动前自动执行 `alembic upgrade head`（建表/加列，幂等） | 跑一次即退出 |
| api | FastAPI 接口（uvicorn ×4 workers） | 2 |
| worker-high | 造数执行（high 队列，celery -c 8） | 2 |
| worker-normal | 数据源同步/回滚/清理（normal+low 队列，celery -c 4） | 1 |
| beat | 定时任务（心跳 30s、02:00 全量同步、03:00 清通知、03:30 清操作日志） | 1（禁止扩容） |
| nginx | 前端静态资源 + /api 反向代理 | 1 |

`.env` 需要填写的配置项（其余用默认值）：

| 变量 | 说明 | 取值 |
|---|---|---|
| DATABASE_URL | 系统库连接串（密码含特殊字符需 URL 编码） | 沿用现有：`mysql+aiomysql://popsicle:QY20Lsf%25%21PLfM25Ts%21@172.28.30.59:3306/data_factory` |
| REDIS_URL | 系统 Redis（Celery broker + 进度/锁） | 沿用现有：`redis://:baiwang@172.28.31.239:6379/3` |
| SECRET_KEY | JWT 签名密钥 | **必须新生成**（命令见 5.2） |
| AES_KEY | 数据源密码 AES-256 加密密钥 | **必须沿用现有的 `backend/.env` 里的值**，否则库里数据源密码解不开；要换新密钥见 5.6 |
| LOG_LEVEL | 日志级别 | 生产用 INFO |
| NACOS_SERVER 等 | Nacos 配置中心 | 可选，不配则降级用代码默认值（不影响功能） |

> **并发/线程数说明**：worker-high 的 `-c 8` 是 Celery 任务并发数（同时执行的造数任务数），每个任务内部执行器默认再开 8 线程（config.py 的 `MAX_WORKERS`）。目标库扛不住时优先调小 `-c`。要改执行器线程数，在 .env 里加 `MAX_WORKERS=8` 覆盖。

### 5.2 服务器准备

```bash
# Ubuntu 22.04+ 为例，安装 Docker 与 Compose 插件
curl -fsSL https://get.docker.com | bash
sudo systemctl enable --now docker
docker compose version    # 确认 v2.x 可用

# 防火墙放行 80 端口（443 可选）
sudo ufw allow 80/tcp
```

### 5.3 上传代码并配置

```bash
# 方式一：git
git clone <你的仓库地址> DataFactory && cd DataFactory
# 方式二：本地打包上传（排除 node_modules/.venv/dist 等）
#   本地：tar --exclude=node_modules --exclude=.venv --exclude=dist -czvf df.tar.gz .
#   服务器：tar -xzvf df.tar.gz && cd DataFactory

# 生成环境变量文件
cp .env.example .env

# 生成 JWT 密钥（把输出粘贴进 .env 的 SECRET_KEY）
python3 -c "import secrets; print(secrets.token_hex(32))"

# AES_KEY：把本地 backend/.env 里现有的 AES_KEY 原样抄进服务器 .env
#   （查看本地值：cat backend/.env）
#   ⚠️ 不要生成新的——库里 df_datasource.password 是用现有密钥加密的
vi .env
```

### 5.4 构建并启动

```bash
docker compose up -d --build      # 首次构建约 5~15 分钟（拉镜像+装依赖）
docker compose ps                 # 应看到 migrate(Exited 0) + api×2 + worker×3 + beat + nginx
```

启动顺序由 compose 保证：`migrate` 先跑完数据库迁移（新建缺失的表/列，幂等），api/worker/beat 才会起来。

### 5.5 验证部署

```bash
# 1) 容器健康
docker compose ps

# 2) API 健康检查（容器内）
docker compose exec api python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/api/health').read().decode())"
# 期望：{"status":"UP","db":"UP","redis":"UP"}

# 3) 查看启动日志（确认无 ERROR；Nacos 连不上只是 WARNING 降级，可忽略）
docker compose logs api | tail -30
docker compose logs worker-high | tail -20

# 4) 浏览器访问 http://服务器IP → 登录页 → popsicle / Avaritia14589
```

### 5.6 AES_KEY 轮换（可选，只有要换新密钥时才需要）

**直接沿用现有密钥可跳过本节**。要换新密钥时必须先重加密库里的数据源密码，顺序不能反：

```bash
# 1. 先在服务器上把新密钥生成好
python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

# 2. 用旧密钥解密、新密钥重加密（在服务器项目目录下执行；密钥建议用环境变量传，避免留在 shell 历史）
docker compose run --rm --no-deps \
  -e AES_KEY_OLD='<现有 AES_KEY>' -e AES_KEY_NEW='<新 AES_KEY>' \
  api python scripts/rekey_aes.py
# 期望输出：完成：轮换 N 个，跳过 0 个。

# 3. 改 .env 的 AES_KEY 为新密钥，重启全部服务
docker compose up -d
```

脚本幂等可重跑：已用新密钥加密的行会自动跳过；任一行解密失败会中止且不写入。

### 5.7 生产加固建议

| 项 | 操作 |
|---|---|
| HTTPS | 取消 compose 中 nginx 的 443 端口注释，挂载 `./ssl` 证书目录，并在 `frontend/nginx.conf` 增加 443 server |
| 副本扩容 | 造数压力大时 `docker compose up -d --scale worker-high=4`（注意目标库连接数） |
| Nacos | 需要配置热更新时把 `.env` 的 `NACOS_SERVER` 指向公司 Nacos 实例，Data ID 用 `popsicle_datafactory_config`、Group 用 `datafactory_group` |
| 备份 | 定期备份系统库 data_factory（含 Case 配置/执行历史/回滚日志） |

### 5.8 日常运维命令

```bash
docker compose logs -f api                    # 跟踪 API 日志
docker compose logs -f worker-high            # 跟踪造数日志
docker compose exec api alembic upgrade head  # 手动执行数据库迁移（正常启动已自动跑）
docker compose restart worker-high worker-normal   # 重启 Worker（策略代码变更后需要）
docker compose down                           # 停止全部（MySQL/Redis 是外部实例，无本地数据卷风险）
docker compose up -d --build                  # 发版：重新构建并滚动拉起
```

---

## 6. 功能验收清单（按序操作即可全覆盖）

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 登录页 popsicle / Avaritia14589 登录 | 进入总览页，连续输错 5 次密码会锁定 10 分钟（错误码 1005） |
| 2 | 数据源管理 → 新增数据源（填一个真实可连的 MySQL，建议先用本机 MySQL 建个空库测试） | 「测试连接」显示成功；保存后提示后台初始化，1 分钟内缓存状态变 ✅（需 Worker 运行） |
| 3 | 数据源列表 → 连接状态灯 | 🟢 在线（Beat 心跳 30s 刷新） |
| 4 | 造数引擎 → 选中数据源 → 点击任意表 | 字段配置页自动预填策略（自增主键灰色 SKIP、created_at→当前时间等） |
| 5 | 配置若干字段策略 → 创建并执行 → 输入 1000 条 | 弹出实时进度面板（总进度/分表进度/速率），完成后目标表有 1000 行数据 |
| 6 | 配置一个 ITERATE_LIST 字段（如状态列填 3 个值、每值 10 条） | 弹窗变「遍历模式」，执行后每张表 30 行且关联值一致 |
| 6-A | 字段配置页 → 关联管理添加 A→B 关联后，再添加 B→C 关联（源表选 B） | 支持多级链式关联，抽屉内拓扑预览图分层展示；执行后三表关联字段逐行一致 |
| 6-B | 字段配置页切换到关联表 Tab → 给关联表字段配置策略（如数字字段选「字段运算派生」cost=income×0.2；证件号选「快捷工具生成」） | 关联表字段可独立配置策略；被关联注入的列显示「关联注入」且禁用编辑；执行后派生值计算正确、工具生成值格式合法 |
| 7 | Case 管理 → 执行/复制/查看历史/删除 | 历史抽屉有执行记录；复制生成 xxx_copy |
| 8 | 场景管理 → 新建场景，拖 2~3 个 Case 连线编排 → 保存并执行 | 场景进度面板按层展示节点状态，全部完成后场景状态成功 |
| 9 | 快捷工具 → 身份证/手机号生成 100 条 | 结果表格展示，出现「导出 CSV/TXT」按钮，复制可用 |
| 10 | 造数总览 | 指标卡有数据，趋势图/饼图/Top10/成员排行渲染，明细表可筛选 |
| 11 | 顶栏铃铛 | 造数完成/失败收到消息，未读角标正确，点击跳转 |
| 12 | 注册页提交新账号 → 用户管理审批通过并勾选权限 | 新账号可登录，侧边栏只显示被授权菜单，且只能看到本组数据 |
| 13 | 个人中心 | 改密码生效、切换 10 款猫咪头像、操作日志有记录 |

---

## 7. FAQ

**Q：不启动 Nacos 可以吗？**
A：可以。Nacos 只负责配置热更新与服务注册，代码已做全量降级（WARNING 日志）。本地开发与生产均可先不用，后续按 5.5 节接入。

**Q：不启动 Celery Beat 可以吗？**
A：可以，但会缺失：数据源定时同步（02:00）、连接状态心跳（30s，影响状态灯）、消息自动清理（03:00）。核心造数功能不受影响（Worker 才是执行者）。

**Q：改了造数策略/引擎代码后，执行报「未知策略」或行为没变化？**
A：重启 **Celery Worker**。策略注册表是 Worker 进程启动时加载的内存单例，重启 FastAPI 不影响 Worker；同理改了 `engine/` 或 `tasks/` 下任何代码都要重启 Worker 生效。

**Q：表结构变了怎么办？**
A：数据源列表点「立即同步」；或等每天 02:00 自动同步。修改 Case 时若检测到表结构变更，系统会提示可能失效的字段（错误码 1402）。

**Q：造数任务中断了数据会回滚吗？**
A：不会（批量 INSERT 无法跨批次事务）。已插入数据保留，可在任务详情点「重试失败批次」断点续传。

**Q：如何接入二期 AI 造数？**
A：管理员在用户管理页创建 AI API Key 后，以 `X-DataForge-AI-Key` 头调用 `/api/v1/ai/*` 接口（数据源/表/字段查询、创建执行任务、进度查询、策略枚举），详见 `docs/popsicle_产品需求readme.md` 第 10 章。

**Q：目标库是 PostgreSQL/Oracle？**
A：一期仅支持 MySQL（表结构已预留 `db_type` 字段，二期扩展）。

---

> 更详细的产品规则见 `docs/popsicle_产品需求readme.md`（PRD V1.4），架构与原理见 `docs/popsicle_架构设计readme.md`（V1.1）。
