"""首次数据初始化脚本（幂等）。

在 main.py lifespan 中调用：
1. 创建内置管理员（username=popsicle，password=Avaritia14589 的 bcrypt 哈希，
   group_type=99，status=1）
2. 初始化 df_menu 全量菜单权限数据

幂等策略：先查后插，已存在的数据直接跳过，可重复执行。
"""

import structlog
from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal
from app.models.user import Menu, User

logger = structlog.get_logger()

# 内置管理员账号
ADMIN_USERNAME = "popsicle"
ADMIN_PASSWORD = "Avaritia14589"

# 全量菜单权限数据
# 格式：(menu_code, menu_name, parent_code, sort_order, icon)
MENUS: list[tuple[str, str, str | None, int, str | None]] = [
    # 造数总览
    ("OVERVIEW", "造数总览", None, 1, "dashboard"),
    ("OVERVIEW:VIEW", "查看大屏", "OVERVIEW", 1, None),
    # 造数引擎
    ("ENGINE", "造数引擎", None, 2, "flash"),
    ("ENGINE:VIEW", "查看表列表", "ENGINE", 1, None),
    ("ENGINE:CREATE", "创建 Case", "ENGINE", 2, None),
    ("ENGINE:EXECUTE", "执行造数", "ENGINE", 3, None),
    # Case 管理
    ("CASE", "Case 管理", None, 3, "folder"),
    ("CASE:VIEW", "查看列表", "CASE", 1, None),
    ("CASE:EDIT", "编辑", "CASE", 2, None),
    ("CASE:DELETE", "删除", "CASE", 3, None),
    ("CASE:EXECUTE", "执行", "CASE", 4, None),
    ("CASE:COPY", "复制", "CASE", 5, None),
    # 场景管理
    ("SCENE", "场景管理", None, 4, "film"),
    ("SCENE:VIEW", "查看列表", "SCENE", 1, None),
    ("SCENE:CREATE", "创建场景", "SCENE", 2, None),
    ("SCENE:EDIT", "编辑", "SCENE", 3, None),
    ("SCENE:DELETE", "删除", "SCENE", 4, None),
    ("SCENE:EXECUTE", "执行场景", "SCENE", 5, None),
    # 快捷工具
    ("TOOL", "快捷工具", None, 5, "build"),
    ("TOOL:USE", "使用所有工具", "TOOL", 1, None),
    # 数据源管理
    ("DATASOURCE", "数据源管理", None, 6, "server"),
    ("DATASOURCE:VIEW", "查看", "DATASOURCE", 1, None),
    ("DATASOURCE:ADD", "新增", "DATASOURCE", 2, None),
    ("DATASOURCE:EDIT", "编辑", "DATASOURCE", 3, None),
    ("DATASOURCE:DELETE", "删除", "DATASOURCE", 4, None),
    # 用户管理（仅管理员）
    ("USER_MGMT", "用户管理", None, 7, "people"),
    ("USER:APPROVE", "审批", "USER_MGMT", 1, None),
    ("USER:PERMISSION", "分配权限", "USER_MGMT", 2, None),
    ("USER:DISABLE", "禁用", "USER_MGMT", 3, None),
]


async def _init_admin(session) -> bool:
    """创建内置管理员（幂等：已存在则跳过）。返回是否新建。"""
    result = await session.execute(select(User).where(User.username == ADMIN_USERNAME))
    if result.scalar_one_or_none() is not None:
        return False
    admin = User(
        username=ADMIN_USERNAME,
        password=get_password_hash(ADMIN_PASSWORD),  # bcrypt 哈希
        real_name="超级管理员",
        group_type=99,  # 管理员
        status=1,  # 正常
    )
    session.add(admin)
    return True


async def _init_menus(session) -> int:
    """初始化 df_menu 全量菜单权限数据（幂等：按 menu_code 先查后插）。返回新增条数。"""
    result = await session.execute(select(Menu.menu_code))
    existing_codes = set(result.scalars().all())
    added = 0
    for menu_code, menu_name, parent_code, sort_order, icon in MENUS:
        if menu_code in existing_codes:
            continue
        session.add(
            Menu(
                menu_code=menu_code,
                menu_name=menu_name,
                parent_code=parent_code,
                sort_order=sort_order,
                icon=icon,
            )
        )
        added += 1
    return added


async def init_first_data() -> None:
    """执行首次数据初始化（幂等，可重复调用）。"""
    async with AsyncSessionLocal() as session:
        admin_created = await _init_admin(session)
        menu_added = await _init_menus(session)
        await session.commit()
    logger.info(
        "init_first_data_done",
        admin_created=admin_created,
        menu_added=menu_added,
    )
