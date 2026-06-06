"""高德地图MCP服务封装 - 提供POI搜索、天气查询、路线规划、图片获取"""

from typing import List, Dict, Any, Optional
from hello_agents.tools import MCPTool
from ..config import get_settings
from ..models.schemas import Location, POIInfo, WeatherInfo
import json
import os  # 2026-06-03 添加：用于设置环境变量
import re
import threading
import httpx


# 全局MCP工具实例
_amap_mcp_tool = None
_mcp_tool_lock = threading.Lock()


def _safe_poi_text(value: Any) -> Optional[str]:
    """2026-06-05: 清洗高德 POI 字段，兼容 tel/address 等字段返回数组导致 Pydantic 校验失败。"""
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(str(item) for item in value if item)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    return text or None


def get_amap_mcp_tool() -> MCPTool:
    """获取共享的高德地图 MCP 工具实例（线程安全单例）"""
    global _amap_mcp_tool

    if _amap_mcp_tool is None:
        with _mcp_tool_lock:
            if _amap_mcp_tool is None:
                settings = get_settings()

                if not settings.amap_api_key:
                    raise ValueError("高德地图API Key未配置,请在.env文件中设置AMAP_API_KEY")

                # 2026-06-03 修复：必须设置 os.environ，否则 amap-mcp-server 子进程拿不到 API Key
                # MCPTool 的 env 参数在某些情况下无法正确传递给子进程
                os.environ["AMAP_MAPS_API_KEY"] = settings.amap_api_key

                _amap_mcp_tool = MCPTool(
                    name="amap",
                    description="高德地图服务,支持POI搜索、路线规划、天气查询等功能",
                    server_command=["uvx", "amap-mcp-server"],
                    env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
                    auto_expand=True
                )

                print(f"[OK] 高德地图MCP工具初始化成功")
                print(f"   工具数量: {len(_amap_mcp_tool._available_tools)}")

                if _amap_mcp_tool._available_tools:
                    print("   可用工具:")
                    for tool in _amap_mcp_tool._available_tools[:5]:
                        print(f"     - {tool.get('name', 'unknown')}")
                    if len(_amap_mcp_tool._available_tools) > 5:
                        print(f"     ... 还有 {len(_amap_mcp_tool._available_tools) - 5} 个工具")

    return _amap_mcp_tool


class AmapService:
    """高德地图服务封装类"""

    def __init__(self):
        # 2026-06-05: MCP 改为懒加载，极速模式只走高德 REST，避免初始化 uvx/MCP 拖慢首个请求
        self._mcp_tool = None

    @property
    def mcp_tool(self) -> MCPTool:
        """2026-06-05: 仅在深度 Agent 模式需要 MCP 工具时初始化，快速模式不触发。"""
        if self._mcp_tool is None:
            self._mcp_tool = get_amap_mcp_tool()
        return self._mcp_tool

    # ------------------------------------------------------------------
    # POI 搜索
    # ------------------------------------------------------------------

    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> List[POIInfo]:
        """搜索 POI（兴趣点）"""
        try:
            result = self.mcp_tool.run({
                "action": "call_tool",
                "tool_name": "maps_text_search",
                "arguments": {
                    "keywords": keywords,
                    "city": city,
                    "citylimit": str(citylimit).lower()
                }
            })

            print(f"POI搜索结果: {result[:200]}...")

            pois = []
            json_match = re.search(r'(\[.*\]|\{.*\})', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())

                if isinstance(data, dict):
                    poi_list = data.get("pois", data.get("results", data.get("data", [])))
                    if not isinstance(poi_list, list):
                        poi_list = [data]
                else:
                    poi_list = data

                for item in poi_list:
                    try:
                        loc_str = item.get("location", "")
                        if isinstance(loc_str, str) and "," in loc_str:
                            lng, lat = loc_str.split(",")
                            location = Location(longitude=float(lng), latitude=float(lat))
                        elif isinstance(loc_str, dict):
                            location = Location(
                                longitude=float(loc_str.get("lng", loc_str.get("longitude", 0))),
                                latitude=float(loc_str.get("lat", loc_str.get("latitude", 0)))
                            )
                        else:
                            location = Location(longitude=0.0, latitude=0.0)

                        poi = POIInfo(
                            id=str(item.get("id", "")),
                            name=str(item.get("name", "")),
                            type=str(item.get("type", "")),
                            address=str(item.get("address", "")),
                            location=location,
                            tel=_safe_poi_text(item.get("tel")),
                            rating=item.get("biz_ext", {}).get("rating") if isinstance(item.get("biz_ext"), dict) else None,
                        )
                        pois.append(poi)
                    except Exception as parse_err:
                        print(f"[WARN] 解析单个POI失败: {parse_err}")
                        continue

            print(f"[OK] 成功解析 {len(pois)} 个POI")
            return pois

        except Exception as e:
            print(f"[ERR] POI搜索失败: {str(e)}")
            return []

    def search_poi_rest(
        self,
        keywords: str,
        city: str = "",
        citylimit: bool = True,
        offset: int = 10,
        location: Optional[Location] = None,
        radius: int = 5000,
    ) -> List[POIInfo]:
        """2026-06-05: 高德 REST POI 搜索，供极速模式绕过 MCP/搜索 Agent 使用。"""
        try:
            settings = get_settings()
            if not settings.amap_api_key:
                print("[WARN] AMAP_API_KEY 未配置，无法 REST 搜索 POI")
                return []

            url = "https://restapi.amap.com/v3/place/text"
            params: Dict[str, Any] = {
                "key": settings.amap_api_key,
                "keywords": keywords,
                "offset": offset,
                "page": 1,
                "extensions": "base",
                "output": "json",
                "citylimit": "true" if citylimit else "false",
            }
            if city:
                params["city"] = city
            if location and location.longitude and location.latitude:
                params["location"] = f"{location.longitude},{location.latitude}"
                params["radius"] = radius

            response = httpx.get(url, params=params, timeout=3.0)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "1":
                print(f"[WARN] 高德 REST POI 搜索失败: info={data.get('info')}, infocode={data.get('infocode')}")
                return []

            pois: List[POIInfo] = []
            for item in data.get("pois", []) or []:
                try:
                    loc_str = item.get("location", "")
                    if not loc_str or "," not in loc_str:
                        continue
                    lng, lat = loc_str.split(",", 1)
                    pois.append(POIInfo(
                        id=str(item.get("id", "")),
                        name=str(item.get("name", "")),
                        type=str(item.get("type", "")),
                        address=str(item.get("address", "")),
                        location=Location(longitude=float(lng), latitude=float(lat)),
                        tel=_safe_poi_text(item.get("tel")),
                        rating=None,
                    ))
                except Exception as parse_err:
                    print(f"[WARN] REST POI 单条解析失败: {parse_err}")
                    continue
            return pois
        except Exception as e:
            print(f"[ERR] REST POI 搜索失败: {str(e)}")
            return []

    # ------------------------------------------------------------------
    # 天气查询
    # ------------------------------------------------------------------

    def get_weather(self, city: str) -> List[WeatherInfo]:
        """查询天气"""
        try:
            result = self.mcp_tool.run({
                "action": "call_tool",
                "tool_name": "maps_weather",
                "arguments": {
                    "city": city
                }
            })

            print(f"天气查询结果: {result[:200]}...")

            weather_list = []
            json_match = re.search(r'(\[.*\]|\{.*\})', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())

                if isinstance(data, dict):
                    forecasts = data.get("forecasts", data.get("casts", data.get("data", [])))
                    if isinstance(forecasts, list) and len(forecasts) > 0:
                        first = forecasts[0] if isinstance(forecasts[0], dict) else {}
                        casts = first.get("casts", forecasts)
                    else:
                        casts = []
                elif isinstance(data, list):
                    casts = data
                else:
                    casts = []

                for cast in casts:
                    try:
                        weather_info = WeatherInfo(
                            date=str(cast.get("date", "")),
                            day_weather=str(cast.get("dayweather", cast.get("day_weather", ""))),
                            night_weather=str(cast.get("nightweather", cast.get("night_weather", ""))),
                            day_temp=cast.get("daytemp", cast.get("day_temp", 0)),
                            night_temp=cast.get("nighttemp", cast.get("night_temp", 0)),
                            wind_direction=str(cast.get("daywind", cast.get("wind_direction", ""))),
                            wind_power=str(cast.get("daypower", cast.get("wind_power", "")))
                        )
                        weather_list.append(weather_info)
                    except Exception as parse_err:
                        print(f"[WARN] 解析单条天气失败: {parse_err}")
                        continue

            print(f"[OK] 成功解析 {len(weather_list)} 条天气数据")
            return weather_list

        except Exception as e:
            print(f"[ERR] 天气查询失败: {str(e)}")
            return []

    def get_weather_rest(self, city: str) -> List[WeatherInfo]:
        """2026-06-05: 高德 REST 天气查询，极速模式避免 MCP 天气工具耗时。"""
        try:
            settings = get_settings()
            if not settings.amap_api_key or not city:
                return []
            url = "https://restapi.amap.com/v3/weather/weatherInfo"
            params = {
                "key": settings.amap_api_key,
                "city": city,
                "extensions": "all",
                "output": "json",
            }
            response = httpx.get(url, params=params, timeout=3.0)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "1":
                print(f"[WARN] 高德 REST 天气失败: info={data.get('info')}, infocode={data.get('infocode')}")
                return []
            forecasts = data.get("forecasts", []) or []
            casts = forecasts[0].get("casts", []) if forecasts else []
            weather_list: List[WeatherInfo] = []
            for cast in casts:
                weather_list.append(WeatherInfo(
                    date=str(cast.get("date", "")),
                    day_weather=str(cast.get("dayweather", "")),
                    night_weather=str(cast.get("nightweather", "")),
                    day_temp=cast.get("daytemp", 0),
                    night_temp=cast.get("nighttemp", 0),
                    wind_direction=str(cast.get("daywind", "")),
                    wind_power=str(cast.get("daypower", "")),
                ))
            return weather_list
        except Exception as e:
            print(f"[ERR] REST 天气查询失败: {str(e)}")
            return []

    # ------------------------------------------------------------------
    # 路线规划
    # ------------------------------------------------------------------

    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking"
    ) -> Dict[str, Any]:
        """规划路线"""
        try:
            tool_map = {
                "walking": "maps_direction_walking_by_address",
                "driving": "maps_direction_driving_by_address",
                "transit": "maps_direction_transit_integrated_by_address"
            }

            tool_name = tool_map.get(route_type, "maps_direction_walking_by_address")

            arguments: Dict[str, str] = {
                "origin_address": origin_address,
                "destination_address": destination_address
            }

            if origin_city:
                arguments["origin_city"] = origin_city
            if destination_city:
                arguments["destination_city"] = destination_city

            result = self.mcp_tool.run({
                "action": "call_tool",
                "tool_name": tool_name,
                "arguments": arguments
            })

            print(f"路线规划结果: {result[:200]}...")

            json_match = re.search(r'(\{.*\})', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())

                route = data.get("route", data)
                paths = route.get("paths", route.get("transits", []))

                if isinstance(paths, list) and len(paths) > 0:
                    first_path = paths[0]
                    return {
                        "distance": float(first_path.get("distance", 0)),
                        "duration": int(first_path.get("duration", 0)),
                        "route_type": route_type,
                        "description": first_path.get(
                            "instruction",
                            first_path.get("strategy", f"{route_type}路线")
                        )
                    }

            return {
                "distance": 0,
                "duration": 0,
                "route_type": route_type,
                "description": "未能解析路线信息"
            }

        except Exception as e:
            print(f"[ERR] 路线规划失败: {str(e)}")
            return {}

    # ------------------------------------------------------------------
    # 地理编码
    # ------------------------------------------------------------------

    def reverse_geocode(self, longitude: float, latitude: float) -> Dict[str, Any]:
        """2026-06-04: 根据浏览器定位坐标反查城市/区域，减少附近快排还要手填城市的问题。"""
        try:
            settings = get_settings()
            if not settings.amap_api_key:
                print("[WARN] AMAP_API_KEY 未配置，无法逆地理编码")
                return {}

            url = "https://restapi.amap.com/v3/geocode/regeo"
            params = {
                "key": settings.amap_api_key,
                "location": f"{longitude},{latitude}",
                "extensions": "base",
                "output": "json",
            }
            response = httpx.get(url, params=params, timeout=8.0)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "1":
                print(f"[WARN] 高德逆地理编码失败: info={data.get('info')}, infocode={data.get('infocode')}")
                return {}

            regeocode = data.get("regeocode") or {}
            address = regeocode.get("addressComponent") or {}
            city = address.get("city") or address.get("province") or ""
            if isinstance(city, list):
                city = address.get("province") or ""

            return {
                "formatted_address": regeocode.get("formatted_address", ""),
                "province": address.get("province", ""),
                "city": city,
                "district": address.get("district", ""),
                "adcode": address.get("adcode", ""),
            }
        except Exception as e:
            print(f"[ERR] 逆地理编码失败: {str(e)}")
            return {}

    def geocode(self, address: str, city: Optional[str] = None) -> Optional[Location]:
        """地理编码（地址转坐标）"""
        try:
            arguments: Dict[str, str] = {"address": address}
            if city:
                arguments["city"] = city

            result = self.mcp_tool.run({
                "action": "call_tool",
                "tool_name": "maps_geo",
                "arguments": arguments
            })

            print(f"地理编码结果: {result[:200]}...")
            # TODO: 解析实际的坐标数据
            return None

        except Exception as e:
            print(f"[ERR] 地理编码失败: {str(e)}")
            return None

    # ------------------------------------------------------------------
    # POI 详情
    # ------------------------------------------------------------------

    def get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        """获取 POI 详情"""
        try:
            result = self.mcp_tool.run({
                "action": "call_tool",
                "tool_name": "maps_search_detail",
                "arguments": {
                    "id": poi_id
                }
            })

            print(f"POI详情结果: {result[:200]}...")

            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data

            return {"raw": result}

        except Exception as e:
            print(f"[ERR] 获取POI详情失败: {str(e)}")
            return {}

    # ------------------------------------------------------------------
    # 通过名称获取图片 URL
    # ------------------------------------------------------------------

    async def get_photos_by_name(self, name: str, city: Optional[str] = None) -> List[str]:
        """通过高德 POI 搜索获取多张图片 URL（2026-06-03 改造：返回多张用于轮播）"""
        try:
            settings = get_settings()

            if not settings.amap_api_key:
                print("[WARN] AMAP_API_KEY 未配置，无法获取高德图片")
                return []

            clean_name = re.sub(r'[\*\(\)（）【】\[\]]+', ' ', name)
            clean_name = re.sub(r'\s+', ' ', clean_name).strip()

            if not clean_name:
                return []

            url = "https://restapi.amap.com/v3/place/text"
            params = {
                "key": settings.amap_api_key,
                "keywords": clean_name,
                "offset": "1",
                "page": "1",
                "extensions": "all",
                "output": "json"
            }

            if city:
                params["city"] = city
                params["citylimit"] = "true"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

            data = response.json()

            if data.get("status") != "1":
                print(
                    f"[WARN] 高德图片搜索失败: "
                    f"info={data.get('info')}, "
                    f"infocode={data.get('infocode')}, "
                    f"name={clean_name}"
                )
                return []

            pois = data.get("pois") or []
            if not pois:
                print(f"[WARN] 高德未找到POI图片: name={clean_name}, city={city}")
                return []

            photos = pois[0].get("photos") or []

            if isinstance(photos, dict):
                photos = [photos]

            if not isinstance(photos, list):
                return []

            # 收集所有图片 URL（最多 5 张）
            urls = []
            for photo in photos:
                if isinstance(photo, dict) and photo.get("url"):
                    urls.append(photo["url"])
                    if len(urls) >= 5:
                        break

            if not urls:
                print(f"[WARN] 高德POI无图片: name={clean_name}, city={city}")

            return urls

        except Exception as e:
            print(
                f"[ERR] 高德图片获取失败: "
                f"type={type(e).__name__}, "
                f"error={repr(e)}, "
                f"name={name}, "
                f"city={city}"
            )
            return []


# ============================================================================
# 全局服务实例
# ============================================================================

_amap_service = None
_amap_service_lock = threading.Lock()


def get_amap_service() -> AmapService:
    """获取高德地图服务实例（线程安全单例）"""
    global _amap_service

    if _amap_service is None:
        with _amap_service_lock:
            if _amap_service is None:
                _amap_service = AmapService()

    return _amap_service
