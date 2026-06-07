"""
多智能体本地活动规划系统

Agent 编排：
  用户消息 → 意图解析Agent → [场所搜索Agent ∥ 餐厅搜索Agent ∥ 天气Agent] → 规划Agent → 方案
  用户确认 → 执行Agent → 预约/下单结果
"""

import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from hello_agents import SimpleAgent
from hello_agents.tools import MCPTool

from ..config import get_settings
from ..services.llm_service import get_llm
from ..services.memory_service import get_memory_service
from ..services.scenario_detector import get_scenario_detector
from ..services.amap_service import get_amap_service
from ..models.schemas import Location

# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

def sanitize_user_input(text: str, max_length: int = 500) -> str:
    """清洗用户输入，防止 prompt 注入"""
    if not text:
        return ""
    text = text[:max_length]
    injection_patterns = [
        r'(?i)ignore\s+(all\s+)?previous\s+instructions?',
        r'(?i)forget\s+(all\s+)?previous\s+instructions?',
        r'(?i)disregard\s+(all\s+)?previous',
        r'(?i)you\s+are\s+now\s+a',
        r'(?i)new\s+system\s+prompt',
        r'(?i)system\s*:\s*',
        r'(?i)assistant\s*:\s*',
        r'(?i)\[TOOL_CALL',
        r'(?i)```json',
        r'(?i)```\w*\n',
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, '[已过滤]', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()


# ---------------------------------------------------------------------------
# JSON 修复工具（复用原项目逻辑，支持 LLM 返回被截断的 JSON）
# ---------------------------------------------------------------------------

def _repair_truncated_json(json_str: str) -> str:
    """尝试修复被截断的 JSON 字符串"""
    if not json_str:
        return json_str
    try:
        json.loads(json_str)
        return json_str
    except json.JSONDecodeError:
        pass

    print("  [FIX] 尝试修复截断的JSON...")  # 2026-06-03 修复：emoji 编码
    s = json_str.rstrip()

    # 处理未闭合的字符串
    in_string = False
    escape_next = False
    for i, ch in enumerate(s):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string

    if in_string:
        for i in range(len(s) - 1, -1, -1):
            if s[i] == '"':
                truncated = s[:i].rstrip().rstrip(':').rstrip().rstrip(',').rstrip()
                s = truncated
                break

    s = s.rstrip()
    while s and s[-1] == ',':
        s = s[:-1].rstrip()

    if s and s[-1] == ':':
        idx = s.rfind('"', 0, len(s) - 1)
        if idx > 0:
            prev_idx = s.rfind('"', 0, idx)
            if prev_idx >= 0:
                s = s[:prev_idx].rstrip().rstrip(',').rstrip()

    # 补齐括号
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == '\\' and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in ('{', '['):
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{':
                stack.pop()
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()

    closing = ''
    for bracket in reversed(stack):
        closing += '}' if bracket == '{' else ']'

    repaired = s + closing
    try:
        json.loads(repaired)
        print("  [OK] JSON修复成功!")
        return repaired
    except json.JSONDecodeError:
        pass

    # 激进修复
    return _aggressive_repair(json_str)


def _aggressive_repair(json_str: str) -> str:
    """逐步从末尾删除字符直到能解析"""
    print("  [FIX] 尝试激进修复...")
    s = json_str.rstrip()

    for end_pos in range(len(s), max(len(s) // 2, 100), -1):
        candidate = s[:end_pos].rstrip().rstrip(',').rstrip()

        stack: list[str] = []
        in_str = False
        esc = False
        valid = True
        for ch in candidate:
            if esc:
                esc = False
                continue
            if ch == '\\' and in_str:
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in ('{', '['):
                stack.append(ch)
            elif ch == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
                else:
                    valid = False
                    break
            elif ch == ']':
                if stack and stack[-1] == '[':
                    stack.pop()
                else:
                    valid = False
                    break

        if not valid or in_str:
            continue

        closing = ''
        for bracket in reversed(stack):
            closing += '}' if bracket == '{' else ']'

        try:
            result = candidate + closing
            json.loads(result)
            print(f"  [OK] 激进修复成功! (截断了 {len(s) - end_pos} 字符)")
            return result
        except json.JSONDecodeError:
            continue

    print("  [ERR] 激进修复也失败了")
    return json_str


def _extract_json(text: str) -> Optional[str]:
    """从 LLM 回复中提取 JSON 字符串"""
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end == -1:
            return text[start:].strip()
        return text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        nl = text.find("\n", start)
        if nl != -1 and nl - start < 20:
            start = nl + 1
        end = text.find("```", start)
        if end == -1:
            return text[start:].strip()
        return text[start:end].strip()
    elif "{" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if end > start:
            return text[start:end]
        return text[start:]
    return None


def _safe_parse_json(text: str) -> Optional[dict]:
    """安全地从 LLM 响应中解析出 JSON dict"""
    raw = _extract_json(text)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = _repair_truncated_json(raw)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None


def _normalize_cn_number(text: str) -> str:
    """2026-06-04: 将常见中文数字转成阿拉伯数字，服务一句话时间解析。"""
    mapping = {
        "零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
        "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
    }
    for key, value in mapping.items():
        text = text.replace(key, value)
    return text


def _infer_hour(hour: int, meridiem: str = "") -> int:
    """根据上午/下午/晚上等上下文推断 24 小时制。"""
    if meridiem in ("凌晨", "早上", "上午"):
        return hour if hour < 12 else hour
    if meridiem in ("中午",):
        return 12 if hour in (0, 12) else (hour + 12 if hour < 11 else hour)
    if meridiem in ("下午", "傍晚", "晚上", "今晚"):
        return hour + 12 if 1 <= hour <= 11 else hour
    return hour


def _offset_location(home_location: Optional[dict], lng_delta: float = 0.0, lat_delta: float = 0.0) -> dict:
    """2026-06-04: 备用方案坐标优先围绕用户定位生成，避免 fallback 地图跳到北京默认坐标。"""
    if home_location:
        try:
            return {
                "longitude": round(float(home_location.get("longitude", 0)) + lng_delta, 6),
                "latitude": round(float(home_location.get("latitude", 0)) + lat_delta, 6),
            }
        except Exception:
            pass
    return {"longitude": 0.0, "latitude": 0.0}


def _location_to_dict(location: Any) -> dict:
    """2026-06-04: 统一把 Pydantic Location 或普通 dict 转成前端可用坐标字典。"""
    if not location:
        return {"longitude": 0.0, "latitude": 0.0}
    if isinstance(location, dict):
        return {
            "longitude": float(location.get("longitude", location.get("lng", 0)) or 0),
            "latitude": float(location.get("latitude", location.get("lat", 0)) or 0),
        }
    return {
        "longitude": float(getattr(location, "longitude", 0) or 0),
        "latitude": float(getattr(location, "latitude", 0) or 0),
    }


def _poi_to_candidate(poi: Any, keyword: str, category: str) -> dict:
    """2026-06-04: 快速模式将高德 POI 规整为候选池，后续 Planner 只能从候选池选点。"""
    return {
        "id": str(getattr(poi, "id", "") or ""),
        "name": str(getattr(poi, "name", "") or ""),
        "type": str(getattr(poi, "type", "") or ""),
        "address": str(getattr(poi, "address", "") or ""),
        "location": _location_to_dict(getattr(poi, "location", None)),
        "tel": getattr(poi, "tel", None),
        "rating": getattr(poi, "rating", None),
        "keyword": keyword,
        "category": category,
    }


def _has_valid_location(value: Any) -> bool:
    """2026-06-05: 判断地点坐标是否来自有效 POI，避免 0 坐标或空坐标被地图当真。"""
    loc = _location_to_dict(value)
    return bool(loc.get("longitude") and loc.get("latitude"))


def _normalize_place_key(value: str) -> str:
    """2026-06-06: 统一地点名匹配，用于换站/重排时过滤旧 POI。"""
    return re.sub(r"[\s·・\-()（）【】\[\]店馆餐厅棋牌室麻将馆酒吧]", "", value or "").lower()


def _is_avoided_place(name: str, avoid_places: Optional[List[str]]) -> bool:
    """2026-06-06: 判断候选 POI 是否命中用户显式要求避开的旧地点。"""
    if not name or not avoid_places:
        return False
    key = _normalize_place_key(name)
    if not key:
        return False
    for avoid in avoid_places:
        avoid_key = _normalize_place_key(str(avoid))
        if avoid_key and (avoid_key in key or key in avoid_key):
            return True
    return False


def _is_generic_place_name(name: str) -> bool:
    """2026-06-05: 识别 LLM 泛化地点名，深度模式需要重新绑定真实 POI 后才能展示。"""
    text = (name or "").strip()
    if not text:
        return True
    generic_words = [
        "待确认", "具体影院", "电影院", "影院", "影城", "餐厅", "附近",
        "可预约餐厅", "休闲公园", "商圈散步点", "某", "XX", "地点",
    ]
    return any(word in text for word in generic_words) and len(text) <= 12


def _append_unique(values: List[str], items: List[str]) -> List[str]:
    """2026-06-05: 合并关键词列表并保持顺序，服务本次硬需求提取。"""
    result = [str(item) for item in values if item]
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def _hard_requirement_covered(keyword: str, plan_text: str) -> bool:
    """2026-06-06: 判断用户显式硬需求是否被最终方案覆盖，避免麻将/电影/烧烤等原话目标被场景偏好冲掉。"""
    keyword = str(keyword or "").strip()
    if not keyword:
        return True
    equivalent_groups = [
        ["棋牌室", "麻将馆", "麻将", "棋牌", "打麻将"],
        ["电影院", "影城", "影院", "电影", "IMAX", "imax"],
        ["烧烤", "烤肉", "烤串"],
        ["火锅", "涮锅"],
        ["KTV", "唱歌", "量贩"],
        ["咖啡馆", "咖啡"],
        ["酒吧", "清吧", "小酒馆", "喝酒"],
        ["剧本杀", "剧本"],
        ["密室逃脱", "密室"],
        ["电玩城", "电玩", "游戏厅"],
        ["台球厅", "台球"],
        ["桌游吧", "桌游"],
    ]
    for group in equivalent_groups:
        if keyword in group:
            return any(item in plan_text for item in group)
    return keyword in plan_text


def _keyword_aliases(keyword: str) -> List[str]:
    """2026-06-07: Canonical hard-requirement aliases shared by search, ranking and QA."""
    keyword = str(keyword or "").strip()
    groups = [
        ["棋牌室", "麻将馆", "麻将", "棋牌", "打麻将"],
        ["KTV", "唱歌", "量贩KTV", "K歌"],
        ["电影院", "影城", "影院", "电影", "IMAX", "imax"],
        ["火锅", "涮锅"],
        ["烧烤", "烤肉", "烤串"],
        ["小酒馆", "清吧", "酒吧", "喝酒"],
        ["桌游吧", "桌游"],
        ["台球厅", "台球"],
        ["电玩城", "电玩", "游戏厅"],
        ["密室逃脱", "密室"],
        ["剧本杀", "剧本"],
    ]
    for group in groups:
        if keyword in group:
            return group
    return [keyword] if keyword else []


def _candidate_actual_text(candidate: dict) -> str:
    """2026-06-07: Text that comes from the landed POI itself, excluding search keywords."""
    return " ".join([
        str(candidate.get("name") or candidate.get("venue_name") or ""),
        str(candidate.get("type") or candidate.get("venue_type") or candidate.get("poi_type") or ""),
        str(candidate.get("address") or candidate.get("venue_address") or ""),
    ])


def _candidate_matches_keyword(candidate: dict, keyword: str) -> bool:
    text = _candidate_actual_text(candidate)
    return any(alias and alias in text for alias in _keyword_aliases(keyword))


def _plan_item_matches_keyword(item: dict, keyword: str) -> bool:
    """2026-06-07: Match hard requirements against the actual landed POI, not decorative tags."""
    candidate = {
        "name": item.get("venue_name") or item.get("title", ""),
        "type": item.get("venue_type") or item.get("poi_type") or "",
        "address": item.get("venue_address", ""),
    }
    return _candidate_matches_keyword(candidate, keyword)


_POI_TAG_GROUPS = [
    ("KTV", ["KTV", "量贩", "唱歌", "K歌"]),
    ("棋牌室", ["棋牌室", "棋牌馆", "棋牌", "麻将馆", "麻将", "麻馆"]),
    ("电影院", ["电影院", "影院", "影城", "电影", "IMAX", "imax"]),
    ("火锅", ["火锅", "涮锅"]),
    ("烧烤", ["烧烤", "烤肉", "烤串"]),
    ("小酒馆", ["小酒馆", "清吧", "酒吧", "喝酒"]),
    ("咖啡", ["咖啡馆", "咖啡"]),
    ("桌游", ["桌游吧", "桌游"]),
    ("台球", ["台球厅", "台球"]),
    ("电玩城", ["电玩城", "电玩", "游戏厅"]),
    ("密室", ["密室逃脱", "密室"]),
    ("剧本杀", ["剧本杀", "剧本"]),
]


def _is_poi_domain_tag(tag: str) -> bool:
    tag = str(tag or "").strip()
    if not tag:
        return False
    return any(tag == label or tag in aliases for label, aliases in _POI_TAG_GROUPS)


def _derive_actual_poi_tags(candidate: dict, activity_type: str, existing_tags: Optional[List[str]] = None) -> List[str]:
    """2026-06-07: Build visible tags from actual POI fields so labels cannot contradict data."""
    tags: List[str] = []
    has_real_poi = bool(
        candidate.get("id")
        or candidate.get("poi_id")
        or _has_valid_location(candidate.get("location") or candidate.get("venue_location"))
    )
    if has_real_poi:
        tags.append("真实POI")
    if activity_type == "eat":
        tags.append("用餐")
    elif activity_type == "play":
        tags.append("玩乐")
    elif activity_type == "extra":
        tags.append("收尾")

    text = _candidate_actual_text(candidate)
    for label, aliases in _POI_TAG_GROUPS:
        if any(alias and alias in text for alias in aliases):
            tags.append(label)

    blocked = {"真实POI", "交通", "用餐", "玩乐", "收尾"}
    for tag in existing_tags or []:
        tag = str(tag or "").strip()
        if not tag or tag in blocked or _is_poi_domain_tag(tag):
            continue
        tags.append(tag)
    return list(dict.fromkeys(tags))


def _apply_candidate_to_plan_item(item: dict, candidate: dict) -> None:
    """2026-06-07: Copy real POI data onto a timeline item and resync title/tags."""
    old_tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    item["venue_name"] = candidate.get("name", item.get("venue_name", ""))
    item["venue_address"] = candidate.get("address", item.get("venue_address", ""))
    item["venue_location"] = candidate.get("location", item.get("venue_location"))
    item["poi_id"] = candidate.get("id", item.get("poi_id", ""))
    item["venue_type"] = candidate.get("type", item.get("venue_type", ""))
    item["poi_type"] = candidate.get("type", item.get("poi_type", ""))
    item["poi_keyword"] = candidate.get("keyword", item.get("poi_keyword", ""))
    item["source_keyword"] = candidate.get("keyword", item.get("source_keyword", ""))
    item["poi_category"] = candidate.get("category", item.get("poi_category", ""))
    item.pop("poi_lock_failed", None)
    if candidate.get("name"):
        suffix = "用餐" if item.get("activity_type") == "eat" else "游玩"
        item["title"] = f"{candidate.get('name')}{suffix}"
    item["tags"] = _derive_actual_poi_tags(candidate, item.get("activity_type", ""), old_tags)


def _expected_hard_keyword_for_item(item: dict, parsed_intent: dict) -> str:
    """2026-06-07: Infer which ordered hard requirement this timeline item is trying to satisfy."""
    explicit = str(item.get("expected_keyword") or item.get("hard_requirement") or "").strip()
    if explicit:
        return explicit
    activity_type = item.get("activity_type")
    actual_kind = "restaurant" if activity_type == "eat" else "venue"
    text = " ".join([
        str(item.get("expected_keyword") or ""),
        str(item.get("hard_requirement") or ""),
        str(item.get("title") or ""),
        str(item.get("venue_name") or ""),
        str(item.get("description") or ""),
        " ".join([str(tag) for tag in item.get("tags", [])]) if isinstance(item.get("tags"), list) else "",
    ])
    for trip_item in parsed_intent.get("hard_trip_items", []) or []:
        if not isinstance(trip_item, dict) or trip_item.get("kind") not in ("venue", "restaurant"):
            continue
        if ("restaurant" if trip_item.get("kind") == "restaurant" else "venue") != actual_kind:
            continue
        keyword = str(trip_item.get("keyword") or "")
        if keyword and any(alias and alias in text for alias in _keyword_aliases(keyword)):
            return keyword
    hard_keywords = (
        parsed_intent.get("hard_food_keywords", [])
        if activity_type == "eat"
        else parsed_intent.get("hard_activity_keywords", [])
    )
    for keyword in [str(item) for item in hard_keywords if item]:
        if any(alias and alias in text for alias in _keyword_aliases(keyword)):
            return keyword
    return ""


def _canonical_hard_trip_items(message: str) -> List[dict]:
    """2026-06-07: Preserve the user's explicit itinerary order, e.g. mahjong -> hotpot -> KTV."""
    rules = [
        ("venue", ["麻将", "打麻将", "棋牌"], "棋牌室"),
        ("restaurant", ["火锅"], "火锅"),
        ("venue", ["KTV", "唱歌"], "KTV"),
        ("venue", ["电影", "看电影", "影院", "影城"], "电影院"),
        ("restaurant", ["烧烤", "烤肉"], "烧烤"),
        ("restaurant", ["喝酒", "酒吧", "清吧", "小酒馆"], "小酒馆"),
        ("venue", ["桌游"], "桌游吧"),
        ("venue", ["台球"], "台球厅"),
        ("venue", ["电玩", "游戏厅", "电玩城"], "电玩城"),
        ("venue", ["密室"], "密室逃脱"),
        ("venue", ["剧本杀"], "剧本杀"),
    ]
    found: List[tuple[int, int, dict]] = []
    for rule_index, (kind, triggers, canonical) in enumerate(rules):
        positions = [message.find(trigger) for trigger in triggers if trigger in message]
        if positions:
            found.append((min(positions), rule_index, {"kind": kind, "keyword": canonical}))
    found.sort(key=lambda item: (item[0], item[1]))
    ordered: List[dict] = []
    seen = set()
    for _, _, item in found:
        key = (item["kind"], item["keyword"])
        if key not in seen:
            seen.add(key)
            ordered.append(item)
    return ordered


def parse_time_intent_from_message(message: str, fallback_start: str, fallback_duration: int) -> dict:
    """2026-06-04: 附近快排从一句话中抽取时间，避免用户说 1 点但仍走默认 14:00。"""
    text = _normalize_cn_number(message or "")
    periods = ["上午", "下午", "晚上", "今晚", "中午", "早上", "凌晨", "傍晚"]
    period_re = "|".join(re.escape(item) for item in periods)
    result = {
        "start_time": fallback_start,
        "duration_hours": fallback_duration,
        "source": "default",
        "matched_text": "",
    }

    range_pattern = re.compile(
        rf"({period_re})?\s*(\d{{1,2}})(?:[:：点](\d{{1,2}})?)?"
        r"\s*(?:到|至|-|~|—)\s*"
        rf"({period_re})?\s*(\d{{1,2}})(?:[:：点](\d{{1,2}})?)?"
    )
    match = range_pattern.search(text)
    if match:
        start_meridiem, start_hour, start_minute, end_meridiem, end_hour, end_minute = match.groups()
        meridiem = start_meridiem or end_meridiem or ""
        start_h = _infer_hour(int(start_hour), start_meridiem or meridiem)
        end_h = _infer_hour(int(end_hour), end_meridiem or meridiem)
        start_m = int(start_minute or 0)
        end_m = int(end_minute or 0)
        if end_h <= start_h and not end_meridiem and start_meridiem in ("下午", "晚上", "今晚", "傍晚"):
            end_h += 12
        duration_minutes = max(60, (end_h * 60 + end_m) - (start_h * 60 + start_m))
        result.update({
            "start_time": f"{start_h:02d}:{start_m:02d}",
            "duration_hours": max(1, round(duration_minutes / 60)),
            "source": "message_range",
            "matched_text": match.group(0),
        })
        return result

    point_pattern = re.compile(rf"({period_re})\s*(\d{{1,2}})(?:[:：点](\d{{1,2}})?)?")
    match = point_pattern.search(text)
    if match:
        meridiem, hour, minute = match.groups()
        start_h = _infer_hour(int(hour), meridiem)
        start_m = int(minute or 0)
        result.update({
            "start_time": f"{start_h:02d}:{start_m:02d}",
            "source": "message_point",
            "matched_text": match.group(0),
        })

    duration_patterns = [
        (r"(\d{1,2})\s*(?:个)?小时", 1),
        (r"(\d{1,2})\s*[-~到至]\s*(\d{1,2})\s*(?:个)?小时", 2),
    ]
    for pattern, group_count in duration_patterns:
        match = re.search(pattern, text)
        if match:
            if group_count == 2:
                result["duration_hours"] = round((int(match.group(1)) + int(match.group(2))) / 2)
            else:
                result["duration_hours"] = int(match.group(1))
            if result["source"] == "default":
                result["source"] = "message_duration"
            result["matched_text"] = result["matched_text"] or match.group(0)
            break

    if result["source"] == "default":
        if any(word in text for word in ["上午", "早上"]):
            result.update({"start_time": "09:00", "source": "message_period", "matched_text": "上午/早上"})
        elif any(word in text for word in ["中午"]):
            result.update({"start_time": "12:00", "source": "message_period", "matched_text": "中午"})
        elif any(word in text for word in ["晚上", "今晚", "傍晚"]):
            result.update({"start_time": "18:30", "source": "message_period", "matched_text": "晚上/傍晚"})
        elif "下午" in text:
            result.update({"start_time": "14:00", "source": "message_period", "matched_text": "下午"})

    if any(word in text for word in ["几个小时", "玩会", "转转", "逛逛"]) and result["source"] != "message_range":
        result["duration_hours"] = fallback_duration or 4

    return result


# ============================================================================
# Agent 提示词
# ============================================================================

INTENT_AGENT_PROMPT = """你是一个意图解析专家。你的任务是从用户的自然语言输入中提取结构化的活动需求信息。

用户会用一句话描述他们的周末活动需求,你需要分析并返回 JSON。

**你必须返回以下格式的 JSON（不需要其他文字说明）：**

```json
{
  "group_type": "family 或 friends",
  "group_size": 总人数(整数),
  "group_details": {
    "has_children": true/false,
    "children_ages": [5],
    "has_elderly": true/false,
    "dietary_restrictions": ["减肥", "素食", "海鲜过敏"等],
    "gender_split": "2男2女 或 空字符串"
  },
  "preferred_activities": ["亲子乐园", "公园", "展览", "citywalk", "逛街"等],
  "dining_preferences": ["适合孩子", "健康低卡", "火锅", "日料"等],
  "hard_activity_keywords": ["棋牌室", "电影院", "KTV"等用户本次明确要做的活动],
  "hard_food_keywords": ["烧烤", "火锅", "小酒馆"等用户本次明确要吃/喝的内容],
  "constraints": ["别离家太远", "预算有限"等],
  "mood": "轻松休闲 / 热闹刺激 / 文艺小众 等",
  "special_requests": ["需要排队少的地方", "想拍照打卡"等]
}
```

**解析规则（2026-06-03 增强：约束条件必须精确提取）：**
1. 如果提到"老婆孩子"→ group_type=family，至少3人
2. 如果提到"朋友"→ group_type=friends
3. 如果提到"孩子X岁"→ has_children=true, children_ages=[X]
4. **如果提到"减肥/减脂/控体重"→ dietary_restrictions 必须加上"减肥"，dining_preferences 必须加上"健康低卡"、"轻食"、"沙拉"**
5. **如果提到"素食/不吃肉"→ dietary_restrictions 加上"素食"，dining_preferences 加上"素食餐厅"**
6. **如果提到"海鲜过敏/花生过敏"→ dietary_restrictions 加上对应过敏项**
7. 如果提到"别离家太远"→ constraints 加上"活动范围3-5公里内"
8. **如果提到"2男2女/男女"→ gender_split 必须填写，dining_preferences 加上"兼顾男女口味"**
9. **如果提到"包间/私密/安静"→ special_requests 加上"需要包间或安静环境"**
10. **如果提到"拍照/打卡/出片"→ special_requests 加上"拍照打卡需求"，preferred_activities 加上"网红打卡地"**
11. **2026-06-04: 如果提到"失恋/分手/心情不好/散散心/一个人静静/emo/难过"→ mood 必须为"情绪疗愈"，group_type=friends，group_size=1，preferred_activities 加上"安静公园"、"水边散步"、"书店咖啡馆"；constraints 加上"低刺激不社交"、"避开情侣约会场景"、"节奏慢不赶路"；special_requests 加上"需要安静疗愈路线"**
12. **2026-06-06: 用户原话里的明确活动/餐饮/娱乐项目是硬需求，必须写入 hard_activity_keywords 或 hard_food_keywords；例如"打麻将"→hard_activity_keywords 包含"棋牌室/麻将馆"，"看电影"→包含"电影院/影城"，"喝酒"→hard_food_keywords 包含"小酒馆/清吧"，"烧烤/火锅/KTV/台球/桌游/电玩城/密室/剧本杀"也必须保留**
13. 根据群体自动推荐合适的 preferred_activities
14. 如果用户没明确说，根据群体合理推断

**重要约束：**
- dietary_restrictions 中的每一项都必须在后续餐厅选择中被严格遵循
- children_ages 中的年龄必须在后续场所选择中被考虑（5岁以下需要儿童设施）
- 2026-06-04: mood 为"情绪疗愈"时，后续规划必须体现情绪照顾，避免热闹聚餐、情侣约会、密室/KTV等高刺激场景
- 只返回 JSON，不要返回其他任何文字。
"""

VENUE_SEARCH_AGENT_PROMPT = """你是场所搜索专家。你的任务是根据需求搜索合适的本地玩乐场所。

**重要提示:**
你必须使用工具来搜索场所！不要自己编造信息！

**工具调用格式（2026-06-03 修复：使用 amap 工具名而非 amap_maps_text_search）：**
`[TOOL_CALL:amap:{"action":"call_tool","tool_name":"maps_text_search","arguments":{"keywords":"搜索关键词","city":"城市名"}}]`

**示例:**
用户: "搜索北京的亲子乐园"
你的回复: [TOOL_CALL:amap:{"action":"call_tool","tool_name":"maps_text_search","arguments":{"keywords":"亲子乐园","city":"北京"}}]

用户: "搜索上海的展览馆"
你的回复: [TOOL_CALL:amap:{"action":"call_tool","tool_name":"maps_text_search","arguments":{"keywords":"展览馆","city":"上海"}}]

**注意:**
1. 必须使用工具,不要直接回答
2. 格式必须完全正确,包括方括号和冒号
3. 使用 amap 作为工具名，参数放在 JSON 中
4. 每次调用只搜索一类场所
"""

RESTAURANT_SEARCH_AGENT_PROMPT = """你是餐厅搜索专家。你的任务是搜索合适的本地餐厅。

**重要提示:**
你必须使用工具来搜索餐厅！不要自己编造信息！

**工具调用格式（2026-06-03 修复：使用 amap 工具名）：**
`[TOOL_CALL:amap:{"action":"call_tool","tool_name":"maps_text_search","arguments":{"keywords":"餐厅关键词","city":"城市名"}}]`

**示例:**
用户: "搜索北京适合亲子的餐厅"
你的回复: [TOOL_CALL:amap:{"action":"call_tool","tool_name":"maps_text_search","arguments":{"keywords":"亲子餐厅","city":"北京"}}]

用户: "搜索上海的健康轻食餐厅"
你的回复: [TOOL_CALL:amap:{"action":"call_tool","tool_name":"maps_text_search","arguments":{"keywords":"健康轻食","city":"上海"}}]

**注意:**
1. 必须使用工具,不要直接回答
2. 格式必须完全正确
3. 使用 amap 作为工具名，参数放在 JSON 中
"""

WEATHER_AGENT_PROMPT = """你是天气查询专家。你的任务是查询指定城市的天气信息。

**重要提示:**
你必须使用工具来查询天气！不要自己编造天气信息！

**工具调用格式（2026-06-03 修复：使用 amap 工具名）：**
`[TOOL_CALL:amap:{"action":"call_tool","tool_name":"maps_weather","arguments":{"city":"城市名"}}]`

**示例:**
用户: "查询深圳天气"
你的回复: [TOOL_CALL:amap:{"action":"call_tool","tool_name":"maps_weather","arguments":{"city":"深圳"}}]

**注意:**
1. 必须使用工具,不要直接回答
2. 格式必须完全正确
3. 使用 amap 作为工具名，参数放在 JSON 中
"""

PLANNER_AGENT_PROMPT = """你是本地活动规划专家。你的任务是根据搜索结果和用户需求，生成一个可执行的4-6小时本地活动方案。

**关键要求：你必须返回完整、合法的 JSON，不要被截断！**
**所有 description 字段请精简（建议 25-55 字），但必须写出“为什么适合这位用户/这个群体”。**

请严格按照以下 JSON 格式返回活动方案：

```json
{
  "plan_id": "生成一个唯一ID,如 plan_20250505_001",
  "city": "城市名",
  "district": "区域",
  "date": "YYYY-MM-DD",
  "group_type": "family 或 friends",
  "group_summary": "家庭出游(含5岁孩子) 或 4人朋友聚会(2男2女)",
  "start_time": "14:00",
  "end_time": "20:00",
  "timeline": [
    {
      "order": 1,
      "start_time": "14:00",
      "end_time": "14:20",
      "activity_type": "transport",
      "title": "出发前往XX公园",
      "description": "从家出发,步行/驾车前往",
      "venue_name": "",
      "venue_address": "",
      "venue_location": {"longitude": 0, "latitude": 0},
      "transportation": "步行",
      "travel_minutes": 20,
      "estimated_cost": 0,
      "tags": ["交通"]
    },
    {
      "order": 2,
      "start_time": "14:20",
      "end_time": "16:30",
      "activity_type": "play",
      "title": "XX公园/亲子乐园游玩",
      "description": "亲子友好，孩子能跑跳放电，也适合父母一起放松互动",
      "venue_name": "场所名称(从搜索结果中选)",
      "venue_address": "具体地址",
      "venue_location": {"longitude": 0, "latitude": 0},
      "transportation": "",
      "travel_minutes": 0,
      "estimated_cost": 50,
      "tags": ["亲子", "户外"],
      "booking_available": true,
      "booking_type": "activity_ticket",
      "ticket_count": 3
    },
    {
      "order": 3,
      "start_time": "16:30",
      "end_time": "16:45",
      "activity_type": "transport",
      "title": "步行前往餐厅",
      "description": "步行约15分钟",
      "venue_name": "",
      "venue_address": "",
      "venue_location": {"longitude": 0, "latitude": 0},
      "transportation": "步行",
      "travel_minutes": 15,
      "estimated_cost": 0,
      "tags": ["交通"]
    },
    {
      "order": 4,
      "start_time": "17:00",
      "end_time": "18:30",
      "activity_type": "eat",
      "title": "在XX餐厅用晚餐",
      "description": "离上一站近，环境适合亲子，招牌菜清淡好吃不折腾",
      "venue_name": "餐厅名称(从搜索结果中选)",
      "venue_address": "具体地址",
      "venue_location": {"longitude": 0, "latitude": 0},
      "transportation": "",
      "travel_minutes": 0,
      "estimated_cost": 300,
      "tags": ["用餐", "亲子友好"],
      "booking_available": true,
      "booking_type": "restaurant",
      "party_size": 3,
      "queue_status": "无需排队 / 约等30分钟",
      "restaurant_features": ["有儿童座椅", "有健康菜单"]
    },
    {
      "order": 5,
      "start_time": "18:30",
      "end_time": "19:30",
      "activity_type": "extra",
      "title": "饭后散步/额外活动",
      "description": "附近商圈逛逛或甜品店",
      "venue_name": "地点名称",
      "venue_address": "地址",
      "venue_location": {"longitude": 0, "latitude": 0},
      "transportation": "步行",
      "travel_minutes": 5,
      "estimated_cost": 50,
      "tags": ["休闲", "逛街"]
    }
  ],
  "weather_summary": "今日天气：晴，25°C，适合户外活动",
  "budget": {
    "activities": 100,
    "dining": 300,
    "transportation": 30,
    "extras": 50,
    "total": 480
  },
  "executable_actions": [
    {
      "action_id": "act_001",
      "action_type": "book_restaurant",
      "description": "预约XX餐厅 3人桌 17:00",
      "params": {
        "restaurant_name": "XX餐厅",
        "party_size": 3,
        "time": "17:00",
        "contact_phone": "待填写"
      }
    },
    {
      "action_id": "act_002",
      "action_type": "book_activity",
      "description": "购买XX公园门票 x3",
      "params": {
        "venue_name": "XX公园",
        "ticket_count": 3,
        "time": "14:20"
      }
    },
    {
      "action_id": "act_003",
      "action_type": "order_delivery",
      "description": "送一个生日蛋糕到XX餐厅(可选)",
      "params": {
        "item_type": "cake",
        "item_name": "6寸生日蛋糕",
        "delivery_address": "XX餐厅地址",
        "delivery_time": "17:30"
      }
    }
  ],
  "share_message": "搞定了！下午2点出发，先去XX公园玩，然后去XX餐厅吃晚饭，最后逛逛XX商圈。预计晚上7点半到家~",
  "overall_tips": "建议提前15分钟出发；餐厅建议提前预约；带好防晒和水"
}
```

**规划原则：**
1. 时间轴必须连贯，每个活动的 end_time 等于下一个活动的 start_time 或加上交通时间
2. 必须包含至少 1 个玩乐活动、1 顿餐饮、1 个额外活动
3. 交通时间要合理，近距离步行（5-20分钟），远距离打车/驾车
4. 餐厅要匹配群体需求（有孩子→亲子友好，减肥→有健康选项）
5. executable_actions 要可执行，包含具体参数
6. share_message 要口语化、简洁，适合发给同伴
7. venue_name 和 venue_address 必须从搜索结果中选取真实信息
8. **所有描述必须是推荐理由，不要只写“户外活动/附近餐厅/环境优美”这种空泛话**
9. **JSON 必须完整闭合，所有括号必须匹配！**
10. 如果是家庭场景，executable_actions 可以包含可选的送蛋糕/鲜花
11. 如果是朋友场景，可以包含桌游/KTV等选项
12. **附近快排必须尽可能读取用户一句话细节：时间、人群、关系、孩子、老人、饮食、心情、距离、预算、想放松/想热闹等**
13. **每个 play/eat/extra 节点的 description 必须回答：为什么推荐它给当前用户。示例：**
    - 家庭亲子：适合孩子放电，也能让父母一起参与，增进亲子互动
    - 老婆孩子：节奏轻松，不折腾，适合一家人一起放松
    - 减肥/健康：有轻食/少油/清淡选择，避免高热量
    - 朋友聚会：适合多人聊天，排队压力小，方便转场
    - 失恋散心：安静、不强社交，可以慢慢走、坐一会儿
14. **餐厅描述要写具体理由：距离近/不用排队/适合孩子/有包间/招牌菜/口味匹配/健康清淡，不能只写“用餐”。**
"""


# ============================================================================
# 多智能体活动规划系统
# ============================================================================

class MultiAgentActivityPlanner:
    """多智能体本地活动规划系统"""

    def __init__(self):
        print("[INIT] 开始初始化多智能体本地活动规划系统...")  # 2026-06-03 修复：emoji 编码

        try:
            settings = get_settings()
            self.llm = get_llm()

            # ---------- 意图解析 Agent（纯 LLM，不需要工具） ----------
            print("  - 创建意图解析Agent...")
            self.intent_agent = SimpleAgent(
                name="意图解析专家",
                llm=self.llm,
                system_prompt=INTENT_AGENT_PROMPT
            )

            # 2026-06-05: 搜索/天气工具 Agent 改为懒初始化，fast 模式不触发 MCP/uvx 启动成本
            self.amap_tool = None
            self.venue_agent = None
            self.restaurant_agent = None
            self.weather_agent = None

            # ---------- 规划 Agent（纯 LLM） ----------
            print("  - 创建活动规划Agent...")
            self.planner_agent = SimpleAgent(
                name="活动规划专家",
                llm=self.llm,
                system_prompt=PLANNER_AGENT_PROMPT
            )
            # 2026-06-04: 普通 Agent 模式搜索结果短期缓存，减少重复演示和重新规划时的高德/MCP 等待
            self._search_cache: Dict[str, str] = {}
            self._search_cache_lock = threading.Lock()

            print(f"[OK] 多智能体本地活动规划系统初始化成功")
            print(f"   意图解析Agent: 纯LLM")
            print(f"   搜索/天气Agent: 懒初始化（仅深度思考模式启用）")
            print(f"   活动规划Agent: 纯LLM")

        except Exception as e:
            print(f"[ERR] 多智能体系统初始化失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

    def _ensure_tool_agents(self) -> None:
        """2026-06-05: 深度思考模式按需初始化 MCP 搜索/天气 Agent，快速模式完全跳过。"""
        if self.venue_agent and self.restaurant_agent and self.weather_agent:
            return

        print("  - 深度模式首次启用，正在初始化共享MCP工具和搜索Agent...")
        from ..services.amap_service import get_amap_mcp_tool
        self.amap_tool = get_amap_mcp_tool()
        self.amap_tool.expandable = True

        self.venue_agent = SimpleAgent(
            name="场所搜索专家",
            llm=self.llm,
            system_prompt=VENUE_SEARCH_AGENT_PROMPT
        )
        self.venue_agent.add_tool(self.amap_tool)

        self.restaurant_agent = SimpleAgent(
            name="餐厅搜索专家",
            llm=self.llm,
            system_prompt=RESTAURANT_SEARCH_AGENT_PROMPT
        )
        self.restaurant_agent.add_tool(self.amap_tool)

        self.weather_agent = SimpleAgent(
            name="天气查询专家",
            llm=self.llm,
            system_prompt=WEATHER_AGENT_PROMPT
        )
        self.weather_agent.add_tool(self.amap_tool)

    # ------------------------------------------------------------------
    # 核心方法：生成活动方案
    # ------------------------------------------------------------------

    def plan_activity(
        self,
        request: dict,
        progress_callback: Optional[Callable[[dict], None]] = None
    ) -> dict:
        """
        使用多智能体协作生成本地活动方案。

        Args:
            request: ActivityRequest 的字典形式，包含:
                - message: 用户自然语言输入
                - city: 城市
                - district: 区域(可选)
                - date: 日期 YYYY-MM-DD
                - start_time: 开始时间 HH:MM (默认 14:00)
                - duration_hours: 可用时长 (默认 4)
                - group_type: family/friends (可选，Agent 也会自动识别)
                - group_info: 附加群体信息 (可选)
            progress_callback: SSE 进度回调

        Returns:
            完整的活动方案字典
        """

        def _report(step: int, total: int, percent: int, message: str):
            if progress_callback:
                progress_callback({
                    "type": "progress",
                    "step": step,
                    "total": total,
                    "percent": percent,
                    "message": message
                })

        try:
            city = request.get("city", "北京")
            district = request.get("district", "")
            user_message = request.get("message", "")
            date_str = request.get("date", datetime.now().strftime("%Y-%m-%d"))
            start_time = request.get("start_time", "14:00")
            duration_hours = request.get("duration_hours", 4)
            group_type_hint = request.get("group_type", "")
            group_info_hint = request.get("group_info", {})
            planning_mode = request.get("planning_mode", "detailed")
            # 2026-06-04: 新增 fast/agent 执行模式，fast 默认服务比赛速度与地图准确性，agent 保留深度多智能体链路
            # 2026-06-05: 执行模式缺失时按规划模式兜底，避免旧前端缓存或重规划请求把“附近快排”误跑成深度 Agent/MCP 链路。
            default_execution_mode = "fast" if planning_mode == "nearby_quick" else "agent"
            execution_mode = request.get("execution_mode") or default_execution_mode
            if execution_mode not in ("fast", "agent"):
                execution_mode = default_execution_mode
            home_location = request.get("home_location")
            user_id = request.get("user_id", "demo_user")

            safe_message = sanitize_user_input(user_message)
            safe_city = sanitize_user_input(city, max_length=50)
            safe_district = sanitize_user_input(district, max_length=50)
            # 2026-06-04: 附近快排有定位坐标时，自动反查城市/区域；城市不再必须由用户手填。
            safe_city, safe_district, location_resolved = self._resolve_location_context(
                safe_city,
                safe_district,
                home_location,
            )
            request["city"] = safe_city
            request["district"] = safe_district
            request["location_resolved"] = location_resolved

            # 2026-06-04: 附近快排优先从一句话里读取时间，如“下午1点到5点”
            time_intent = {
                "start_time": start_time,
                "duration_hours": duration_hours,
                "source": "request",
                "matched_text": "",
            }
            if planning_mode == "nearby_quick":
                time_intent = parse_time_intent_from_message(
                    safe_message,
                    fallback_start=start_time,
                    fallback_duration=duration_hours,
                )
                start_time = time_intent["start_time"]
                duration_hours = time_intent["duration_hours"]
                if time_intent["source"] == "default" and start_time < "12:00":
                    # 2026-06-05: 附近快排未明确说时间时，不沿用精细规划残留的上午时间，默认回到更符合本地活动的下午档。
                    start_time = "14:00"
                    time_intent["start_time"] = start_time
                    time_intent["source"] = "nearby_default_afternoon"
                request["start_time"] = start_time
                request["duration_hours"] = duration_hours

            print(f"\n{'='*60}")
            print(f"[START] 开始多智能体协作规划本地活动...")
            print(f"规划模式: {planning_mode}")
            print(f"执行模式: {execution_mode}")
            print(f"用户消息: {safe_message}")
            print(f"城市: {safe_city}  区域: {safe_district}")
            print(f"日期: {date_str}  开始: {start_time}  时长: {duration_hours}h")
            if planning_mode == "nearby_quick":
                print(f"时间解析: {time_intent['source']} {time_intent.get('matched_text', '')}")
            if home_location:
                print(f"当前位置: {home_location}")
                print(f"定位反查: {location_resolved}")
            print(f"{'='*60}\n")

            # ========== 步骤 1：意图解析 ==========
            _report(1, 7, 5, "[BRAIN] 正在理解您的需求...")
            print("[BRAIN] 步骤1: 意图解析...")

            if execution_mode == "fast":
                # 2026-06-05: 极速模式使用轻量 LLM 抽取“本次硬需求”，比纯规则更准确，但不触发 MCP/深度搜索。
                parsed_intent = self._fast_intent_with_llm(safe_message, group_type_hint, group_info_hint)
                parsed_intent["_home_location"] = home_location
                print(f"  [FAST] 硬需求: 活动={parsed_intent.get('hard_activity_keywords', [])} 餐饮={parsed_intent.get('hard_food_keywords', [])}")
            else:
                intent_query = self._build_intent_query(
                    safe_message, safe_city, safe_district,
                    date_str, start_time, duration_hours,
                    group_type_hint, group_info_hint
                )
                intent_response = self.intent_agent.run(intent_query)
                parsed_intent = _safe_parse_json(intent_response)

                if parsed_intent is None:
                    print("  [WARN] 意图解析返回无法解析的JSON，使用默认意图")
                    parsed_intent = self._default_intent(group_type_hint, group_info_hint)

            # 2026-06-05: 从用户原话中二次提取“电影/烧烤”等本次硬需求，防止深度 Agent 被约会/记忆偏好带偏。
            parsed_intent = self._apply_message_hard_requirements(parsed_intent, safe_message)
            # 2026-06-06: 重排请求显式携带避开地点，后续搜索、POI 落地和 Planner 提示词都会使用。
            parsed_intent["avoid_places"] = request.get("avoid_places", []) or []

            # 2026-06-04: 场景识别独立化，作为记忆隔离和搜索/规划策略的统一入口
            scenario = get_scenario_detector().detect(
                safe_message,
                parsed_intent=parsed_intent,
                planning_mode=planning_mode,
            )
            parsed_intent["scenario"] = scenario

            # 2026-06-04: 规划前检索三层记忆，形成 Graph Memory RAG 上下文注入 Planner
            memory_service = get_memory_service()
            memory_context = memory_service.get_memory_context(user_id, scenario)
            memory_service.record_message_event(
                user_id=user_id,
                scenario=scenario,
                message=safe_message,
                tags=scenario.get("prefer", []),
            )

            _report(1, 7, 15, "[BRAIN] 需求理解完成")
            print(f"  解析意图: {json.dumps(parsed_intent, ensure_ascii=False)[:300]}...\n")
            print(f"  场景识别: {json.dumps(scenario, ensure_ascii=False)}")
            print(f"  记忆命中: {json.dumps(memory_context.get('used_labels', []), ensure_ascii=False)}\n")

            # ========== 步骤 2-3：并行获取规划上下文 ==========
            # 2026-06-04: fast 走高德结构化候选池并锁定真实坐标；agent 保留原多智能体搜索链路
            if execution_mode == "fast":
                context = self._collect_planning_context_fast(
                    city=safe_city,
                    district=safe_district,
                    parsed_intent=parsed_intent,
                    start_time=start_time,
                    avoid_places=request.get("avoid_places", []),
                    report=_report,
                )
            else:
                context = self._collect_planning_context_parallel(
                    city=safe_city,
                    district=safe_district,
                    parsed_intent=parsed_intent,
                    start_time=start_time,
                    report=_report,
                )
            venue_results = context["venue_results"]
            restaurant_results = context["restaurant_results"]
            weather_response = context["weather_response"]
            availability_info = context["availability_info"]
            poi_candidates = context.get("poi_candidates", {})
            fast_candidate_quality = context.get("fast_candidate_quality", {})

            # ========== 步骤 4：生成综合方案 ==========
            _report(4, 7, 65, "[PLAN] 正在生成完整活动方案...")
            print("[PLAN] 步骤4: 生成活动方案...")

            if execution_mode == "fast":
                # 2026-06-05: 极速模式不再等待 Planner LLM，直接用真实 POI 候选池确定性排程
                plan = self._create_fast_plan(
                    request=request,
                    parsed_intent=parsed_intent,
                    scenario=scenario,
                    memory_context=memory_context,
                    poi_candidates=poi_candidates,
                    weather_response=weather_response,
                    availability_info=availability_info,
                )
                plan["time_intent"] = time_intent
                plan["execution_mode"] = execution_mode
                plan["poi_candidate_summary"] = {
                    "venue_count": len(poi_candidates.get("venues", [])),
                    "restaurant_count": len(poi_candidates.get("restaurants", [])),
                    "location_locked": True,
                    "low_candidate_quality": bool(fast_candidate_quality.get("low", False)),
                }
                plan["scenario"] = scenario
                plan["memory_context"] = {
                    "user_id": user_id,
                    "scenario": memory_context.get("scenario"),
                    "used_labels": memory_context.get("used_labels", []),
                    "stable_preferences": memory_context.get("stable_preferences", []),
                    "scenario_preferences": memory_context.get("scenario_preferences", []),
                    "object_memories": memory_context.get("object_memories", []),
                }
                self._enrich_plan_reasons(plan, parsed_intent, safe_message)

                _report(5, 7, 84, "[CHECK] 正在进行规则质检...")
                quality_report = self._validate_plan_rules(plan, request, parsed_intent)
                plan["quality_report"] = quality_report
                _report(6, 7, 92, "[CHECK] 极速模式跳过 LLM 语义质检")
                plan["llm_quality_report"] = {
                    "enabled": False,
                    "message": "极速模式为确定性排程，跳过 LLM 语义质检以满足速度约束"
                }
                _report(7, 7, 100, "[OK] 极速活动方案生成完成！")
                print(f"  [FAST] 确定性方案完成: score={quality_report['score']} issues={len(quality_report['issues'])}")
                return plan

            planner_query = self._build_planner_query(
                city=safe_city,
                district=safe_district,
                date_str=date_str,
                start_time=start_time,
                duration_hours=duration_hours,
                user_message=safe_message,
                parsed_intent=parsed_intent,
                venue_results=venue_results,
                restaurant_results=restaurant_results,
                weather_info=weather_response,
                availability_info=json.dumps(availability_info, ensure_ascii=False),
                planning_mode=planning_mode,
                execution_mode=execution_mode,
                home_location=home_location,
                location_resolved=location_resolved,
                scenario=scenario,
                memory_context=memory_context,
            )
            planner_response = self.planner_agent.run(planner_query)

            _report(4, 7, 76, "[PLAN] 正在解析方案数据...")
            print(f"  规划结果: {planner_response[:400]}...\n")

            # 解析方案
            plan = self._parse_plan_response(planner_response, request, parsed_intent)
            plan["time_intent"] = time_intent
            plan["execution_mode"] = execution_mode
            if execution_mode == "fast":
                # 2026-06-04: 返回快速模式候选池摘要，便于前端/调试确认地点来自真实 POI 候选池
                plan["poi_candidate_summary"] = {
                    "venue_count": len(poi_candidates.get("venues", [])),
                    "restaurant_count": len(poi_candidates.get("restaurants", [])),
                    "location_locked": True,
                    "low_candidate_quality": bool(fast_candidate_quality.get("low", False)),
                }
            plan["scenario"] = scenario
            plan["memory_context"] = {
                "user_id": user_id,
                "scenario": memory_context.get("scenario"),
                "used_labels": memory_context.get("used_labels", []),
                "stable_preferences": memory_context.get("stable_preferences", []),
                "scenario_preferences": memory_context.get("scenario_preferences", []),
                "object_memories": memory_context.get("object_memories", []),
            }
            if execution_mode == "fast":
                self._lock_plan_locations_to_candidates(plan, poi_candidates)
            else:
                # 2026-06-05: 深度多智能体模式保留 LLM 规划，但最终地点必须落到高德真实 POI，避免“待确认影院/泛化餐厅”直接展示。
                self._lock_agent_plan_to_real_pois(plan, request, parsed_intent)
            self._trim_extra_nodes_after_hard_trip(plan, parsed_intent)
            # 2026-06-05: 通用补充异常覆盖策略，满足比赛“至少三类故障”的显性展示要求。
            plan["exception_strategies"] = self._build_exception_strategies(plan.get("weather_summary", ""), parsed_intent)
            self._enrich_plan_reasons(plan, parsed_intent, safe_message)

            # ========== 步骤 5：规则质检 ==========
            _report(5, 7, 84, "[CHECK] 正在进行规则质检...")
            quality_report = self._validate_plan_rules(plan, request, parsed_intent)
            plan["quality_report"] = quality_report
            print(f"  规则质检: passed={quality_report['passed']} score={quality_report['score']} issues={len(quality_report['issues'])}")

            # ========== 步骤 6：语义质检预留 ==========
            # 2026-06-04: 第二层 LLM 质检将在下一步接入；当前先显式预留进度和结果结构
            _report(6, 7, 92, "[CHECK] 规则质检完成，语义质检节点已预留")
            plan["llm_quality_report"] = {
                "enabled": False,
                "message": "LLM 语义质检节点已预留，下一步接入"
            }

            # ========== 步骤 7：完成 ==========
            _report(7, 7, 100, "[OK] 活动方案生成完成！")
            print(f"{'='*60}")
            print(f"[OK] 活动方案生成完成!")
            print(f"{'='*60}\n")

            return plan

        except Exception as e:
            print(f"[ERR] 生成活动方案失败: {str(e)}")
            import traceback
            traceback.print_exc()
            if progress_callback:
                progress_callback({
                    "type": "error",
                    "message": f"生成失败: {str(e)}"
                })
            return self._create_fallback_plan({**request, "fallback_reason": f"planner_exception: {str(e)[:80]}"})

    def _resolve_location_context(self, city: str, district: str, home_location: Optional[dict]) -> tuple[str, str, dict]:
        """2026-06-04: 附近快排支持只传定位坐标，后端自动反查城市/区域并标记坐标为优先位置。"""
        resolved = {
            "source": "manual_city" if city else "unknown",
            "city": city,
            "district": district,
            "formatted_address": "",
        }
        if not home_location:
            return city, district, resolved

        try:
            geo = get_amap_service().reverse_geocode(
                longitude=float(home_location.get("longitude")),
                latitude=float(home_location.get("latitude")),
            )
        except Exception as exc:
            print(f"  [WARN] 当前位置反查城市失败: {exc}")
            geo = {}

        resolved_city = city or str(geo.get("city") or "").replace("市", "")
        resolved_district = district or str(geo.get("district") or "")
        resolved.update({
            "source": "home_location_regeo" if geo else "home_location",
            "city": resolved_city,
            "district": resolved_district,
            "formatted_address": geo.get("formatted_address", "") if geo else "",
        })
        return resolved_city, resolved_district, resolved

    # ------------------------------------------------------------------
    # 2026-06-04: 并行上下文获取与规则质检
    # ------------------------------------------------------------------

    def _get_weather_info(self, city: str) -> str:
        """查询天气信息；优先直接调用 AmapService，失败后降级到天气 Agent。"""
        try:
            from ..services.amap_service import get_amap_service
            amap_service = get_amap_service()
            weather_list = amap_service.get_weather(city)
            if weather_list:
                weather_data = [{
                    "date": w.date,
                    "day_weather": w.day_weather,
                    "night_weather": w.night_weather,
                    "day_temp": w.day_temp,
                    "night_temp": w.night_temp,
                    "wind_direction": w.wind_direction,
                    "wind_power": w.wind_power
                } for w in weather_list]
                return json.dumps(weather_data, ensure_ascii=False)
            return f"未获取到{city}的天气数据"
        except Exception as weather_err:
            print(f"  [WARN] 天气查询直接调用失败: {weather_err}")
            weather_query = f"请查询{city}的天气信息"
            self._ensure_tool_agents()
            return self.weather_agent.run(weather_query)

    def _get_weather_info_fast(self, city: str) -> str:
        """2026-06-05: 极速模式只走高德 REST 天气，失败直接返回轻量兜底，不触发 MCP/天气 Agent。"""
        try:
            amap_service = get_amap_service()
            weather_list = amap_service.get_weather_rest(city)
            if weather_list:
                weather_data = [{
                    "date": w.date,
                    "day_weather": w.day_weather,
                    "night_weather": w.night_weather,
                    "day_temp": w.day_temp,
                    "night_temp": w.night_temp,
                    "wind_direction": w.wind_direction,
                    "wind_power": w.wind_power
                } for w in weather_list]
                return json.dumps(weather_data, ensure_ascii=False)
        except Exception as exc:
            print(f"  [WARN] 极速天气 REST 查询失败: {exc}")
        return f"未获取到{city}的天气数据"

    def _check_restaurant_availability(self, city: str, party_size: int, time: str) -> dict:
        """查询餐厅可用性（Mock），供规划和执行动作生成使用。"""
        from ..services.mock_service import get_mock_service
        mock_svc = get_mock_service()
        return mock_svc.batch_check_restaurant_availability(
            city=city,
            party_size=party_size,
            time=time
        )

    def _collect_planning_context_parallel(
        self,
        city: str,
        district: str,
        parsed_intent: dict,
        start_time: str,
        report: Callable[[int, int, int, str], None],
    ) -> dict:
        """并行获取场所、餐厅、天气和 Mock 可用性，减少新增质检后的总体等待时间。"""
        self._ensure_tool_agents()
        print("[PARALLEL] 步骤2: 并行搜索场所、餐厅、天气和可用性...")
        report(2, 7, 20, "[SEARCH] 正在并行搜索附近场所、餐厅和天气...")

        tasks = {
            "venue_results": (
                "场所搜索",
                lambda: self._search_venues(city, district, parsed_intent)
            ),
            "restaurant_results": (
                "餐厅搜索",
                lambda: self._search_restaurants(city, district, parsed_intent)
            ),
            "weather_response": (
                "天气查询",
                lambda: self._get_weather_info(city)
            ),
            "availability_info": (
                "餐厅可用性",
                lambda: self._check_restaurant_availability(
                    city=city,
                    party_size=parsed_intent.get("group_size", 3),
                    time=start_time
                )
            ),
        }

        results: dict = {
            "venue_results": "",
            "restaurant_results": "",
            "weather_response": f"未获取到{city}的天气数据",
            "availability_info": {},
        }
        progress_map = {
            "venue_results": 32,
            "restaurant_results": 40,
            "weather_response": 46,
            "availability_info": 52,
        }

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_map = {
                executor.submit(fn): (key, label)
                for key, (label, fn) in tasks.items()
            }
            for future in as_completed(future_map):
                key, label = future_map[future]
                try:
                    results[key] = future.result()
                    report(2, 7, progress_map[key], f"[OK] {label}完成")
                    print(f"  [OK] {label}完成")
                except Exception as e:
                    print(f"  [WARN] {label}失败: {e}")
                    report(2, 7, progress_map[key], f"[WARN] {label}失败，使用降级结果")
                    if key in ("venue_results", "restaurant_results"):
                        results[key] = f"【{label}】搜索失败"

        report(3, 7, 58, "[OK] 场所、餐厅、天气和可用性已汇总")
        print(f"  场所搜索结果: {str(results['venue_results'])[:300]}...\n")
        print(f"  餐厅搜索结果: {str(results['restaurant_results'])[:300]}...\n")
        print(f"  天气结果: {str(results['weather_response'])[:200]}...\n")
        print(f"  可用性信息: {json.dumps(results['availability_info'], ensure_ascii=False)[:300]}...\n")
        return results

    def _collect_planning_context_fast(
        self,
        city: str,
        district: str,
        parsed_intent: dict,
        start_time: str,
        avoid_places: Optional[List[str]],
        report: Callable[[int, int, int, str], None],
    ) -> dict:
        """2026-06-04: 快速模式直接调用高德 POI 服务形成结构化候选池，减少搜索 Agent 耗时并锁定坐标。"""
        print("[FAST] 步骤2: 极速模式采集高德结构化候选池...")
        report(2, 7, 20, "[FAST] 正在直接检索真实场所和餐厅...")

        venue_keywords = self._build_fast_search_keywords(parsed_intent, category="venue")
        restaurant_keywords = self._build_fast_search_keywords(parsed_intent, category="restaurant")
        search_city = city or ""
        location_prefix = district.strip()

        candidates = {
            "venues": [],
            "restaurants": [],
        }

        def search_group(category: str, keywords: List[str]) -> List[dict]:
            group_results: List[dict] = []
            amap_service = get_amap_service()
            home_location = parsed_intent.get("_home_location")
            rest_location = None
            if home_location:
                try:
                    loc = _location_to_dict(home_location)
                    rest_location = Location(longitude=loc["longitude"], latitude=loc["latitude"])
                except Exception:
                    rest_location = None
            for keyword in keywords:
                full_keyword = f"{location_prefix}{keyword}".strip() if location_prefix else keyword
                pois = amap_service.search_poi_rest(
                    full_keyword,
                    search_city,
                    citylimit=bool(search_city),
                    offset=6,
                    location=rest_location,
                    radius=5000,
                )
                for poi in pois[:5]:
                    candidate = _poi_to_candidate(poi, full_keyword, category)
                    loc = candidate.get("location", {})
                    # 2026-06-06: 快速模式重排时过滤用户明确要求避开的旧 POI，确保“换一个/换一套”真的变化。
                    if candidate["name"] and loc.get("longitude") and loc.get("latitude") and not _is_avoided_place(candidate["name"], avoid_places):
                        group_results.append(candidate)
            return self._dedupe_candidates(group_results)[: max(10, len(keywords) * 3)]

        tasks = {
            "venues": ("真实场所", lambda: search_group("venue", venue_keywords)),
            "restaurants": ("真实餐厅", lambda: search_group("restaurant", restaurant_keywords)),
            "weather_response": ("天气查询", lambda: self._get_weather_info_fast(city)),
            "availability_info": (
                "餐厅可用性",
                lambda: self._check_restaurant_availability(
                    city=city,
                    party_size=parsed_intent.get("group_size", 3),
                    time=start_time,
                ),
            ),
        }
        results: dict = {
            "weather_response": f"未获取到{city}的天气数据",
            "availability_info": {},
        }

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_map = {
                executor.submit(fn): (key, label)
                for key, (label, fn) in tasks.items()
            }
            for future in as_completed(future_map):
                key, label = future_map[future]
                try:
                    results[key] = future.result()
                    print(f"  [FAST] {label}完成")
                except Exception as exc:
                    print(f"  [WARN] 快速模式{label}失败: {exc}")
                    results[key] = [] if key in ("venues", "restaurants") else results.get(key)

        candidates["venues"] = results.get("venues", [])
        candidates["restaurants"] = results.get("restaurants", [])

        venue_results = self._format_poi_candidates_for_prompt(candidates["venues"], "玩乐候选 POI")
        restaurant_results = self._format_poi_candidates_for_prompt(candidates["restaurants"], "餐饮候选 POI")
        low_candidate_quality = len(candidates["venues"]) < 3 or len(candidates["restaurants"]) < 2
        if low_candidate_quality:
            # 2026-06-05: 极速模式不再混入深度 Agent 兜底，候选不足只在质量摘要里标记，避免速度失控
            print("  [FAST] 候选池偏少，将使用确定性兜底排程，不触发深度搜索。")

        report(3, 7, 58, "[FAST] 真实地点、餐厅、天气和可用性已汇总")
        print(f"  [FAST] 玩乐候选: {len(candidates['venues'])} 个，餐饮候选: {len(candidates['restaurants'])} 个")

        return {
            "venue_results": venue_results,
            "restaurant_results": restaurant_results,
            "weather_response": results.get("weather_response", ""),
            "availability_info": results.get("availability_info", {}),
            "poi_candidates": candidates,
            "fast_candidate_quality": {
                "low": low_candidate_quality,
                "venue_count": len(candidates["venues"]),
                "restaurant_count": len(candidates["restaurants"]),
            },
        }

    def _run_cached_agent_search(self, cache_key: str, agent: SimpleAgent, query: str) -> str:
        """2026-06-04: 普通 Agent 模式复用短期搜索缓存，减少重复 POI 搜索和工具等待。"""
        with self._search_cache_lock:
            if cache_key in self._search_cache:
                return self._search_cache[cache_key]

        result = agent.run(query)
        with self._search_cache_lock:
            if len(self._search_cache) > 80:
                self._search_cache.clear()
            self._search_cache[cache_key] = result
        return result

    def _is_unusable_agent_search_result(self, result: str) -> bool:
        """2026-06-06: 识别搜索 Agent 的道歉/建议文本，避免把无效搜索结果继续交给 Planner。"""
        text = result or ""
        bad_patterns = [
            "搜索工具暂时无法使用",
            "无法为您获取实时",
            "无法获取实时",
            "工具暂时无法",
            "请您直接在美团",
            "大众点评等平台搜索",
            "搜索失败",
        ]
        return not text.strip() or any(pattern in text for pattern in bad_patterns)

    def _search_poi_rest_fallback_text(self, keyword: str, city: str, district: str, category: str) -> str:
        """2026-06-06: 深度模式搜索失败时降级到高德 REST，确保 Planner 仍拿到真实 POI 候选。"""
        full_keyword = f"{district}{keyword}".strip() if district and district not in keyword else keyword
        try:
            pois = get_amap_service().search_poi_rest(
                full_keyword,
                city,
                citylimit=bool(city),
                offset=8,
            )
            candidates = [
                _poi_to_candidate(poi, full_keyword, category)
                for poi in pois
            ]
            candidates = [
                item for item in candidates
                if item.get("name") and item.get("address") and _has_valid_location(item.get("location"))
            ]
            if not candidates:
                return "高德 REST 兜底未找到可用真实 POI。"
            return self._format_poi_candidates_for_prompt(candidates, f"{keyword}真实 POI 兜底")
        except Exception as e:
            print(f"  [WARN] 高德 REST 兜底搜索 {keyword} 失败: {e}")
            return "高德 REST 兜底搜索失败。"

    def _apply_message_hard_requirements(self, parsed_intent: dict, message: str) -> dict:
        """2026-06-05: 统一抽取本次明确需求，fast/agent 共用，避免场景记忆覆盖用户原话。"""
        parsed_intent = dict(parsed_intent or {})
        text = message or ""
        preferred = [str(item) for item in parsed_intent.get("preferred_activities", []) if item]
        dining = [str(item) for item in parsed_intent.get("dining_preferences", []) if item]
        hard_activities = [str(item) for item in parsed_intent.get("hard_activity_keywords", []) if item]
        hard_food = [str(item) for item in parsed_intent.get("hard_food_keywords", []) if item]

        activity_rules = [
            (["电影", "看电影", "影院", "影城", "IMAX", "imax"], ["电影院", "影城"], ["电影院"]),
            (["麻将", "打麻将", "棋牌"], ["棋牌室", "麻将馆"], ["棋牌室"]),
            (["拍照", "出片", "打卡"], ["拍照打卡", "网红打卡"], ["网红打卡地"]),
            (["展览", "看展"], ["展览馆", "美术馆"], ["展览"]),
            (["密室"], ["密室逃脱"], ["密室逃脱"]),
            (["剧本杀"], ["剧本杀"], ["剧本杀"]),
            (["KTV", "唱歌"], ["KTV"], ["KTV"]),
            (["桌游"], ["桌游吧"], ["桌游"]),
            (["台球"], ["台球厅"], ["台球"]),
            (["电玩", "游戏厅", "电玩城"], ["电玩城", "游戏厅"], ["电玩"]),
            (["保龄球"], ["保龄球馆"], ["保龄球"]),
            (["按摩", "足疗", "洗脚"], ["足疗按摩"], ["按摩足疗"]),
        ]
        food_rules = [
            (["烧烤", "烤肉"], ["烧烤"], ["烧烤"]),
            (["火锅"], ["火锅"], ["火锅"]),
            (["日料", "寿司"], ["日本料理", "日料"], ["日料"]),
            (["西餐", "牛排"], ["西餐厅", "西餐"], ["西餐"]),
            (["咖啡"], ["咖啡馆"], ["咖啡"]),
            (["喝酒", "酒吧", "清吧", "小酒馆"], ["小酒馆", "清吧"], ["喝酒聊天"]),
            (["夜宵", "宵夜"], ["夜宵"], ["夜宵"]),
            (["茶馆", "喝茶"], ["茶馆"], ["茶馆"]),
            (["轻食", "减肥", "减脂", "低卡"], ["轻食", "健康餐"], ["健康低卡"]),
        ]

        for triggers, keywords, prefs in activity_rules:
            if any(word in text for word in triggers):
                hard_activities = _append_unique(hard_activities, keywords)
                preferred = _append_unique(preferred, prefs)
        for triggers, keywords, prefs in food_rules:
            if any(word in text for word in triggers):
                hard_food = _append_unique(hard_food, keywords)
                dining = _append_unique(dining, prefs)

        parsed_intent["preferred_activities"] = preferred
        parsed_intent["dining_preferences"] = dining
        parsed_intent["hard_activity_keywords"] = hard_activities
        parsed_intent["hard_food_keywords"] = hard_food
        parsed_intent["hard_trip_items"] = _canonical_hard_trip_items(text)
        return parsed_intent

    def _rule_based_intent(self, message: str, group_type_hint: str, group_info_hint: dict) -> dict:
        """2026-06-05: 极速模式规则意图解析，跳过 LLM，保留场景/人群/饮食核心信息。"""
        text = message or ""
        is_family = any(word in text for word in ["孩子", "娃", "亲子", "老婆", "老公", "父母", "爸妈", "一家", "带爸", "带妈"])
        has_child = any(word in text for word in ["孩子", "娃", "亲子", "小孩"])
        has_elderly = any(word in text for word in ["父母", "爸妈", "老人", "妈妈", "爸爸"])
        group_type = group_type_hint or ("family" if is_family else "friends")
        if any(word in text for word in ["女朋友", "男朋友", "约会", "情侣"]):
            group_size = 2
        elif has_elderly and has_child:
            group_size = 4
        elif has_child:
            group_size = 3
        elif any(word in text for word in ["一个人", "自己", "独自"]):
            group_size = 1
        else:
            match = re.search(r"(\d+)\s*个?人", text)
            group_size = int(match.group(1)) if match else (3 if group_type == "family" else 4)

        dietary: List[str] = []
        if any(word in text for word in ["减肥", "减脂", "低卡", "清淡", "健康"]):
            dietary.extend(["健康低卡", "清淡少油"])
        if "素食" in text:
            dietary.append("素食")

        preferred: List[str] = []
        if any(word in text for word in ["电影", "看电影", "影院", "影城", "IMAX", "imax"]):
            # 2026-06-05: 极速模式强识别“电影+吃饭”这种明确目标，避免约会场景只按网红打卡/夜景泛化推荐。
            preferred.append("电影院")
        if any(word in text for word in ["散步", "散心", "放松", "公园"]):
            preferred.append("公园")
        if any(word in text for word in ["拍照", "出片", "网红"]):
            preferred.append("网红打卡")
        if any(word in text for word in ["夜景", "晚上"]):
            preferred.append("夜景")
        if any(word in text for word in ["展", "展览"]):
            preferred.append("展览")
        if has_child:
            preferred.append("亲子乐园")

        return {
            "group_type": group_type,
            "group_size": group_size,
            "group_details": group_info_hint or {
                "has_children": has_child,
                "children_ages": [],
                "has_elderly": has_elderly,
                "dietary_restrictions": dietary,
                "gender_split": "",
            },
            "preferred_activities": list(dict.fromkeys(preferred)) or ["公园", "商圈"],
            "dining_preferences": dietary or (["亲子友好"] if has_child else []),
            "constraints": ["别太远"] if any(word in text for word in ["附近", "别太远", "近一点", "周围"]) else [],
            "mood": "轻松休闲",
            "special_requests": [],
        }

    def _fast_intent_with_llm(self, message: str, group_type_hint: str, group_info_hint: dict) -> dict:
        """2026-06-05: 极速模式轻量 LLM 意图抽取，只提取本次显式硬需求，避免记忆或场景泛化覆盖用户原话。"""
        fallback = self._rule_based_intent(message, group_type_hint, group_info_hint)
        prompt = f"""
你是本地生活快排的意图抽取器。请只根据用户这一次输入抽取硬需求，不要根据历史偏好脑补。

用户输入：{message}
表单群体类型：{group_type_hint}
表单群体信息：{json.dumps(group_info_hint or {}, ensure_ascii=False)}

请输出 JSON：
{{
  "group_type": "family/friends",
  "group_size": 2,
  "preferred_activities": ["电影院"],
  "dining_preferences": ["烧烤"],
  "hard_activity_keywords": ["电影院", "影城"],
  "hard_food_keywords": ["烧烤"],
  "constraints": ["别太远"],
  "mood": "轻松约会",
  "special_requests": []
}}

要求：
- 2026-06-06：用户原话里明确出现的活动/餐饮/娱乐项目都属于硬需求，必须写入 hard_activity_keywords 或 hard_food_keywords。
- 例如“看电影/电影/影院”必须包含“电影院”或“影城”；“打麻将/麻将/棋牌”必须包含“棋牌室”或“麻将馆”；“唱歌/KTV/桌游/台球/电玩城/密室/剧本杀”也要保留。
- 例如“烧烤/火锅/咖啡/日料/西餐/小酒馆/喝酒/夜宵”必须包含对应餐饮词。
- 如果用户只是说“拍拍照/出片”，不要写电影院；如果用户只是说“喝酒”，不要自动写麻将。
- 不要把历史记忆、常见约会偏好写成硬需求；硬需求只能来自用户本次原话。
"""
        try:
            response = self.intent_agent.run(prompt)
            parsed = _safe_parse_json(response) or {}
            if not isinstance(parsed, dict):
                return fallback
            merged = {**fallback, **parsed}
            merged["preferred_activities"] = list(dict.fromkeys(
                [str(item) for item in parsed.get("preferred_activities", []) if item]
                or fallback.get("preferred_activities", [])
            ))
            merged["dining_preferences"] = list(dict.fromkeys(
                [str(item) for item in parsed.get("dining_preferences", []) if item]
                or fallback.get("dining_preferences", [])
            ))
            # 2026-06-06: LLM 抽取结果与规则兜底合并，避免任一方漏掉用户原话里的明确事项。
            merged["hard_activity_keywords"] = list(dict.fromkeys(
                [str(item) for item in fallback.get("hard_activity_keywords", []) if item]
                + [str(item) for item in parsed.get("hard_activity_keywords", []) if item]
            ))
            merged["hard_food_keywords"] = list(dict.fromkeys(
                [str(item) for item in fallback.get("hard_food_keywords", []) if item]
                + [str(item) for item in parsed.get("hard_food_keywords", []) if item]
            ))
            merged["fast_intent_source"] = "llm"
            return merged
        except Exception as exc:
            print(f"  [WARN] 极速模式轻量意图 LLM 失败，回退规则意图: {exc}")
            fallback["fast_intent_source"] = "rules"
            return fallback

    def _create_fast_plan(
        self,
        request: dict,
        parsed_intent: dict,
        scenario: dict,
        memory_context: dict,
        poi_candidates: dict,
        weather_response: str,
        availability_info: dict,
    ) -> dict:
        """2026-06-05: 极速模式确定性排程，不等待 Planner LLM，保证比赛速度约束。"""
        city = request.get("city") or "当前位置"
        district = request.get("district", "")
        date_str = request.get("date", datetime.now().strftime("%Y-%m-%d"))
        start_time = request.get("start_time", "14:00")
        duration = int(request.get("duration_hours", 4) or 4)
        home_location = request.get("home_location")
        start_h, start_m = [int(x) for x in start_time.split(":", 1)]
        start_minutes = start_h * 60 + start_m

        def fmt(minutes: int) -> str:
            minutes = min(minutes, 23 * 60 + 59)
            return f"{minutes // 60:02d}:{minutes % 60:02d}"

        venues = poi_candidates.get("venues", []) or []
        restaurants = poi_candidates.get("restaurants", []) or []
        if not venues or not restaurants:
            # 2026-06-05: 极速模式禁止虚拟兜底地点；真实 POI 不足时直接返回候选不足方案，避免“附近餐厅/待确认影院”污染地图。
            return self._create_candidate_shortage_plan(
                request=request,
                parsed_intent=parsed_intent,
                scenario=scenario,
                weather_response=weather_response,
                venue_count=len(venues),
                restaurant_count=len(restaurants),
            )
        # 2026-06-05: 极速模式保留轻量 LLM，只让它在真实 POI 候选池里做选择和理由，不允许编地点/坐标。
        selection = self._select_fast_candidates_with_llm(
            request=request,
            parsed_intent=parsed_intent,
            scenario=scenario,
            # 2026-06-05: 极速模式选择阶段弱化记忆，防止历史“酒吧/夜景”等偏好覆盖本次“电影/烧烤”等显式需求。
            memory_context={"used_labels": []},
            venues=venues,
            restaurants=restaurants,
        )
        selection = self._enforce_fast_hard_trip_selection(selection, parsed_intent, venues, restaurants)

        def pick(items: List[dict], index: int) -> dict:
            safe_index = max(0, min(index, len(items) - 1))
            return items[safe_index]

        main_venue = pick(
            venues,
            int(selection.get("main_venue_index", 0) or 0),
        )
        extra_venue = pick(
            venues,
            int(selection.get("extra_venue_index", 1) or 1),
        )
        has_second_hard_venue = len([
            item for item in parsed_intent.get("hard_trip_items", [])
            if isinstance(item, dict) and item.get("kind") == "venue"
        ]) >= 2
        if extra_venue.get("name") == main_venue.get("name") and not has_second_hard_venue:
            extra_venue = next((item for item in venues if item.get("name") != main_venue.get("name")), None)
        if not extra_venue:
            extra_venue = main_venue
        restaurant = pick(
            restaurants,
            int(selection.get("restaurant_index", 0) or 0),
        )

        group_size = int(parsed_intent.get("group_size", 2) or 2)
        group_type = parsed_intent.get("group_type", "friends")
        scenario_primary = scenario.get("primary", "")
        weather_summary = self._summarize_weather(weather_response)
        group_summary = self._build_group_summary(parsed_intent, scenario)

        t0 = start_minutes
        t1 = t0 + 20
        t2 = t1 + 90
        t3 = t2 + 15
        t4 = t3 + 75
        t5 = min(t0 + duration * 60, t4 + 45)

        llm_reasons = selection.get("reasons", {}) if isinstance(selection.get("reasons"), dict) else {}
        play_reason = llm_reasons.get("play") or self._fast_reason(main_venue, "play", parsed_intent, scenario)
        eat_reason = llm_reasons.get("eat") or self._fast_reason(restaurant, "eat", parsed_intent, scenario)
        extra_reason = llm_reasons.get("extra") or self._fast_reason(extra_venue, "extra", parsed_intent, scenario)
        dining_cost = 90 * max(group_size, 1)
        activity_cost = 60 * max(group_size, 1) if "免费" not in str(main_venue.get("type", "")) else 0
        extras_cost = 30 * max(group_size, 1)

        plan_id = f"plan_fast_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        plan = {
            "plan_id": plan_id,
            "city": city,
            "district": district,
            "date": date_str,
            "group_type": group_type,
            "group_summary": group_summary,
            "start_time": fmt(t0),
            "end_time": fmt(t5),
            "timeline": [
                {
                    "order": 1,
                    "start_time": fmt(t0),
                    "end_time": fmt(t1),
                    "activity_type": "transport",
                    "title": "出发",
                    "description": f"从当前位置前往{main_venue.get('name')}",
                    "venue_name": "",
                    "venue_address": "",
                    "venue_location": _offset_location(home_location),
                    "transportation": "打车/步行",
                    "travel_minutes": 20,
                    "estimated_cost": 10,
                    "tags": ["交通"],
                },
                {
                    "order": 2,
                    "start_time": fmt(t1),
                    "end_time": fmt(t2),
                    "activity_type": "play",
                    "title": f"{main_venue.get('name')}游玩",
                    "description": play_reason,
                    "venue_name": main_venue.get("name", ""),
                    "venue_address": main_venue.get("address", ""),
                    "venue_location": main_venue.get("location"),
                    "transportation": "",
                    "travel_minutes": 0,
                    "estimated_cost": activity_cost,
                    "tags": self._fast_tags("play", parsed_intent, scenario, main_venue),
                    "booking_available": True,
                    "booking_type": "activity_ticket",
                    "ticket_count": group_size,
                    "poi_id": main_venue.get("id", ""),
                    "venue_type": main_venue.get("type", ""),
                    "poi_type": main_venue.get("type", ""),
                    "poi_keyword": main_venue.get("keyword", ""),
                    "source_keyword": main_venue.get("keyword", ""),
                    "poi_category": main_venue.get("category", "venue"),
                },
                {
                    "order": 3,
                    "start_time": fmt(t2),
                    "end_time": fmt(t3),
                    "activity_type": "transport",
                    "title": "前往餐厅",
                    "description": f"转场到{restaurant.get('name')}，减少来回折返",
                    "venue_name": "",
                    "venue_address": "",
                    "venue_location": restaurant.get("location"),
                    "transportation": "步行/打车",
                    "travel_minutes": 15,
                    "estimated_cost": 10,
                    "tags": ["交通"],
                },
                {
                    "order": 4,
                    "start_time": fmt(t3),
                    "end_time": fmt(t4),
                    "activity_type": "eat",
                    "title": f"在{restaurant.get('name')}用餐",
                    "description": eat_reason,
                    "venue_name": restaurant.get("name", ""),
                    "venue_address": restaurant.get("address", ""),
                    "venue_location": restaurant.get("location"),
                    "transportation": "",
                    "travel_minutes": 0,
                    "estimated_cost": dining_cost,
                    "tags": self._fast_tags("eat", parsed_intent, scenario, restaurant),
                    "booking_available": True,
                    "booking_type": "restaurant",
                    "party_size": group_size,
                    "queue_status": "建议提前预约",
                    "restaurant_features": ["可预约", "转场方便"],
                    "poi_id": restaurant.get("id", ""),
                    "venue_type": restaurant.get("type", ""),
                    "poi_type": restaurant.get("type", ""),
                    "poi_keyword": restaurant.get("keyword", ""),
                    "source_keyword": restaurant.get("keyword", ""),
                    "poi_category": restaurant.get("category", "restaurant"),
                },
                {
                    "order": 5,
                    "start_time": fmt(t4),
                    "end_time": fmt(t5),
                    "activity_type": "extra",
                    "title": f"{extra_venue.get('name')}收尾",
                    "description": extra_reason,
                    "venue_name": extra_venue.get("name", ""),
                    "venue_address": extra_venue.get("address", ""),
                    "venue_location": extra_venue.get("location"),
                    "transportation": "步行",
                    "travel_minutes": 5,
                    "estimated_cost": extras_cost,
                    "tags": self._fast_tags("extra", parsed_intent, scenario, extra_venue),
                    "poi_id": extra_venue.get("id", ""),
                    "venue_type": extra_venue.get("type", ""),
                    "poi_type": extra_venue.get("type", ""),
                    "poi_keyword": extra_venue.get("keyword", ""),
                    "source_keyword": extra_venue.get("keyword", ""),
                    "poi_category": extra_venue.get("category", "venue"),
                },
            ],
            "weather_summary": weather_summary,
            "budget": {
                "activities": activity_cost,
                "dining": dining_cost,
                "transportation": 20,
                "extras": extras_cost,
                "total": activity_cost + dining_cost + extras_cost + 20,
            },
            "executable_actions": [
                {
                    "action_id": "act_fast_restaurant",
                    "action_type": "book_restaurant",
                    "description": f"预约{restaurant.get('name')} {group_size}人 {fmt(t3)}",
                    "params": {
                        "restaurant_name": restaurant.get("name"),
                        "party_size": group_size,
                        "time": fmt(t3),
                        "contact_phone": "待填写",
                    },
                    "is_optional": False,
                    "estimated_cost": 0,
                }
            ],
            "share_message": f"安排好了，{fmt(t0)}出发，先去{main_venue.get('name')}，再到{restaurant.get('name')}吃饭，最后去{extra_venue.get('name')}轻松收尾。",
            "overall_tips": self._fast_overall_tips(scenario_primary, weather_summary),
            # 2026-06-05: 补齐比赛要求的异常覆盖展示，让 Demo 能明确看到无座、无票、时间/天气冲突的处理策略。
            "exception_strategies": self._build_exception_strategies(weather_summary, parsed_intent),
            "parsed_intent": parsed_intent,
            "availability_snapshot": availability_info,
            "fast_llm_selection": selection,
        }
        self._annotate_timeline_hard_expectations(plan, parsed_intent)
        if main_venue.get("id"):
            plan["executable_actions"].append({
                "action_id": "act_fast_ticket",
                "action_type": "book_activity",
                "description": f"购买{main_venue.get('name')}门票 x{group_size}",
                "params": {
                    "venue_name": main_venue.get("name"),
                    "ticket_count": group_size,
                    "time": fmt(t1),
                },
                "is_optional": True,
                "estimated_cost": activity_cost,
            })
        return plan

    def _select_fast_candidates_with_llm(
        self,
        request: dict,
        parsed_intent: dict,
        scenario: dict,
        memory_context: dict,
        venues: List[dict],
        restaurants: List[dict],
    ) -> dict:
        """2026-06-05: 极速模式轻量 LLM 决策层，只在真实 POI 候选池里选索引和理由，兼顾速度与智能感。"""
        fallback = self._select_fast_candidates_by_rules(parsed_intent, scenario, venues, restaurants)
        if not venues and not restaurants:
            return fallback

        def compact(items: List[dict]) -> List[dict]:
            compacted = []
            for idx, item in enumerate(items[:8]):
                compacted.append({
                    "index": idx,
                    "name": item.get("name", ""),
                    "type": item.get("type", ""),
                    "address": item.get("address", ""),
                    "keyword": item.get("keyword", ""),
                })
            return compacted

        prompt = f"""
你是本地生活活动规划的轻量选择器。只能从候选 POI 里选择索引，不能编造地点。

用户需求：{request.get("message", "")}
本次显式活动硬需求：{parsed_intent.get("hard_activity_keywords", [])}
本次显式餐饮硬需求：{parsed_intent.get("hard_food_keywords", [])}
当前场景：{scenario.get("primary")}，语气：{scenario.get("tone", "")}
场景偏好：{scenario.get("prefer", [])}
历史记忆命中（仅弱提示，不能覆盖本次显式需求）：{memory_context.get("used_labels", [])}

玩乐/活动候选：
{json.dumps(compact(venues), ensure_ascii=False)}

餐厅候选：
{json.dumps(compact(restaurants), ensure_ascii=False)}

请输出 JSON：
{{
  "main_venue_index": 0,
  "restaurant_index": 0,
  "extra_venue_index": 1,
  "reasons": {{
    "play": "为什么主活动适合当前用户",
    "eat": "为什么餐厅适合当前用户",
    "extra": "为什么收尾点适合当前用户"
  }}
}}

要求：
- 索引必须来自候选列表范围。
- 如果用户是约会/女朋友/拍照，优先出片、氛围、转场少、适合聊天。
- 如果用户明确说电影，优先影院/影城。
- 如果用户明确说烧烤，餐厅必须优先选择烧烤候选。
- 本次显式需求优先级高于历史记忆和通用场景偏好。
- 理由要具体，不要写“不错”“环境好”这种空话。
"""
        try:
            response = self.planner_agent.run(prompt)
            parsed = _safe_parse_json(response) or {}
            if not isinstance(parsed, dict):
                return fallback
            parsed["main_venue_index"] = self._bounded_index(parsed.get("main_venue_index"), len(venues), fallback.get("main_venue_index", 0))
            parsed["restaurant_index"] = self._bounded_index(parsed.get("restaurant_index"), len(restaurants), fallback.get("restaurant_index", 0))
            parsed["extra_venue_index"] = self._bounded_index(parsed.get("extra_venue_index"), len(venues), fallback.get("extra_venue_index", 1))
            if not isinstance(parsed.get("reasons"), dict):
                parsed["reasons"] = fallback.get("reasons", {})
            parsed["source"] = "fast_llm"
            return parsed
        except Exception as exc:
            print(f"  [WARN] 极速模式轻量 LLM 选择失败，使用规则候选评分: {exc}")
            return fallback

    def _bounded_index(self, value: Any, length: int, fallback: int) -> int:
        """2026-06-05: 限制轻量 LLM 输出索引，避免越界选择候选池之外的地点。"""
        if length <= 0:
            return 0
        try:
            index = int(value)
        except Exception:
            index = int(fallback or 0)
        return max(0, min(index, length - 1))

    def _select_fast_candidates_by_rules(self, parsed_intent: dict, scenario: dict, venues: List[dict], restaurants: List[dict]) -> dict:
        """2026-06-05: 轻量 LLM 不可用时的规则评分兜底，保证极速模式仍能稳定返回。"""
        preferred = [str(item) for item in parsed_intent.get("preferred_activities", [])]
        scenario_prefer = [str(item) for item in scenario.get("prefer", [])]
        hard_activity_keywords = [str(item) for item in parsed_intent.get("hard_activity_keywords", []) if item]
        hard_food_keywords = [str(item) for item in parsed_intent.get("hard_food_keywords", []) if item]
        wants_movie = any("电影" in item or "影院" in item or "影城" in item for item in preferred)

        def score(item: dict, kind: str) -> int:
            text = f"{item.get('name', '')} {item.get('type', '')} {item.get('address', '')} {item.get('keyword', '')}"
            value = 0
            for pref in preferred + scenario_prefer:
                if pref and pref in text:
                    value += 6
            hard_keywords = hard_food_keywords if kind == "restaurant" else hard_activity_keywords
            for hard in hard_keywords:
                if hard and hard in text:
                    value += 30
            if wants_movie and any(word in text for word in ["影院", "影城", "电影", "IMAX"]):
                value += 20
            if kind == "restaurant" and any("烧烤" in item for item in hard_food_keywords) and "烧烤" in text:
                value += 30
            if scenario.get("primary") == "couple_date" and any(word in text for word in ["拍照", "网红", "夜景", "商场", "咖啡", "艺术", "影城", "影院"]):
                value += 8
            if kind == "restaurant" and any(word in text for word in ["餐厅", "西餐", "日料", "咖啡", "商场"]):
                value += 5
            if any(word in text for word in ["公司", "银行", "停车场", "厕所"]):
                value -= 10
            return value

        venue_ranked = sorted(enumerate(venues), key=lambda pair: score(pair[1], "venue"), reverse=True)
        restaurant_ranked = sorted(enumerate(restaurants), key=lambda pair: score(pair[1], "restaurant"), reverse=True)
        main_idx = venue_ranked[0][0] if venue_ranked else 0
        extra_idx = next((idx for idx, _ in venue_ranked if idx != main_idx), 1 if len(venues) > 1 else 0)
        restaurant_idx = restaurant_ranked[0][0] if restaurant_ranked else 0
        return {
            "source": "fast_rules",
            "main_venue_index": main_idx,
            "restaurant_index": restaurant_idx,
            "extra_venue_index": extra_idx,
            "reasons": {},
        }

    def _find_candidate_index_for_keyword(self, candidates: List[dict], keyword: str, exclude: Optional[set[int]] = None) -> Optional[int]:
        """2026-06-07: Pick a real POI that satisfies a specific hard requirement."""
        exclude = exclude or set()
        for idx, candidate in enumerate(candidates):
            if idx in exclude:
                continue
            if _candidate_matches_keyword(candidate, keyword):
                return idx
        for idx, candidate in enumerate(candidates):
            if idx in exclude:
                continue
            if keyword and keyword in str(candidate.get("keyword", "")):
                return idx
        return None

    def _enforce_fast_hard_trip_selection(self, selection: dict, parsed_intent: dict, venues: List[dict], restaurants: List[dict]) -> dict:
        """2026-06-07: Ensure fast mode covers ordered hard items instead of dropping KTV/mahjong/etc."""
        selection = dict(selection or {})
        trip_items = [
            item for item in parsed_intent.get("hard_trip_items", [])
            if isinstance(item, dict) and item.get("keyword") and item.get("kind") in ("venue", "restaurant")
        ]
        venue_items = [item for item in trip_items if item.get("kind") == "venue"]
        restaurant_items = [item for item in trip_items if item.get("kind") == "restaurant"]

        used_venues: set[int] = set()
        if venue_items:
            first_idx = self._find_candidate_index_for_keyword(venues, venue_items[0]["keyword"], used_venues)
            if first_idx is not None:
                selection["main_venue_index"] = first_idx
                used_venues.add(first_idx)
        if len(venue_items) >= 2:
            second_idx = self._find_candidate_index_for_keyword(venues, venue_items[1]["keyword"], used_venues)
            if second_idx is not None:
                selection["extra_venue_index"] = second_idx
                used_venues.add(second_idx)
        elif venue_items:
            current_main = int(selection.get("main_venue_index", 0) or 0)
            used_venues.add(current_main)
            existing_extra = int(selection.get("extra_venue_index", 1) or 1)
            if existing_extra == current_main:
                fallback_extra = next((idx for idx in range(len(venues)) if idx not in used_venues), current_main)
                selection["extra_venue_index"] = fallback_extra

        if restaurant_items:
            restaurant_idx = self._find_candidate_index_for_keyword(restaurants, restaurant_items[0]["keyword"])
            if restaurant_idx is not None:
                selection["restaurant_index"] = restaurant_idx

        selection["hard_trip_enforced"] = bool(trip_items)
        return selection

    def _fallback_candidate(self, city: str, name: str, category: str, home_location: Optional[dict], lng_delta: float, lat_delta: float) -> dict:
        """2026-06-05: 极速模式 POI 候选不足时的坐标兜底，仍围绕用户当前位置。"""
        return {
            "id": "",
            "name": name,
            "type": "兜底推荐",
            "address": f"{city}附近",
            "location": _offset_location(home_location, lng_delta, lat_delta),
            "keyword": name,
            "category": category,
        }

    def _create_candidate_shortage_plan(
        self,
        request: dict,
        parsed_intent: dict,
        scenario: dict,
        weather_response: str,
        venue_count: int,
        restaurant_count: int,
    ) -> dict:
        """2026-06-05: 真实 POI 候选不足时给出显式失败态，不再用虚构地点冒充可执行方案。"""
        city = request.get("city") or "当前位置"
        date_str = request.get("date", datetime.now().strftime("%Y-%m-%d"))
        start_time = request.get("start_time", "14:00")
        duration = int(request.get("duration_hours", 4) or 4)
        start_h = int(start_time.split(":", 1)[0])
        plan = {
            "plan_id": f"plan_shortage_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
            "city": city,
            "district": request.get("district", ""),
            "date": date_str,
            "group_type": parsed_intent.get("group_type", "friends"),
            "group_summary": self._build_group_summary(parsed_intent, scenario),
            "start_time": start_time,
            "end_time": f"{min(start_h + duration, 23):02d}:00",
            "timeline": [],
            "weather_summary": self._summarize_weather(weather_response),
            "budget": {"activities": 0, "dining": 0, "transportation": 0, "extras": 0, "total": 0},
            "executable_actions": [],
            "share_message": "",
            "overall_tips": "真实 POI 候选不足，建议换一个区域、放宽距离或切换深度思考模式重新规划。",
            "exception_strategies": self._build_exception_strategies("", parsed_intent),
            "parsed_intent": parsed_intent,
            "scenario": scenario,
            "poi_candidate_summary": {
                "venue_count": venue_count,
                "restaurant_count": restaurant_count,
                "location_locked": False,
                "low_candidate_quality": True,
            },
            "quality_report": {
                "passed": False,
                "score": 40,
                "error_count": 1,
                "warning_count": 0,
                "issues": [
                    {
                        "severity": "error",
                        "category": "poi_candidate",
                        "message": f"真实 POI 候选不足：场所 {venue_count} 个，餐厅 {restaurant_count} 个",
                        "repair_hint": "换区域、放宽距离或切换深度思考模式，但不要生成虚构地点。",
                    }
                ],
            },
        }
        return plan

    def _summarize_weather(self, weather_response: str) -> str:
        """2026-06-05: 极速模式轻量天气摘要，避免再调 LLM 生成天气文案。"""
        try:
            data = json.loads(weather_response) if weather_response else []
            if isinstance(data, list) and data:
                first = data[0]
                return f"{first.get('day_weather', '天气未知')}，{first.get('day_temp', '')}°C/{first.get('night_temp', '')}°C，出门前留意天气变化"
        except Exception:
            pass
        return "天气数据暂不完整，建议出发前再确认一次"

    def _build_group_summary(self, parsed_intent: dict, scenario: dict) -> str:
        """2026-06-05: 极速模式用规则生成群体摘要。"""
        group_size = parsed_intent.get("group_size", 2)
        primary = scenario.get("primary", "")
        if primary == "couple_date":
            return f"{group_size}人情侣约会"
        if primary in ("family_kid", "family_mixed"):
            return f"{group_size}人家庭出游"
        if primary == "family_elderly":
            return f"{group_size}人家庭长辈出行"
        if primary == "solo_healing":
            return "1人散心放松"
        if primary.startswith("friend"):
            return f"{group_size}人朋友聚会"
        return f"{group_size}人本地活动"

    def _fast_reason(self, candidate: dict, activity_type: str, parsed_intent: dict, scenario: dict) -> str:
        """2026-06-05: 极速模式确定性推荐理由，保证结果不是空泛地点描述。"""
        name = candidate.get("name", "这里")
        primary = scenario.get("primary", "")
        if activity_type == "eat":
            if primary in ("family_kid", "family_mixed"):
                return f"{name}转场方便，适合一家人坐下来休息，用餐安排更稳妥"
            if primary == "couple_date":
                return f"{name}适合两个人边吃边聊，能把约会节奏放慢一点"
            if primary == "friend_drink":
                return f"{name}适合朋友喝点东西聊聊天，后续转场也方便"
            if primary == "solo_healing":
                return f"{name}一个人用餐压力小，适合安静坐一会儿缓缓心情"
            return f"{name}距离上一站近，口味和转场都比较稳妥"
        if primary in ("family_kid", "family_mixed"):
            return f"{name}适合孩子活动放电，大人也能轻松陪伴，整体不太折腾"
        if primary == "couple_date":
            return f"{name}适合拍照和聊天，节奏轻松，能照顾两个人的约会体验"
        if primary == "solo_healing":
            return f"{name}节奏安静、不强社交，适合慢慢走走，把心情缓下来"
        if primary.startswith("friend"):
            return f"{name}适合朋友一起转转，互动感强，后面吃饭也方便"
        return f"{name}转场方便、活动强度适中，适合作为今天的主要安排"

    def _fast_tags(self, activity_type: str, parsed_intent: dict, scenario: dict, candidate: Optional[dict] = None) -> List[str]:
        """2026-06-05: 极速模式按场景生成标签，辅助前端展示和后续反馈记忆。"""
        tags = _derive_actual_poi_tags(candidate or {}, activity_type, [])
        if not tags and activity_type != "transport":
            tags = ["真实POI"]
        primary = scenario.get("primary", "")
        if primary in ("family_kid", "family_mixed"):
            tags.append("亲子友好")
        if primary == "couple_date":
            tags.extend(["约会", "出片"])
        if primary == "solo_healing":
            tags.extend(["安静", "慢节奏"])
        if primary.startswith("friend"):
            tags.append("朋友")
        return list(dict.fromkeys(tags))

    def _fast_overall_tips(self, scenario_primary: str, weather_summary: str) -> str:
        """2026-06-05: 极速模式整体提示模板，避免额外 LLM 文案耗时。"""
        if scenario_primary in ("family_kid", "family_mixed"):
            return f"建议带好水和纸巾，餐厅提前预约减少等待；{weather_summary}"
        if scenario_primary == "couple_date":
            return f"建议提前预约餐厅，拍照点可留一点弹性时间；{weather_summary}"
        if scenario_primary == "solo_healing":
            return f"路线不必赶，觉得累可以直接缩短最后一站；{weather_summary}"
        return f"建议提前预约餐厅，按现场排队情况微调最后一站；{weather_summary}"

    def _build_exception_strategies(self, weather_summary: str, parsed_intent: dict) -> List[dict]:
        """2026-06-05: 生成可展示的异常处理策略，覆盖无座、无票、时间冲突、天气不适合四类比赛要求场景。"""
        strategies = [
            {
                "type": "restaurant_no_seat",
                "title": "餐厅无座",
                "trigger": "预约失败、排队过久或当前不可订",
                "strategy": "自动改约附近同类型餐厅，并保留原用餐时间和人数",
                "fallback_action": "book_restaurant",
            },
            {
                "type": "ticket_sold_out",
                "title": "门票无票",
                "trigger": "购票失败、余票不足或预约名额已满",
                "strategy": "替换为附近免费/免预约活动，或改为现场购票/候补重试",
                "fallback_action": "book_activity",
            },
            {
                "type": "time_conflict",
                "title": "时间冲突/超时",
                "trigger": "总时长超出可用时间、交通过长或节点重叠",
                "strategy": "自动压缩最后一站，减少停留时间，必要时删除可选活动",
                "fallback_action": "compress_plan",
            },
            {
                "type": "weather_bad",
                "title": "天气不适合",
                "trigger": "下雨、高温、强风或户外体验明显下降",
                "strategy": "优先替换为室内商场、影院、展览、书店咖啡馆等备选",
                "fallback_action": "replace_indoor",
            },
        ]
        weather_text = weather_summary or ""
        if any(word in weather_text for word in ["雨", "雷", "高温", "强风", "暴晒", "紫外线强"]):
            strategies[3]["active"] = True
            strategies[3]["strategy"] = "本次天气可能影响户外体验，优先准备室内替代点"
        else:
            strategies[3]["active"] = False
        return strategies

    def _build_fast_search_keywords(self, parsed_intent: dict, category: str) -> List[str]:
        """2026-06-04: 快速模式复用场景识别结果生成少量高质量搜索词，控制工具调用数量。"""
        scenario = parsed_intent.get("scenario", {}) or {}
        primary = scenario.get("primary", "")
        group_type = parsed_intent.get("group_type", "family")
        preferred = parsed_intent.get("preferred_activities", [])
        dining_prefs = parsed_intent.get("dining_preferences", [])
        hard_activity_keywords = [str(item) for item in parsed_intent.get("hard_activity_keywords", []) if item]
        hard_food_keywords = [str(item) for item in parsed_intent.get("hard_food_keywords", []) if item]
        wants_movie = any("电影" in str(item) or "影院" in str(item) or "影城" in str(item) for item in preferred)

        if category == "restaurant":
            if hard_food_keywords:
                # 2026-06-05: 极速模式以用户本次明确餐饮需求为最高优先级，例如“烧烤”不能被约会记忆改成酒吧。
                return list(dict.fromkeys(hard_food_keywords))
            if primary == "solo_healing":
                base = ["一人食", "安静咖啡馆"]
            elif primary == "couple_date":
                base = ["适合约会餐厅", "商场餐厅"] if wants_movie else ["适合约会餐厅", "氛围感餐厅"]
            elif primary == "friend_drink":
                base = ["小酒馆", "烧烤夜宵"]
            elif primary == "friend_party":
                base = ["火锅", "聚会餐厅"]
            elif group_type == "family":
                base = ["亲子餐厅", "家庭餐厅"]
            else:
                base = ["餐厅", "咖啡馆"]
            for item in dining_prefs:
                if "减肥" in item or "低卡" in item or "健康" in item:
                    base.insert(0, "健康轻食")
                if "烧烤" in item:
                    base.insert(0, "烧烤")
                if "火锅" in item:
                    base.insert(0, "火锅")
            return list(dict.fromkeys(base))[:2]

        if hard_activity_keywords:
            # 2026-06-05: 极速模式以用户本次明确活动需求为最高优先级，例如“看电影”必须优先搜影院。
            base = hard_activity_keywords
        elif primary == "solo_healing":
            base = ["安静公园", "书店咖啡馆", "滨江公园"]
        elif primary == "couple_date":
            base = ["电影院", "影城", "商场"] if wants_movie else ["网红打卡", "夜景", "展览"]
        elif primary == "friend_drink":
            base = ["小酒馆", "夜市", "清吧"]
        elif primary == "solo_fun":
            base = ["展览", "电影院", "电玩"]
        elif group_type == "family":
            base = ["亲子乐园", "儿童公园", "公园"]
        else:
            base = ["展览", "公园", "商圈"]
        for item in preferred:
            if item and item not in base:
                base.append(item)
        # 2026-06-05: 极速模式控制关键词数量，避免高德 REST 短时间多次请求触发 CUQPS 限流。
        unique = list(dict.fromkeys(base))
        return unique if hard_activity_keywords else unique[:2]

    def _dedupe_candidates(self, candidates: List[dict]) -> List[dict]:
        """2026-06-04: 快速候选池按 POI id/name 去重，避免 Planner 看到重复商户。"""
        seen = set()
        deduped: List[dict] = []
        for candidate in candidates:
            key = candidate.get("id") or f"{candidate.get('name')}::{candidate.get('address')}"
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    def _format_poi_candidates_for_prompt(self, candidates: List[dict], title: str) -> str:
        """2026-06-04: 将结构化 POI 候选池压缩成 Planner 易遵守的 JSON 文本。"""
        compact = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "address": item.get("address"),
                "location": item.get("location"),
                "keyword": item.get("keyword"),
                "category": item.get("category"),
            }
            for item in candidates
        ]
        return f"【{title}｜快速模式结构化候选池】\n{json.dumps(compact, ensure_ascii=False)}"

    def _lock_plan_locations_to_candidates(self, plan: dict, poi_candidates: dict) -> None:
        """2026-06-04: 快速模式回填真实 POI 地址和坐标，防止地图点位被模型自由生成带偏。"""
        all_candidates = [
            *poi_candidates.get("venues", []),
            *poi_candidates.get("restaurants", []),
        ]
        if not all_candidates:
            return

        def normalize(value: str) -> str:
            return re.sub(r"[\s·・\-()（）【】\[\]]", "", value or "").lower()

        for item in plan.get("timeline", []):
            if not isinstance(item, dict) or item.get("activity_type") == "transport":
                continue
            title_key = normalize(item.get("title", ""))
            venue_key = normalize(item.get("venue_name", ""))
            best = None
            for candidate in all_candidates:
                candidate_name = normalize(candidate.get("name", ""))
                if not candidate_name:
                    continue
                if candidate_name in title_key or candidate_name in venue_key or title_key in candidate_name or venue_key in candidate_name:
                    best = candidate
                    break
            if not best:
                desired = "restaurant" if item.get("activity_type") == "eat" else "venue"
                best = next((c for c in all_candidates if c.get("category") == desired), None)
            if not best:
                continue
            _apply_candidate_to_plan_item(item, best)

    def _lock_agent_plan_to_real_pois(self, plan: dict, request: dict, parsed_intent: dict) -> None:
        """2026-06-05: 深度 Agent 输出后做真实 POI 落地，保留多智能体思考但禁止泛化地点直接进入结果页。"""
        city = request.get("city", "")
        district = request.get("district", "")
        home_location = request.get("home_location")
        avoid_places = request.get("avoid_places", []) or []
        rest_location = None
        if home_location:
            try:
                loc = _location_to_dict(home_location)
                rest_location = Location(longitude=loc["longitude"], latitude=loc["latitude"])
            except Exception:
                rest_location = None

        lock_report = {"locked": 0, "failed": []}
        self._annotate_timeline_hard_expectations(plan, parsed_intent)

        for item in plan.get("timeline", []):
            if not isinstance(item, dict) or item.get("activity_type") == "transport":
                continue
            candidate = self._resolve_real_poi_for_plan_item(
                item=item,
                city=city,
                district=district,
                parsed_intent=parsed_intent,
                rest_location=rest_location,
                avoid_places=avoid_places,
            )
            if not candidate:
                item["poi_lock_failed"] = True
                lock_report["failed"].append(item.get("title") or item.get("venue_name") or "未命名节点")
                continue

            _apply_candidate_to_plan_item(item, candidate)
            lock_report["locked"] += 1

        plan["poi_lock_report"] = lock_report

    def _annotate_timeline_hard_expectations(self, plan: dict, parsed_intent: dict) -> None:
        """2026-06-07: Map ordered hard requirements onto non-transport timeline nodes before POI locking."""
        trip_items = [
            item for item in parsed_intent.get("hard_trip_items", [])
            if isinstance(item, dict) and item.get("keyword") and item.get("kind") in ("venue", "restaurant")
        ]
        if not trip_items or not isinstance(plan.get("timeline"), list):
            return

        next_index = 0
        for item in plan.get("timeline", []):
            if not isinstance(item, dict) or item.get("activity_type") == "transport":
                continue
            if next_index >= len(trip_items):
                break
            expected = trip_items[next_index]
            expected_kind = "restaurant" if expected.get("kind") == "restaurant" else "venue"
            actual_kind = "restaurant" if item.get("activity_type") == "eat" else "venue"
            if actual_kind != expected_kind:
                continue
            item["expected_keyword"] = str(expected.get("keyword") or "")
            item["hard_requirement"] = str(expected.get("keyword") or "")
            next_index += 1

    def _trim_extra_nodes_after_hard_trip(self, plan: dict, parsed_intent: dict) -> None:
        """2026-06-07: Once ordered hard itinerary is covered, remove weak filler nodes after it."""
        hard_trip_items = [
            item for item in parsed_intent.get("hard_trip_items", [])
            if isinstance(item, dict) and item.get("keyword")
        ]
        if len(hard_trip_items) < 2 or not isinstance(plan.get("timeline"), list):
            return

        timeline = plan.get("timeline", [])
        hard_index = 0
        last_hard_node_idx: Optional[int] = None
        for idx, item in enumerate(timeline):
            if not isinstance(item, dict) or item.get("activity_type") == "transport":
                continue
            if hard_index >= len(hard_trip_items):
                continue
            expected = hard_trip_items[hard_index]
            expected_kind = "restaurant" if expected.get("kind") == "restaurant" else "venue"
            actual_kind = "restaurant" if item.get("activity_type") == "eat" else "venue"
            if actual_kind == expected_kind and _plan_item_matches_keyword(item, str(expected.get("keyword"))):
                last_hard_node_idx = idx
                hard_index += 1

        if hard_index < len(hard_trip_items) or last_hard_node_idx is None:
            return

        trimmed: List[dict] = []
        for idx, item in enumerate(timeline):
            if idx <= last_hard_node_idx:
                trimmed.append(item)
                continue
            # Drop transport and non-transport filler after all explicit hard items are completed.

        if len(trimmed) != len(timeline):
            for order, item in enumerate(trimmed, start=1):
                if isinstance(item, dict):
                    item["order"] = order
            plan["timeline"] = trimmed
            if trimmed and isinstance(trimmed[-1], dict) and trimmed[-1].get("end_time"):
                plan["end_time"] = trimmed[-1]["end_time"]
            if isinstance(plan.get("budget"), dict):
                total = sum(int(item.get("estimated_cost") or 0) for item in trimmed if isinstance(item, dict))
                plan["budget"]["total"] = total

    def _resolve_real_poi_for_plan_item(
        self,
        item: dict,
        city: str,
        district: str,
        parsed_intent: dict,
        rest_location: Optional[Location],
        avoid_places: Optional[List[str]] = None,
    ) -> Optional[dict]:
        """2026-06-05: 为单个深度模式节点查找真实高德 POI，优先本次硬需求，其次原地点名。"""
        current_name = item.get("venue_name") or item.get("title") or ""
        current_addr = item.get("venue_address") or ""
        if (
            item.get("poi_id")
            and current_name
            and current_addr
            and _has_valid_location(item.get("venue_location"))
            and not _is_generic_place_name(current_name)
            and not _is_avoided_place(current_name, avoid_places)
        ):
            current_candidate = {
                "id": item.get("poi_id", ""),
                "name": current_name,
                "address": current_addr,
                "location": _location_to_dict(item.get("venue_location")),
                "category": "restaurant" if item.get("activity_type") == "eat" else "venue",
                "type": item.get("venue_type") or item.get("poi_type") or "",
                "keyword": item.get("poi_keyword") or item.get("source_keyword") or "",
            }
            expected_keyword = _expected_hard_keyword_for_item(item, parsed_intent)
            if not expected_keyword or _candidate_matches_keyword(current_candidate, expected_keyword):
                return current_candidate

        keywords = self._build_agent_poi_lock_keywords(item, parsed_intent)
        amap_service = get_amap_service()
        category = "restaurant" if item.get("activity_type") == "eat" else "venue"
        for keyword in keywords:
            full_keyword = f"{district}{keyword}".strip() if district and district not in keyword else keyword
            pois = amap_service.search_poi_rest(
                full_keyword,
                city,
                citylimit=bool(city),
                offset=5,
                location=rest_location,
                radius=5000,
            )
            candidates = [
                _poi_to_candidate(poi, full_keyword, category)
                for poi in pois
            ]
            candidates = [
                candidate for candidate in candidates
                if candidate.get("name")
                and candidate.get("address")
                and _has_valid_location(candidate.get("location"))
                and not _is_avoided_place(candidate.get("name", ""), avoid_places)
            ]
            expected_keyword = _expected_hard_keyword_for_item(item, parsed_intent)
            if expected_keyword:
                exact_candidates = [
                    candidate for candidate in candidates
                    if _candidate_matches_keyword(candidate, expected_keyword)
                ]
                if not exact_candidates:
                    continue
                candidates = exact_candidates
            if candidates:
                return self._rank_agent_poi_candidates(item, candidates, parsed_intent)
        return None

    def _build_agent_poi_lock_keywords(self, item: dict, parsed_intent: dict) -> List[str]:
        """2026-06-05: 深度模式落地真实 POI 的搜索词，显式硬需求优先于 Planner 泛化标题。"""
        activity_type = item.get("activity_type")
        hard_activity = [str(x) for x in parsed_intent.get("hard_activity_keywords", []) if x]
        hard_food = [str(x) for x in parsed_intent.get("hard_food_keywords", []) if x]
        expected_keyword = _expected_hard_keyword_for_item(item, parsed_intent)
        raw_names = [
            str(item.get("venue_name", "")),
            str(item.get("title", "")),
        ]
        keywords: List[str] = []
        if activity_type == "eat":
            if expected_keyword:
                keywords.append(expected_keyword)
            else:
                keywords.extend(hard_food)
            keywords.extend(raw_names)
            keywords.append("餐厅")
        else:
            if expected_keyword:
                keywords.append(expected_keyword)
            else:
                keywords.extend(hard_activity)
            keywords.extend(raw_names)
            keyword_context = ([expected_keyword] if expected_keyword else hard_activity) + raw_names
            if any("电影" in x or "影院" in x or "影城" in x for x in keyword_context):
                keywords.extend(["电影院", "影城"])
            if any("KTV" in x or "唱歌" in x for x in keyword_context):
                keywords.extend(["KTV", "量贩KTV"])
            if any("麻将" in x or "棋牌" in x for x in keyword_context):
                # 2026-06-06: 深度模式真实 POI 落地时保留“打麻将/棋牌”硬需求，避免被泛化成普通酒吧或商圈。
                keywords.extend(["棋牌室", "麻将馆"])
            keywords.append("商场" if activity_type == "extra" else "景点")

        clean: List[str] = []
        for keyword in keywords:
            keyword = re.sub(r"(游玩|用餐|晚餐|午餐|收尾|前往|看一场|看场|一起|待确认|具体)", "", keyword).strip()
            if not keyword or keyword in clean:
                continue
            clean.append(keyword)
        return clean[:5]

    def _rank_agent_poi_candidates(self, item: dict, candidates: List[dict], parsed_intent: dict) -> dict:
        """2026-06-05: 对真实 POI 候选打分，确保电影/烧烤等硬需求优先命中。"""
        hard_activity = [str(x) for x in parsed_intent.get("hard_activity_keywords", []) if x]
        hard_food = [str(x) for x in parsed_intent.get("hard_food_keywords", []) if x]
        expected_keyword = _expected_hard_keyword_for_item(item, parsed_intent)
        target_keywords = [expected_keyword] if expected_keyword else (hard_food if item.get("activity_type") == "eat" else hard_activity)

        def score(candidate: dict) -> int:
            text = _candidate_actual_text(candidate)
            value = 0
            for keyword in target_keywords:
                if keyword and _candidate_matches_keyword(candidate, keyword):
                    value += 80
            if expected_keyword and not _candidate_matches_keyword(candidate, expected_keyword):
                value -= 100
            if item.get("activity_type") == "eat" and any(word in text for word in ["餐厅", "美食", "烧烤", "火锅", "料理", "咖啡"]):
                value += 8
            if item.get("activity_type") != "eat" and any(word in text for word in ["影院", "影城", "电影", "公园", "商场", "展览", "景区", "棋牌", "麻将", "KTV", "量贩"]):
                value += 8
            if any(word in text for word in ["停车场", "卫生间", "公司", "银行", "住宅"]):
                value -= 20
            return value

        return sorted(candidates, key=score, reverse=True)[0]

    def _validate_plan_rules(
        self,
        plan: dict,
        request: dict,
        parsed_intent: dict,
    ) -> dict:
        """第一层规则质检：覆盖结构、时间、地理、组成、执行闭环、场景、预算和安全文案。"""
        issues: List[dict] = []

        def add_issue(severity: str, category: str, message: str, repair_hint: str = ""):
            issues.append({
                "severity": severity,
                "category": category,
                "message": message,
                "repair_hint": repair_hint,
            })

        # 2026-06-06: Planner JSON 解析失败时生成的备用方案不能被误判为满分正常方案。
        if plan.get("is_fallback"):
            add_issue(
                "warning",
                "fallback",
                f"当前方案来自备用流程：{plan.get('fallback_reason', 'unknown')}",
                "建议重新生成或检查 Planner JSON 输出格式",
            )

        def parse_minutes(value: str) -> Optional[int]:
            if not value or ":" not in value:
                return None
            try:
                hour, minute = value.split(":", 1)
                return int(hour) * 60 + int(minute)
            except Exception:
                return None

        required_fields = [
            "city", "date", "start_time", "end_time", "timeline",
            "budget", "executable_actions", "share_message", "overall_tips"
        ]
        for field in required_fields:
            if field not in plan:
                add_issue("error", "structure", f"缺少字段：{field}", "补齐活动方案基础字段")

        timeline = plan.get("timeline", [])
        if not isinstance(timeline, list) or not timeline:
            add_issue("error", "structure", "timeline 为空或格式不正确", "至少生成交通、活动、餐饮和额外活动节点")
            timeline = []

        action_types = {
            item.get("action_type")
            for item in plan.get("executable_actions", [])
            if isinstance(item, dict)
        }
        # 2026-06-06: 方案全文需要供硬需求、场景安全和文案安全等规则共用，必须在所有检查前准备好。
        plan_text = json.dumps(plan, ensure_ascii=False)
        activity_types = [item.get("activity_type") for item in timeline if isinstance(item, dict)]

        for idx, item in enumerate(timeline):
            if not isinstance(item, dict):
                add_issue("error", "structure", f"第 {idx + 1} 个时间轴节点不是对象", "修复 timeline 节点格式")
                continue
            for field in ["title", "start_time", "end_time", "activity_type"]:
                if not item.get(field):
                    add_issue("error", "structure", f"第 {idx + 1} 个节点缺少 {field}", "补齐节点标题、时间和类型")
            if item.get("activity_type") != "transport" and not item.get("venue_name"):
                add_issue("warning", "structure", f"第 {idx + 1} 个非交通节点缺少 venue_name", "补充真实场所名称")
            if item.get("activity_type") != "transport":
                name = item.get("venue_name", "")
                if item.get("poi_lock_failed"):
                    add_issue("error", "geo", f"{item.get('title', '某节点')} 未能绑定真实高德 POI", "重新搜索真实 POI 或换成有坐标的候选地点")
                if _is_generic_place_name(name):
                    add_issue("error", "geo", f"{item.get('title', '某节点')} 仍是泛化地点名", "替换为具体商户/场馆名称")
                if not _has_valid_location(item.get("venue_location")):
                    add_issue("error", "geo", f"{item.get('title', '某节点')} 缺少有效坐标", "从高德 POI 回填真实经纬度")
            if item.get("activity_type") == "eat":
                if not item.get("venue_address"):
                    add_issue("warning", "structure", "餐饮节点缺少餐厅地址", "补充餐厅真实地址")
                if not item.get("party_size") and not item.get("queue_status"):
                    add_issue("warning", "structure", "餐饮节点缺少用餐人数或排队信息", "补充 party_size 或 queue_status")

        start = parse_minutes(plan.get("start_time", ""))
        end = parse_minutes(plan.get("end_time", ""))
        if start is not None and end is not None:
            duration = end - start
            if duration < 0:
                add_issue("error", "time", "方案结束时间早于开始时间", "修正 start_time/end_time")
            elif duration < 210 or duration > 390:
                add_issue("warning", "time", "总时长不在 4-6 小时附近", "将路线控制在约 4-6 小时")

        previous_end: Optional[int] = None
        for item in timeline:
            item_start = parse_minutes(item.get("start_time", ""))
            item_end = parse_minutes(item.get("end_time", ""))
            if item_start is None or item_end is None:
                continue
            if item_end <= item_start:
                add_issue("error", "time", f"{item.get('title', '某节点')} 时间倒流或时长为 0", "修正该节点起止时间")
            if previous_end is not None:
                gap = item_start - previous_end
                if gap < 0:
                    add_issue("error", "time", f"{item.get('title', '某节点')} 与上一节点时间重叠", "调整时间轴顺序")
                elif gap > 45:
                    add_issue("warning", "time", "时间轴存在超过 45 分钟空白", "补充交通/休息说明，情绪疗愈场景可保留适度留白")
            item_duration = item_end - item_start
            if item.get("activity_type") == "eat" and (item_duration < 35 or item_duration > 130):
                add_issue("warning", "time", "餐饮节点时长不够自然", "餐饮建议控制在 40-120 分钟")
            if item.get("activity_type") == "play" and item_duration > 180:
                add_issue("warning", "time", "单个玩乐节点过长", "拆分为休息或额外活动")
            previous_end = item_end

        request_city = request.get("city", "")
        if request_city and plan.get("city") and request_city not in plan.get("city", "") and plan.get("city", "") not in request_city:
            add_issue("error", "geo", "方案城市与用户输入城市不一致", "统一城市和搜索结果")
        for item in timeline:
            address_blob = f"{item.get('venue_address', '')}{item.get('title', '')}"
            if request_city and any(city in address_blob for city in ["北京", "上海", "广州", "深圳", "南京", "杭州", "成都"]):
                if request_city not in address_blob and item.get("activity_type") != "transport":
                    add_issue("warning", "geo", f"{item.get('title', '某地点')} 地址可能不在用户城市", "替换为同城地点")

        if "play" not in activity_types:
            add_issue("error", "composition", "方案缺少玩乐/活动节点", "至少加入一个真实活动地点")
        if "eat" not in activity_types:
            add_issue("warning", "composition", "方案缺少餐饮/休息节点", "加入餐饮或咖啡馆休息点")
        if "transport" not in activity_types:
            add_issue("warning", "composition", "方案缺少交通安排", "补充交通节点或步行说明")
        if len([t for t in activity_types if t != "transport"]) < 2:
            add_issue("warning", "composition", "非交通地点过少，像单点推荐", "补充额外活动或饭后安排")

        # 2026-06-06: 显式硬需求是最高优先级；如果用户说了麻将/电影/烧烤等，最终方案必须覆盖，不能被场景记忆或通用偏好冲掉。
        hard_trip_items = [
            item for item in parsed_intent.get("hard_trip_items", [])
            if isinstance(item, dict) and item.get("keyword")
        ]
        missing_hard_requirements: List[str] = []
        if hard_trip_items:
            hard_index = 0
            for item in timeline:
                if not isinstance(item, dict) or item.get("activity_type") == "transport":
                    continue
                if hard_index >= len(hard_trip_items):
                    break
                expected = hard_trip_items[hard_index]
                expected_kind = "restaurant" if expected.get("kind") == "restaurant" else "venue"
                actual_kind = "restaurant" if item.get("activity_type") == "eat" else "venue"
                if actual_kind == expected_kind and _plan_item_matches_keyword(item, str(expected.get("keyword"))):
                    hard_index += 1
            missing_hard_requirements = [
                str(item.get("keyword"))
                for item in hard_trip_items[hard_index:]
                if item.get("keyword")
            ]
        else:
            hard_requirements = [
                str(item)
                for item in (
                    parsed_intent.get("hard_activity_keywords", [])
                    + parsed_intent.get("hard_food_keywords", [])
                )
                if item
            ]
            missing_hard_requirements = [
                item for item in dict.fromkeys(hard_requirements)
                if not any(
                    isinstance(timeline_item, dict)
                    and timeline_item.get("activity_type") != "transport"
                    and _plan_item_matches_keyword(timeline_item, item)
                    for timeline_item in timeline
                )
            ]
        if missing_hard_requirements:
            add_issue(
                "error",
                "hard_requirement",
                f"方案遗漏用户本次明确需求：{', '.join(missing_hard_requirements)}",
                "重新规划时必须把这些需求作为时间轴节点或餐饮节点落地",
            )

        if "eat" in activity_types and "book_restaurant" not in action_types:
            add_issue("error", "execution", "有餐饮节点但缺少餐厅预约动作", "添加 book_restaurant executable_action")
        ticket_like = any(
            item.get("booking_available") and item.get("booking_type") in ("activity_ticket", "ticket")
            for item in timeline
        )
        if ticket_like and "book_activity" not in action_types:
            add_issue("warning", "execution", "有可购票活动但缺少购票动作", "添加 book_activity executable_action")
        for action in plan.get("executable_actions", []):
            if not action.get("action_type") or not action.get("description"):
                add_issue("error", "execution", "存在缺少类型或描述的可执行动作", "补齐 action_type 和 description")

        mood_text = " ".join([
            str(parsed_intent.get("mood", "")),
            *[str(x) for x in parsed_intent.get("constraints", [])],
            *[str(x) for x in parsed_intent.get("special_requests", [])],
        ])
        if any(word in mood_text for word in ["情绪疗愈", "失恋", "散心", "心情不好", "安静"]):
            forbidden = ["情侣", "约会", "KTV", "密室", "剧本杀", "生日蛋糕", "鲜花", "轰趴", "酒吧"]
            hit = [word for word in forbidden if word in plan_text]
            if hit:
                add_issue("error", "scenario_match", f"情绪疗愈场景出现不合适元素：{', '.join(hit)}", "替换为安静公园、书店、咖啡馆或水边散步")
            if len(timeline) > 6:
                add_issue("warning", "scenario_match", "情绪疗愈路线排得过满", "减少节点，保留散步和独处留白")
        group_details = parsed_intent.get("group_details", {})
        if group_details.get("has_children"):
            forbidden = ["酒吧", "密室", "恐怖", "成人", "深夜"]
            hit = [word for word in forbidden if word in plan_text]
            if hit:
                add_issue("error", "scenario_match", f"亲子场景出现不合适元素：{', '.join(hit)}", "替换为亲子友好、可休息的地点")
        dietary = " ".join([str(x) for x in group_details.get("dietary_restrictions", [])])
        if any(word in dietary for word in ["减肥", "减脂", "控体重"]):
            hit = [word for word in ["烧烤", "自助", "重油", "炸鸡", "火锅"] if word in plan_text]
            if hit:
                add_issue("warning", "scenario_match", f"健康饮食约束下出现偏重口餐饮：{', '.join(hit)}", "优先轻食、粤菜、日料或健康餐")

        budget = plan.get("budget", {})
        if isinstance(budget, dict):
            parts = [
                budget.get("activities", 0) or 0,
                budget.get("dining", 0) or 0,
                budget.get("transportation", 0) or 0,
                budget.get("extras", 0) or 0,
            ]
            total = budget.get("total", 0) or 0
            if any(v < 0 for v in parts + [total]):
                add_issue("error", "budget", "预算中出现负数", "修正预算金额")
            if total and abs(sum(parts) - total) > max(30, total * 0.2):
                add_issue("warning", "budget", "预算总额与分项合计差异较大", "同步预算分项和总额")
            budget_limit = request.get("budget_limit")
            if budget_limit and total > budget_limit * 1.15:
                add_issue("warning", "budget", "方案预算明显超过用户上限", "降低餐饮或活动费用")

        if any(word in mood_text for word in ["情绪疗愈", "失恋", "散心", "心情不好"]):
            unsafe_share = [word for word in ["失恋", "分手", "难过", "emo"] if word in str(plan.get("share_message", ""))]
            if unsafe_share:
                add_issue("warning", "copy_safety", "分享文案可能暴露用户敏感情绪", "改成温和中性的自我提醒或简短安排")
        if "保证" in plan_text and any(word in mood_text for word in ["情绪疗愈", "失恋", "心情不好"]):
            add_issue("warning", "copy_safety", "情绪场景不应承诺保证疗愈效果", "使用温和陪伴式措辞")

        error_count = sum(1 for item in issues if item["severity"] == "error")
        warning_count = sum(1 for item in issues if item["severity"] == "warning")
        score = max(0, 100 - error_count * 18 - warning_count * 6)
        return {
            "passed": error_count == 0,
            "score": score,
            "error_count": error_count,
            "warning_count": warning_count,
            "issues": issues,
        }

    def _enrich_plan_reasons(self, plan: dict, parsed_intent: dict, user_message: str) -> None:
        """2026-06-04: 兜底补强推荐理由，避免结果只写空泛地点描述。"""
        group_details = parsed_intent.get("group_details", {}) or {}
        group_type = parsed_intent.get("group_type", "")
        dietary = " ".join([str(x) for x in group_details.get("dietary_restrictions", [])])
        mood_text = " ".join([
            user_message,
            str(parsed_intent.get("mood", "")),
            *[str(x) for x in parsed_intent.get("constraints", [])],
            *[str(x) for x in parsed_intent.get("special_requests", [])],
        ])

        is_family = group_type == "family" or any(word in user_message for word in ["老婆", "孩子", "一家", "亲子", "爸妈", "父母"])
        has_child = group_details.get("has_children") or any(word in user_message for word in ["孩子", "亲子", "娃"])
        wants_relax = any(word in mood_text for word in ["放松", "散心", "休闲", "不折腾", "轻松"])
        is_healing = any(word in mood_text for word in ["情绪疗愈", "失恋", "分手", "心情不好", "难过", "emo"])
        diet_health = any(word in dietary or word in user_message for word in ["减肥", "减脂", "控体重", "健康", "低卡"])

        vague_words = ["户外活动", "附近餐厅", "环境优美", "用餐", "休闲游玩", "附近散步", "适合群体需求", "餐厅用餐"]

        def is_vague(text: str) -> bool:
            if not text or len(text.strip()) < 12:
                return True
            return any(word in text for word in vague_words)

        for item in plan.get("timeline", []):
            activity_type = item.get("activity_type")
            if activity_type == "transport":
                continue
            current = item.get("description", "")
            if not is_vague(current):
                continue

            venue_name = item.get("venue_name") or item.get("title", "这里")
            if activity_type == "play":
                if is_healing:
                    reason = f"{venue_name}节奏安静、不强社交，适合一个人慢慢走走，把心情缓下来"
                elif has_child:
                    reason = f"{venue_name}适合孩子跑跳放电，父母也能一起参与，轻松增进亲子互动"
                elif is_family:
                    reason = f"{venue_name}节奏轻松不折腾，适合一家人边逛边聊，放松半天刚好"
                elif wants_relax:
                    reason = f"{venue_name}离得近、节奏慢，适合随便转转，不需要赶行程"
                else:
                    reason = f"{venue_name}转场方便，活动强度适中，适合作为今天的主要玩乐点"
            elif activity_type == "eat":
                if diet_health:
                    reason = f"{venue_name}距离上一站近，适合家庭落座休息，也方便选择清淡低负担菜品"
                elif has_child:
                    reason = f"{venue_name}离上一站近，亲子友好，孩子休息吃饭都方便，少折腾"
                elif is_healing:
                    reason = f"{venue_name}一人用餐压力小，环境相对安静，适合坐下来慢慢吃点东西"
                else:
                    reason = f"{venue_name}转场方便，适合边吃边聊，招牌菜口味稳妥不容易踩雷"
            else:
                if is_healing:
                    reason = f"{venue_name}适合饭后慢慢散步，留一点独处时间，不把行程排太满"
                elif is_family:
                    reason = f"{venue_name}适合饭后轻松走走，让孩子消食，也给一家人留点聊天时间"
                else:
                    reason = f"{venue_name}离前一站近，适合收尾放松，避免来回折返"

            item["description"] = reason[:80]

    # ------------------------------------------------------------------
    # 核心方法：执行方案（预约/下单）
    # ------------------------------------------------------------------

    def execute_actions(self, plan: dict, action_ids: Optional[List[str]] = None) -> dict:
        """
        执行方案中的预约/下单动作（Mock）。

        Args:
            plan: 完整的活动方案字典
            action_ids: 要执行的 action_id 列表；为 None 则执行全部

        Returns:
            执行结果字典
        """
        from ..services.mock_service import get_mock_service
        mock_svc = get_mock_service()

        all_actions = plan.get("executable_actions", [])
        if action_ids is not None:
            actions_to_run = [a for a in all_actions if a.get("action_id") in action_ids]
        else:
            actions_to_run = all_actions

        results: List[dict] = []
        all_success = True

        for action in actions_to_run:
            action_type = action.get("action_type", "")
            params = action.get("params", {})
            action_id = action.get("action_id", "unknown")
            description = action.get("description", "")
            # 2026-06-04: 记录每个 Mock 订单动作的状态流转时间
            started_at = datetime.now().isoformat(timespec="seconds")

            print(f"  [EXEC] 执行动作 [{action_id}]: {description}")  # 2026-06-03 修复：emoji 编码

            try:
                if action_type == "book_restaurant":
                    result = mock_svc.book_restaurant(
                        restaurant_name=params.get("restaurant_name", ""),
                        city=plan.get("city", ""),
                        party_size=params.get("party_size", 2),
                        time=params.get("time", "17:00"),
                        contact_name=params.get("contact_name", "用户"),
                        contact_phone=params.get("contact_phone", "13800138000"),
                    )
                elif action_type == "book_activity":
                    result = mock_svc.book_activity_tickets(
                        venue_name=params.get("venue_name", ""),
                        city=plan.get("city", ""),
                        ticket_count=params.get("ticket_count", 1),
                        time=params.get("time", "14:00"),
                    )
                elif action_type == "order_delivery":
                    result = mock_svc.order_delivery(
                        item_type=params.get("item_type", "cake"),
                        item_name=params.get("item_name", "蛋糕"),
                        delivery_address=params.get("delivery_address", ""),
                        delivery_time=params.get("delivery_time", "17:30"),
                    )
                elif action_type == "check_queue":
                    result = mock_svc.check_queue_status(
                        restaurant_name=params.get("restaurant_name", ""),
                        city=plan.get("city", ""),
                    )
                else:
                    result = {
                        "success": False,
                        "message": f"未知动作类型: {action_type}"
                    }

                completed_at = datetime.now().isoformat(timespec="seconds")
                success = result.get("success", False)
                status = "success" if success else "failed"
                status_text = "已完成" if success else "执行失败"
                fallback = self._build_fallback_action(action, plan, result) if not success else None

                results.append({
                    "action_id": action_id,
                    "action_type": action_type,
                    "description": description,
                    "status": status,
                    "status_text": status_text,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "timeline": [
                        {
                            "status": "pending",
                            "text": "待确认",
                            "time": started_at,
                            "done": True,
                        },
                        {
                            "status": "processing",
                            "text": "执行中",
                            "time": started_at,
                            "done": True,
                        },
                        {
                            "status": status,
                            "text": status_text,
                            "time": completed_at,
                            "done": True,
                        },
                    ],
                    "retryable": not success,
                    "fallback_action": fallback.get("action") if fallback else None,
                    "fallback_reason": fallback.get("reason") if fallback else None,
                    **result
                })

                if not success:
                    all_success = False

            except Exception as e:
                all_success = False
                completed_at = datetime.now().isoformat(timespec="seconds")
                fallback = self._build_fallback_action(action, plan, {"message": str(e)})
                results.append({
                    "action_id": action_id,
                    "action_type": action_type,
                    "description": description,
                    "status": "failed",
                    "status_text": "执行异常",
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "timeline": [
                        {
                            "status": "pending",
                            "text": "待确认",
                            "time": started_at,
                            "done": True,
                        },
                        {
                            "status": "processing",
                            "text": "执行中",
                            "time": started_at,
                            "done": True,
                        },
                        {
                            "status": "failed",
                            "text": "执行异常",
                            "time": completed_at,
                            "done": True,
                        },
                    ],
                    "retryable": True,
                    "fallback_action": fallback.get("action") if fallback else None,
                    "fallback_reason": fallback.get("reason") if fallback else None,
                    "success": False,
                    "message": f"执行异常: {str(e)}"
                })

        summary_parts = []
        for r in results:
            status = "[OK]" if r.get("success") else "[ERR]"
            summary_parts.append(f"{status} {r.get('description', '')}")

        return {
            "plan_id": plan.get("plan_id", ""),
            "all_success": all_success,
            "results": results,
            "summary": "\n".join(summary_parts)
        }

    def _build_fallback_action(self, action: dict, plan: dict, result: dict) -> Optional[dict]:
        """2026-06-04: 失败后生成可重试/备选动作，让执行闭环不止停在失败。"""
        action_type = action.get("action_type", "")
        params = dict(action.get("params", {}) or {})
        city = plan.get("city", "")
        message = result.get("message", "")
        original_description = re.sub(r"^(重试)+", "", str(action.get("description", "该动作"))).strip() or "该动作"

        if action_type == "book_restaurant":
            original_name = params.get("restaurant_name", "原餐厅")
            party_size = params.get("party_size", 2)
            time = params.get("time", "17:00")
            fallback_name = self._pick_fallback_restaurant_name(plan, original_name)
            fallback_action = {
                "action_id": f"{action.get('action_id', 'act')}_fallback",
                "action_type": "book_restaurant",
                "description": f"改约{fallback_name} {party_size}人桌 {time}",
                "params": {
                    **params,
                    "restaurant_name": fallback_name,
                    "party_size": party_size,
                    "time": time,
                },
                "is_optional": False,
                "estimated_cost": action.get("estimated_cost", 0),
            }
            return {
                "action": fallback_action,
                "reason": f"{original_name}当前不可订或无位，已准备同城更稳妥的备选餐厅；{message or '可直接改约。'}",
            }

        if action_type == "book_activity":
            venue_name = params.get("venue_name") or action.get("params", {}).get("venue_name") or "原活动"
            ticket_count = params.get("ticket_count", 1)
            fallback_venue = self._pick_activity_fallback_name(plan, venue_name)
            fallback_action = {
                "action_id": f"{action.get('action_id', 'act')}_fallback_free",
                "action_type": "book_activity",
                "description": f"改为备选活动：{fallback_venue} x{ticket_count}",
                "params": {
                    **params,
                    "venue_name": fallback_venue,
                    "ticket_count": ticket_count,
                    "time": params.get("time", "14:00"),
                    "ticket_mode": "free_or_no_reservation",
                },
                "is_optional": False,
                "estimated_cost": 0,
            }
            return {
                "action": fallback_action,
                "reason": f"{venue_name}可能无票或预约名额不足，已准备不同于原地点的同类/低门槛备选活动。",
            }

        if action_type == "order_delivery":
            fallback_action = {
                **action,
                "action_id": f"{action.get('action_id', 'act')}_retry",
                "description": f"重试{original_description if original_description != '该动作' else '配送下单'}",
            }
            return {
                "action": fallback_action,
                "reason": "配送下单可重试；如果仍失败，建议改为到店自取或更换配送时间。",
            }

        return {
            "action": {
                **action,
                "action_id": f"{action.get('action_id', 'act')}_retry",
                "description": f"重试{original_description}",
            },
            "reason": "该动作失败后可以重试一次。",
        }

    def _pick_fallback_restaurant_name(self, plan: dict, original_name: str) -> str:
        """挑一个不等于原餐厅的备选餐厅名，优先贴合亲子/安静场景。"""
        plan_text = json.dumps(plan, ensure_ascii=False)
        if any(word in plan_text for word in ["孩子", "亲子", "老婆"]):
            candidates = ["附近亲子友好餐厅", "轻松家庭餐厅", "有儿童座椅的邻近餐厅"]
        elif any(word in plan_text for word in ["失恋", "散心", "一个人", "安静"]):
            candidates = ["安静一人食餐厅", "附近安静咖啡简餐", "邻近轻食小馆"]
        else:
            candidates = ["附近评价较稳餐厅", "邻近可预约餐厅", "转场方便的备选餐厅"]

        for name in candidates:
            if name != original_name:
                return name
        return f"{original_name}附近备选餐厅"

    def _pick_activity_fallback_name(self, plan: dict, original_name: str) -> str:
        """2026-06-06: 活动执行失败时按同类需求换不同地点，避免“改用备选”仍然是原棋牌室。"""
        plan_text = json.dumps(plan, ensure_ascii=False)
        if any(word in f"{original_name}{plan_text}" for word in ["棋牌", "麻将"]):
            candidates = ["附近另一家棋牌室", "同区麻将馆备选", "邻近可预约棋牌茶室"]
        elif any(word in f"{original_name}{plan_text}" for word in ["电影", "影院", "影城"]):
            candidates = ["附近另一家影城", "同区可购票电影院", "邻近商场影院"]
        elif any(word in f"{original_name}{plan_text}" for word in ["KTV", "唱歌"]):
            candidates = ["附近另一家KTV", "同区可预订量贩KTV", "邻近K歌房"]
        else:
            candidates = []

        for name in candidates:
            if name != original_name and not _is_avoided_place(name, [original_name]):
                return name
        return self._pick_free_activity_name(plan, original_name)

    def _pick_free_activity_name(self, plan: dict, original_name: str) -> str:
        """2026-06-05: 门票无票时优先选择同方案内免费/免预约活动，形成可演示的无票异常备选。"""
        for item in plan.get("timeline", []):
            if item.get("activity_type") in ("play", "extra"):
                name = item.get("venue_name") or item.get("title")
                if name and name != original_name and not item.get("booking_available"):
                    return name
        plan_text = json.dumps(plan, ensure_ascii=False)
        if any(word in plan_text for word in ["雨", "高温", "室内"]):
            return "附近室内商场/书店咖啡馆"
        if any(word in plan_text for word in ["约会", "女朋友", "拍照"]):
            return "附近商圈拍照散步点"
        if any(word in plan_text for word in ["孩子", "亲子"]):
            return "附近免费亲子公园"
        return "附近免费公园/商圈"

    # ------------------------------------------------------------------
    # 私有方法：构建查询
    # ------------------------------------------------------------------

    def _build_intent_query(
        self,
        message: str,
        city: str,
        district: str,
        date_str: str,
        start_time: str,
        duration_hours: int,
        group_type_hint: str,
        group_info_hint: dict
    ) -> str:
        """构建意图解析查询"""
        query = f"""请解析以下用户需求，返回结构化 JSON：

**用户消息：** "{message}"

**已知上下文：**
- 城市：{city}
- 区域：{district if district else '未指定'}
- 日期：{date_str}
- 可用时间：{start_time} 开始，约 {duration_hours} 小时
"""
        if group_type_hint:
            query += f"- 用户选择的群体类型：{group_type_hint}\n"
        if group_info_hint:
            query += f"- 用户提供的群体信息：{json.dumps(group_info_hint, ensure_ascii=False)}\n"

        query += "\n请返回 JSON（只返回 JSON，不要其他文字）。"
        return query

    def _search_venues(self, city: str, district: str, parsed_intent: dict) -> str:
        """搜索玩乐场所，按偏好进行多次搜索并合并"""
        preferred = parsed_intent.get("preferred_activities", [])
        group_type = parsed_intent.get("group_type", "family")
        mood = parsed_intent.get("mood", "")
        constraints = parsed_intent.get("constraints", [])
        special_requests = parsed_intent.get("special_requests", [])
        scenario = parsed_intent.get("scenario", {}) or {}
        hard_activity_keywords = [str(item) for item in parsed_intent.get("hard_activity_keywords", []) if item]

        # 根据群体类型和偏好确定搜索关键词
        search_keywords: List[str] = []

        # 2026-06-05: 深度 Agent 模式搜索也必须让本次硬需求优先，例如“看电影”不能被约会通用的网红打卡/展览挤掉。
        search_keywords.extend(hard_activity_keywords)

        # 2026-06-04: 情绪疗愈场景单独处理，避免普通聚会/打卡推荐偏题
        emotional_text = " ".join([mood, *preferred, *constraints, *special_requests])
        if scenario.get("primary") == "solo_healing" or any(word in emotional_text for word in ["情绪疗愈", "散心", "失恋", "分手", "心情不好", "安静"]):
            search_keywords.extend(["安静公园", "滨江公园", "书店 咖啡馆"])
        elif scenario.get("primary") == "couple_date":
            search_keywords.extend(["安静咖啡馆", "网红打卡地", "展览"])
        elif scenario.get("primary") == "friend_drink":
            search_keywords.extend(["小酒馆", "烧烤 夜宵", "清吧"])
        elif scenario.get("primary") == "solo_fun":
            search_keywords.extend(["展览", "电影院", "电玩城"])
        elif group_type == "family":
            has_children = parsed_intent.get("group_details", {}).get("has_children", True)
            if has_children:
                search_keywords.extend(["亲子乐园", "儿童公园"])
            else:
                search_keywords.extend(["公园", "景区"])
        else:
            search_keywords.extend(["展览", "公园"])

        # 从用户偏好中补充
        keyword_map = {
            "亲子乐园": "亲子乐园",
            "公园": "公园",
            "展览": "展览馆",
            "citywalk": "步行街 商圈",
            "逛街": "购物中心",
            "博物馆": "博物馆",
            "安静公园": "安静公园",
            "水边散步": "滨江公园",
            "书店咖啡馆": "书店 咖啡馆",
            "游乐场": "游乐场",
            "电影": "电影院",
            "运动": "运动馆",
            "密室逃脱": "密室逃脱",
            "剧本杀": "剧本杀",
            "KTV": "KTV",
        }
        for pref in preferred:
            for key, val in keyword_map.items():
                if key in pref and val not in search_keywords:
                    search_keywords.append(val)

        # 2026-06-07: Never trim explicit hard requirements; only cap extra scenario/preference keywords.
        hard_unique = list(dict.fromkeys(hard_activity_keywords))
        extra_keywords = [kw for kw in search_keywords if kw not in hard_unique]
        search_keywords = list(dict.fromkeys([*hard_unique, *extra_keywords[: max(0, 3 - len(hard_unique))]]))
        if not search_keywords:
            search_keywords = ["公园", "景点"]

        location_suffix = f"{district}" if district else ""
        # 2026-06-04: 普通模式关键词内部并发搜索，并配合缓存降低重复规划等待时间
        tasks = []
        for kw in search_keywords:
            full_kw = f"{location_suffix}{kw}".strip() if location_suffix else kw
            # 2026-06-03 修复：使用 amap 工具名，参数放在 JSON 中
            query = (
                f"请使用amap工具搜索{city}的{full_kw}。\n"
                f'[TOOL_CALL:amap:{{"action":"call_tool","tool_name":"maps_text_search",'
                f'"arguments":{{"keywords":"{full_kw}","city":"{city}"}}}}]'
            )
            tasks.append((kw, full_kw, query))

        all_results: List[str] = []
        with ThreadPoolExecutor(max_workers=min(3, len(tasks) or 1)) as executor:
            future_map = {
                executor.submit(
                    self._run_cached_agent_search,
                    f"venue::{city}::{full_kw}",
                    self.venue_agent,
                    query,
                ): kw
                for kw, full_kw, query in tasks
            }
            for future in as_completed(future_map):
                kw = future_map[future]
                try:
                    result = future.result()
                    if self._is_unusable_agent_search_result(result):
                        print(f"  [WARN] 场所 Agent 搜索 {kw} 无效，改用高德 REST 兜底")
                        result = self._search_poi_rest_fallback_text(kw, city, district, "venue")
                    all_results.append(f"【{kw}搜索结果】\n{result}")
                except Exception as e:
                    print(f"  [WARN] 搜索 {kw} 失败: {e}")
                    fallback = self._search_poi_rest_fallback_text(kw, city, district, "venue")
                    all_results.append(f"【{kw}搜索结果】\n{fallback}")

        return "\n\n".join(all_results)

    def _search_restaurants(self, city: str, district: str, parsed_intent: dict) -> str:
        """搜索餐厅"""
        dining_prefs = parsed_intent.get("dining_preferences", [])
        group_type = parsed_intent.get("group_type", "family")
        mood = parsed_intent.get("mood", "")
        constraints = parsed_intent.get("constraints", [])
        special_requests = parsed_intent.get("special_requests", [])
        scenario = parsed_intent.get("scenario", {}) or {}
        hard_food_keywords = [str(item) for item in parsed_intent.get("hard_food_keywords", []) if item]

        search_keywords: List[str] = []

        # 2026-06-05: 深度 Agent 模式餐厅搜索也优先本次明确菜系，例如“烧烤”不能被约会餐厅/氛围餐厅截断。
        search_keywords.extend(hard_food_keywords)

        # 2026-06-04: 情绪疗愈场景优先一人友好、安静、清淡，避免热闹聚餐
        emotional_text = " ".join([mood, *dining_prefs, *constraints, *special_requests])
        if scenario.get("primary") == "solo_healing" or any(word in emotional_text for word in ["情绪疗愈", "散心", "失恋", "分手", "心情不好", "安静"]):
            search_keywords.extend(["一人食", "安静咖啡馆"])
        elif scenario.get("primary") == "couple_date":
            search_keywords.extend(["氛围感餐厅", "适合约会餐厅"])
        elif scenario.get("primary") == "friend_drink":
            search_keywords.extend(["小酒馆", "烧烤"])
        elif scenario.get("primary") == "friend_party":
            search_keywords.extend(["火锅", "聚会餐厅"])
        elif group_type == "family":
            search_keywords.append("亲子餐厅")
        else:
            search_keywords.append("餐厅")

        # 从饮食偏好中补充
        diet_keyword_map = {
            "健康低卡": "轻食 沙拉",
            "减肥": "健康餐",
            "火锅": "火锅",
            "日料": "日本料理",
            "烧烤": "烧烤",
            "西餐": "西餐厅",
            "中餐": "中餐馆",
            "川菜": "川菜",
            "粤菜": "粤菜",
        }
        for pref in dining_prefs:
            for key, val in diet_keyword_map.items():
                if key in pref and val not in search_keywords:
                    search_keywords.append(val)

        # 2026-06-07: Hard food requirements are mandatory; cap only non-hard fallback keywords.
        hard_unique = list(dict.fromkeys(hard_food_keywords))
        extra_keywords = [kw for kw in search_keywords if kw not in hard_unique]
        search_keywords = list(dict.fromkeys([*hard_unique, *extra_keywords[: max(0, 2 - len(hard_unique))]]))
        if not search_keywords:
            search_keywords = ["餐厅"]

        location_suffix = f"{district}" if district else ""
        # 2026-06-04: 餐厅关键词内部并发搜索，保留 Agent 语义包装但减少串行等待
        tasks = []
        for kw in search_keywords:
            full_kw = f"{location_suffix}{kw}".strip() if location_suffix else kw
            # 2026-06-03 修复：使用 amap 工具名，参数放在 JSON 中
            query = (
                f"请使用amap工具搜索{city}的{full_kw}。\n"
                f'[TOOL_CALL:amap:{{"action":"call_tool","tool_name":"maps_text_search",'
                f'"arguments":{{"keywords":"{full_kw}","city":"{city}"}}}}]'
            )
            tasks.append((kw, full_kw, query))

        all_results: List[str] = []
        with ThreadPoolExecutor(max_workers=min(2, len(tasks) or 1)) as executor:
            future_map = {
                executor.submit(
                    self._run_cached_agent_search,
                    f"restaurant::{city}::{full_kw}",
                    self.restaurant_agent,
                    query,
                ): kw
                for kw, full_kw, query in tasks
            }
            for future in as_completed(future_map):
                kw = future_map[future]
                try:
                    result = future.result()
                    if self._is_unusable_agent_search_result(result):
                        print(f"  [WARN] 餐厅 Agent 搜索 {kw} 无效，改用高德 REST 兜底")
                        result = self._search_poi_rest_fallback_text(kw, city, district, "restaurant")
                    all_results.append(f"【{kw}搜索结果】\n{result}")
                except Exception as e:
                    print(f"  [WARN] 搜索 {kw} 失败: {e}")
                    fallback = self._search_poi_rest_fallback_text(kw, city, district, "restaurant")
                    all_results.append(f"【{kw}搜索结果】\n{fallback}")

        return "\n\n".join(all_results)

    def _build_planner_query(
        self,
        city: str,
        district: str,
        date_str: str,
        start_time: str,
        duration_hours: int,
        user_message: str,
        parsed_intent: dict,
        venue_results: str,
        restaurant_results: str,
        weather_info: str,
        availability_info: str,
        planning_mode: str = "detailed",
        execution_mode: str = "agent",
        home_location: Optional[dict] = None,
        location_resolved: Optional[dict] = None,
        scenario: Optional[dict] = None,
        memory_context: Optional[dict] = None,
    ) -> str:
        """构建规划 Agent 的查询"""
        end_hour = int(start_time.split(":")[0]) + duration_hours
        end_time = f"{min(end_hour, 23):02d}:00"

        group_type = parsed_intent.get("group_type", "family")
        group_size = parsed_intent.get("group_size", 3)
        group_details = parsed_intent.get("group_details", {})
        preferred = parsed_intent.get("preferred_activities", [])
        dining_prefs = parsed_intent.get("dining_preferences", [])
        constraints = parsed_intent.get("constraints", [])
        special = parsed_intent.get("special_requests", [])
        mood = parsed_intent.get("mood", "")
        hard_activity_keywords = [str(item) for item in parsed_intent.get("hard_activity_keywords", []) if item]
        hard_food_keywords = [str(item) for item in parsed_intent.get("hard_food_keywords", []) if item]
        hard_trip_items = [
            item for item in parsed_intent.get("hard_trip_items", [])
            if isinstance(item, dict) and item.get("keyword")
        ]
        avoid_places = [str(item) for item in (memory_context.get("avoid_places", []) if isinstance(memory_context, dict) else []) if item]
        avoid_places.extend([str(item) for item in parsed_intent.get("avoid_places", []) if item])
        scenario = scenario or {}
        memory_context = memory_context or {}
        mode_name = "附近快排" if planning_mode == "nearby_quick" else "精细规划"
        execution_name = "极速生成" if execution_mode == "fast" else "深度思考"
        mode_guidance = (
            "这是附近快排模式：用户只给了一句话和少量位置上下文。请主动补全合理假设，"
            "优先选择同一区域或附近3-5公里内的场所，减少折返和长距离交通，输出一个能直接执行的下午/周末短时方案。"
            "如果用户在一句话里提到时间、人群关系、孩子、老人、饮食、心情、想放松等细节，必须体现在时间轴和推荐理由里。"
            if planning_mode == "nearby_quick"
            else "这是精细规划模式：请严格尊重用户填写的城市、区域、时间、预算和群体信息。"
        )
        # 2026-06-04: 快速模式要求 Planner 只在结构化候选池内选点，地点和坐标由高德候选池兜底锁定
        execution_guidance = (
            "这是极速生成模式：玩乐和餐饮搜索结果是结构化高德 POI 候选池。timeline 中的 play/eat/extra 地点必须优先从候选池选择，"
            "venue_name、venue_address、venue_location 不要自由编造；如果候选不足，只能选择最接近用户需求的候选并说明取舍。"
            if execution_mode == "fast"
            else "这是深度思考模式：保留多智能体搜索结果，请综合搜索文本、天气、可用性和用户记忆生成更细致的方案。"
        )
        # 2026-06-04: 对失恋/散心等情绪型输入注入专门的疗愈规划策略
        emotional_text = " ".join([mood, *preferred, *constraints, *special])
        emotional_guidance = ""
        if any(word in emotional_text for word in ["情绪疗愈", "散心", "失恋", "分手", "心情不好", "安静"]):
            emotional_guidance = """

**情绪疗愈策略（必须遵守）：**
- 用户处在低落/失恋/想散心状态，方案目标不是热闹玩乐，而是帮他安全、安静、轻负担地度过这几个小时。
- 优先安排：安静公园/水边步道/书店/咖啡馆/小型展览/夜景散步。
- 避免安排：情侣约会感强的场所、KTV/密室/剧本杀、强社交餐厅、过度消费、过度打卡。
- 时间轴要留白，不要排太满；每段 description 要体现“缓一缓、慢慢走、找个角落坐坐”这类情绪照顾。
- 餐饮优先选择一人友好、安静、不需要排队太久的店；executable_actions 可以包含预约座位/购票，但不要生成蛋糕鲜花等庆祝类动作。
- share_message 不要像群发邀约，要像发给自己或可信朋友的温和提醒。
"""
        # 2026-06-04: 将场景识别和 Graph Memory RAG 结果注入规划提示词，提升个性化且避免跨场景串味
        scenario_guidance = ""
        if scenario:
            scenario_guidance = f"""

**当前场景识别：**
- 主场景：{scenario.get("primary", "unknown")}
- 辅助标签：{", ".join(scenario.get("secondary", [])) or "无"}
- 识别信号：{", ".join(scenario.get("signals", [])) or "无"}
- 场景偏好：{", ".join(scenario.get("prefer", [])) or "无"}
- 场景避雷：{", ".join(scenario.get("avoid", [])) or "无"}
- 推荐语气：{scenario.get("tone", "轻松实用")}
请让路线、推荐理由、餐厅选择和分享文案都贴合这个场景。
"""
        memory_prompt = memory_context.get("prompt", "暂无可用历史记忆。")
        request_avoid_places = memory_context.get("request_avoid_places", []) if isinstance(memory_context, dict) else []
        avoid_places = list(dict.fromkeys([*avoid_places, *[str(item) for item in request_avoid_places if item]]))
        location_resolved = location_resolved or {}
        location_context = (
            (
                f"- 用户当前位置坐标：{json.dumps(home_location, ensure_ascii=False)}\n"
                f"- 定位反查结果：{json.dumps(location_resolved, ensure_ascii=False)}\n"
                "- 位置策略：附近快排必须以用户当前位置为中心，优先选择当前位置 3-5 公里内或同一区域内的场所；城市/区域只作为搜索和天气兜底。\n"
            )
            if home_location else
            "- 用户当前位置坐标：未提供，按城市和区域理解“附近”。\n"
        )

        query = f"""请根据以下信息生成一个完整的本地活动方案（返回 JSON）：

**基本信息：**
- 规划模式：{mode_name}
- 执行模式：{execution_name}
- 城市：{city}
- 区域：{district if district else '不限'}
- 日期：{date_str}
- 时间范围：{start_time} 至 {end_time}（约 {duration_hours} 小时）
- 用户原始一句话：{user_message}
{location_context}

**模式策略：**
{mode_guidance}

**执行策略：**
{execution_guidance}
{emotional_guidance}
{scenario_guidance}

**用户历史记忆（Graph Memory RAG）：**
{memory_prompt}
请只使用和当前场景相关的记忆，不要把亲子偏好误用于约会、兄弟喝酒或独处场景。
如果对象级记忆中有“避开”的地点或餐厅，请不要再次推荐。

**群体信息：**
- 类型：{group_type}
- 总人数：{group_size}
- 详细：{json.dumps(group_details, ensure_ascii=False)}
- 结构化意图：{json.dumps(parsed_intent, ensure_ascii=False)}

**偏好和约束：**
- 用户本次显式活动硬需求：{', '.join(hard_activity_keywords) if hard_activity_keywords else '无'}
- 用户本次显式餐饮硬需求：{', '.join(hard_food_keywords) if hard_food_keywords else '无'}
- 用户本次有序硬行程：{json.dumps(hard_trip_items, ensure_ascii=False) if hard_trip_items else '无'}
- 本次必须避开的地点/餐厅：{', '.join(avoid_places) if avoid_places else '无'}
- 活动偏好：{', '.join(preferred) if preferred else '无特别偏好'}
- 饮食偏好：{', '.join(dining_prefs) if dining_prefs else '无特别偏好'}
- 约束条件：{', '.join(constraints) if constraints else '无'}
- 特殊要求：{', '.join(special) if special else '无'}

**搜索到的玩乐场所：**
{venue_results}

**搜索到的餐厅：**
{restaurant_results}

**天气信息：**
{weather_info}

**餐厅可用性/排队情况：**
{availability_info}

**要求：**
1. 返回完整合法的 JSON
2. timeline 中的场所名称、地址、经纬度必须来自搜索结果；如搜索结果缺少坐标，可使用用户当前位置附近的合理偏移，但禁止照抄示例坐标
3. 时间必须连贯，考虑交通时间
4. 餐厅要匹配群体饮食需求
5. executable_actions 至少包含餐厅预约
6. share_message 要口语化
7. 所有描述精简(建议不超过60字)，但必须写清推荐理由，确保JSON完整
8. 如果是附近快排模式，不要要求用户继续补充信息，直接给出可落地方案
9. timeline 中每个 play/eat/extra 节点的 description 必须是“推荐理由”，要明确写出它为什么适合当前用户和群体
10. 对“老婆孩子/亲子/放松”等表达，要体现亲子友好、轻松不折腾、增进家人互动；餐厅要说明距离、亲子友好、招牌/口味或排队优势
11. 不要输出空泛描述，例如“环境优美”“附近餐厅用餐”“户外活动”；要写成“孩子能跑跳放电，父母也能一起参与，适合一家人放松”
12. 2026-06-07：用户本次显式硬需求优先级最高，必须在 timeline 中逐项落地；例如“上午棋牌室打麻将、中午火锅、下午KTV唱歌”必须分别有棋牌室/麻将馆节点、火锅餐饮节点、KTV节点，不能用第二个棋牌室替代 KTV
13. 2026-06-06：如果“本次必须避开的地点/餐厅”不为空，timeline 和 executable_actions 都不能再使用这些名称或高度相似名称；这是用户点击“换一个/换一套”后的硬约束
"""
        return query

    # ------------------------------------------------------------------
    # 解析与容错
    # ------------------------------------------------------------------

    def _parse_plan_response(self, response: str, request: dict, parsed_intent: dict) -> dict:
        """解析规划 Agent 的响应"""
        plan = _safe_parse_json(response)

        if plan is not None:
            # 补全可能缺失的字段
            plan.setdefault("plan_id", f"plan_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}")
            plan.setdefault("city", request.get("city", "北京"))
            plan.setdefault("date", request.get("date", datetime.now().strftime("%Y-%m-%d")))
            plan.setdefault("group_type", parsed_intent.get("group_type", "family"))
            plan.setdefault("group_summary", "")
            plan.setdefault("start_time", request.get("start_time", "14:00"))
            plan.setdefault("end_time", "20:00")
            plan.setdefault("timeline", [])
            plan.setdefault("weather_summary", "")
            plan.setdefault("budget", {"activities": 0, "dining": 0, "transportation": 0, "extras": 0, "total": 0})
            plan.setdefault("executable_actions", [])
            plan.setdefault("share_message", "")
            plan.setdefault("overall_tips", "")
            print("  [OK] 方案解析成功")
            return plan

        print("  [WARN] 方案解析失败，使用备用方案")
        request = {**request, "fallback_reason": "planner_json_parse_failed"}
        return self._create_fallback_plan(request)

    def _default_intent(self, group_type_hint: str, group_info_hint: dict) -> dict:
        """返回默认意图（当解析失败时）"""
        gt = group_type_hint if group_type_hint else "family"
        return {
            "group_type": gt,
            "group_size": 3 if gt == "family" else 4,
            "group_details": group_info_hint if group_info_hint else {
                "has_children": gt == "family",
                "children_ages": [5] if gt == "family" else [],
                "has_elderly": False,
                "dietary_restrictions": [],
                "gender_split": "" if gt == "family" else "2男2女"
            },
            "preferred_activities": ["公园", "亲子乐园"] if gt == "family" else ["展览", "citywalk"],
            "dining_preferences": ["适合孩子"] if gt == "family" else [],
            "constraints": ["别离家太远"],
            "mood": "轻松休闲",
            "special_requests": []
        }

    def _create_fallback_plan(self, request: dict) -> dict:
        """创建备用方案（当所有 Agent 失败时）"""
        city = request.get("city") or "当前位置"
        date_str = request.get("date", datetime.now().strftime("%Y-%m-%d"))
        start_time = request.get("start_time", "14:00")
        start_h = int(start_time.split(":")[0])
        duration = request.get("duration_hours", 4)
        home_location = request.get("home_location")

        plan_id = f"plan_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"

        return {
            "plan_id": plan_id,
            "is_fallback": True,
            "fallback_reason": request.get("fallback_reason", "planner_failed_or_json_parse_failed"),
            "city": city,
            "district": request.get("district", ""),
            "date": date_str,
            "group_type": request.get("group_type", "family"),
            "group_summary": "家庭出游",
            "start_time": start_time,
            "end_time": f"{min(start_h + duration, 23):02d}:00",
            "timeline": [
                {
                    "order": 1,
                    "start_time": start_time,
                    "end_time": f"{start_h}:20",
                    "activity_type": "transport",
                    "title": "出发",
                    "description": "从家出发前往目的地",
                    "venue_name": "",
                    "venue_address": "",
                    "venue_location": _offset_location(home_location),
                    "transportation": "步行",
                    "travel_minutes": 20,
                    "estimated_cost": 0,
                    "tags": ["交通"]
                },
                {
                    "order": 2,
                    "start_time": f"{start_h}:20",
                    "end_time": f"{start_h + 2}:00",
                    "activity_type": "play",
                    "title": f"{city}公园游玩",
                    "description": "在附近公园休闲游玩",
                    "venue_name": f"{city}公园",
                    "venue_address": f"{city}市",
                    "venue_location": _offset_location(home_location, 0.003, 0.003),
                    "transportation": "",
                    "travel_minutes": 0,
                    "estimated_cost": 0,
                    "tags": ["休闲", "户外"],
                    "booking_available": False
                },
                {
                    "order": 3,
                    "start_time": f"{start_h + 2}:00",
                    "end_time": f"{start_h + 2}:15",
                    "activity_type": "transport",
                    "title": "前往餐厅",
                    "description": "步行前往附近餐厅",
                    "venue_name": "",
                    "venue_address": "",
                    "venue_location": _offset_location(home_location, 0.004, 0.004),
                    "transportation": "步行",
                    "travel_minutes": 15,
                    "estimated_cost": 0,
                    "tags": ["交通"]
                },
                {
                    "order": 4,
                    "start_time": f"{start_h + 2}:15",
                    "end_time": f"{start_h + 3}:30",
                    "activity_type": "eat",
                    "title": "用餐",
                    "description": "在附近餐厅用餐",
                    "venue_name": "附近餐厅",
                    "venue_address": f"{city}市",
                    "venue_location": _offset_location(home_location, 0.004, 0.004),
                    "transportation": "",
                    "travel_minutes": 0,
                    "estimated_cost": 200,
                    "tags": ["用餐"],
                    "booking_available": True,
                    "booking_type": "restaurant",
                    "party_size": 3
                },
                {
                    "order": 5,
                    "start_time": f"{start_h + 3}:30",
                    "end_time": f"{min(start_h + duration, 23)}:00",
                    "activity_type": "extra",
                    "title": "饭后休闲",
                    "description": "在附近散步或逛商圈",
                    "venue_name": "附近商圈",
                    "venue_address": f"{city}市",
                    "venue_location": _offset_location(home_location, 0.005, 0.005),
                    "transportation": "步行",
                    "travel_minutes": 5,
                    "estimated_cost": 50,
                    "tags": ["休闲"]
                }
            ],
            "weather_summary": "请关注当日天气预报",
            "budget": {
                "activities": 0,
                "dining": 200,
                "transportation": 0,
                "extras": 50,
                "total": 250
            },
            "executable_actions": [
                {
                    "action_id": "act_fallback_001",
                    "action_type": "book_restaurant",
                    "description": "预约附近餐厅",
                    "params": {
                        "restaurant_name": "附近餐厅",
                        "party_size": 3,
                        "time": f"{start_h + 2}:15",
                        "contact_phone": "待填写"
                    }
                }
            ],
            "share_message": f"今天下午{start_time}出发，先去公园逛逛，然后找个餐厅吃饭，最后随便逛逛~",
            "overall_tips": "建议提前查看目的地开放时间，出行注意天气变化。"
        }


# ============================================================================
# 全局单例
# ============================================================================

_activity_planner: Optional[MultiAgentActivityPlanner] = None
_planner_lock = threading.Lock()


def get_activity_planner() -> MultiAgentActivityPlanner:
    """获取多智能体活动规划系统实例（线程安全单例）"""
    global _activity_planner

    if _activity_planner is None:
        with _planner_lock:
            if _activity_planner is None:
                _activity_planner = MultiAgentActivityPlanner()

    return _activity_planner
