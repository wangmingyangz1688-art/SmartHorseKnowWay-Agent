"""地图服务API路由"""

from fastapi import APIRouter, HTTPException, Query
from ...models.schemas import (
    POISearchRequest,
    POISearchResponse,
    RouteRequest,
    RouteResponse,
    WeatherResponse,
)
from ...services.amap_service import get_amap_service

router = APIRouter(prefix="/map", tags=["地图服务"])


@router.get(
    "/poi",
    response_model=POISearchResponse,
    summary="搜索POI",
    description="根据关键词搜索POI(兴趣点)",
)
async def search_poi(
    keywords: str = Query(..., description="搜索关键词", example="亲子乐园"),
    city: str = Query(..., description="城市", example="北京"),
    citylimit: bool = Query(True, description="是否限制在城市范围内"),
):
    """搜索POI"""
    try:
        service = get_amap_service()
        pois = service.search_poi(keywords, city, citylimit)

        return POISearchResponse(
            success=True,
            message="POI搜索成功",
            data=pois,
        )

    except Exception as e:
        print(f"[ERR] POI搜索失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"POI搜索失败: {str(e)}",
        )


@router.get(
    "/weather",
    response_model=WeatherResponse,
    summary="查询天气",
    description="查询指定城市的天气信息",
)
async def get_weather(
    city: str = Query(..., description="城市名称", example="北京"),
):
    """查询天气"""
    try:
        service = get_amap_service()
        weather_info = service.get_weather(city)

        return WeatherResponse(
            success=True,
            message="天气查询成功",
            data=weather_info,
        )

    except Exception as e:
        print(f"[ERR] 天气查询失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"天气查询失败: {str(e)}",
        )


@router.get(
    "/reverse-geocode",
    summary="坐标反查城市区域",
    description="根据浏览器定位坐标反查城市、区域和格式化地址",
)
async def reverse_geocode(
    longitude: float = Query(..., description="经度"),
    latitude: float = Query(..., description="纬度"),
):
    """2026-06-04: 前端定位后自动反查城市/区域，附近快排不再强制用户手填城市。"""
    try:
        service = get_amap_service()
        data = service.reverse_geocode(longitude=longitude, latitude=latitude)
        return {
            "success": bool(data),
            "message": "坐标反查成功" if data else "未能识别当前位置城市",
            "data": data,
        }
    except Exception as e:
        print(f"[ERR] 坐标反查失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"坐标反查失败: {str(e)}",
        )


@router.post(
    "/route",
    response_model=RouteResponse,
    summary="规划路线",
    description="规划两点之间的路线",
)
async def plan_route(request: RouteRequest):
    """规划路线"""
    try:
        service = get_amap_service()
        route_info = service.plan_route(
            origin_address=request.origin_address,
            destination_address=request.destination_address,
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            route_type=request.route_type,
        )

        return RouteResponse(
            success=True,
            message="路线规划成功",
            data=route_info,
        )

    except Exception as e:
        print(f"[ERR] 路线规划失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"路线规划失败: {str(e)}",
        )


@router.get(
    "/health",
    summary="健康检查",
    description="检查地图服务是否正常",
)
async def health_check():
    """健康检查"""
    try:
        service = get_amap_service()

        return {
            "status": "healthy",
            "service": "map-service",
            "mcp_tools_count": len(service.mcp_tool._available_tools),
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"服务不可用: {str(e)}",
        )
