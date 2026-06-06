"""FastAPI主应用 - 本地活动规划与执行"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ..config import get_settings, validate_config, print_config
from .routes import activity, poi, map as map_routes

# 获取配置
settings = get_settings()

# 创建FastAPI应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="基于HelloAgents框架的智能本地活动规划助手API —— "
                "接受一句自然语言目标，输出可执行的完整方案并自动完成关键下单/预订动作。",
    docs_url="/docs",
    redoc_url="/redoc",
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# 注册路由
# ============================================================================

# 核心：活动规划与执行
app.include_router(activity.router, prefix="/api")

# 辅助：POI 搜索、图片获取
app.include_router(poi.router, prefix="/api")

# 辅助：地图服务（天气、路线）
app.include_router(map_routes.router, prefix="/api")


# ============================================================================
# 生命周期事件
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    print("\n" + "=" * 60)
    print(f"[START] {settings.app_name} v{settings.app_version}")  # 2026-06-03 修复：Windows emoji 编码崩溃
    print("=" * 60)

    # 打印配置信息
    print_config()

    # 验证配置
    try:
        validate_config()
        print("\n[OK] 配置验证通过")  # 2026-06-03 修复：emoji 编码
    except ValueError as e:
        print(f"\n[ERR] 配置验证失败:\n{e}")  # 2026-06-03 修复：emoji 编码
        print("\n请检查.env文件并确保所有必要的配置项都已设置")
        raise

    # 2026-06-04: Neo4j 图谱记忆为可选增强，连接失败不阻塞主服务启动
    try:
        from ..services.graph_memory_service import get_graph_memory_service
        graph_memory = get_graph_memory_service()
        graph_health = graph_memory.health()
        if graph_health["enabled"] and graph_health["available"]:
            # 2026-06-04: 启动时整理旧图谱显示名，让 UserScenario 显示为“约会场景/亲子场景”而不是用户ID
            graph_memory.normalize_display_names()
            print(f"[OK] Neo4j图谱记忆已连接: {graph_health['uri']} / {graph_health['database']}")
        elif graph_health["enabled"]:
            print(f"[WARN] Neo4j图谱记忆已启用但不可用: {graph_health['error']}")
        else:
            print("[INFO] Neo4j图谱记忆未启用")
    except Exception as e:
        print(f"[WARN] Neo4j图谱记忆检查失败: {e}")

    print("\n" + "=" * 60)
    print("[API] API文档: http://localhost:8000/docs")  # 2026-06-03 修复：emoji 编码
    print("[DOC] ReDoc文档: http://localhost:8000/redoc")
    print("=" * 60)
    print()
    print("核心端点:")
    print("  POST /api/activity/plan          — 生成活动方案")
    print("  POST /api/activity/plan/stream   — 生成方案(流式进度)")
    print("  POST /api/activity/execute       — 一键执行预约/下单")
    print("  POST /api/activity/share         — 生成分享消息")
    print("  GET  /api/activity/deals         — 附近团购优惠")
    print("  POST /api/activity/check-queue   — 查询排队状态")
    print("=" * 60 + "\n")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    print("\n" + "=" * 60)
    print("[STOP] 应用正在关闭,清理资源...")  # 2026-06-03 修复：emoji 编码

    # 清理 MCP 子进程
    try:
        from ..services.amap_service import _amap_mcp_tool
        if _amap_mcp_tool is not None:
            try:
                if hasattr(_amap_mcp_tool, '_process') and _amap_mcp_tool._process:
                    try:
                        _amap_mcp_tool._process.terminate()
                        _amap_mcp_tool._process.wait(timeout=5)
                    except Exception:
                        _amap_mcp_tool._process.kill()

                if hasattr(_amap_mcp_tool, 'close'):
                    _amap_mcp_tool.close()
                elif hasattr(_amap_mcp_tool, 'shutdown'):
                    _amap_mcp_tool.shutdown()
                print("[OK] MCP工具已清理")  # 2026-06-03 修复：emoji 编码
            except Exception as e:
                print(f"[WARN] MCP工具清理失败: {e}")  # 2026-06-03 修复：emoji 编码
    except ImportError:
        pass

    # 重置全局单例
    try:
        import app.agents.activity_planner_agent as apa
        apa._activity_planner = None
    except Exception:
        pass

    try:
        import app.services.amap_service as ams
        ams._amap_mcp_tool = None
        ams._amap_service = None
    except Exception:
        pass

    try:
        import app.services.mock_service as ms
        ms._mock_service = None
    except Exception:
        pass

    try:
        import app.services.graph_memory_service as gms
        if gms._graph_memory_service is not None:
            gms._graph_memory_service.close()
            gms._graph_memory_service = None
            print("[OK] Neo4j图谱记忆连接已关闭")
    except Exception:
        pass

    print("=" * 60 + "\n")


# ============================================================================
# 根路径与健康检查
# ============================================================================

@app.get("/", summary="根路径", tags=["系统"])
async def root():
    """根路径 — 返回服务基本信息"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "description": "本地活动规划与执行Agent",
        "docs": "/docs",
        "redoc": "/redoc",
        "endpoints": {
            "plan": "/api/activity/plan",
            "plan_stream": "/api/activity/plan/stream",
            "execute": "/api/activity/execute",
            "share": "/api/activity/share",
            "deals": "/api/activity/deals",
            "check_queue": "/api/activity/check-queue",
            "check_availability": "/api/activity/check-availability",
            "poi_search": "/api/poi/search",
            "poi_photo": "/api/poi/photo",
            "weather": "/api/map/weather",
            "route": "/api/map/route",
        },
    }


@app.get("/health", summary="健康检查", tags=["系统"])
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


# ============================================================================
# 直接运行入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
