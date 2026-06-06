"""数据模型定义 - 本地活动规划与执行"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator
from datetime import date


# ============================================================================
# 通用基础模型（复用）
# ============================================================================

class Location(BaseModel):
    """地理位置"""
    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")


class WeatherInfo(BaseModel):
    """天气信息"""
    date: str = Field(default="", description="日期 YYYY-MM-DD")
    day_weather: str = Field(default="", description="白天天气")
    night_weather: str = Field(default="", description="夜间天气")
    day_temp: Union[int, str] = Field(default=0, description="白天温度")
    night_temp: Union[int, str] = Field(default=0, description="夜间温度")
    wind_direction: str = Field(default="", description="风向")
    wind_power: str = Field(default="", description="风力")

    @field_validator('day_temp', 'night_temp', mode='before')
    @classmethod
    def parse_temperature(cls, v):
        if isinstance(v, str):
            v = v.replace('°C', '').replace('℃', '').replace('°', '').strip()
            try:
                return int(v)
            except ValueError:
                return 0
        return v


# ============================================================================
# 活动规划 - 请求模型
# ============================================================================

class GroupDetails(BaseModel):
    """群体详细信息"""
    has_children: bool = Field(default=False, description="是否有儿童")
    children_ages: List[int] = Field(default_factory=list, description="儿童年龄列表")
    has_elderly: bool = Field(default=False, description="是否有老人")
    dietary_restrictions: List[str] = Field(
        default_factory=list,
        description="饮食限制,如 ['减肥', '素食', '海鲜过敏']"
    )
    gender_split: str = Field(default="", description="性别比例,如 '2男2女'")


class ActivityRequest(BaseModel):
    """活动规划请求 - 核心入口"""
    # 2026-06-04: 新增轻量记忆身份，先用 demo_user 代替完整登录系统
    user_id: str = Field(default="demo_user", description="记忆身份/用户ID", example="demo_user")
    planning_mode: str = Field(
        default="detailed",
        description="规划模式: nearby_quick(附近快排) / detailed(精细规划)",
        example="nearby_quick"
    )
    # 2026-06-04: 新增执行模式，fast 走高德结构化候选池，agent 保留原多智能体深度搜索链路
    execution_mode: str = Field(
        default="agent",
        description="执行模式: fast(极速生成/坐标锁定) / agent(深度思考/多智能体)",
        example="fast"
    )
    message: str = Field(
        ...,
        description="用户自然语言输入",
        example="今天下午是空的，想和老婆孩子出去玩几个小时，别离家太远，帮我安排一下。"
    )
    # 2026-06-04: 附近快排允许只提供定位坐标，后端会尝试反查城市；精细规划仍建议填写城市
    city: str = Field(default="", description="城市；附近快排可为空，由定位坐标反查", example="北京")
    district: str = Field(default="", description="区域/商圈", example="朝阳区")
    date: str = Field(
        default="",
        description="日期 YYYY-MM-DD,为空则取当天",
        example="2025-06-07"
    )
    start_time: str = Field(default="14:00", description="开始时间 HH:MM", example="14:00")
    duration_hours: int = Field(
        default=4, ge=1, le=12,
        description="可用时长(小时)",
        example=4
    )
    group_type: str = Field(
        default="",
        description="群体类型: family / friends,为空由 Agent 自动识别",
        example="family"
    )
    group_info: Optional[GroupDetails] = Field(
        default=None,
        description="群体详细信息(可选,Agent 也会从 message 中解析)"
    )
    home_location: Optional[Location] = Field(
        default=None,
        description="家庭位置(可选,用于计算距离)"
    )
    budget_limit: Optional[int] = Field(
        default=None,
        description="预算上限(元,可选)",
        example=500
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "demo_user",
                "planning_mode": "nearby_quick",
                "execution_mode": "fast",
                "message": "今天下午是空的，想和老婆孩子出去玩几个小时，别离家太远，帮我安排一下。孩子5岁，老婆最近在减肥。",
                "city": "北京",
                "district": "朝阳区",
                "date": "2025-06-07",
                "start_time": "14:00",
                "duration_hours": 5,
                "group_type": "family",
                "group_info": {
                    "has_children": True,
                    "children_ages": [5],
                    "has_elderly": False,
                    "dietary_restrictions": ["减肥"],
                    "gender_split": ""
                }
            }
        }


# ============================================================================
# 活动规划 - 意图解析结果（Agent 内部使用，也可作为调试输出）
# ============================================================================

class ParsedIntent(BaseModel):
    """Agent 解析后的结构化意图"""
    group_type: str = Field(default="family", description="family / friends")
    group_size: int = Field(default=3, description="总人数")
    group_details: Optional[GroupDetails] = Field(default=None, description="群体详情")
    preferred_activities: List[str] = Field(
        default_factory=list,
        description="偏好活动类型,如 ['亲子乐园', '公园', '展览']"
    )
    dining_preferences: List[str] = Field(
        default_factory=list,
        description="餐饮偏好,如 ['健康低卡', '适合孩子']"
    )
    constraints: List[str] = Field(
        default_factory=list,
        description="约束条件,如 ['活动范围3-5公里内']"
    )
    mood: str = Field(default="轻松休闲", description="氛围偏好")
    special_requests: List[str] = Field(
        default_factory=list,
        description="特殊要求"
    )


# ============================================================================
# 活动规划 - 方案模型
# ============================================================================

class TimelineItem(BaseModel):
    """时间轴中的单个条目"""
    order: int = Field(..., description="顺序编号,从1开始")
    start_time: str = Field(..., description="开始时间 HH:MM")
    end_time: str = Field(..., description="结束时间 HH:MM")
    activity_type: str = Field(
        ...,
        description="活动类型: transport / play / eat / extra"
    )
    title: str = Field(..., description="活动标题")
    description: str = Field(default="", description="活动描述(简短)")

    # 场所信息
    venue_name: str = Field(default="", description="场所名称")
    venue_address: str = Field(default="", description="场所地址")
    venue_location: Optional[Location] = Field(default=None, description="场所坐标")

    # 交通信息
    transportation: str = Field(default="", description="交通方式: 步行/驾车/公交/地铁")
    travel_minutes: int = Field(default=0, description="交通耗时(分钟)")

    # 费用
    estimated_cost: int = Field(default=0, description="预估费用(元)")

    # 标签
    tags: List[str] = Field(default_factory=list, description="标签,如 ['亲子', '户外']")

    # 可预订信息（仅 play / eat 类型）
    booking_available: Optional[bool] = Field(default=None, description="是否可预订")
    booking_type: Optional[str] = Field(
        default=None,
        description="预订类型: restaurant / activity_ticket"
    )

    # 餐厅专属字段
    party_size: Optional[int] = Field(default=None, description="用餐人数")
    queue_status: Optional[str] = Field(default=None, description="排队状态")
    restaurant_features: Optional[List[str]] = Field(
        default=None,
        description="餐厅特色,如 ['有儿童座椅', '有健康菜单']"
    )

    # 活动专属字段
    ticket_count: Optional[int] = Field(default=None, description="门票数量")

    # POI信息（用于获取图片等）
    poi_id: Optional[str] = Field(default=None, description="高德POI ID")
    image_url: Optional[str] = Field(default=None, description="场所图片URL")


class ActivityBudget(BaseModel):
    """活动预算"""
    activities: int = Field(default=0, description="玩乐费用(元)")
    dining: int = Field(default=0, description="餐饮费用(元)")
    transportation: int = Field(default=0, description="交通费用(元)")
    extras: int = Field(default=0, description="其他费用(元)")
    total: int = Field(default=0, description="总费用(元)")


class ExecutableAction(BaseModel):
    """可执行的动作（预约/下单）"""
    action_id: str = Field(..., description="动作唯一ID,如 act_001")
    action_type: str = Field(
        ...,
        description="动作类型: book_restaurant / book_activity / order_delivery / check_queue"
    )
    description: str = Field(..., description="动作描述,如 '预约XX餐厅 3人桌 17:00'")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="动作参数,随 action_type 不同而不同"
    )
    is_optional: bool = Field(
        default=False,
        description="是否为可选动作(如送蛋糕鲜花)"
    )
    estimated_cost: int = Field(default=0, description="预估费用(元)")


class ActivityPlan(BaseModel):
    """完整的活动方案"""
    plan_id: str = Field(..., description="方案唯一ID")
    city: str = Field(..., description="城市")
    district: str = Field(default="", description="区域")
    date: str = Field(..., description="日期 YYYY-MM-DD")
    group_type: str = Field(default="family", description="群体类型")
    group_summary: str = Field(
        default="",
        description="群体描述,如 '家庭出游(含5岁孩子)'"
    )
    start_time: str = Field(..., description="开始时间 HH:MM")
    end_time: str = Field(..., description="结束时间 HH:MM")

    timeline: List[TimelineItem] = Field(
        default_factory=list,
        description="时间轴条目列表"
    )

    weather_summary: str = Field(default="", description="天气摘要")

    budget: Optional[ActivityBudget] = Field(
        default=None,
        description="预算明细"
    )

    executable_actions: List[ExecutableAction] = Field(
        default_factory=list,
        description="可执行动作列表"
    )

    share_message: str = Field(
        default="",
        description="分享给同伴的消息文案"
    )

    overall_tips: str = Field(default="", description="总体提示建议")

    # 调试/透明度字段（可选）
    parsed_intent: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Agent 解析出的意图(调试用)"
    )


# ============================================================================
# 执行动作 - 请求与响应
# ============================================================================

class ExecutionRequest(BaseModel):
    """执行动作请求"""
    plan_id: str = Field(..., description="方案ID")
    plan: Dict[str, Any] = Field(..., description="完整方案数据")
    action_ids: Optional[List[str]] = Field(
        default=None,
        description="要执行的动作ID列表；为空则执行全部"
    )
    contact_name: str = Field(default="用户", description="联系人姓名")
    contact_phone: str = Field(default="", description="联系人电话")

    class Config:
        json_schema_extra = {
            "example": {
                "plan_id": "plan_20250607_abc123",
                "plan": {},
                "action_ids": ["act_001", "act_002"],
                "contact_name": "小明",
                "contact_phone": "13800138000"
            }
        }


class ActionResult(BaseModel):
    """单个动作的执行结果"""
    action_id: str = Field(..., description="动作ID")
    action_type: str = Field(..., description="动作类型")
    description: str = Field(default="", description="动作描述")
    success: bool = Field(..., description="是否成功")
    # 2026-06-04: 订单式执行状态，用于展示 待确认 -> 执行中 -> 成功/失败 的闭环
    status: str = Field(default="success", description="执行状态: pending / processing / success / failed")
    status_text: str = Field(default="", description="状态文案")
    started_at: Optional[str] = Field(default=None, description="开始执行时间")
    completed_at: Optional[str] = Field(default=None, description="完成执行时间")
    retryable: bool = Field(default=False, description="失败后是否可重试")
    fallback_action: Optional[Dict[str, Any]] = Field(default=None, description="失败后的备选动作")
    fallback_reason: Optional[str] = Field(default=None, description="推荐备选动作的原因")
    message: str = Field(default="", description="结果消息")
    order_id: Optional[str] = Field(default=None, description="订单号(如有)")
    confirmation_code: Optional[str] = Field(
        default=None,
        description="确认码/预约号(如有)"
    )
    timeline: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="订单状态流转时间线"
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="额外细节"
    )


class ExecutionResponse(BaseModel):
    """执行动作响应"""
    success: bool = Field(..., description="是否全部成功")
    message: str = Field(default="", description="整体消息")
    plan_id: str = Field(default="", description="方案ID")
    all_success: bool = Field(default=False, description="是否所有动作都成功")
    results: List[ActionResult] = Field(
        default_factory=list,
        description="每个动作的执行结果"
    )
    summary: str = Field(default="", description="执行结果摘要文本")


# ============================================================================
# 分享消息
# ============================================================================

class ShareRequest(BaseModel):
    """生成分享消息请求"""
    plan: Dict[str, Any] = Field(..., description="完整方案数据")
    recipient: str = Field(
        default="同伴",
        description="分享对象,如 '老婆' / '朋友们'"
    )
    tone: str = Field(
        default="casual",
        description="语气风格: casual(口语) / formal(正式)"
    )


class ShareResponse(BaseModel):
    """生成分享消息响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    share_text: str = Field(default="", description="分享文案")
    short_text: str = Field(
        default="",
        description="短文案(适合微信聊天)"
    )
    detailed_text: str = Field(
        default="",
        description="详细文案(适合群发)"
    )


# ============================================================================
# 记忆反馈 - 请求与响应
# ============================================================================

class MemoryFeedbackRequest(BaseModel):
    """2026-06-04: 自然语言反馈请求，用于沉淀用户级/场景级/对象级记忆。"""
    user_id: str = Field(default="demo_user", description="记忆身份/用户ID")
    scenario: str = Field(default="", description="当前场景标签，如 family_kid / couple_date")
    event_type: str = Field(default="feedback", description="反馈类型: feedback / like / dislike / avoid / execute")
    target_type: str = Field(default="", description="反馈对象类型: venue / restaurant / plan / action")
    target_name: str = Field(default="", description="反馈对象名称")
    tags: List[str] = Field(default_factory=list, description="对象标签")
    feedback_text: str = Field(..., description="用户自然语言反馈")
    raw_text: str = Field(default="", description="原始上下文")


class MemoryFeedbackResponse(BaseModel):
    """自然语言反馈写入结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="结果消息")
    data: Dict[str, Any] = Field(default_factory=dict, description="事件和提取结果")


class MemoryContextResponse(BaseModel):
    """记忆上下文响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="结果消息")
    data: Dict[str, Any] = Field(default_factory=dict, description="记忆上下文")


# ============================================================================
# 活动规划 - API 响应包装
# ============================================================================

class ActivityPlanResponse(BaseModel):
    """活动方案 API 响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[ActivityPlan] = Field(default=None, description="活动方案数据")


class ActivityPlanRawResponse(BaseModel):
    """活动方案 API 响应（dict 形式，兼容 Agent 返回的原始 JSON）"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="活动方案数据(字典)")


# ============================================================================
# Mock 服务相关模型
# ============================================================================

class RestaurantAvailability(BaseModel):
    """餐厅可用性信息"""
    restaurant_name: str = Field(..., description="餐厅名称")
    available: bool = Field(..., description="是否有空位")
    queue_length: int = Field(default=0, description="排队组数")
    estimated_wait_minutes: int = Field(default=0, description="预估等待时间(分钟)")
    queue_status: str = Field(
        default="未知",
        description="排队状态: 无需排队 / 约等15分钟 / 约等30分钟 / 约等60分钟以上"
    )
    available_time_slots: List[str] = Field(
        default_factory=list,
        description="可预约时间段, 如 ['17:00', '17:30', '18:00']"
    )
    accepts_reservation: bool = Field(
        default=True,
        description="是否接受预约"
    )
    special_notes: str = Field(default="", description="特别说明")


class BookingResult(BaseModel):
    """预订结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="结果消息")
    order_id: Optional[str] = Field(default=None, description="订单号")
    confirmation_code: Optional[str] = Field(default=None, description="确认码")
    booking_time: Optional[str] = Field(default=None, description="预订时间")
    details: Optional[Dict[str, Any]] = Field(default=None, description="详情")


class DeliveryOrderResult(BaseModel):
    """配送下单结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="结果消息")
    order_id: Optional[str] = Field(default=None, description="订单号")
    estimated_delivery_time: Optional[str] = Field(
        default=None,
        description="预计送达时间"
    )
    item_name: str = Field(default="", description="商品名称")
    price: int = Field(default=0, description="价格(元)")
    details: Optional[Dict[str, Any]] = Field(default=None, description="详情")


# ============================================================================
# POI 相关模型（保留，地图/搜索 API 仍需要）
# ============================================================================

class POIInfo(BaseModel):
    """POI信息"""
    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="名称")
    type: str = Field(..., description="类型")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: Optional[str] = Field(default=None, description="电话")
    rating: Optional[str] = Field(default=None, description="评分")
    photos: Optional[List[str]] = Field(default_factory=list, description="图片列表")


class POISearchRequest(BaseModel):
    """POI搜索请求"""
    keywords: str = Field(..., description="搜索关键词", example="亲子餐厅")
    city: str = Field(..., description="城市", example="北京")
    citylimit: bool = Field(default=True, description="是否限制在城市范围内")


class POISearchResponse(BaseModel):
    """POI搜索响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[POIInfo] = Field(default=[], description="POI列表")


# ============================================================================
# 路线规划模型（保留）
# ============================================================================

class RouteRequest(BaseModel):
    """路线规划请求"""
    origin_address: str = Field(..., description="起点地址")
    destination_address: str = Field(..., description="终点地址")
    origin_city: Optional[str] = Field(default=None, description="起点城市")
    destination_city: Optional[str] = Field(default=None, description="终点城市")
    route_type: str = Field(
        default="walking",
        description="路线类型: walking/driving/transit"
    )


class RouteInfo(BaseModel):
    """路线信息"""
    distance: float = Field(..., description="距离(米)")
    duration: int = Field(..., description="时间(秒)")
    route_type: str = Field(..., description="路线类型")
    description: str = Field(..., description="路线描述")


class RouteResponse(BaseModel):
    """路线规划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[RouteInfo] = Field(default=None, description="路线信息")


# ============================================================================
# 天气响应（保留）
# ============================================================================

class WeatherResponse(BaseModel):
    """天气查询响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[WeatherInfo] = Field(default=[], description="天气信息")


# ============================================================================
# 通用错误响应
# ============================================================================

class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = Field(default=False, description="是否成功")
    message: str = Field(..., description="错误消息")
    error_code: Optional[str] = Field(default=None, description="错误代码")


# ============================================================================
# 健康检查
# ============================================================================

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="服务状态")
    service: str = Field(..., description="服务名称")
    version: str = Field(default="1.0.0", description="版本")
    agents: Optional[Dict[str, str]] = Field(default=None, description="Agent 状态")
    tools_count: Optional[Dict[str, int]] = Field(default=None, description="工具数量")
