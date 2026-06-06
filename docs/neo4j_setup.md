# Neo4j Setup For Graph Memory RAG

> 2026-06-04: Neo4j 是可选图谱记忆层。SQLite 负责可靠存储原始事件，Neo4j 负责展示和推理用户-场景-偏好-地点关系。

## 1. Start Neo4j Desktop Instance

In Neo4j Desktop:

1. Open the `Trip` instance.
2. Click `Start`.
3. Wait until the status changes from `STOPPED` to running.
4. Confirm the connection URI is:

```text
neo4j://127.0.0.1:7687
```

Your screenshot already shows this URI.

## 2. Configure Backend `.env`

Edit:

```text
backend/.env
```

Set:

```env
NEO4J_ENABLED=true
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_real_neo4j_password
NEO4J_DATABASE=neo4j
```

Important:

- `NEO4J_PASSWORD` must be the password you set in Neo4j Desktop.
- If you want to use your `trip1` database later, set `NEO4J_DATABASE=trip1`.
- For the first run, `neo4j` is recommended because it is always present.

## 3. Install Python Dependency

From:

```text
backend
```

Run:

```powershell
pip install -r requirements.txt
```

This installs:

```text
neo4j
```

## 4. Start Backend

From:

```text
backend
```

Run:

```powershell
python run.py
```

If connection works, startup logs should show:

```text
[OK] Neo4j图谱记忆已连接: neo4j://127.0.0.1:7687 / neo4j
```

If Neo4j is not running or password is wrong, logs will show:

```text
[WARN] Neo4j图谱记忆已启用但不可用: ...
```

The main activity planner will still run.

## 5. Current Implementation Status

Implemented:

- Neo4j config fields
- optional graph memory service
- startup health check
- shutdown cleanup
- uniqueness constraints for graph nodes
- 2026-06-04: feedback memory graph sync
- 2026-06-04: display name normalization for graph visualization

## 6. Recommended Graph View

2026-06-04: 主图已经收敛为“用户 -> 场景 -> 地点 -> 反馈标签”。SQLite 保存原始反馈事件，Neo4j 只展示凝练后的记忆画像。
比赛展示时建议看“用户画像主图”：

```cypher
MATCH p=(u:User {user_id: "WMY"})-[:HAS_SCENARIO]->(s:UserScenario)
OPTIONAL MATCH p1=(s)-[:LIKES_PLACE|DISLIKES_PLACE]->(place:Place)
OPTIONAL MATCH p2=(place)-[:HAS_POSITIVE_FEEDBACK|HAS_NEGATIVE_FEEDBACK]->(:Preference)
OPTIONAL MATCH p3=(s)-[:PREFERS|AVOIDS]->(:Preference)
RETURN p, p1, p2, p3
```

这张图应该是：

```text
WMY
  -> 约会场景
      -> 某餐厅/某景点
          -> 出片 / 安静 / 夜景 / 太远
      -> 通用偏好：少排队
  -> 亲子场景
      -> 某公园
          -> 亲子友好 / 户外 / 不想再推荐
```

如果需要追溯“这条记忆从哪次反馈来的”，看 SQLite 的 `memory_events` 表；Neo4j 主图不再写入 `FeedbackEvent`，避免 Browser 里出现 `like/dislike/feedback` 事件节点干扰展示。

## 7. Clean Up Old Display Names

2026-06-04 之后，后端启动时会自动整理旧节点和旧关系：

- `User` 显示为用户 ID，例如 `WMY`
- `UserScenario` 显示为中文场景，例如 `约会场景`
- `Preference` 显示为偏好词，例如 `出片`
- `Place` 显示为地点名
- 删除旧版 `FeedbackEvent` 事件节点
- 删除旧版 `ScenarioType` 公共场景节点和 `OF_TYPE` 关系
- 删除旧版“场景直接连接偏好”的边；有具体地点时，反馈标签应挂在地点下面

如果不想重启后端，也可以在 Neo4j Browser 手动执行：

```cypher
MATCH (u:User)
SET u.name = u.user_id,
    u.display_name = u.user_id;

MATCH (us:UserScenario)
SET us.name = CASE us.scenario
    WHEN 'family_kid' THEN '亲子场景'
    WHEN 'family_elderly' THEN '长辈场景'
    WHEN 'family_mixed' THEN '全家场景'
    WHEN 'couple_date' THEN '约会场景'
    WHEN 'couple_birthday' THEN '生日约会场景'
    WHEN 'friend_drink' THEN '兄弟喝酒场景'
    WHEN 'friend_party' THEN '朋友聚会场景'
    WHEN 'solo_healing' THEN '独处疗愈场景'
    WHEN 'solo_fun' THEN '独自找乐子场景'
    ELSE coalesce(us.scenario, '未识别') + '场景'
END,
us.display_name = us.name,
us.owner_id = coalesce(us.owner_id, us.user_id)
REMOVE us.user_id;

MATCH (p:Preference)
SET p.name = p.key,
    p.display_name = p.key;

MATCH (p:Place)
SET p.display_name = coalesce(p.name, p.key);

MATCH (:UserScenario)-[r:OF_TYPE]->(:ScenarioType)
DELETE r;

MATCH (st:ScenarioType)
DETACH DELETE st;

MATCH (evt:FeedbackEvent)
DETACH DELETE evt;

MATCH (us:UserScenario)-[r:PREFERS|AVOIDS]->(:Preference)
WHERE EXISTS {
    MATCH (us)-[:LIKES_PLACE|DISLIKES_PLACE]->(:Place)
}
DELETE r;
```

## 8. Rebuild Graph From SQLite

2026-06-04: 如果你先清理了旧版 `场景 -> 偏好` 边，可能会看到蓝色反馈标签暂时消失。原因是旧图的标签还没有重放到新的 `地点 -> 反馈标签` 结构。

不要重新手动反馈，直接调用重建接口：

```powershell
curl -X POST "http://127.0.0.1:8000/api/activity/memory/rebuild-graph?user_id=WMY"
```

重建后再查主图：

```cypher
MATCH p=(u:User {user_id: "WMY"})-[:HAS_SCENARIO]->(s:UserScenario)
OPTIONAL MATCH p1=(s)-[:LIKES_PLACE|DISLIKES_PLACE]->(place:Place)
OPTIONAL MATCH p2=(place)-[:HAS_POSITIVE_FEEDBACK|HAS_NEGATIVE_FEEDBACK]->(:Preference)
OPTIONAL MATCH p3=(s)-[:PREFERS|AVOIDS]->(:Preference)
RETURN p, p1, p2, p3
```
