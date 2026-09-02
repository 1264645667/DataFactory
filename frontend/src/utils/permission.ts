import type { UserInfo } from '@/api/types'

// 菜单权限树，供用户管理权限分配弹窗使用
export interface PermissionNode {
  label: string
  key: string
  children?: { label: string; key: string }[]
}

export const PERMISSION_TREE: PermissionNode[] = [
  { label: '造数总览', key: 'OVERVIEW', children: [{ label: '查看大屏', key: 'OVERVIEW:VIEW' }] },
  {
    label: '造数引擎',
    key: 'ENGINE',
    children: [
      { label: '查看表列表', key: 'ENGINE:VIEW' },
      { label: '创建 Case', key: 'ENGINE:CREATE' },
      { label: '执行造数', key: 'ENGINE:EXECUTE' },
    ],
  },
  {
    label: 'Case 管理',
    key: 'CASE',
    children: [
      { label: '查看列表', key: 'CASE:VIEW' },
      { label: '编辑', key: 'CASE:EDIT' },
      { label: '删除', key: 'CASE:DELETE' },
      { label: '执行', key: 'CASE:EXECUTE' },
      { label: '复制', key: 'CASE:COPY' },
    ],
  },
  {
    label: '场景管理',
    key: 'SCENE',
    children: [
      { label: '查看列表', key: 'SCENE:VIEW' },
      { label: '创建场景', key: 'SCENE:CREATE' },
      { label: '编辑', key: 'SCENE:EDIT' },
      { label: '删除', key: 'SCENE:DELETE' },
      { label: '执行场景', key: 'SCENE:EXECUTE' },
    ],
  },
  { label: '快捷工具', key: 'TOOL', children: [{ label: '使用所有工具', key: 'TOOL:USE' }] },
  {
    label: '数据源管理',
    key: 'DATASOURCE',
    children: [
      { label: '查看', key: 'DATASOURCE:VIEW' },
      { label: '新增', key: 'DATASOURCE:ADD' },
      { label: '编辑', key: 'DATASOURCE:EDIT' },
      { label: '删除', key: 'DATASOURCE:DELETE' },
    ],
  },
  {
    label: '用户管理',
    key: 'USER_MGMT',
    children: [
      { label: '审批', key: 'USER:APPROVE' },
      { label: '分配权限', key: 'USER:PERMISSION' },
      { label: '禁用', key: 'USER:DISABLE' },
    ],
  },
]

/** 权限树全部叶子权限编码 */
export const ALL_PERMISSION_KEYS: string[] = PERMISSION_TREE.flatMap((g) =>
  (g.children ?? []).map((c) => c.key),
)

/** 判断用户是否拥有某权限：管理员（group_type=99）默认全量权限 */
export function hasPermission(user: UserInfo | null, perm: string): boolean {
  if (!user) return false
  if (user.group_type === 99) return true
  return (user.permissions ?? []).includes(perm)
}

/** 分组类型 → 中文名 */
export function groupName(groupType: number | null | undefined): string {
  if (groupType === 1) return '销项组'
  if (groupType === 2) return '申报组'
  if (groupType === 99) return '管理员'
  return '-'
}
