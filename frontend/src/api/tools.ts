import request from '@/utils/request'
import type { ApiResponse, IdCardItem, SnowflakeItem, ToolResult } from './types'

// 快捷工具模块 /api/v1/tools（全部 POST，请求体为生成参数）
export const toolsApi = {
  /** 身份证号生成 */
  idcard(params: { province?: string; gender?: string; birth_year_start?: number; birth_year_end?: number; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<IdCardItem>>>('/v1/tools/idcard', params)
  },
  /** 手机号生成 */
  phone(params: { carrier?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<string>>>('/v1/tools/phone', params)
  },
  /** 银行卡号生成 */
  bankcard(params: { bank?: string; card_type?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<{ card_no: string; bank: string; card_type: string }>>>('/v1/tools/bankcard', params)
  },
  /** 随机姓名生成 */
  name(params: { language?: string; gender?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<string>>>('/v1/tools/name', params)
  },
  /** 统一社会信用代码生成 */
  creditCode(params: { department?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<string>>>('/v1/tools/credit-code', params)
  },
  /** 纳税人识别号生成 */
  taxpayerId(params: { taxpayer_type?: string; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<string>>>('/v1/tools/taxpayer-id', params)
  },
  /** 随机地址生成 */
  address(params: { province?: string; precision?: 'province_city' | 'province_city_district' | 'full'; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<string>>>('/v1/tools/address', params)
  },
  /** 批量生成日期 */
  date(params: { start_date: string; end_date: string; fmt?: string; dedup?: boolean; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<string | number>>>('/v1/tools/date', params)
  },
  /** 批量生成 UUID */
  uuid(params: { fmt?: 'hyphen' | 'plain' | 'upper' | 'lower'; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<string>>>('/v1/tools/uuid', params)
  },
  /** 生成雪花 ID */
  snowflake(params: { machine_id?: number; datacenter_id?: number; count: number }) {
    return request.post<unknown, ApiResponse<ToolResult<SnowflakeItem>>>('/v1/tools/snowflake', params)
  },
}
