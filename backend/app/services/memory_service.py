"""轻量记忆服务 - SQLite 事件日志与三层记忆凝练"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .graph_memory_service import get_graph_memory_service


TECHNICAL_MEMORY_TAGS = {"真实POI", "交通"}
FEEDBACK_ACTION_TAGS = {"不想再推荐", "下次别推", "别推荐", "不要再推荐", "不推荐", "换一个", "不喜欢这个"}


def _filter_memory_tags(tags: Optional[List[str]]) -> List[str]:
    """2026-06-06: 过滤内部技术标签和反馈动作词，避免它们被当成可泛化用户偏好。"""
    clean: List[str] = []
    for tag in tags or []:
        value = str(tag).strip()
        if not value or value in TECHNICAL_MEMORY_TAGS or value in FEEDBACK_ACTION_TAGS:
            continue
        if value not in clean:
            clean.append(value)
    return clean


@dataclass
class ExtractedMemory:
    """单次反馈提炼出的记忆片段"""

    level: str
    relation: str
    key: str
    value: str
    target_type: str = ""
    target_name: str = ""
    confidence: float = 0.65
    reason: str = ""


class MemoryExtractor:
    """2026-06-04: 从自然语言反馈中凝练用户级、场景级、对象级记忆。"""

    NEGATIVE_RULES = {
        "太远": ["太远", "远", "折腾", "跨区"],
        "排队久": ["排队", "等位", "等太久", "人太多"],
        "太贵": ["太贵", "贵", "预算", "不划算"],
        "太累": ["太累", "走不动", "累", "暴走"],
        "太吵": ["太吵", "吵", "嘈杂"],
        "重油重辣": ["太油", "油腻", "重油", "太辣", "重口"],
        "不适合孩子": ["不适合孩子", "不适合小孩", "孩子不喜欢"],
        "不适合老人": ["不适合老人", "爸妈累", "父母累"],
    }
    FEEDBACK_ACTION_RULES = ["下次别推", "别推荐", "不要再推荐", "不想再推荐", "不推荐", "换一个", "不喜欢这个"]
    POSITIVE_RULES = {
        "近距离": ["离得近", "很近", "方便", "不远"],
        "少排队": ["不用排队", "排队少", "不用等"],
        "适合聊天": ["适合聊天", "能聊天", "坐下来聊"],
        "安静": ["安静", "清净", "不吵"],
        "出片": ["出片", "好拍", "拍照好看"],
        "亲子友好": ["适合孩子", "孩子喜欢", "亲子", "儿童"],
        "清淡健康": ["清淡", "健康", "低卡", "少油"],
        "氛围好": ["氛围好", "有感觉", "浪漫", "舒服"],
    }

    def extract(
        self,
        *,
        event_type: str,
        feedback_text: str,
        scenario: str,
        target_type: str = "",
        target_name: str = "",
        tags: Optional[List[str]] = None,
    ) -> List[ExtractedMemory]:
        text = feedback_text or ""
        tags = _filter_memory_tags(tags)
        memories: List[ExtractedMemory] = []

        negative_hits = self._match_rules(text, self.NEGATIVE_RULES)
        positive_hits = self._match_rules(text, self.POSITIVE_RULES)
        # 2026-06-06: 反馈动作词只决定对象级 DISLIKES_PLACE，不再生成“不想再推荐”偏好节点。
        action_rejects_target = event_type in ("dislike", "avoid", "skip") or self._has_feedback_action(text)
        if event_type in ("like", "execute", "copy_share"):
            positive_hits.extend(tags[:3])

        for value in dict.fromkeys(positive_hits):
            memories.append(ExtractedMemory(
                level="scenario",
                relation="PREFERS",
                key="prefer_tag",
                value=value,
                confidence=0.75 if event_type == "like" else 0.6,
                reason=text,
            ))
        for value in dict.fromkeys(negative_hits):
            memories.append(ExtractedMemory(
                level="scenario",
                relation="AVOIDS",
                key="avoid_tag",
                value=value,
                confidence=0.8,
                reason=text,
            ))

        if target_name:
            if event_type in ("like", "execute"):
                memories.append(ExtractedMemory(
                    level="object",
                    relation="LIKES_PLACE",
                    key="place_like",
                    value=target_name,
                    target_type=target_type,
                    target_name=target_name,
                    confidence=0.85 if event_type == "like" else 0.7,
                    reason=text,
                ))
            if action_rejects_target or negative_hits:
                memories.append(ExtractedMemory(
                    level="object",
                    relation="DISLIKES_PLACE",
                    key="place_dislike",
                    value=target_name,
                    target_type=target_type,
                    target_name=target_name,
                    confidence=0.85,
                    reason=text,
                ))

        for tag in tags[:6]:
            if event_type in ("like", "execute"):
                memories.append(ExtractedMemory(
                    level="scenario",
                    relation="PREFERS",
                    key="prefer_tag",
                    value=str(tag),
                    confidence=0.58,
                    reason=f"来自推荐标签：{tag}",
                ))

        return memories

    def _match_rules(self, text: str, rules: Dict[str, List[str]]) -> List[str]:
        hits: List[str] = []
        for value, keywords in rules.items():
            if any(keyword in text for keyword in keywords):
                hits.append(value)
        return hits

    def _has_feedback_action(self, text: str) -> bool:
        """2026-06-06: 识别“下次别推/换一个”等动作词，只用于决定是否避开当前对象。"""
        return any(keyword in text for keyword in self.FEEDBACK_ACTION_RULES)


class MemoryService:
    """2026-06-04: SQLite 保存原始反馈与凝练记忆，Neo4j 可用时同步成图谱关系。"""

    def __init__(self):
        # 2026-06-04: 记忆数据库固定放在 backend/data，避免写进 app 包目录
        root = Path(__file__).resolve().parents[3]
        self.db_path = root / "data" / "activity_memory.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.extractor = MemoryExtractor()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_events (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    target_type TEXT DEFAULT '',
                    target_name TEXT DEFAULT '',
                    tags_json TEXT DEFAULT '[]',
                    feedback_text TEXT DEFAULT '',
                    raw_text TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_profile_memory (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL DEFAULT 0.6,
                    evidence_count INTEGER DEFAULT 1,
                    last_seen TEXT NOT NULL,
                    UNIQUE(user_id, key, value, relation)
                );
                CREATE TABLE IF NOT EXISTS scenario_memory (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL DEFAULT 0.6,
                    evidence_count INTEGER DEFAULT 1,
                    last_seen TEXT NOT NULL,
                    UNIQUE(user_id, scenario, key, value, relation)
                );
                CREATE TABLE IF NOT EXISTS object_memory (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    object_type TEXT DEFAULT '',
                    object_name TEXT NOT NULL,
                    preference TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.6,
                    evidence_count INTEGER DEFAULT 1,
                    last_seen TEXT NOT NULL,
                    UNIQUE(user_id, scenario, object_name, preference)
                );
                """
            )

    def record_message_event(
        self,
        *,
        user_id: str,
        scenario: Dict[str, Any],
        message: str,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """保存规划输入弱事件，不直接当成强偏好。"""
        return self.record_event(
            user_id=user_id,
            event_type="message",
            scenario=scenario.get("primary", "unknown"),
            target_type="plan",
            target_name="",
            tags=tags or scenario.get("prefer", []),
            feedback_text="",
            raw_text=message,
            extract=False,
        )

    def record_event(
        self,
        *,
        user_id: str,
        event_type: str,
        scenario: str,
        target_type: str = "",
        target_name: str = "",
        tags: Optional[List[str]] = None,
        feedback_text: str = "",
        raw_text: str = "",
        extract: bool = True,
    ) -> Dict[str, Any]:
        tags = _filter_memory_tags(tags)
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat(timespec="seconds")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_events (
                    id, user_id, event_type, scenario, target_type, target_name,
                    tags_json, feedback_text, raw_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    user_id,
                    event_type,
                    scenario,
                    target_type,
                    target_name,
                    json.dumps(tags, ensure_ascii=False),
                    feedback_text,
                    raw_text,
                    now,
                ),
            )

        extracted: List[ExtractedMemory] = []
        if extract:
            extracted = self.extractor.extract(
                event_type=event_type,
                feedback_text=feedback_text,
                scenario=scenario,
                target_type=target_type,
                target_name=target_name,
                tags=tags,
            )
            self._persist_extracted(user_id, scenario, extracted)
            self._promote_cross_scenario_preferences(user_id)
            self._sync_graph_event(
                event_id=event_id,
                user_id=user_id,
                event_type=event_type,
                scenario=scenario,
                target_type=target_type,
                target_name=target_name,
                tags=tags,
                feedback_text=feedback_text,
                extracted=extracted,
                created_at=now,
            )

        return {
            "event_id": event_id,
            "extracted_count": len(extracted),
            "extracted": [memory.__dict__ for memory in extracted],
        }

    def get_memory_context(self, user_id: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """按当前场景检索三层记忆，作为 Graph Memory RAG 上下文注入 Planner。"""
        primary = scenario.get("primary", "unknown")
        with self._connect() as conn:
            stable = self._fetch_all(
                conn,
                "SELECT key, value, relation, confidence, evidence_count FROM user_profile_memory WHERE user_id=? ORDER BY evidence_count DESC, confidence DESC LIMIT 8",
                (user_id,),
            )
            scene = self._fetch_all(
                conn,
                "SELECT key, value, relation, confidence, evidence_count FROM scenario_memory WHERE user_id=? AND scenario=? ORDER BY evidence_count DESC, confidence DESC LIMIT 12",
                (user_id, primary),
            )
            objects = self._fetch_all(
                conn,
                "SELECT object_type, object_name, preference, reason, confidence, evidence_count FROM object_memory WHERE user_id=? AND scenario=? ORDER BY evidence_count DESC, confidence DESC LIMIT 8",
                (user_id, primary),
            )

        used_labels = _filter_memory_tags([item["value"] for item in stable[:4]] + [item["value"] for item in scene[:6]])
        return {
            "user_id": user_id,
            "scenario": primary,
            "stable_preferences": stable,
            "scenario_preferences": scene,
            "object_memories": objects,
            "used_labels": list(dict.fromkeys(used_labels))[:8],
            "prompt": self._build_memory_prompt(stable, scene, objects, primary),
        }

    def cleanup_technical_tags(self, user_id: str = "") -> Dict[str, Any]:
        """2026-06-06: 清理历史误写入的内部技术标签和反馈动作词，修复“真实POI/不想再推荐”出现在记忆命中里的问题。"""
        scenario_deleted = 0
        profile_deleted = 0
        object_reason_updated = 0
        cleanup_tags = TECHNICAL_MEMORY_TAGS | FEEDBACK_ACTION_TAGS
        with self._connect() as conn:
            for tag in cleanup_tags:
                if user_id:
                    cur = conn.execute(
                        "DELETE FROM scenario_memory WHERE user_id=? AND value=?",
                        (user_id, tag),
                    )
                    scenario_deleted += cur.rowcount or 0
                    cur = conn.execute(
                        "DELETE FROM user_profile_memory WHERE user_id=? AND value=?",
                        (user_id, tag),
                    )
                    profile_deleted += cur.rowcount or 0
                    cur = conn.execute(
                        "UPDATE object_memory SET reason='' WHERE user_id=? AND reason=?",
                        (user_id, tag),
                    )
                    object_reason_updated += cur.rowcount or 0
                else:
                    cur = conn.execute("DELETE FROM scenario_memory WHERE value=?", (tag,))
                    scenario_deleted += cur.rowcount or 0
                    cur = conn.execute("DELETE FROM user_profile_memory WHERE value=?", (tag,))
                    profile_deleted += cur.rowcount or 0
                    cur = conn.execute("UPDATE object_memory SET reason='' WHERE reason=?", (tag,))
                    object_reason_updated += cur.rowcount or 0
        return {
            "scenario_deleted": scenario_deleted,
            "profile_deleted": profile_deleted,
            "object_reason_updated": object_reason_updated,
            "filtered_tags": sorted(cleanup_tags),
        }

    def get_summary(self, user_id: str) -> Dict[str, Any]:
        """给前端展示的轻量记忆摘要。"""
        with self._connect() as conn:
            stable = self._fetch_all(
                conn,
                "SELECT value, relation, evidence_count FROM user_profile_memory WHERE user_id=? ORDER BY evidence_count DESC LIMIT 8",
                (user_id,),
            )
            scenes = self._fetch_all(
                conn,
                "SELECT scenario, value, relation, evidence_count FROM scenario_memory WHERE user_id=? ORDER BY last_seen DESC LIMIT 12",
                (user_id,),
            )
            recent = self._fetch_all(
                conn,
                "SELECT event_type, scenario, target_name, feedback_text, created_at FROM memory_events WHERE user_id=? ORDER BY created_at DESC LIMIT 6",
                (user_id,),
            )
        return {"user_id": user_id, "stable": stable, "scenes": scenes, "recent_events": recent}

    def rebuild_graph_for_user(self, user_id: str) -> Dict[str, Any]:
        """2026-06-04: 从 SQLite 原始反馈重建某个用户的 Neo4j 主画像图，适配新的 场景->地点->反馈标签 结构。"""
        graph = get_graph_memory_service()
        if not graph.available:
            return {
                "rebuilt": False,
                "reason": "Neo4j 未连接，SQLite 记忆仍可正常使用",
                "event_count": 0,
            }

        with self._connect() as conn:
            rows = self._fetch_all(
                conn,
                """
                SELECT id, user_id, event_type, scenario, target_type, target_name,
                       tags_json, feedback_text, raw_text, created_at
                FROM memory_events
                WHERE user_id=? AND feedback_text <> ''
                ORDER BY created_at ASC
                """,
                (user_id,),
            )

        graph.clear_user_profile(user_id)
        rebuilt_count = 0
        for row in rows:
            try:
                tags = json.loads(row.get("tags_json") or "[]")
            except Exception:
                tags = []
            extracted = self.extractor.extract(
                event_type=row["event_type"],
                feedback_text=row["feedback_text"],
                scenario=row["scenario"],
                target_type=row["target_type"],
                target_name=row["target_name"],
                tags=tags,
            )
            graph.upsert_feedback_memory(
                event={
                    "event_id": row["id"],
                    "user_id": row["user_id"],
                    "event_type": row["event_type"],
                    "scenario": row["scenario"],
                    "target_type": row["target_type"],
                    "target_name": row["target_name"],
                    "tags": tags,
                    "feedback_text": row["feedback_text"],
                    "created_at": row["created_at"],
                },
                extracted=[memory.__dict__ for memory in extracted],
            )
            rebuilt_count += 1

        graph.normalize_display_names()
        return {
            "rebuilt": True,
            "user_id": user_id,
            "event_count": rebuilt_count,
            "message": "Neo4j 用户画像图已按新结构重建",
        }

    def rebuild_memories_from_events(self, user_id: str = "") -> Dict[str, Any]:
        """2026-06-06: 使用最新抽取规则重建 SQLite 凝练记忆，并同步重建 Neo4j 用户画像。"""
        with self._connect() as conn:
            if user_id:
                conn.execute("DELETE FROM scenario_memory WHERE user_id=?", (user_id,))
                conn.execute("DELETE FROM object_memory WHERE user_id=?", (user_id,))
                conn.execute("DELETE FROM user_profile_memory WHERE user_id=?", (user_id,))
            else:
                conn.execute("DELETE FROM scenario_memory")
                conn.execute("DELETE FROM object_memory")
                conn.execute("DELETE FROM user_profile_memory")

            query = """
                SELECT id, user_id, event_type, scenario, target_type, target_name,
                       tags_json, feedback_text, raw_text, created_at
                FROM memory_events
                WHERE feedback_text <> ''
            """
            params: tuple[Any, ...] = ()
            if user_id:
                query += " AND user_id=?"
                params = (user_id,)
            query += " ORDER BY created_at ASC"
            rows = self._fetch_all(conn, query, params)

        rebuilt_count = 0
        rebuilt_users: set[str] = set()
        for row in rows:
            try:
                tags = json.loads(row.get("tags_json") or "[]")
            except Exception:
                tags = []
            extracted = self.extractor.extract(
                event_type=row["event_type"],
                feedback_text=row["feedback_text"],
                scenario=row["scenario"],
                target_type=row["target_type"],
                target_name=row["target_name"],
                tags=tags,
            )
            self._persist_extracted(row["user_id"], row["scenario"], extracted)
            rebuilt_users.add(row["user_id"])
            rebuilt_count += 1

        for uid in rebuilt_users:
            self._promote_cross_scenario_preferences(uid)
            try:
                self.rebuild_graph_for_user(uid)
            except Exception as exc:
                print(f"[WARN] Neo4j用户画像重建失败: {exc}")

        return {
            "success": True,
            "user_id": user_id or "ALL",
            "rebuilt_events": rebuilt_count,
            "rebuilt_users": sorted(rebuilt_users),
        }

    def _persist_extracted(self, user_id: str, scenario: str, memories: List[ExtractedMemory]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            for memory in memories:
                if memory.level == "scenario":
                    self._upsert_memory(
                        conn,
                        "scenario_memory",
                        {
                            "id": f"sm_{uuid.uuid4().hex[:12]}",
                            "user_id": user_id,
                            "scenario": scenario,
                            "key": memory.key,
                            "value": memory.value,
                            "relation": memory.relation,
                            "confidence": memory.confidence,
                            "last_seen": now,
                        },
                        ["user_id", "scenario", "key", "value", "relation"],
                    )
                elif memory.level == "object" and memory.target_name:
                    self._upsert_memory(
                        conn,
                        "object_memory",
                        {
                            "id": f"om_{uuid.uuid4().hex[:12]}",
                            "user_id": user_id,
                            "scenario": scenario,
                            "object_type": memory.target_type,
                            "object_name": memory.target_name,
                            "preference": memory.relation,
                            "reason": memory.reason,
                            "confidence": memory.confidence,
                            "last_seen": now,
                        },
                        ["user_id", "scenario", "object_name", "preference"],
                    )

    def _promote_cross_scenario_preferences(self, user_id: str) -> None:
        """同一偏好跨至少两个场景、多次出现时升级为用户级稳定记忆。"""
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            rows = self._fetch_all(
                conn,
                """
                SELECT key, value, relation, COUNT(DISTINCT scenario) AS scenario_count,
                       SUM(evidence_count) AS total_evidence, AVG(confidence) AS avg_confidence
                FROM scenario_memory
                WHERE user_id=?
                GROUP BY key, value, relation
                HAVING scenario_count >= 2 AND total_evidence >= 3
                """,
                (user_id,),
            )
            for row in rows:
                self._upsert_memory(
                    conn,
                    "user_profile_memory",
                    {
                        "id": f"up_{uuid.uuid4().hex[:12]}",
                        "user_id": user_id,
                        "key": row["key"],
                        "value": row["value"],
                        "relation": row["relation"],
                        "confidence": min(0.95, float(row["avg_confidence"] or 0.7) + 0.1),
                        "last_seen": now,
                    },
                    ["user_id", "key", "value", "relation"],
                )

    def _sync_graph_event(
        self,
        *,
        event_id: str,
        user_id: str,
        event_type: str,
        scenario: str,
        target_type: str,
        target_name: str,
        tags: List[str],
        feedback_text: str,
        extracted: List[ExtractedMemory],
        created_at: str,
    ) -> None:
        try:
            graph = get_graph_memory_service()
            if not graph.available:
                return
            graph.upsert_feedback_memory(
                event={
                    "event_id": event_id,
                    "user_id": user_id,
                    "event_type": event_type,
                    "scenario": scenario,
                    "target_type": target_type,
                    "target_name": target_name,
                    "tags": tags,
                    "feedback_text": feedback_text,
                    "created_at": created_at,
                },
                extracted=[memory.__dict__ for memory in extracted],
            )
        except Exception as exc:
            print(f"[WARN] Neo4j记忆同步失败: {exc}")

    def _build_memory_prompt(self, stable: List[dict], scene: List[dict], objects: List[dict], scenario: str) -> str:
        if not stable and not scene and not objects:
            return "暂无可用历史记忆。"

        lines = ["【Graph Memory RAG 检索到的用户记忆】"]
        if stable:
            lines.append("跨场景稳定偏好：")
            for item in stable:
                verb = "偏好" if item["relation"] in ("PREFERS", "HAS_STABLE_PREFERENCE") else "避免"
                lines.append(f"- 用户多次反馈{verb}：{item['value']}（证据{item['evidence_count']}次）")
        if scene:
            lines.append(f"当前场景 {scenario} 的偏好/避雷：")
            for item in scene:
                verb = "偏好" if item["relation"] == "PREFERS" else "避免"
                lines.append(f"- {verb}：{item['value']}（证据{item['evidence_count']}次）")
        if objects:
            lines.append("对象级记忆：")
            for item in objects:
                verb = "喜欢" if item["preference"] == "LIKES_PLACE" else "避开"
                reason = f"，原因：{item['reason']}" if item.get("reason") else ""
                lines.append(f"- {verb}{item['object_name']}{reason}")
        return "\n".join(lines)

    def _fetch_all(self, conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[dict]:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def _upsert_memory(self, conn: sqlite3.Connection, table: str, values: Dict[str, Any], keys: List[str]) -> None:
        columns = list(values.keys())
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join([
            "evidence_count = evidence_count + 1",
            "confidence = MIN(0.95, MAX(confidence, excluded.confidence) + 0.03)",
            "last_seen = excluded.last_seen",
        ])
        if "reason" in columns:
            updates += ", reason = excluded.reason"
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT({', '.join(keys)}) DO UPDATE SET {updates}"
        )
        conn.execute(sql, tuple(values[col] for col in columns))


_memory_service: MemoryService | None = None


def get_memory_service() -> MemoryService:
    """获取进程级记忆服务。"""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
