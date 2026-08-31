import request from '@/utils/request'
import type { ApiResponse, IdCardItem, SnowflakeItem, ToolResult } from './types'

// 快捷工具模块 /api/v1/tools（全部 POST，请求体为生成参数）
export const toolsApi = {
  /** 身份证号生成 */
  idcard(params: { province?: string; gender?: string; year_min?: number; year_max?: number; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<IdCardItem>>>('/v1/tools/idcard', params)
  },
  /** 手机号生成 */
  phone(params: { carrier?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<{ phone: string; carrier?: string }>>>('/v1/tools/phone', params)
  },
  /** 银行卡号生成 */
  bankcard(params: { bank?: string; card_type?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<{ card_no: string; bank?: string; card_type?: string }>>>('/v1/tools/bankcard', params)
  },
  /** 随机姓名生成 */
  name(params: { lang?: string; gender?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<{ name: string }>>>('/v1/tools/name', params)
  },
  /** 统一社会信用代码生成 */
  creditCode(params: { dept?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<{ code: string }>>>('/v1/tools/credit-code', params)
  },
  /** 纳税人识别号生成 */
  taxpayerId(params: { type?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<{ taxpayer_id: string }>>>('/v1/tools/taxpayer-id', params)
  },
  /** 随机地址生成 */
  address(params: { province?: string; precision?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<{ address: string }>>>('/v1/tools/address', params)
  },
  /** 批量生成日期 */
  date(params: { start_date: string; end_date: string; format?: string; unique?: boolean; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<{ value: string }>>>('/v1/tools/date', params)
  },
  /** 批量生成 UUID */
  uuid(params: { format?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<{ uuid: string }>>>('/v1/tools/uuid', params)
  },
  /** 生成雪花 ID */
  snowflake(params: { machine_id?: number; datacenter_id?: number; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<SnowflakeItem>>>('/v1/tools/snowflake', params)
  },
}
