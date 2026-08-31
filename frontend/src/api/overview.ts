import request from '@/utils/request'
import type {
  ApiResponse,
  ExecRecord,
  ExecRecordQuery,
  MemberRankItem,
  OverviewMetrics,
  PageResult,
  StatusDistItem,
  TableTopItem,
  TrendPoint,
} from './types'

// 造数总览模块 /api/v1/overview
export const overviewApi = {
  /** 核心指标卡片数据 */
  metrics() {
    return request.get<unknown, ApiResponse<OverviewMetrics>>('/v1/overview/metrics')
  },
  /** 执行趋势折线图数据（近 7/30/90 天） */
  trend(days: 7 | 30 | 90) {
    return request.get<unknown, ApiResponse<TrendPoint[]>>('/v1/overview/trend', { params: { days } })
  },
  /** 执行状态分布饼图数据 */
  statusDist(days: 7 | 30 | 90) {
    return request.get<unknown, ApiResponse<StatusDistItem[]>>('/v1/overview/status-dist', { params: { days } })
  },
  /** 表操作量 Top10 柱状图数据 */
  tableTop10(days?: number) {
    return request.get<unknown, ApiResponse<TableTopItem[]>>('/v1/overview/table-top10', { params: { days } })
  },
  /** 成员贡献排行数据 */
  memberRank(days?: number) {
    return request.get<unknown, ApiResponse<MemberRankItem[]>>('/v1/overview/member-rank', { params: { days } })
  },
  /** 执行记录明细表（分页 + 筛选） */
  execRecords(params: ExecRecordQuery) {
    return request.get<unknown, ApiResponse<PageResult<ExecRecord>>>('/v1/overview/exec-records', { params })
  },
}
