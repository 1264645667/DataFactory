import request from '@/utils/request'
import type {
  ApiResponse,
  PageResult,
  SceneDetail,
  SceneHistoryItem,
  SceneItem,
  SceneProgressData,
  SceneSaveParams,
} from './types'

// 场景管理模块 /api/v1/scenes
export const scenesApi = {
  /** 场景列表（分页 + 筛选，last_exec_status 为摘要码 0~4） */
  list(params: {
    page?: number
    page_size?: number
    name?: string
    created_by?: number
    last_exec_status?: number[]
    start_time?: string
    end_time?: string
  }) {
    return request.get<unknown, ApiResponse<PageResult<SceneItem>>>('/v1/scenes', { params })
  },
  /** 场景详情（含 nodes + edges） */
  detail(id: number) {
    return request.get<unknown, ApiResponse<SceneDetail>>(`/v1/scenes/${id}`)
  },
  /** 新建场景 */
  create(params: SceneSaveParams) {
    return request.post<unknown, ApiResponse<{ scene_id: number }>>('/v1/scenes', params)
  },
  /** 编辑场景 */
  update(id: number, params: SceneSaveParams) {
    return request.put<unknown, ApiResponse<null>>(`/v1/scenes/${id}`, params)
  },
  /** 逻辑删除场景 */
  remove(id: number) {
    return request.delete<unknown, ApiResponse<null>>(`/v1/scenes/${id}`)
  },
  /** 执行场景（返回 scene_exec_no） */
  execute(id: number) {
    return request.post<unknown, ApiResponse<{ scene_exec_no: string }>>(`/v1/scenes/${id}/execute`)
  },
  /** 复制场景 */
  copy(id: number, sceneName: string) {
    return request.post<unknown, ApiResponse<{ scene_id: number }>>(`/v1/scenes/${id}/copy`, { scene_name: sceneName })
  },
  /** 场景执行历史列表（纯数组，不分页） */
  history(id: number) {
    return request.get<unknown, ApiResponse<SceneHistoryItem[]>>(`/v1/scenes/${id}/history`)
  },
  /** 场景执行实时进度 */
  execProgress(sceneExecNo: string) {
    return request.get<unknown, ApiResponse<SceneProgressData>>(`/v1/scenes/exec/${sceneExecNo}/progress`)
  },
  /** 强制停止场景 */
  abortExec(sceneExecNo: string) {
    return request.post<unknown, ApiResponse<null>>(`/v1/scenes/exec/${sceneExecNo}/abort`)
  },
  /** 重试失败节点 */
  retryNodes(sceneExecNo: string, nodeIds: string[]) {
    return request.post<unknown, ApiResponse<null>>(`/v1/scenes/exec/${sceneExecNo}/retry-nodes`, {
      node_ids: nodeIds,
    })
  },
}
