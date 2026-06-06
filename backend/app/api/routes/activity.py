"""
本地活动规划 API 路由

端点：
  POST /api/activity/plan          — 生成活动方案（非流式）
  POST /api/activity/plan/stream   — 生成活动方案（SSE 流式进度）
  POST /api/activity/execute       — 执行方案中的预约/下单动作
  POST /api/activity/share         — 生成分享消息
  GET  /api/activity/deals         — 获取附近团购优惠
  POST /api/activity/check-queue   — 查询餐厅排队状态
  GET  /api/activity/health        — 健康检查
"""

import asyncio
import json
import queue
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from ...models.schemas import (
    ActivityRequest,
    ActivityPlanRawResponse,
    ExecutionRequest,
    ExecutionResponse,
    ActionResult,
    ShareRequest,
    ShareResponse,
    MemoryFeedbackRequest,
    MemoryFeedbackResponse,
    MemoryContextResponse,
    ErrorResponse,
)
from ...agents.activity_planner_agent import get_activity_planner

router = APIRouter(prefix="/activity", tags=["本地活动规划"])


def _build_server_timing(start_perf: float, start_wall: datetime) -> dict:
    """2026-06-04: 生成后端端到端耗时信息，从收到 POST 到准备返回前端。"""
    end_wall = datetime.now(timezone.utc)
    duration_ms = round((time.perf_counter() - start_perf) * 1000, 2)
    return {
        "received_at": start_wall.isoformat(),
        "completed_at": end_wall.isoformat(),
        "duration_ms": duration_ms,
        "duration_seconds": round(duration_ms / 1000, 3),
    }


# ============================================================================
# 1. 生成活动方案（非流式）
# ============================================================================

@router.post(
    "/plan",
    response_model=ActivityPlanRawResponse,
    summary="生成活动方案",
    description="根据用户自然语言输入，生成可执行的本地活动方案",
)
async def plan_activity(request: ActivityRequest):
    """生成活动方案（非流式）"""
    # 2026-06-04: 记录非流式 POST 从进入路由到返回前端的总耗时
    start_perf = time.perf_counter()
    start_wall = datetime.now(timezone.utc)
    try:
        print(f"\n{'='*60}")
        print(f"[REQ] 收到活动规划请求:")
        print(f"   消息: {request.message[:100]}")
        print(f"   城市: {request.city}")
        print(f"   日期: {request.date}")
        print(f"   开始: {request.start_time}  时长: {request.duration_hours}h")
        print(f"   群体: {request.group_type}")
        print(f"{'='*60}\n")

        planner = get_activity_planner()

        # 构建请求字典
        req_dict = _build_request_dict(request)

        # 在线程池中执行（避免阻塞事件循环）
        plan = await asyncio.to_thread(planner.plan_activity, req_dict)
        plan["server_timing"] = _build_server_timing(start_perf, start_wall)

        print(f"[OK] 活动方案生成成功，用时 {plan['server_timing']['duration_seconds']}s\n")

        return ActivityPlanRawResponse(
            success=True,
            message="活动方案生成成功",
            data=plan,
        )

    except Exception as e:
        print(f"[ERR] 生成活动方案失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"生成活动方案失败: {str(e)}",
        )


# ============================================================================
# 2. 生成活动方案（SSE 流式进度）
# ============================================================================

@router.post(
    "/plan/stream",
    summary="生成活动方案（流式进度）",
    description="通过 SSE 实时推送各阶段进度，最终返回完整的活动方案",
)
async def plan_activity_stream(request: ActivityRequest):
    """
    返回 text/event-stream，事件格式：
      data: {"type":"progress", "step":1, "total":5, "percent":10, "message":"..."}
      data: {"type":"complete", "success":true, "message":"...", "data":{...}}
      data: {"type":"error", "success":false, "message":"..."}
    """
    # 2026-06-04: 记录流式 POST 从进入路由到 complete 事件发出前的总耗时
    start_perf = time.perf_counter()
    start_wall = datetime.now(timezone.utc)

    # 2026-06-03 修复：添加实时日志，让终端能看到后端进展
    print(f"\n{'='*60}")
    print(f"[REQ] 收到流式活动规划请求:")
    print(f"   消息: {request.message[:100]}")
    print(f"   城市: {request.city}")
    print(f"{'='*60}\n")

    progress_queue: queue.Queue = queue.Queue()

    def progress_callback(data: dict):
        """Agent 同步线程中调用，向队列写入进度"""
        msg = data.get("message", "")
        step = data.get("step", 0)
        if msg:
            print(f"  [STREAM] Step {step}: {msg}")
        progress_queue.put(data)

    planner = get_activity_planner()
    req_dict = _build_request_dict(request)

    async def run_agent():
        print("[INIT] 开始多智能体协作规划...")
        return await asyncio.to_thread(
            planner.plan_activity, req_dict, progress_callback
        )

    async def event_generator():
        task = asyncio.create_task(run_agent())

        # 持续消费进度队列
        while not task.done():
            try:
                event = progress_queue.get_nowait()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except queue.Empty:
                pass
            await asyncio.sleep(0.2)

        # 排空剩余事件
        while not progress_queue.empty():
            event = progress_queue.get_nowait()
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # 获取最终结果
        try:
            result = task.result()
            server_timing = _build_server_timing(start_perf, start_wall)
            result["server_timing"] = server_timing
            print(f"[OK] 流式方案生成完成，用时 {server_timing['duration_seconds']}s\n")
            final_event = {
                "type": "complete",
                "success": True,
                "message": "活动方案生成成功",
                "data": result,
                "server_timing": server_timing,
            }
            yield f"data: {json.dumps(final_event, ensure_ascii=False)}\n\n"
        except Exception as e:
            print(f"[ERR] 流式方案生成失败: {str(e)}\n")
            error_event = {
                "type": "error",
                "success": False,
                "message": str(e),
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================================
# 3. 执行方案动作（预约/下单）
# ============================================================================

@router.post(
    "/execute",
    response_model=ExecutionResponse,
    summary="执行方案动作",
    description="用户确认方案后，一键执行预约/下单等动作（Mock）",
)
async def execute_actions(request: ExecutionRequest):
    """执行方案中的预约/下单动作"""
    try:
        print(f"\n{'='*60}")
        print(f"[EXEC] 收到执行请求:")
        print(f"   方案ID: {request.plan_id}")
        print(f"   动作数: {len(request.action_ids) if request.action_ids else '全部'}")
        print(f"   联系人: {request.contact_name} {request.contact_phone}")
        print(f"{'='*60}\n")

        planner = get_activity_planner()

        # 注入联系人信息到 plan 的 executable_actions 中
        plan = request.plan
        if request.contact_phone:
            for action in plan.get("executable_actions", []):
                params = action.get("params", {})
                if not params.get("contact_phone") or params["contact_phone"] == "待填写":
                    params["contact_phone"] = request.contact_phone
                if not params.get("contact_name"):
                    params["contact_name"] = request.contact_name

        # 在线程池中执行
        result = await asyncio.to_thread(
            planner.execute_actions, plan, request.action_ids
        )

        print(f"[OK] 执行完成: all_success={result.get('all_success')}\n")

        # 转换结果
        action_results = []
        for r in result.get("results", []):
            action_results.append(ActionResult(
                action_id=r.get("action_id", ""),
                action_type=r.get("action_type", ""),
                description=r.get("description", ""),
                success=r.get("success", False),
                # 2026-06-04: 透传订单式状态和失败备选，避免 response_model 过滤执行闭环字段
                status=r.get("status", "success" if r.get("success", False) else "failed"),
                status_text=r.get("status_text", ""),
                started_at=r.get("started_at"),
                completed_at=r.get("completed_at"),
                retryable=r.get("retryable", False),
                fallback_action=r.get("fallback_action"),
                fallback_reason=r.get("fallback_reason"),
                message=r.get("message", ""),
                order_id=r.get("order_id"),
                confirmation_code=r.get("confirmation_code"),
                timeline=r.get("timeline"),
                details=r.get("details"),
            ))

        return ExecutionResponse(
            success=result.get("all_success", False),
            message="全部执行成功" if result.get("all_success") else "部分动作执行失败",
            plan_id=result.get("plan_id", request.plan_id),
            all_success=result.get("all_success", False),
            results=action_results,
            summary=result.get("summary", ""),
        )

    except Exception as e:
        print(f"[ERR] 执行动作失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"执行动作失败: {str(e)}",
        )


# ============================================================================
# 4. 生成分享消息
# ============================================================================

@router.post(
    "/share",
    response_model=ShareResponse,
    summary="生成分享消息",
    description="根据活动方案生成可分享给同伴的文案",
)
async def generate_share_message(request: ShareRequest):
    """生成分享消息"""
    try:
        plan = request.plan
        recipient = request.recipient
        tone = request.tone

        # 从 plan 中提取信息构建分享文案
        city = plan.get("city", "")
        date = plan.get("date", "")
        start_time = plan.get("start_time", "14:00")
        end_time = plan.get("end_time", "20:00")
        timeline = plan.get("timeline", [])
        budget = plan.get("budget", {})
        overall_tips = plan.get("overall_tips", "")

        # 如果 plan 中已有 share_message，直接使用
        existing_share = plan.get("share_message", "")

        # 构建短消息（微信聊天风格）
        activity_names = []
        restaurant_name = ""
        for item in timeline:
            if item.get("activity_type") == "play" and item.get("venue_name"):
                activity_names.append(item["venue_name"])
            if item.get("activity_type") == "eat" and item.get("venue_name"):
                restaurant_name = item["venue_name"]

        short_parts = [f"搞定了！{date} {start_time}出发"]
        if activity_names:
            short_parts.append(f"先去{activity_names[0]}")
        if restaurant_name:
            short_parts.append(f"然后去{restaurant_name}吃饭")
        if budget and budget.get("total"):
            short_parts.append(f"预算约¥{budget['total']}")
        short_text = "，".join(short_parts) + "~"

        # 构建详细消息（群发风格）
        detailed_lines = [
            f"📋 {city}活动安排 ({date})",
            f"⏰ {start_time} - {end_time}",
            "",
        ]
        for item in timeline:
            if item.get("activity_type") == "transport":
                continue
            emoji_map = {"play": "🎯", "eat": "🍽️", "extra": "✨"}
            emoji = emoji_map.get(item.get("activity_type", ""), "📍")
            line = f"{emoji} {item.get('start_time', '')} - {item.get('end_time', '')}  {item.get('title', '')}"
            if item.get("venue_address"):
                line += f"\n   📍 {item['venue_address']}"
            if item.get("estimated_cost", 0) > 0:
                line += f"\n   💰 约¥{item['estimated_cost']}"
            detailed_lines.append(line)
            detailed_lines.append("")

        if budget and budget.get("total"):
            detailed_lines.append(f"💰 预估总费用：¥{budget['total']}")
        if overall_tips:
            detailed_lines.append(f"💡 {overall_tips}")

        detailed_text = "\n".join(detailed_lines)

        return ShareResponse(
            success=True,
            message="分享文案生成成功",
            share_text=existing_share if existing_share else short_text,
            short_text=short_text,
            detailed_text=detailed_text,
        )

    except Exception as e:
        print(f"[ERR] 生成分享消息失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"生成分享消息失败: {str(e)}",
        )


# ============================================================================
# 5. 获取附近团购优惠
# ============================================================================

@router.get(
    "/deals",
    summary="获取附近团购优惠",
    description="获取附近的团购优惠信息（Mock）",
)
async def get_nearby_deals(
    city: str = Query(..., description="城市", example="北京"),
    district: str = Query("", description="区域", example="朝阳区"),
    category: str = Query("", description="类别筛选", example="亲子"),
    limit: int = Query(5, ge=1, le=20, description="返回数量"),
):
    """获取附近团购优惠"""
    try:
        from ...services.mock_service import get_mock_service
        mock_svc = get_mock_service()

        result = mock_svc.get_nearby_deals(
            city=city,
            district=district,
            category=category,
            limit=limit,
        )

        return {
            "success": True,
            "message": f"获取到 {result.get('count', 0)} 条团购优惠",
            "data": result,
        }

    except Exception as e:
        print(f"[ERR] 获取团购优惠失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取团购优惠失败: {str(e)}",
        )


# ============================================================================
# 6. 查询餐厅排队状态
# ============================================================================

class QueueCheckRequest(BaseModel):
    """排队查询请求"""
    restaurant_name: str = Field(..., description="餐厅名称")
    city: str = Field(default="", description="城市")


@router.post(
    "/check-queue",
    summary="查询餐厅排队状态",
    description="实时查询指定餐厅的排队情况（Mock）",
)
async def check_queue_status(request: QueueCheckRequest):
    """查询餐厅排队状态"""
    try:
        from ...services.mock_service import get_mock_service
        mock_svc = get_mock_service()

        result = mock_svc.check_queue_status(
            restaurant_name=request.restaurant_name,
            city=request.city,
        )

        return {
            "success": True,
            "message": result.get("message", ""),
            "data": result,
        }

    except Exception as e:
        print(f"[ERR] 查询排队状态失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询排队状态失败: {str(e)}",
        )


# ============================================================================
# 7. 查询餐厅可用性
# ============================================================================

class AvailabilityCheckRequest(BaseModel):
    """餐厅可用性查询请求"""
    restaurant_name: str = Field(..., description="餐厅名称")
    city: str = Field(default="", description="城市")
    party_size: int = Field(default=2, description="用餐人数")
    time: str = Field(default="17:00", description="用餐时间 HH:MM")


@router.post(
    "/check-availability",
    summary="查询餐厅可用性",
    description="查询餐厅的座位和预约可用情况（Mock）",
)
async def check_restaurant_availability(request: AvailabilityCheckRequest):
    """查询餐厅可用性"""
    try:
        from ...services.mock_service import get_mock_service
        mock_svc = get_mock_service()

        result = mock_svc.check_restaurant_availability(
            restaurant_name=request.restaurant_name,
            city=request.city,
            party_size=request.party_size,
            time=request.time,
        )

        return {
            "success": True,
            "message": result.get("queue_status", ""),
            "data": result,
        }

    except Exception as e:
        print(f"[ERR] 查询餐厅可用性失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询餐厅可用性失败: {str(e)}",
        )


# ============================================================================
# 8. 健康检查
# ============================================================================

@router.get(
    "/health",
    summary="健康检查",
    description="检查活动规划服务是否正常",
)
async def health_check():
    """健康检查"""
    try:
        planner = get_activity_planner()

        return {
            "status": "healthy",
            "service": "activity-planner",
            # 2026-06-05: 搜索/天气 Agent 已懒初始化，健康检查不再触发 MCP 初始化，避免误伤极速模式启动速度
            "agents": {
                "intent_agent": planner.intent_agent.name,
                "venue_agent": planner.venue_agent.name if planner.venue_agent else "lazy",
                "restaurant_agent": planner.restaurant_agent.name if planner.restaurant_agent else "lazy",
                "weather_agent": planner.weather_agent.name if planner.weather_agent else "lazy",
                "planner_agent": planner.planner_agent.name,
            },
            "tools_count": {
                "venue_agent": len(planner.venue_agent.list_tools()) if planner.venue_agent else 0,
                "restaurant_agent": len(planner.restaurant_agent.list_tools()) if planner.restaurant_agent else 0,
                "weather_agent": len(planner.weather_agent.list_tools()) if planner.weather_agent else 0,
            },
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"服务不可用: {str(e)}",
        )


# ============================================================================
# 9. 记忆反馈与上下文查询
# ============================================================================

@router.post(
    "/memory/feedback",
    response_model=MemoryFeedbackResponse,
    summary="提交自然语言反馈",
    description="用户用自然语言评价某条推荐，后端提取为用户级、场景级、对象级记忆并同步图谱。",
)
async def submit_memory_feedback(request: MemoryFeedbackRequest):
    """2026-06-04: 接收前端自然语言反馈，写入 SQLite 并可选同步 Neo4j 图谱。"""
    try:
        from ...services.memory_service import get_memory_service
        memory_service = get_memory_service()
        result = memory_service.record_event(
            user_id=request.user_id or "demo_user",
            event_type=request.event_type or "feedback",
            scenario=request.scenario or "unknown",
            target_type=request.target_type,
            target_name=request.target_name,
            tags=request.tags,
            feedback_text=request.feedback_text,
            raw_text=request.raw_text,
            extract=True,
        )
        return MemoryFeedbackResponse(
            success=True,
            message="反馈已写入记忆系统",
            data=result,
        )
    except Exception as e:
        print(f"[ERR] 写入记忆反馈失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"写入记忆反馈失败: {str(e)}")


@router.get(
    "/memory/summary",
    response_model=MemoryContextResponse,
    summary="获取用户记忆摘要",
    description="查看当前用户已沉淀的稳定偏好、场景偏好和最近反馈。",
)
async def get_memory_summary(user_id: str = Query("demo_user", description="记忆身份/用户ID")):
    """2026-06-04: 给前端展示轻量记忆摘要，便于用户理解 Agent 记住了什么。"""
    try:
        from ...services.memory_service import get_memory_service
        memory_service = get_memory_service()
        return MemoryContextResponse(
            success=True,
            message="记忆摘要获取成功",
            data=memory_service.get_summary(user_id),
        )
    except Exception as e:
        print(f"[ERR] 获取记忆摘要失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取记忆摘要失败: {str(e)}")


@router.post(
    "/memory/cleanup-technical-tags",
    response_model=MemoryContextResponse,
    summary="清理内部技术记忆标签",
    description="清理历史误写入的真实POI/交通等技术标签，避免它们被展示为用户偏好。",
)
async def cleanup_memory_technical_tags(user_id: str = Query("", description="记忆身份/用户ID；为空则清理全部用户")):
    """2026-06-05: 清理记忆系统历史污染的内部标签，例如“真实POI”。"""
    try:
        from ...services.memory_service import get_memory_service
        memory_service = get_memory_service()
        return MemoryContextResponse(
            success=True,
            message="内部技术标签清理完成",
            data=memory_service.cleanup_technical_tags(user_id),
        )
    except Exception as e:
        print(f"[ERR] 清理内部技术标签失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清理内部技术标签失败: {str(e)}")


@router.post(
    "/memory/rebuild-graph",
    response_model=MemoryContextResponse,
    summary="重建 Neo4j 用户画像图",
    description="从 SQLite 原始反馈事件重新生成 Neo4j 主图，用于图谱结构调整后的演示修复。",
)
async def rebuild_memory_graph(user_id: str = Query("demo_user", description="记忆身份/用户ID")):
    """2026-06-04: 从 SQLite 重放反馈事件，按最新 场景->地点->反馈标签 结构重建 Neo4j。"""
    try:
        from ...services.memory_service import get_memory_service
        memory_service = get_memory_service()
        return MemoryContextResponse(
            success=True,
            message="Neo4j 用户画像图重建完成",
            data=memory_service.rebuild_graph_for_user(user_id),
        )
    except Exception as e:
        print(f"[ERR] 重建 Neo4j 用户画像图失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重建 Neo4j 用户画像图失败: {str(e)}")


@router.post(
    "/memory/rebuild-memories",
    response_model=MemoryContextResponse,
    summary="按最新规则重建凝练记忆",
    description="从 SQLite 原始反馈事件重建场景记忆、对象记忆和 Neo4j 图谱，用于修复反馈动作词被误抽成偏好节点的问题。",
)
async def rebuild_memory_profiles(user_id: str = Query("", description="记忆身份/用户ID；为空则重建全部用户")):
    """2026-06-06: 将“下次别推/换一个”等反馈动作词从偏好节点中剥离，按最新规则重建记忆画像。"""
    try:
        from ...services.memory_service import get_memory_service
        memory_service = get_memory_service()
        return MemoryContextResponse(
            success=True,
            message="凝练记忆已按最新规则重建",
            data=memory_service.rebuild_memories_from_events(user_id),
        )
    except Exception as e:
        print(f"[ERR] 重建凝练记忆失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重建凝练记忆失败: {str(e)}")


# ============================================================================
# 辅助函数
# ============================================================================

def _build_request_dict(request: ActivityRequest) -> dict:
    """将 Pydantic 模型转换为 Agent 使用的 dict"""
    from datetime import datetime as dt

    req_dict: Dict[str, Any] = {
        # 2026-06-04: 透传轻量记忆身份，用于规划前 Graph Memory RAG 检索
        "user_id": request.user_id,
        "planning_mode": request.planning_mode,
        # 2026-06-05: 明确把执行模式放进 Agent 请求字典，确保极速模式不会回退到深度模式。
        "execution_mode": request.execution_mode,
        "message": request.message,
        "city": request.city,
        "district": request.district,
        "date": request.date if request.date else dt.now().strftime("%Y-%m-%d"),
        "start_time": request.start_time,
        "duration_hours": request.duration_hours,
        "group_type": request.group_type,
    }

    if request.group_info:
        req_dict["group_info"] = request.group_info.model_dump()

    if request.home_location:
        req_dict["home_location"] = request.home_location.model_dump()

    if request.budget_limit is not None:
        req_dict["budget_limit"] = request.budget_limit

    return req_dict
