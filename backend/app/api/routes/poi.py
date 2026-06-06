"""POI相关API路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from ...services.amap_service import get_amap_service

router = APIRouter(prefix="/poi", tags=["POI"])


class POIDetailResponse(BaseModel):
    """POI详情响应"""
    success: bool
    message: str
    data: Optional[dict] = None


@router.get(
    "/detail/{poi_id}",
    response_model=POIDetailResponse,
    summary="获取POI详情",
    description="根据POI ID获取详细信息,包括图片",
)
async def get_poi_detail(poi_id: str):
    """获取POI详情"""
    try:
        amap_service = get_amap_service()
        result = amap_service.get_poi_detail(poi_id)
        return POIDetailResponse(
            success=True,
            message="获取POI详情成功",
            data=result,
        )
    except Exception as e:
        print(f"[ERR] 获取POI详情失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取POI详情失败: {str(e)}",
        )


@router.get(
    "/search",
    summary="搜索POI",
    description="根据关键词搜索POI",
)
async def search_poi(keywords: str, city: str = "北京"):
    """搜索POI"""
    try:
        amap_service = get_amap_service()
        result = amap_service.search_poi(keywords, city)
        return {
            "success": True,
            "message": "搜索成功",
            "data": result,
        }
    except Exception as e:
        print(f"[ERR] 搜索POI失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"搜索POI失败: {str(e)}",
        )


@router.get(
    "/photo",
    summary="获取场所图片",
    description="从高德POI获取场所图片",
)
async def get_venue_photo(name: str, city: str = ""):
    """获取场所图片"""
    try:
        amap_service = get_amap_service()

        # 2026-06-03 改造：返回多张图片用于轮播
        photo_urls = await amap_service.get_photos_by_name(name=name, city=city)
        source = "amap" if photo_urls else None

        return {
            "success": True,
            "message": "获取图片成功" if photo_urls else "未找到图片，前端可使用占位图",
            "data": {
                "name": name,
                "city": city,
                "photo_url": photo_urls[0] if photo_urls else None,
                "photo_urls": photo_urls,  # 多张图片数组
                "source": source,
            },
        }

    except Exception as e:
        print(f"[ERR] 获取场所图片失败: {type(e).__name__}, {repr(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取场所图片失败: {str(e)}",
        )
