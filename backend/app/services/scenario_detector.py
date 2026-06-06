"""场景识别服务 - 将一句话需求转成可复用的场景标签"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List


@dataclass
class ScenarioResult:
    """结构化场景识别结果"""

    primary: str
    secondary: List[str]
    confidence: float
    signals: List[str]
    prefer: List[str]
    avoid: List[str]
    tone: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ScenarioDetector:
    """2026-06-04: 独立场景识别模块，避免亲子/约会/散心等偏好互相污染。"""

    SCENARIOS = {
        "family_kid": {
            "signals": ["孩子", "娃", "亲子", "老婆孩子", "带娃", "小孩"],
            "prefer": ["亲子友好", "孩子能放电", "少折腾", "有休息点"],
            "avoid": ["不适合孩子", "酒吧", "恐怖密室", "长时间排队"],
            "tone": "轻松、亲子友好、照顾孩子和家长体验",
        },
        "family_elderly": {
            "signals": ["父母", "爸妈", "老人", "长辈", "妈妈", "爸爸"],
            "prefer": ["低强度", "少走路", "安静", "有座位休息"],
            "avoid": ["爬山", "暴走", "太吵", "深夜"],
            "tone": "稳妥、舒适、少走路",
        },
        "family_mixed": {
            "signals": ["老婆孩子父母", "孩子父母", "一家人", "全家"],
            "prefer": ["多年龄友好", "亲子友好", "老人可休息", "转场少"],
            "avoid": ["太远", "太累", "排队久", "强刺激"],
            "tone": "兼顾孩子和老人，减少折腾",
        },
        "couple_birthday": {
            "signals": ["生日", "纪念日", "惊喜", "蛋糕", "鲜花"],
            "prefer": ["有仪式感", "适合拍照", "可预约", "餐厅环境好"],
            "avoid": ["排队久", "太嘈杂", "临时不可订"],
            "tone": "有仪式感、细腻、适合分享",
        },
        "couple_date": {
            "signals": ["女朋友", "男朋友", "约会", "老婆", "老公", "二人世界"],
            "prefer": ["安静", "出片", "适合聊天", "氛围好"],
            "avoid": ["太吵", "排队久", "过度亲子化", "太赶"],
            "tone": "轻松、有氛围、适合两个人慢慢聊",
        },
        "friend_drink": {
            "signals": ["兄弟", "喝酒", "小酒馆", "夜宵", "撸串", "烧烤"],
            "prefer": ["适合喝酒聊天", "可订座", "夜间营业", "转场方便"],
            "avoid": ["管得太严", "太安静", "不能聊天", "无酒水"],
            "tone": "松弛、适合聊天、带点夜生活氛围",
        },
        "friend_party": {
            "signals": ["朋友聚会", "KTV", "剧本杀", "密室", "桌游", "轰趴"],
            "prefer": ["多人友好", "热闹", "可预订", "适合互动"],
            "avoid": ["空间太小", "分散座位", "排队久"],
            "tone": "热闹、方便组织、多人参与感强",
        },
        "solo_healing": {
            "signals": ["失恋", "分手", "心情不好", "难过", "emo", "散散心", "一个人静静"],
            "prefer": ["安静", "水边散步", "书店咖啡馆", "一人食", "慢节奏"],
            "avoid": ["情侣约会", "强社交", "KTV", "密室", "庆祝"],
            "tone": "温和、低刺激、不打鸡血",
        },
        "solo_fun": {
            "signals": ["一个人", "自己", "找点乐子", "随便转转", "想玩点"],
            "prefer": ["自由度高", "新鲜体验", "不用组局", "可临时决定"],
            "avoid": ["强社交", "必须多人", "强绑定消费"],
            "tone": "自由、轻松、有一点新鲜感",
        },
        "solo_work_leisure": {
            "signals": ["咖啡馆坐坐", "书店", "办公", "写东西", "看书"],
            "prefer": ["安静", "可久坐", "有咖啡", "环境稳定"],
            "avoid": ["太吵", "限时", "无座"],
            "tone": "安静、可停留、低打扰",
        },
    }

    CROSS_CUTTING = {
        "health_diet": {
            "signals": ["减肥", "减脂", "控体重", "低卡", "清淡", "少油", "健康"],
            "prefer": ["健康低卡", "清淡少油", "轻食", "可控热量"],
            "avoid": ["重油", "自助", "炸鸡", "高热量"],
        },
        "nearby_quick": {
            "signals": ["附近", "别太远", "不远", "周围", "近一点"],
            "prefer": ["近距离", "转场少", "3-5公里内"],
            "avoid": ["跨城", "远距离折返"],
        },
        "relax": {
            "signals": ["放松", "休闲", "不折腾", "轻松", "缓一缓"],
            "prefer": ["慢节奏", "少排队", "舒服", "可休息"],
            "avoid": ["太赶", "暴走", "强刺激"],
        },
    }

    def detect(
        self,
        message: str,
        parsed_intent: Dict[str, Any] | None = None,
        planning_mode: str = "detailed",
    ) -> Dict[str, Any]:
        """识别主场景、横切标签、偏好、避雷和推荐语气。"""
        text = message or ""
        parsed_intent = parsed_intent or {}
        blob = " ".join([
            text,
            str(parsed_intent.get("mood", "")),
            " ".join(str(x) for x in parsed_intent.get("preferred_activities", [])),
            " ".join(str(x) for x in parsed_intent.get("dining_preferences", [])),
            " ".join(str(x) for x in parsed_intent.get("constraints", [])),
            " ".join(str(x) for x in parsed_intent.get("special_requests", [])),
        ])

        best_name = "friend_casual"
        best_score = 0
        best_meta = {
            "signals": [],
            "prefer": ["轻松可执行", "方便转场"],
            "avoid": ["排队久", "太远"],
            "tone": "轻松、实用、少折腾",
        }

        for name, meta in self.SCENARIOS.items():
            hits = [signal for signal in meta["signals"] if signal in blob]
            score = len(hits)
            if score > best_score:
                best_name = name
                best_score = score
                best_meta = {**meta, "signals": hits}

        secondary: List[str] = []
        signals: List[str] = list(best_meta.get("signals", []))
        prefer: List[str] = list(best_meta.get("prefer", []))
        avoid: List[str] = list(best_meta.get("avoid", []))

        if planning_mode == "nearby_quick":
            secondary.append("nearby_quick")

        for name, meta in self.CROSS_CUTTING.items():
            hits = [signal for signal in meta["signals"] if signal in blob]
            if hits or (name == "nearby_quick" and planning_mode == "nearby_quick"):
                if name not in secondary:
                    secondary.append(name)
                signals.extend(hits)
                prefer.extend(meta["prefer"])
                avoid.extend(meta["avoid"])

        group_details = parsed_intent.get("group_details") or {}
        if group_details.get("has_children") and best_name not in ("family_kid", "family_mixed"):
            secondary.append("family_kid")
            prefer.extend(self.SCENARIOS["family_kid"]["prefer"])
            avoid.extend(self.SCENARIOS["family_kid"]["avoid"])
        if group_details.get("has_elderly") and best_name not in ("family_elderly", "family_mixed"):
            secondary.append("family_elderly")
            prefer.extend(self.SCENARIOS["family_elderly"]["prefer"])
            avoid.extend(self.SCENARIOS["family_elderly"]["avoid"])

        confidence = min(0.95, 0.55 + best_score * 0.12 + len(secondary) * 0.04)
        if best_name == "friend_casual" and not signals:
            confidence = 0.45

        return ScenarioResult(
            primary=best_name,
            secondary=list(dict.fromkeys(secondary)),
            confidence=round(confidence, 2),
            signals=list(dict.fromkeys(signals)),
            prefer=list(dict.fromkeys(prefer))[:12],
            avoid=list(dict.fromkeys(avoid))[:12],
            tone=best_meta.get("tone", "轻松、实用、可执行"),
        ).to_dict()


_scenario_detector: ScenarioDetector | None = None


def get_scenario_detector() -> ScenarioDetector:
    """获取进程级场景识别器。"""
    global _scenario_detector
    if _scenario_detector is None:
        _scenario_detector = ScenarioDetector()
    return _scenario_detector
