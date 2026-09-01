-- ============================================================================
-- DataForge 造数工厂 — MySQL 首次初始化脚本
-- 目标库：172.28.30.59:3306 / data_factory
-- 依据文档：docs/popsicle_架构设计readme.md 第 4.1 / 6.7 / 11.2 节
--
-- 重要说明：
--   1. 管理员账号 popsicle 不在本脚本中插入，由后端首次启动脚本自动创建
--      （bcrypt 哈希由后端在启动时生成，避免在 SQL 中硬编码哈希值）。
--   2. 使用公司外部 MySQL 实例，需 DBA 提前创建好数据库并授予 popsicle 账号权限。
--   3. Nacos 表结构由 Nacos 服务自身管理（若需本地 Nacos，请单独创建 nacos_db）。
-- ============================================================================

CREATE DATABASE IF NOT EXISTS data_factory DEFAULT CHARACTER SET utf8mb4;

-- 授权 popsicle 账号（公司外部 MySQL）
GRANT ALL PRIVILEGES ON data_factory.* TO 'popsicle'@'%';
FLUSH PRIVILEGES;

USE data_factory;

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
    char_max_length  BIGINT       COMMENT 'varchar最大长度（longtext 可达 4294967295，超 INT 范围）',
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
    -- 遍历模式扩展列（文档 6.7 节，首次建表即内联，无需再走 ALTER 迁移）
    round_no    SMALLINT     DEFAULT NULL COMMENT '遍历模式轮次序号（从0开始）',
    drive_value VARCHAR(500) DEFAULT NULL COMMENT '遍历模式当前驱动值',
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
    nodes_json       MEDIUMTEXT    NOT NULL COMMENT '节点配置JSON数组，见文档4.3节格式规范',
    -- 注：MySQL 8.0 中 TEXT 类列的默认值必须使用表达式写法 DEFAULT ('[]')，
    -- 文档原文的 DEFAULT '[]' 会触发 ERROR 1101 (ER_BLOB_CANT_HAVE_DEFAULT)
    edges_json       MEDIUMTEXT    NOT NULL DEFAULT ('[]') COMMENT '连线关系JSON数组',
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

-- ================================================================
-- 补充索引（文档 11.2 节：高频查询所需）
-- ================================================================

-- df_case：列表页按创建时间倒序 + 分组过滤
ALTER TABLE df_case
    ADD INDEX idx_group_created_at (group_type, is_deleted, created_at);

-- df_audit_log：按用户+时间查询（个人日志）
ALTER TABLE df_audit_log
    ADD INDEX idx_user_created (user_id, created_at);

-- df_exec_batch_log：遍历模式按 round_no 重试查询（依赖上方内联的 round_no 列）
ALTER TABLE df_exec_batch_log
    ADD INDEX idx_task_round (task_id, round_no, status);
