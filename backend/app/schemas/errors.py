"""业务错误码与业务异常。

错误码分段规则：
- 1000~1099 通用错误（参数校验、认证、权限）
- 1100~1199 用户模块
- 1200~1299 数据源模块
- 1300~1399 造数引擎
- 1400~1499 Case 模块
- 1500~1599 场景模块
- 1600~1699 工具模块
- 9000~9099 系统级
"""

# ── 通用错误（1000~1099）────────────────────────────────────
PARAM_INVALID = 1000  # 请求参数不合法
UNAUTHORIZED = 1001  # 未登录或登录已过期，请重新登录
FORBIDDEN = 1002  # 无操作权限
DATA_NOT_FOUND = 1003  # 数据不存在或已被删除
DATA_DUPLICATE = 1004  # 数据已存在，请勿重复创建
OPERATION_TOO_FREQUENT = 1005  # 操作过于频繁，请稍后再试
TOKEN_BLACKLISTED = 1006  # Token 已失效，请重新登录

# ── 用户模块（1100~1199）────────────────────────────────────
USER_NOT_FOUND = 1100  # 用户不存在
PASSWORD_WRONG = 1101  # 密码错误
USER_DISABLED = 1102  # 账号已被禁用，请联系管理员
USER_PENDING = 1103  # 账号正在审批中，请等待管理员审批
USER_REJECTED = 1104  # 注册申请已被拒绝
USERNAME_TAKEN = 1105  # 用户名已被占用
OLD_PASSWORD_WRONG = 1106  # 原密码错误
PASSWORD_TOO_WEAK = 1107  # 密码强度不足，需至少 8 位且包含数字和字母

# ── 数据源模块（1200~1299）───────────────────────────────────
DS_NOT_FOUND = 1200  # 数据源不存在
DS_NAME_TAKEN = 1201  # 数据源名称已存在
DS_CONNECT_FAILED = 1202  # 数据源连接失败
DS_SYNC_LOCKED = 1203  # 该数据源同步任务正在进行中，请稍候
DS_NOT_INITIALIZED = 1204  # 数据源表结构尚未初始化，请先同步
DS_PERMISSION_DENIED = 1205  # 无权访问该数据源（不属于本组）
DS_HAS_ACTIVE_CASES = 1206  # 该数据源下存在关联的 Case，删除前请先处理关联数据

# ── 造数引擎（1300~1399）────────────────────────────────────
TABLE_NOT_FOUND = 1300  # 目标表不存在或尚未同步
COLUMN_TYPE_INCOMPATIBLE = 1301  # 字段类型不兼容，无法关联
ASSOCIATION_CYCLE = 1302  # 检测到循环关联，请检查关联配置
ITERATE_LIST_DUPLICATE = 1303  # 一个 Case 只允许一个字段使用按序遍历插入策略
STRATEGY_PARAM_INVALID = 1304  # 策略参数不合法
TASK_NOT_FOUND = 1305  # 执行任务不存在
TASK_ALREADY_FINISHED = 1306  # 任务已结束，无法停止
TARGET_COUNT_TOO_LARGE = 1307  # 目标造数量超过单次限制
BATCH_RETRY_EXHAUSTED = 1308  # 批次重试已耗尽（3次），该批次跳过
TASK_NOT_ROLLBACKABLE = 1309  # 任务无可回滚数据（表无主键/规模超阈值未采集/已回滚）
TASK_ROLLBACK_CONFLICT = 1310  # 任务已回滚或回滚进行中

# ── Case 模块（1400~1499）───────────────────────────────────
CASE_NOT_FOUND = 1400  # Case 不存在或已被删除
CASE_NAME_TAKEN = 1401  # 该数据源下已存在同名 Case
CASE_SCHEMA_OUTDATED = 1402  # 检测到表结构已更新，以下字段配置可能失效
CASE_CONFIG_INVALID = 1403  # Case 配置不合法，请重新检查字段策略
FOLDER_NOT_FOUND = 1404  # 文件夹不存在
FOLDER_NAME_TAKEN = 1405  # 文件夹名称已存在

# ── 场景模块（1500~1599）────────────────────────────────────
SCENE_NOT_FOUND = 1500  # 场景不存在或已被删除
SCENE_NAME_TAKEN = 1501  # 场景名称已存在
SCENE_NODE_TOO_FEW = 1502  # 场景至少需要 2 个 Case 节点
SCENE_CYCLE_DETECTED = 1503  # 检测到循环依赖，请检查连线
SCENE_NODE_CASE_DELETED = 1504  # 节点引用的 Case 已删除，请替换
SCENE_TARGET_COUNT_MISSING = 1505  # 节点的造数条数未填写
SCENE_EXEC_NOT_FOUND = 1506  # 场景执行记录不存在

# ── 系统级（9000~9099）──────────────────────────────────────
INTERNAL_ERROR = 9000  # 服务内部错误，请联系管理员
DATABASE_ERROR = 9001  # 数据库操作失败，请稍后重试
REDIS_UNAVAILABLE = 9002  # 缓存服务不可用，部分功能可能受影响
CELERY_SUBMIT_FAILED = 9003  # 任务队列提交失败，请稍后重试
NACOS_CONFIG_UNAVAILABLE = 9004  # 配置中心不可用，使用默认配置运行

# 错误码 → 默认中文提示
ERROR_MESSAGES: dict[int, str] = {
    PARAM_INVALID: "请求参数不合法",
    UNAUTHORIZED: "未登录或登录已过期，请重新登录",
    FORBIDDEN: "无操作权限",
    DATA_NOT_FOUND: "数据不存在或已被删除",
    DATA_DUPLICATE: "数据已存在，请勿重复创建",
    OPERATION_TOO_FREQUENT: "操作过于频繁，请稍后再试",
    TOKEN_BLACKLISTED: "Token 已失效，请重新登录",
    USER_NOT_FOUND: "用户不存在",
    PASSWORD_WRONG: "密码错误",
    USER_DISABLED: "账号已被禁用，请联系管理员",
    USER_PENDING: "账号正在审批中，请等待管理员审批",
    USER_REJECTED: "注册申请已被拒绝",
    USERNAME_TAKEN: "用户名已被占用",
    OLD_PASSWORD_WRONG: "原密码错误",
    PASSWORD_TOO_WEAK: "密码强度不足，需至少 8 位且包含数字和字母",
    DS_NOT_FOUND: "数据源不存在",
    DS_NAME_TAKEN: "数据源名称已存在",
    DS_CONNECT_FAILED: "数据源连接失败",
    DS_SYNC_LOCKED: "该数据源同步任务正在进行中，请稍候",
    DS_NOT_INITIALIZED: "数据源表结构尚未初始化，请先同步",
    DS_PERMISSION_DENIED: "无权访问该数据源（不属于本组）",
    DS_HAS_ACTIVE_CASES: "该数据源下存在关联的 Case，删除前请先处理关联数据",
    TABLE_NOT_FOUND: "目标表不存在或尚未同步",
    COLUMN_TYPE_INCOMPATIBLE: "字段类型不兼容，无法关联",
    ASSOCIATION_CYCLE: "检测到循环关联，请检查关联配置",
    ITERATE_LIST_DUPLICATE: "一个 Case 只允许一个字段使用按序遍历插入策略",
    STRATEGY_PARAM_INVALID: "策略参数不合法",
    TASK_NOT_FOUND: "执行任务不存在",
    TASK_ALREADY_FINISHED: "任务已结束，无法停止",
    TARGET_COUNT_TOO_LARGE: "目标造数量超过单次限制",
    BATCH_RETRY_EXHAUSTED: "批次重试已耗尽（3次），该批次跳过",
    TASK_NOT_ROLLBACKABLE: "任务无可回滚数据（表缺少单列主键、规模超阈值未采集或已全部回滚）",
    TASK_ROLLBACK_CONFLICT: "任务已回滚或回滚进行中",
    CASE_NOT_FOUND: "Case 不存在或已被删除",
    CASE_NAME_TAKEN: "该数据源下已存在同名 Case",
    CASE_SCHEMA_OUTDATED: "检测到表结构已更新，以下字段配置可能失效",
    CASE_CONFIG_INVALID: "Case 配置不合法，请重新检查字段策略",
    FOLDER_NOT_FOUND: "文件夹不存在",
    FOLDER_NAME_TAKEN: "文件夹名称已存在",
    SCENE_NOT_FOUND: "场景不存在或已被删除",
    SCENE_NAME_TAKEN: "场景名称已存在",
    SCENE_NODE_TOO_FEW: "场景至少需要 2 个 Case 节点",
    SCENE_CYCLE_DETECTED: "检测到循环依赖，请检查连线",
    SCENE_NODE_CASE_DELETED: "节点引用的 Case 已删除，请替换",
    SCENE_TARGET_COUNT_MISSING: "节点的造数条数未填写",
    SCENE_EXEC_NOT_FOUND: "场景执行记录不存在",
    INTERNAL_ERROR: "服务内部错误，请联系管理员",
    DATABASE_ERROR: "数据库操作失败，请稍后重试",
    REDIS_UNAVAILABLE: "缓存服务不可用，部分功能可能受影响",
    CELERY_SUBMIT_FAILED: "任务队列提交失败，请稍后重试",
    NACOS_CONFIG_UNAVAILABLE: "配置中心不可用，使用默认配置运行",
}


class BizException(Exception):
    """业务异常。

    由全局异常处理器统一转换为 ApiResponse(code, message)。
    message 不传时使用错误码对应的默认中文提示。
    """

    def __init__(self, code: int, message: str | None = None) -> None:
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, "业务处理失败")
        super().__init__(self.message)
