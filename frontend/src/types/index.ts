/**
 * 前端类型定义 — 本地活动规划与执行
 *
 * 与后端 schemas.py 一一对应，确保前后端类型安全。
 */

// ============================================================================
// 基础类型
// ============================================================================

/** 地理坐标 */
export interface Location {
  longitude: number
  latitude: number
}

/** POI 信息 */
export interface POIInfo {
  id: string
  name: string
  type: string
  address: string
  location: Location
  tel?: string
  rating?: string
}

/** 天气信息 */
export interface WeatherInfo {
  date: string
  day_weather: string
  night_weather: string
  day_temp: number | string
  night_temp: number | string
  wind_direction: string
  wind_power: string
}

// ============================================================================
// 活动规划 — 请求
// ============================================================================

/** 群体详细信息 */
export interface GroupInfo {
  has_children: boolean
  children_ages: number[]
  has_elderly: boolean
  dietary_restrictions: string[]
  gender_split: string
}

/** 活动规划请求 */
export interface ActivityRequest {
  /** 2026-06-04: 轻量记忆身份，先用 demo_user 代替完整登录 */
  user_id?: string
  /** 规划模式：nearby_quick / detailed */
  planning_mode?: 'nearby_quick' | 'detailed'
  /** 2026-06-04: 执行模式，fast 走高德候选池，agent 保留深度多智能体链路 */
  execution_mode?: 'fast' | 'agent'
  /** 用户自然语言输入 */
  message: string
  /** 城市 */
  city: string
  /** 区域（选填） */
  district?: string
  /** 日期 YYYY-MM-DD */
  date?: string
  /** 开始时间 HH:MM */
  start_time?: string
  /** 可用时长（小时） */
  duration_hours?: number
  /** 群体类型：family / friends */
  group_type?: string
  /** 群体详细信息 */
  group_info?: GroupInfo
  /** 出发地坐标 */
  home_location?: Location
  /** 预算上限（元） */
  budget_limit?: number
}

// ============================================================================
// 活动规划 — 响应（方案）
// ============================================================================

/** 预算明细 */
export interface ActivityBudget {
  /** 总费用 */
  total: number
  /** 玩乐费用 */
  activities: number
  /** 餐饮费用 */
  dining: number
  /** 交通费用 */
  transportation: number
  /** 其他费用（蛋糕/鲜花等） */
  extras: number
}

/** 时间轴条目 */
export interface TimelineItem {
  /** 序号 */
  order: number
  /** 活动类型：transport / play / eat / extra */
  activity_type: 'transport' | 'play' | 'eat' | 'extra'
  /** 标题 */
  title: string
  /** 描述 */
  description?: string
  /** 开始时间 HH:MM */
  start_time: string
  /** 结束时间 HH:MM */
  end_time: string

  // —— 场所信息 ——
  /** 场所名称 */
  venue_name?: string
  /** 场所地址 */
  venue_address?: string
  /** 场所坐标 */
  venue_location?: Location
  /** 场所图片 URL */
  image_url?: string

  // —— 费用 & 标签 ——
  /** 预估费用（元） */
  estimated_cost?: number
  /** 标签（如 "亲子友好", "免费", "网红打卡"） */
  tags?: string[]

  // —— 交通信息（activity_type === 'transport' 时） ——
  /** 交通方式描述 */
  transportation?: string
  /** 交通时长（分钟） */
  travel_minutes?: number

  // —— 餐厅专属（activity_type === 'eat' 时） ——
  /** 用餐人数 */
  party_size?: number
  /** 排队状态描述 */
  queue_status?: string
  /** 是否可预约 */
  booking_available?: boolean
  /** 预订类型：restaurant / activity */
  booking_type?: string
  /** 餐厅特色标签（如 "有包间", "有儿童椅"） */
  restaurant_features?: string[]
}

/** 可执行动作 */
export interface ExecutableAction {
  /** 动作唯一 ID */
  action_id: string
  /** 动作类型：book_restaurant / book_activity / order_delivery / check_queue */
  action_type: 'book_restaurant' | 'book_activity' | 'order_delivery' | 'check_queue'
  /** 动作描述（面向用户的文案） */
  description: string
  /** 预估费用 */
  estimated_cost?: number
  /** 是否可选（true = 用户可跳过） */
  is_optional?: boolean
  /** 执行参数（传给后端 MockService） */
  params: Record<string, any>
}

/** 完整活动方案 */
export interface ActivityPlan {
  /** 方案 ID */
  plan_id?: string
  /** 城市 */
  city: string
  /** 区域 */
  district?: string
  /** 日期 */
  date: string
  /** 开始时间 */
  start_time: string
  /** 结束时间 */
  end_time: string
  /** 群体类型 */
  group_type?: string
  /** 群体概况文字（如 "一家三口，孩子5岁"） */
  group_summary?: string
  /** 天气概况（如 "晴，28°C，适合户外活动"） */
  weather_summary?: string
  /** 总体出行提示 */
  overall_tips?: string

  /** 预算明细 */
  budget?: ActivityBudget
  /** 时间轴 */
  timeline: TimelineItem[]
  /** 可执行动作列表 */
  executable_actions?: ExecutableAction[]
  /** 分享文案（LLM 直接生成的口语化短消息） */
  share_message?: string
  /** 2026-06-04: 后端端到端耗时 */
  server_timing?: Record<string, any>
  /** 2026-06-04: 规则质检报告 */
  quality_report?: Record<string, any>
  /** 2026-06-04: LLM 语义质检占位/报告 */
  llm_quality_report?: Record<string, any>
  /** 2026-06-04: 一句话时间解析结果 */
  time_intent?: Record<string, any>
  /** 2026-06-04: fast/agent 执行模式，结果页可用于展示生成策略 */
  execution_mode?: 'fast' | 'agent' | string
  /** 2026-06-04: 快速模式候选池摘要，说明地图点位已按真实 POI 锁定 */
  poi_candidate_summary?: Record<string, any>
  /** 2026-06-04: 后端返回的场景识别结果 */
  scenario?: Record<string, any>
  /** 2026-06-04: 本次规划命中的三层记忆上下文 */
  memory_context?: Record<string, any>
}

/** 2026-06-04: 自然语言反馈请求，用于记忆系统沉淀偏好 */
export interface MemoryFeedbackRequest {
  user_id: string
  scenario?: string
  event_type?: string
  target_type?: string
  target_name?: string
  tags?: string[]
  feedback_text: string
  raw_text?: string
}

/** 活动方案 API 响应包装 */
export interface ActivityPlanResponse {
  success: boolean
  message: string
  data?: ActivityPlan
}

// ============================================================================
// 执行动作 — 请求 & 响应
// ============================================================================

/** 执行请求 */
export interface ExecutionRequest {
  /** 方案 ID */
  plan_id: string
  /** 完整方案数据（后端需要从中提取 executable_actions） */
  plan: ActivityPlan
  /** 要执行的动作 ID 列表（为空 = 执行全部） */
  action_ids?: string[]
  /** 联系人姓名 */
  contact_name?: string
  /** 联系人电话 */
  contact_phone?: string
}

/** 单个动作执行结果 */
export interface ActionResult {
  /** 动作 ID */
  action_id: string
  /** 动作类型 */
  action_type: string
  /** 动作描述 */
  description: string
  /** 是否成功 */
  success: boolean
  /** 2026-06-04: 订单式执行状态：pending / processing / success / failed */
  status?: 'pending' | 'processing' | 'success' | 'failed' | string
  /** 2026-06-04: 状态文案 */
  status_text?: string
  /** 2026-06-04: 开始执行时间 */
  started_at?: string
  /** 2026-06-04: 完成执行时间 */
  completed_at?: string
  /** 2026-06-04: 是否可重试 */
  retryable?: boolean
  /** 2026-06-04: 失败后的备选动作 */
  fallback_action?: ExecutableAction | Record<string, any>
  /** 2026-06-04: 推荐备选动作的原因 */
  fallback_reason?: string
  /** 结果消息 */
  message: string
  /** 订单 ID */
  order_id?: string
  /** 确认码 */
  confirmation_code?: string
  /** 2026-06-04: 订单状态流转节点 */
  timeline?: Array<Record<string, any>>
  /** 详细数据 */
  details?: Record<string, any>
}

/** 执行响应 */
export interface ExecutionResponse {
  success: boolean
  message: string
  plan_id: string
  all_success: boolean
  results: ActionResult[]
  summary?: string
}

// ============================================================================
// 分享 — 请求 & 响应
// ============================================================================

/** 分享请求 */
export interface ShareRequest {
  /** 完整方案 */
  plan: ActivityPlan
  /** 接收人（如 "老婆", "小张"） */
  recipient?: string
  /** 语气：casual / formal */
  tone?: 'casual' | 'formal'
}

/** 分享响应 */
export interface ShareResponse {
  success: boolean
  message: string
  /** 默认分享文案 */
  share_text: string
  /** 短消息版（微信聊天） */
  short_text: string
  /** 详细版（群发） */
  detailed_text: string
}

// ============================================================================
// SSE 流式进度事件
// ============================================================================

/** 进度事件 */
export interface ProgressEvent {
  type: 'progress'
  step: number
  total: number
  percent: number
  message: string
}

/** 完成事件 */
export interface CompleteEvent {
  type: 'complete'
  success: boolean
  message: string
  data: ActivityPlan
}

/** 错误事件 */
export interface ErrorEvent {
  type: 'error'
  success: false
  message: string
}

/** SSE 事件联合类型 */
export type SSEEvent = ProgressEvent | CompleteEvent | ErrorEvent

// ============================================================================
// 排队查询
// ============================================================================

/** 排队查询请求 */
export interface QueueCheckRequest {
  restaurant_name: string
  city?: string
}

/** 排队查询结果 */
export interface QueueCheckResult {
  success: boolean
  message: string
  queue_length: number
  estimated_wait_minutes: number
  your_number?: string
}

// ============================================================================
// 餐厅可用性查询
// ============================================================================

/** 可用性查询请求 */
export interface AvailabilityCheckRequest {
  restaurant_name: string
  city?: string
  party_size?: number
  time?: string
}

/** 可用性查询结果 */
export interface AvailabilityCheckResult {
  restaurant_name: string
  available: boolean
  queue_length: number
  estimated_wait_minutes: number
  queue_status: string
  available_time_slots: string[]
  accepts_reservation: boolean
  special_notes?: string
}

// ============================================================================
// 团购优惠
// ============================================================================

/** 团购优惠条目 */
export interface DealItem {
  deal_id: string
  deal_name: string
  original_price: number
  deal_price: number
  discount: string
  remaining: number
  merchant: string
  address: string
}

/** 团购优惠响应 */
export interface DealsResponse {
  success: boolean
  count: number
  deals: DealItem[]
}

// ============================================================================
// 地图服务
// ============================================================================

/** POI 搜索请求 */
export interface POISearchRequest {
  keywords: string
  city: string
  citylimit?: boolean
}

/** POI 搜索响应 */
export interface POISearchResponse {
  success: boolean
  message: string
  data: POIInfo[]
}

/** 路线规划请求 */
export interface RouteRequest {
  origin_address: string
  destination_address: string
  origin_city?: string
  destination_city?: string
  route_type?: 'walking' | 'driving' | 'transit'
}

/** 路线规划结果 */
export interface RouteResult {
  distance: number
  duration: number
  route_type: string
  description: string
}

/** 路线规划响应 */
export interface RouteResponse {
  success: boolean
  message: string
  data: RouteResult
}

/** 天气响应 */
export interface WeatherResponse {
  success: boolean
  message: string
  data: WeatherInfo[]
}

// ============================================================================
// 通用
// ============================================================================

/** 通用错误响应 */
export interface ErrorResponse {
  success: false
  message: string
  detail?: string
}

/** 通用 API 响应包装 */
export interface ApiResponse<T = any> {
  success: boolean
  message: string
  data?: T
}

/** 健康检查响应 */
export interface HealthCheckResponse {
  status: 'healthy' | 'degraded' | 'unhealthy' | 'deprecated'
  service: string
  version?: string
  agents?: Record<string, string>
  tools_count?: Record<string, number>
}
