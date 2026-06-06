"""
Mock 执行服务 —— 模拟美团式本地生活操作

所有方法返回**模拟数据**，用于演示"可执行方案"的完整链路：
  - 餐厅可用性 / 排队查询
  - 餐厅预约
  - 活动门票购买
  - 外卖/蛋糕/鲜花配送下单
  - 附近团购优惠

真实上线时只需将这些方法替换为真实 API 调用即可，接口签名无需改变。
"""

import random
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 辅助：生成 Mock ID
# ---------------------------------------------------------------------------

def _mock_order_id(prefix: str = "ORD") -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{ts}_{uuid.uuid4().hex[:6].upper()}"


def _mock_confirmation_code() -> str:
    return f"CFM-{random.randint(100000, 999999)}"


# ---------------------------------------------------------------------------
# Mock 数据池
# ---------------------------------------------------------------------------

_MOCK_RESTAURANT_POOL = [
    {"name_fragment": "海底捞", "queue": 8, "wait": 45, "accepts": True},
    {"name_fragment": "外婆家", "queue": 3, "wait": 15, "accepts": True},
    {"name_fragment": "西贝", "queue": 0, "wait": 0, "accepts": True},
    {"name_fragment": "必胜客", "queue": 1, "wait": 10, "accepts": True},
    {"name_fragment": "肯德基", "queue": 0, "wait": 0, "accepts": False},
    {"name_fragment": "麦当劳", "queue": 0, "wait": 0, "accepts": False},
    {"name_fragment": "呷哺呷哺", "queue": 5, "wait": 25, "accepts": True},
]

_MOCK_DELIVERY_ITEMS = {
    "cake": {"name": "6寸奶油生日蛋糕", "price": 128, "delivery_min": 45},
    "flower": {"name": "11朵红玫瑰花束", "price": 168, "delivery_min": 60},
    "fruit": {"name": "精选水果拼盘", "price": 88, "delivery_min": 40},
    "balloon": {"name": "生日气球套装", "price": 58, "delivery_min": 30},
    "wine": {"name": "进口红酒礼盒", "price": 258, "delivery_min": 50},
}

_MOCK_DEALS = [
    {"deal_name": "双人电影票", "original_price": 120, "deal_price": 79, "remaining": 23},
    {"deal_name": "亲子游乐园套票", "original_price": 198, "deal_price": 128, "remaining": 15},
    {"deal_name": "精品下午茶套餐", "original_price": 168, "deal_price": 99, "remaining": 8},
    {"deal_name": "密室逃脱4人票", "original_price": 320, "deal_price": 199, "remaining": 5},
    {"deal_name": "KTV 欢唱3小时", "original_price": 288, "deal_price": 158, "remaining": 12},
    {"deal_name": "真人CS对战(10人)", "original_price": 500, "deal_price": 299, "remaining": 3},
]


# ============================================================================
# MockService 类
# ============================================================================

class MockService:
    """模拟美团式本地生活操作服务"""

    # ------------------------------------------------------------------
    # 1. 餐厅可用性 / 排队查询
    # ------------------------------------------------------------------

    def check_restaurant_availability(
        self,
        restaurant_name: str,
        city: str = "",
        party_size: int = 2,
        time: str = "17:00",
    ) -> Dict[str, Any]:
        """
        查询指定餐厅的可用性（座位 / 排队情况）。

        Returns:
            {
                "restaurant_name": str,
                "available": bool,
                "queue_length": int,
                "estimated_wait_minutes": int,
                "queue_status": str,
                "available_time_slots": [str],
                "accepts_reservation": bool,
                "special_notes": str,
            }
        """
        print(f"  [PHONE] [Mock] 查询餐厅可用性: {restaurant_name} ({city}) {party_size}人 {time}")

        # 在 Mock 池中模糊匹配
        matched = None
        for item in _MOCK_RESTAURANT_POOL:
            if item["name_fragment"] in restaurant_name:
                matched = item
                break

        if matched is None:
            # 未匹配到，随机生成
            queue = random.choice([0, 0, 0, 2, 5, 10])
            wait = queue * random.randint(5, 10)
            accepts = random.choice([True, True, True, False])
        else:
            queue = matched["queue"] + random.randint(-1, 2)
            queue = max(0, queue)
            wait = matched["wait"] + random.randint(-5, 10)
            wait = max(0, wait)
            accepts = matched["accepts"]

        # 生成可预约时间段
        base_hour = int(time.split(":")[0])
        slots = []
        if accepts:
            for offset in [0, 30, 60, 90]:
                slot_min = base_hour * 60 + int(time.split(":")[1]) + offset
                h, m = divmod(slot_min, 60)
                if h <= 21:
                    slots.append(f"{h:02d}:{m:02d}")

        available = queue == 0 or wait <= 15

        if wait == 0:
            queue_status = "无需排队"
        elif wait <= 15:
            queue_status = f"约等{wait}分钟"
        elif wait <= 30:
            queue_status = f"约等{wait}分钟"
        elif wait <= 60:
            queue_status = f"约等{wait}分钟，建议提前预约"
        else:
            queue_status = f"排队较长(约{wait}分钟)，建议换一家"

        # 大桌（>6人）特殊提示
        special = ""
        if party_size > 6:
            special = "大桌位有限，建议提前至少1小时预约"
        elif party_size > 4:
            special = "4人以上建议预约包间"

        result = {
            "restaurant_name": restaurant_name,
            "available": available,
            "queue_length": queue,
            "estimated_wait_minutes": wait,
            "queue_status": queue_status,
            "available_time_slots": slots,
            "accepts_reservation": accepts,
            "special_notes": special,
        }
        print(f"    → 可用={available}, 排队={queue}组, 等{wait}min, 可预约={accepts}")
        return result

    def batch_check_restaurant_availability(
        self,
        city: str = "",
        party_size: int = 2,
        time: str = "17:00",
        restaurant_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        批量查询多家餐厅可用性。
        如果 restaurant_names 为空，则返回一组通用的 Mock 提示。
        """
        if restaurant_names:
            return [
                self.check_restaurant_availability(name, city, party_size, time)
                for name in restaurant_names
            ]

        # 没有具体餐厅名时，返回通用信息
        return [
            {
                "restaurant_name": "(通用提示)",
                "available": True,
                "queue_length": 0,
                "estimated_wait_minutes": 0,
                "queue_status": "大部分餐厅该时段有空位",
                "available_time_slots": [time],
                "accepts_reservation": True,
                "special_notes": f"建议{party_size}人以上提前预约",
            }
        ]

    # ------------------------------------------------------------------
    # 2. 餐厅预约
    # ------------------------------------------------------------------

    def book_restaurant(
        self,
        restaurant_name: str,
        city: str = "",
        party_size: int = 2,
        time: str = "17:00",
        contact_name: str = "用户",
        contact_phone: str = "13800138000",
    ) -> Dict[str, Any]:
        """
        预约餐厅。

        Returns:
            {
                "success": bool,
                "message": str,
                "order_id": str,
                "confirmation_code": str,
                "booking_time": str,
                "details": {...}
            }
        """
        print(f"  [EAT] [Mock] 预约餐厅: {restaurant_name} ({city}) {party_size}人 {time}")

        # 90% 成功率
        success = random.random() < 0.9

        if success:
            order_id = _mock_order_id("RST")
            code = _mock_confirmation_code()
            return {
                "success": True,
                "message": f"预约成功！{restaurant_name} {time} {party_size}人桌",
                "order_id": order_id,
                "confirmation_code": code,
                "booking_time": time,
                "details": {
                    "restaurant_name": restaurant_name,
                    "party_size": party_size,
                    "time": time,
                    "contact_name": contact_name,
                    "contact_phone": contact_phone,
                    "status": "confirmed",
                    "cancel_before": f"{int(time.split(':')[0]) - 1}:00",
                    "notes": "如需取消请提前1小时操作",
                }
            }
        else:
            return {
                "success": False,
                "message": f"抱歉，{restaurant_name} {time} 时段已满，建议换个时间或餐厅",
                "order_id": None,
                "confirmation_code": None,
                "booking_time": time,
                "details": {
                    "restaurant_name": restaurant_name,
                    "suggested_times": [
                        f"{int(time.split(':')[0]) + 1}:00",
                        f"{int(time.split(':')[0]) + 1}:30",
                    ]
                }
            }

    # ------------------------------------------------------------------
    # 3. 排队状态查询
    # ------------------------------------------------------------------

    def check_queue_status(
        self,
        restaurant_name: str,
        city: str = "",
    ) -> Dict[str, Any]:
        """
        查询实时排队状态。

        Returns:
            {
                "success": bool,
                "message": str,
                "queue_length": int,
                "estimated_wait_minutes": int,
                "your_number": str | None,
            }
        """
        print(f"  [NUM] [Mock] 查询排队: {restaurant_name} ({city})")

        queue = random.randint(0, 15)
        wait = queue * random.randint(4, 8)

        return {
            "success": True,
            "message": f"当前排队{queue}组，预计等待{wait}分钟" if queue > 0 else "当前无需排队，可直接入座",
            "queue_length": queue,
            "estimated_wait_minutes": wait,
            "your_number": f"A{random.randint(100, 999)}" if queue > 0 else None,
        }

    # ------------------------------------------------------------------
    # 4. 活动门票购买
    # ------------------------------------------------------------------

    def book_activity_tickets(
        self,
        venue_name: str,
        city: str = "",
        ticket_count: int = 1,
        time: str = "14:00",
        ticket_type: str = "standard",
    ) -> Dict[str, Any]:
        """
        购买活动/景点门票。

        Returns:
            {
                "success": bool,
                "message": str,
                "order_id": str,
                "confirmation_code": str,
                "details": {...}
            }
        """
        print(f"  [TICKET] [Mock] 购买门票: {venue_name} ({city}) x{ticket_count} {time}")

        # 票价 Mock
        price_map = {
            "standard": random.choice([0, 20, 35, 50, 68, 80, 99]),
            "vip": random.choice([98, 128, 168, 198]),
            "child": random.choice([0, 10, 20, 35]),
        }
        unit_price = price_map.get(ticket_type, 50)
        total_price = unit_price * ticket_count

        # 95% 成功率
        success = random.random() < 0.95

        if success:
            order_id = _mock_order_id("TKT")
            code = _mock_confirmation_code()
            return {
                "success": True,
                "message": f"购票成功！{venue_name} x{ticket_count}张，共¥{total_price}",
                "order_id": order_id,
                "confirmation_code": code,
                "details": {
                    "venue_name": venue_name,
                    "ticket_type": ticket_type,
                    "ticket_count": ticket_count,
                    "unit_price": unit_price,
                    "total_price": total_price,
                    "valid_date": datetime.now().strftime("%Y-%m-%d"),
                    "valid_time": time,
                    "status": "paid",
                    "entry_method": "凭确认码或二维码入场",
                    "refund_policy": "使用前可免费退票",
                }
            }
        else:
            return {
                "success": False,
                "message": f"抱歉，{venue_name} 该时段门票已售罄",
                "order_id": None,
                "confirmation_code": None,
                "details": {
                    "venue_name": venue_name,
                    "suggested_times": [
                        f"{int(time.split(':')[0]) + 1}:00",
                        f"{int(time.split(':')[0]) + 2}:00",
                    ]
                }
            }

    # ------------------------------------------------------------------
    # 5. 外卖/蛋糕/鲜花配送下单
    # ------------------------------------------------------------------

    def order_delivery(
        self,
        item_type: str = "cake",
        item_name: str = "",
        delivery_address: str = "",
        delivery_time: str = "17:30",
        special_notes: str = "",
    ) -> Dict[str, Any]:
        """
        下单配送（蛋糕/鲜花/水果等送到指定餐厅或地址）。

        Args:
            item_type: cake / flower / fruit / balloon / wine
            item_name: 商品名称(为空则用默认)
            delivery_address: 配送地址
            delivery_time: 期望送达时间
            special_notes: 备注,如"贺卡写：生日快乐"

        Returns:
            {
                "success": bool,
                "message": str,
                "order_id": str,
                "estimated_delivery_time": str,
                "item_name": str,
                "price": int,
                "details": {...}
            }
        """
        print(f"  [DELIVERY] [Mock] 下单配送: {item_type} → {delivery_address} @{delivery_time}")

        mock_item = _MOCK_DELIVERY_ITEMS.get(item_type, {
            "name": item_name or "定制商品",
            "price": 99,
            "delivery_min": 45,
        })

        actual_name = item_name if item_name else mock_item["name"]
        price = mock_item["price"]
        delivery_min = mock_item["delivery_min"]

        # 预计送达时间
        try:
            h, m = map(int, delivery_time.split(":"))
            estimated = f"{h:02d}:{m:02d}"
        except Exception:
            estimated = delivery_time

        # 95% 成功率
        success = random.random() < 0.95

        if success:
            order_id = _mock_order_id("DLV")
            return {
                "success": True,
                "message": f"下单成功！{actual_name} 将于 {estimated} 前送达",
                "order_id": order_id,
                "estimated_delivery_time": estimated,
                "item_name": actual_name,
                "price": price,
                "details": {
                    "item_type": item_type,
                    "item_name": actual_name,
                    "price": price,
                    "delivery_address": delivery_address,
                    "delivery_time": delivery_time,
                    "estimated_delivery_time": estimated,
                    "special_notes": special_notes,
                    "status": "accepted",
                    "rider_phone": f"138{random.randint(10000000, 99999999)}",
                    "tracking_url": f"https://mock-tracking.example.com/{order_id}",
                }
            }
        else:
            return {
                "success": False,
                "message": f"抱歉，{actual_name} 当前库存不足或配送员繁忙，请稍后再试",
                "order_id": None,
                "estimated_delivery_time": None,
                "item_name": actual_name,
                "price": price,
                "details": {}
            }

    # ------------------------------------------------------------------
    # 6. 附近团购优惠
    # ------------------------------------------------------------------

    def get_nearby_deals(
        self,
        city: str = "",
        district: str = "",
        category: str = "",
        limit: int = 5,
    ) -> Dict[str, Any]:
        """
        获取附近团购优惠信息。

        Args:
            city: 城市
            district: 区域
            category: 类别筛选,如 "电影" / "亲子" / "美食"
            limit: 返回数量上限

        Returns:
            {
                "success": bool,
                "deals": [
                    {
                        "deal_id": str,
                        "deal_name": str,
                        "original_price": int,
                        "deal_price": int,
                        "discount": str,
                        "remaining": int,
                        "merchant": str,
                        "address": str,
                    }
                ]
            }
        """
        print(f"  [TAG] [Mock] 获取团购: {city} {district} {category} limit={limit}")

        pool = _MOCK_DEALS.copy()

        # 按 category 简单过滤
        if category:
            filtered = [d for d in pool if category in d["deal_name"]]
            if filtered:
                pool = filtered

        random.shuffle(pool)
        selected = pool[:limit]

        deals = []
        for i, d in enumerate(selected):
            discount = f"{d['deal_price'] / d['original_price']:.1f}折" if d['original_price'] > 0 else "免费"
            deals.append({
                "deal_id": f"DEAL_{uuid.uuid4().hex[:8].upper()}",
                "deal_name": d["deal_name"],
                "original_price": d["original_price"],
                "deal_price": d["deal_price"],
                "discount": discount,
                "remaining": d["remaining"],
                "merchant": f"{city}{district}某{d['deal_name'][:2]}店",
                "address": f"{city}{district}XX路{random.randint(1, 200)}号",
            })

        return {
            "success": True,
            "count": len(deals),
            "deals": deals,
        }

    # ------------------------------------------------------------------
    # 7. 综合：一键执行多个动作
    # ------------------------------------------------------------------

    def execute_batch(self, actions: List[Dict[str, Any]], city: str = "") -> List[Dict[str, Any]]:
        """
        批量执行多个动作，返回每个动作的结果。
        这是一个快捷方法，内部分发到对应的具体方法。
        """
        results = []
        for action in actions:
            action_type = action.get("action_type", "")
            params = action.get("params", {})
            action_id = action.get("action_id", f"act_{uuid.uuid4().hex[:6]}")
            description = action.get("description", "")

            try:
                if action_type == "book_restaurant":
                    r = self.book_restaurant(
                        restaurant_name=params.get("restaurant_name", ""),
                        city=city,
                        party_size=params.get("party_size", 2),
                        time=params.get("time", "17:00"),
                        contact_name=params.get("contact_name", "用户"),
                        contact_phone=params.get("contact_phone", "13800138000"),
                    )
                elif action_type == "book_activity":
                    r = self.book_activity_tickets(
                        venue_name=params.get("venue_name", ""),
                        city=city,
                        ticket_count=params.get("ticket_count", 1),
                        time=params.get("time", "14:00"),
                        ticket_type=params.get("ticket_type", "standard"),
                    )
                elif action_type == "order_delivery":
                    r = self.order_delivery(
                        item_type=params.get("item_type", "cake"),
                        item_name=params.get("item_name", ""),
                        delivery_address=params.get("delivery_address", ""),
                        delivery_time=params.get("delivery_time", "17:30"),
                        special_notes=params.get("special_notes", ""),
                    )
                elif action_type == "check_queue":
                    r = self.check_queue_status(
                        restaurant_name=params.get("restaurant_name", ""),
                        city=city,
                    )
                elif action_type == "get_deals":
                    r = self.get_nearby_deals(
                        city=city,
                        district=params.get("district", ""),
                        category=params.get("category", ""),
                        limit=params.get("limit", 5),
                    )
                else:
                    r = {"success": False, "message": f"未知动作类型: {action_type}"}

                results.append({
                    "action_id": action_id,
                    "action_type": action_type,
                    "description": description,
                    **r
                })

            except Exception as e:
                results.append({
                    "action_id": action_id,
                    "action_type": action_type,
                    "description": description,
                    "success": False,
                    "message": f"执行异常: {str(e)}",
                })

        return results


# ============================================================================
# 全局单例
# ============================================================================

_mock_service: Optional[MockService] = None
_mock_lock = threading.Lock()


def get_mock_service() -> MockService:
    """获取 Mock 服务实例（线程安全单例）"""
    global _mock_service

    if _mock_service is None:
        with _mock_lock:
            if _mock_service is None:
                _mock_service = MockService()
                print("[OK] Mock执行服务初始化成功")

    return _mock_service
