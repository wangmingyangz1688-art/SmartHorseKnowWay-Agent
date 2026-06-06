"""Neo4j 图谱记忆服务。

2026-06-04: Neo4j 作为可选 Graph Memory RAG 层；未配置或不可用时，
活动规划仍然依赖 SQLite 记忆 MVP 正常运行。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..config import get_settings

_graph_memory_service: Optional["GraphMemoryService"] = None


class GraphMemoryService:
    """Neo4j 封装：维护 User -> UserScenario -> Place -> Preference 的图谱结构。"""

    SCENARIO_LABELS = {
        "family_kid": "亲子场景",
        "family_elderly": "长辈场景",
        "family_mixed": "全家场景",
        "couple_date": "约会场景",
        "couple_birthday": "生日约会场景",
        "friend_drink": "兄弟喝酒场景",
        "friend_party": "朋友聚会场景",
        "friend_casual": "朋友随性场景",
        "solo_healing": "独处疗愈场景",
        "solo_fun": "独自找乐子场景",
        "solo_work_leisure": "独处轻办公场景",
        "unknown": "未识别场景",
    }

    def __init__(self):
        self.settings = get_settings()
        self._driver = None
        self._available = False
        self._error = ""

        if not self.settings.neo4j_enabled:
            self._error = "Neo4j disabled by config"
            return

        try:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            self._driver.verify_connectivity()
            self._available = True
            self._ensure_constraints()
        except Exception as exc:
            self._available = False
            self._error = str(exc)
            if self._driver:
                try:
                    self._driver.close()
                except Exception:
                    pass
            self._driver = None

    @property
    def available(self) -> bool:
        return self._available

    def health(self) -> Dict[str, Any]:
        """Return a safe health payload for startup logs and API checks."""
        return {
            "enabled": self.settings.neo4j_enabled,
            "available": self._available,
            "uri": self.settings.neo4j_uri,
            "database": self.settings.neo4j_database,
            "error": self._error,
        }

    def close(self) -> None:
        if self._driver:
            self._driver.close()
            self._driver = None
            self._available = False

    def _ensure_constraints(self) -> None:
        """2026-06-04: 创建主记忆图约束，主图保留用户、场景、地点和地点反馈标签。"""
        if not self._driver:
            return

        statements = [
            "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE",
            "CREATE CONSTRAINT user_scenario_key IF NOT EXISTS FOR (s:UserScenario) REQUIRE s.key IS UNIQUE",
            "CREATE CONSTRAINT preference_key IF NOT EXISTS FOR (p:Preference) REQUIRE p.key IS UNIQUE",
            "CREATE CONSTRAINT place_key IF NOT EXISTS FOR (p:Place) REQUIRE p.key IS UNIQUE",
        ]
        with self._driver.session(database=self.settings.neo4j_database) as session:
            for statement in statements:
                session.run(statement)

    def upsert_feedback_memory(self, event: Dict[str, Any], extracted: list[Dict[str, Any]]) -> None:
        """2026-06-04: 将反馈凝练为干净主图关系；原始事件证据保留在 SQLite。"""
        if not self._available or not self._driver:
            return

        with self._driver.session(database=self.settings.neo4j_database) as session:
            session.execute_write(self._write_feedback_tx, event, extracted)

    def normalize_display_names(self) -> None:
        """2026-06-04: 整理旧图谱，确保主图呈现 User -> 场景 -> 地点 -> 反馈标签。"""
        if not self._available or not self._driver:
            return
        with self._driver.session(database=self.settings.neo4j_database) as session:
            session.run(
                """
                MATCH (u:User)
                SET u.name = u.user_id,
                    u.display_name = u.user_id
                """
            )
            session.run(
                """
                MATCH (us:UserScenario)
                SET us.name = CASE us.scenario
                    WHEN 'family_kid' THEN '亲子场景'
                    WHEN 'family_elderly' THEN '长辈场景'
                    WHEN 'family_mixed' THEN '全家场景'
                    WHEN 'couple_date' THEN '约会场景'
                    WHEN 'couple_birthday' THEN '生日约会场景'
                    WHEN 'friend_drink' THEN '兄弟喝酒场景'
                    WHEN 'friend_party' THEN '朋友聚会场景'
                    WHEN 'friend_casual' THEN '朋友随性场景'
                    WHEN 'solo_healing' THEN '独处疗愈场景'
                    WHEN 'solo_fun' THEN '独自找乐子场景'
                    WHEN 'solo_work_leisure' THEN '独处轻办公场景'
                    ELSE coalesce(us.scenario, '未识别') + '场景'
                END,
                us.display_name = us.name,
                us.owner_id = coalesce(us.owner_id, us.user_id)
                REMOVE us.user_id
                """
            )
            session.run("MATCH (p:Preference) SET p.name = p.key, p.display_name = p.key")
            session.run("MATCH (p:Place) SET p.display_name = coalesce(p.name, p.key)")
            # 2026-06-04: 主图不展示事件证据链和公共场景类型，避免 Neo4j Browser 里用户画像发散混乱。
            session.run("MATCH (:UserScenario)-[r:OF_TYPE]->(:ScenarioType) DELETE r")
            session.run("MATCH (st:ScenarioType) DETACH DELETE st")
            session.run("MATCH (evt:FeedbackEvent) DETACH DELETE evt")
            # 2026-06-04: 地点存在时，反馈标签应挂到地点下；旧版直接挂在场景下的偏好边需要清理后重新沉淀。
            session.run(
                """
                MATCH (us:UserScenario)-[r:PREFERS|AVOIDS]->(pref:Preference)
                WHERE EXISTS {
                    MATCH (us)-[:LIKES_PLACE|DISLIKES_PLACE]->(:Place)
                }
                DELETE r
                """
            )

    def clear_user_profile(self, user_id: str) -> None:
        """2026-06-04: 重建前清理某个用户的 Neo4j 画像图，保留 SQLite 原始反馈作为数据源。"""
        if not self._available or not self._driver:
            return
        with self._driver.session(database=self.settings.neo4j_database) as session:
            session.run(
                """
                MATCH (u:User {user_id: $user_id})-[:HAS_SCENARIO]->(us:UserScenario)
                DETACH DELETE us
                """,
                {"user_id": user_id},
            )
            session.run(
                """
                MATCH (p:Place)
                WHERE NOT (p)--()
                DELETE p
                """
            )
            session.run(
                """
                MATCH (p:Preference)
                WHERE NOT (p)--()
                DELETE p
                """
            )

    @staticmethod
    def _write_feedback_tx(tx, event: Dict[str, Any], extracted: list[Dict[str, Any]]) -> None:
        user_id = event.get("user_id", "demo_user")
        scenario = event.get("scenario", "unknown")
        user_scenario_key = f"{user_id}::{scenario}"
        scenario_label = GraphMemoryService.SCENARIO_LABELS.get(scenario, f"{scenario}场景")

        # 2026-06-04: UserScenario 直接作为用户下的中文场景节点，不再额外连接 ScenarioType。
        tx.run(
            """
            MERGE (u:User {user_id: $user_id})
              ON CREATE SET u.created_at = $created_at
            SET u.last_seen = $created_at,
                u.name = $user_id,
                u.display_name = $user_id
            MERGE (us:UserScenario {key: $user_scenario_key})
              ON CREATE SET us.created_at = $created_at
            SET us.owner_id = $user_id,
                us.scenario = $scenario,
                us.name = $scenario_label,
                us.display_name = $scenario_label,
                us.last_seen = $created_at
            REMOVE us.user_id
            MERGE (u)-[:HAS_SCENARIO]->(us)
            """,
            {
                "user_id": user_id,
                "scenario": scenario,
                "scenario_label": scenario_label,
                "user_scenario_key": user_scenario_key,
                "event_id": event.get("event_id"),
                "event_type": event.get("event_type", ""),
                "feedback_text": event.get("feedback_text", ""),
                "target_type": event.get("target_type", ""),
                "target_name": event.get("target_name", ""),
                "created_at": event.get("created_at", ""),
            },
        )

        if event.get("target_name"):
            tx.run(
                """
                MERGE (place:Place {key: $place_key})
                SET place.name = $target_name,
                    place.display_name = $target_name,
                    place.type = $target_type,
                    place.last_seen = $created_at
                """,
                {
                    "event_id": event.get("event_id"),
                    "place_key": f"{event.get('target_type', 'place')}::{event.get('target_name')}",
                    "target_name": event.get("target_name"),
                    "target_type": event.get("target_type", ""),
                    "created_at": event.get("created_at", ""),
                },
            )

        for memory in extracted:
            GraphMemoryService._write_extracted_memory(tx, event, memory, user_scenario_key)

    @staticmethod
    def _write_extracted_memory(tx, event: Dict[str, Any], memory: Dict[str, Any], user_scenario_key: str) -> None:
        relation = memory.get("relation", "")
        value = memory.get("value", "")
        if not value:
            return

        base_params = {
            "user_id": event.get("user_id", "demo_user"),
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type", ""),
            "user_scenario_key": user_scenario_key,
            "preference_key": value,
            "confidence": float(memory.get("confidence", 0.65)),
            "reason": memory.get("reason", ""),
            "created_at": event.get("created_at", ""),
        }

        if relation in ("PREFERS", "AVOIDS"):
            rel_type = "PREFERS" if relation == "PREFERS" else "AVOIDS"
            target_name = event.get("target_name")
            target_type = event.get("target_type") or "place"
            if target_name:
                # 2026-06-04: 有具体地点时，反馈标签挂在地点下面，而不是和地点并列挂在场景下面。
                place_key = f"{target_type}::{target_name}"
                place_rel = "HAS_POSITIVE_FEEDBACK" if relation == "PREFERS" else "HAS_NEGATIVE_FEEDBACK"
                scenario_place_rel = (
                    "DISLIKES_PLACE"
                    if relation == "AVOIDS" or event.get("event_type") in ("dislike", "avoid", "skip")
                    else "LIKES_PLACE"
                )
                tx.run(
                    f"""
                    MATCH (us:UserScenario {{key: $user_scenario_key}})
                    MERGE (place:Place {{key: $place_key}})
                    SET place.name = $target_name,
                        place.display_name = $target_name,
                        place.type = $target_type,
                        place.last_seen = $created_at
                    MERGE (us)-[sr:{scenario_place_rel}]->(place)
                      ON CREATE SET sr.evidence_count = 0
                    SET sr.evidence_count = sr.evidence_count + 1,
                        sr.last_event_id = $event_id,
                        sr.last_event_type = $event_type,
                        sr.last_seen = $created_at
                    MERGE (pref:Preference {{key: $preference_key}})
                    SET pref.name = $preference_key,
                        pref.display_name = $preference_key
                    MERGE (place)-[r:{place_rel}]->(pref)
                      ON CREATE SET r.evidence_count = 0
                    SET r.evidence_count = r.evidence_count + 1,
                        r.last_event_id = $event_id,
                        r.last_event_type = $event_type,
                        r.confidence = CASE
                          WHEN r.confidence IS NULL THEN $confidence
                          WHEN r.confidence + 0.03 > 0.95 THEN 0.95
                          ELSE r.confidence + 0.03
                        END,
                        r.last_seen = $created_at,
                        r.reason = $reason
                    """,
                    {
                        **base_params,
                        "place_key": place_key,
                        "target_name": target_name,
                        "target_type": target_type,
                    },
                )
                return

            # 2026-06-04: 没有具体地点对象时，才把通用偏好直接挂到场景节点。
            tx.run(
                f"""
                MATCH (us:UserScenario {{key: $user_scenario_key}})
                MERGE (pref:Preference {{key: $preference_key}})
                SET pref.name = $preference_key,
                    pref.display_name = $preference_key
                MERGE (us)-[r:{rel_type}]->(pref)
                  ON CREATE SET r.evidence_count = 0
                SET r.evidence_count = r.evidence_count + 1,
                    r.last_event_id = $event_id,
                    r.last_event_type = $event_type,
                    r.confidence = CASE
                      WHEN r.confidence IS NULL THEN $confidence
                      WHEN r.confidence + 0.03 > 0.95 THEN 0.95
                      ELSE r.confidence + 0.03
                    END,
                    r.last_seen = $created_at,
                    r.reason = $reason
                """,
                base_params,
            )
            return

        if relation in ("LIKES_PLACE", "DISLIKES_PLACE"):
            target_name = memory.get("target_name") or event.get("target_name")
            target_type = memory.get("target_type") or event.get("target_type") or "place"
            if not target_name:
                return
            place_key = f"{target_type}::{target_name}"
            rel_type = "LIKES_PLACE" if relation == "LIKES_PLACE" else "DISLIKES_PLACE"
            tx.run(
                f"""
                MATCH (us:UserScenario {{key: $user_scenario_key}})
                MERGE (place:Place {{key: $place_key}})
                SET place.name = $target_name,
                    place.display_name = $target_name,
                    place.type = $target_type,
                    place.last_seen = $created_at
                MERGE (us)-[r:{rel_type}]->(place)
                  ON CREATE SET r.evidence_count = 0
                SET r.evidence_count = r.evidence_count + 1,
                    r.last_event_id = $event_id,
                    r.last_event_type = $event_type,
                    r.confidence = CASE
                      WHEN r.confidence IS NULL THEN $confidence
                      WHEN r.confidence + 0.03 > 0.95 THEN 0.95
                      ELSE r.confidence + 0.03
                    END,
                    r.reason = $reason,
                    r.last_seen = $created_at
                """,
                {
                    **base_params,
                    "place_key": place_key,
                    "target_name": target_name,
                    "target_type": target_type,
                },
            )


def get_graph_memory_service() -> GraphMemoryService:
    """Return process-wide optional graph memory service."""
    global _graph_memory_service
    if _graph_memory_service is None:
        _graph_memory_service = GraphMemoryService()
    return _graph_memory_service
