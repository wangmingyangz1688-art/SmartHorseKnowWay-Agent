/**
 * API 服务层 — 本地活动规划与执行
 *
 * 封装所有后端 API 调用，统一错误处理。
 * 与后端 routes/activity.py、routes/map.py、routes/poi.py 一一对应。
 */

import type {
  ActivityRequest,
  ActivityPlan,
  ActivityPlanResponse,
  ExecutionRequest,
  ExecutionResponse,
  ShareRequest,
  ShareResponse,
  QueueCheckRequest,
  QueueCheckResult,
  AvailabilityCheckRequest,
  AvailabilityCheckResult,
  DealItem,
  POISearchResponse,
  RouteRequest,
  RouteResponse,
  WeatherResponse,
  ApiResponse,
  HealthCheckResponse,
  SSEEvent,
  MemoryFeedbackRequest,
} from '@/types'

// ============================================================================
// 基础配置
// ============================================================================

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

/**
 * 通用 fetch 封装
 */
async function request<T = any>(
  url: string,
  options: RequestInit = {}
): Promise<T> {
  const fullUrl = `${BASE_URL}${url}`

  const defaultHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  const response = await fetch(fullUrl, {
    ...options,
    headers: {
      ...defaultHeaders,
      ...(options.headers as Record<string, string>),
    },
  })

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`
    try {
      const errorData = await response.json()
      errorMessage = errorData.detail || errorData.message || errorMessage
    } catch {
      // 无法解析 JSON，使用默认错误信息
    }
    throw new ApiError(errorMessage, response.status)
  }

  return response.json()
}

/**
 * 自定义 API 错误
 */
export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// ============================================================================
// 1. 活动规划
// ============================================================================

/**
 * 生成活动方案（非流式）
 *
 * POST /api/activity/plan
 */
export async function planActivity(
  req: ActivityRequest
): Promise<ActivityPlanResponse> {
  return request<ActivityPlanResponse>('/api/activity/plan', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

/**
 * 生成活动方案（SSE 流式进度）
 *
 * POST /api/activity/plan/stream
 *
 * @param req        活动请求
 * @param onProgress 每收到一条 SSE 事件时的回调
 * @returns          最终的完整方案（从 complete 事件中提取）
 */
export async function planActivityStream(
  req: ActivityRequest,
  onProgress?: (event: SSEEvent) => void
): Promise<ActivityPlan> {
  const fullUrl = `${BASE_URL}/api/activity/plan/stream`

  const response = await fetch(fullUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`
    try {
      const errorData = await response.json()
      errorMessage = errorData.detail || errorData.message || errorMessage
    } catch {
      // ignore
    }
    throw new ApiError(errorMessage, response.status)
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new ApiError('无法读取响应流', 0)
  }

  const decoder = new TextDecoder()
  let resultPlan: ActivityPlan | null = null
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // 按换行分割处理每一行
    const lines = buffer.split('\n')
    // 最后一行可能不完整，保留在 buffer
    buffer = lines.pop() || ''

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data: ')) continue

      try {
        const event: SSEEvent = JSON.parse(trimmed.slice(6))

        // 回调
        onProgress?.(event)

        if (event.type === 'complete' && event.success) {
          resultPlan = event.data as ActivityPlan
        } else if (event.type === 'error') {
          throw new ApiError(event.message || '规划失败', 500)
        }
      } catch (parseErr) {
        // 如果是我们自己抛出的 ApiError，继续抛
        if (parseErr instanceof ApiError) throw parseErr
        // 否则忽略不完整的 JSON
        console.warn('SSE 解析跳过:', trimmed)
      }
    }
  }

  // 处理 buffer 中的剩余数据
  if (buffer.trim().startsWith('data: ')) {
    try {
      const event: SSEEvent = JSON.parse(buffer.trim().slice(6))
      onProgress?.(event)
      if (event.type === 'complete' && event.success) {
        resultPlan = event.data as ActivityPlan
      }
    } catch {
      // ignore
    }
  }

  if (!resultPlan) {
    throw new ApiError('未获取到活动方案', 500)
  }

  return resultPlan
}

// ============================================================================
// 2. 执行动作
// ============================================================================

/**
 * 执行方案中的预约/下单动作
 *
 * POST /api/activity/execute
 */
export async function executeActions(
  req: ExecutionRequest
): Promise<ExecutionResponse> {
  return request<ExecutionResponse>('/api/activity/execute', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

/**
 * 执行单个动作的便捷方法
 */
export async function executeSingleAction(
  plan: ActivityPlan,
  actionId: string,
  contactName?: string,
  contactPhone?: string
): Promise<ExecutionResponse> {
  return executeActions({
    plan_id: plan.plan_id || 'unknown',
    plan,
    action_ids: [actionId],
    contact_name: contactName || '用户',
    contact_phone: contactPhone || '',
  })
}

/**
 * 执行所有未完成动作的便捷方法
 */
export async function executeAllActions(
  plan: ActivityPlan,
  excludeActionIds?: string[],
  contactName?: string,
  contactPhone?: string
): Promise<ExecutionResponse> {
  const allIds = (plan.executable_actions || []).map((a) => a.action_id)
  const actionIds = excludeActionIds
    ? allIds.filter((id) => !excludeActionIds.includes(id))
    : allIds

  return executeActions({
    plan_id: plan.plan_id || 'unknown',
    plan,
    action_ids: actionIds,
    contact_name: contactName || '用户',
    contact_phone: contactPhone || '',
  })
}

// ============================================================================
// 2026-06-04: 记忆反馈
// ============================================================================

/**
 * 提交自然语言反馈，后端会解析成用户级/场景级/对象级记忆。
 */
export async function submitMemoryFeedback(
  req: MemoryFeedbackRequest
): Promise<ApiResponse<any>> {
  return request<ApiResponse<any>>('/api/activity/memory/feedback', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

/**
 * 获取当前记忆身份的摘要。
 */
export async function getMemorySummary(userId: string): Promise<ApiResponse<any>> {
  return request<ApiResponse<any>>(`/api/activity/memory/summary?user_id=${encodeURIComponent(userId)}`)
}

// ============================================================================
// 3. 分享
// ============================================================================

/**
 * 生成分享文案
 *
 * POST /api/activity/share
 */
export async function generateShareMessage(
  req: ShareRequest
): Promise<ShareResponse> {
  return request<ShareResponse>('/api/activity/share', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

/**
 * 快速生成分享文案的便捷方法
 */
export async function quickShare(
  plan: ActivityPlan,
  recipient?: string
): Promise<ShareResponse> {
  return generateShareMessage({
    plan,
    recipient,
    tone: 'casual',
  })
}

// ============================================================================
// 4. 排队 & 可用性查询
// ============================================================================

/**
 * 查询餐厅排队状态
 *
 * POST /api/activity/check-queue
 */
export async function checkQueueStatus(
  req: QueueCheckRequest
): Promise<ApiResponse<QueueCheckResult>> {
  return request<ApiResponse<QueueCheckResult>>('/api/activity/check-queue', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

/**
 * 查询餐厅可用性
 *
 * POST /api/activity/check-availability
 */
export async function checkAvailability(
  req: AvailabilityCheckRequest
): Promise<ApiResponse<AvailabilityCheckResult>> {
  return request<ApiResponse<AvailabilityCheckResult>>(
    '/api/activity/check-availability',
    {
      method: 'POST',
      body: JSON.stringify(req),
    }
  )
}

// ============================================================================
// 5. 团购优惠
// ============================================================================

/**
 * 获取附近团购优惠
 *
 * GET /api/activity/deals?city=...&district=...&category=...&limit=...
 */
export async function getNearbyDeals(params: {
  city: string
  district?: string
  category?: string
  limit?: number
}): Promise<ApiResponse<{ count: number; deals: DealItem[] }>> {
  const query = new URLSearchParams()
  query.set('city', params.city)
  if (params.district) query.set('district', params.district)
  if (params.category) query.set('category', params.category)
  if (params.limit) query.set('limit', String(params.limit))

  return request(`/api/activity/deals?${query.toString()}`)
}

// ============================================================================
// 6. POI 服务
// ============================================================================

/**
 * 搜索 POI
 *
 * GET /api/poi/search?keywords=...&city=...
 */
export async function searchPOI(
  keywords: string,
  city: string = '北京'
): Promise<ApiResponse> {
  const query = new URLSearchParams({ keywords, city })
  return request(`/api/poi/search?${query.toString()}`)
}

/**
 * 获取 POI 详情
 *
 * GET /api/poi/detail/:poiId
 */
export async function getPOIDetail(poiId: string): Promise<ApiResponse> {
  return request(`/api/poi/detail/${poiId}`)
}

/**
 * 获取场所图片
 *
 * GET /api/poi/photo?name=...&city=...
 */
export async function getVenuePhoto(
  name: string,
  city?: string
): Promise<
  ApiResponse<{
    name: string
    city: string
    photo_url: string | null
    source: string | null
  }>
> {
  const query = new URLSearchParams({ name })
  if (city) query.set('city', city)
  return request(`/api/poi/photo?${query.toString()}`)
}

/**
 * 批量获取场所图片
 * （前端便捷方法，内部并发调用 getVenuePhoto）
 */
export async function batchGetVenuePhotos(
  venues: Array<{ name: string; city?: string }>
): Promise<Record<string, string>> {
  const results: Record<string, string> = {}

  const promises = venues.map(async (v) => {
    try {
      const res = await getVenuePhoto(v.name, v.city)
      if (res.success && res.data?.photo_url) {
        results[v.name] = res.data.photo_url
      }
    } catch {
      // 单个失败不影响整体
      console.warn(`获取图片失败: ${v.name}`)
    }
  })

  await Promise.allSettled(promises)
  return results
}

// ============================================================================
// 7. 地图服务
// ============================================================================

/**
 * 搜索 POI（通过地图服务路由）
 *
 * GET /api/map/poi?keywords=...&city=...&citylimit=...
 */
export async function mapSearchPOI(
  keywords: string,
  city: string,
  citylimit: boolean = true
): Promise<POISearchResponse> {
  const query = new URLSearchParams({
    keywords,
    city,
    citylimit: String(citylimit),
  })
  return request<POISearchResponse>(`/api/map/poi?${query.toString()}`)
}

/**
 * 查询天气
 *
 * GET /api/map/weather?city=...
 */
export async function getWeather(city: string): Promise<WeatherResponse> {
  const query = new URLSearchParams({ city })
  return request<WeatherResponse>(`/api/map/weather?${query.toString()}`)
}

/**
 * 规划路线
 *
 * POST /api/map/route
 */
export async function planRoute(req: RouteRequest): Promise<RouteResponse> {
  return request<RouteResponse>('/api/map/route', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

/**
 * 地图服务健康检查
 *
 * GET /api/map/health
 */
export async function mapHealthCheck(): Promise<ApiResponse> {
  return request('/api/map/health')
}

// ============================================================================
// 8. 系统
// ============================================================================

/**
 * 根路径 — 获取服务基本信息
 *
 * GET /
 */
export async function getServiceInfo(): Promise<ApiResponse> {
  return request('/')
}

/**
 * 系统健康检查
 *
 * GET /health
 */
export async function healthCheck(): Promise<{
  status: string
  service: string
  version: string
}> {
  return request('/health')
}

/**
 * 活动服务健康检查
 *
 * GET /api/activity/health
 */
export async function activityHealthCheck(): Promise<HealthCheckResponse> {
  return request<HealthCheckResponse>('/api/activity/health')
}

// ============================================================================
// 9. 工具函数
// ============================================================================

/**
 * 检查后端是否可用
 */
export async function isBackendAvailable(): Promise<boolean> {
  try {
    const res = await healthCheck()
    return res.status === 'healthy'
  } catch {
    return false
  }
}

/**
 * 检查所有服务状态
 */
export async function checkAllServices(): Promise<{
  backend: boolean
  activity: boolean
  map: boolean
}> {
  const [backendOk, activityOk, mapOk] = await Promise.allSettled([
    healthCheck().then(() => true).catch(() => false),
    activityHealthCheck().then(() => true).catch(() => false),
    mapHealthCheck().then(() => true).catch(() => false),
  ])

  return {
    backend: backendOk.status === 'fulfilled' ? backendOk.value : false,
    activity: activityOk.status === 'fulfilled' ? activityOk.value : false,
    map: mapOk.status === 'fulfilled' ? mapOk.value : false,
  }
}

// ============================================================================
// 默认导出
// ============================================================================

export default {
  // 活动规划
  planActivity,
  planActivityStream,

  // 执行
  executeActions,
  executeSingleAction,
  executeAllActions,

  // 分享
  generateShareMessage,
  quickShare,

  // 排队 & 可用性
  checkQueueStatus,
  checkAvailability,

  // 团购
  getNearbyDeals,

  // POI
  searchPOI,
  getPOIDetail,
  getVenuePhoto,
  batchGetVenuePhotos,

  // 地图
  mapSearchPOI,
  getWeather,
  planRoute,

  // 系统
  getServiceInfo,
  healthCheck,
  activityHealthCheck,
  isBackendAvailable,
  checkAllServices,
}
