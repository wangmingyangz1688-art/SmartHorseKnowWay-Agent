# SmartHorseKnowWay Agent Progress Memory

> 2026-06-04: This file records implementation progress and next tasks for the local activity planning competition project.

## Current Direction

SmartHorseKnowWay_agent is being shaped into a local-life activity planning and execution Agent.

Core competition story:

1. User gives one natural-language goal.
2. Agent detects scenario, time, people, mood, constraints, and location context.
3. Agent searches nearby venues, restaurants, weather, and availability.
4. Agent generates a 4-6 hour executable plan.
5. System validates plan quality.
6. User confirms and the system performs mock booking/order/queue actions.
7. System can learn preferences through lightweight memory.

## Completed

### One-Sentence Planning Mode

- Added two planning modes on Home page:
  - `nearby_quick`: one-sentence nearby arrangement.
  - `detailed`: original detailed form mode.
- Nearby quick mode keeps input lightweight:
  - message
  - city
  - optional district
  - optional browser location
- Backend request now carries `planning_mode` and optional `home_location`.

### Time Intent Parsing

- Added rule-based time parsing for nearby quick mode.
- One-sentence inputs such as `下午1点到5点` should override default form time.
- Examples:
  - `下午1点到5点` -> `13:00`, 4 hours
  - `上午想去玩` -> morning default
  - `晚上出去转转` -> evening default
- Parsed result is attached to plan as `time_intent`.

### ScenarioDetector And Scenario-Sensitive Planning

- Added emotion-aware handling for words like:
  - `失恋`
  - `分手`
  - `心情不好`
  - `散散心`
  - `一个人静静`
  - `emo`
- 2026-06-04: Added standalone `backend/app/services/scenario_detector.py`.
- ScenarioDetector outputs:
  - primary scenario
  - secondary/cross-cutting labels
  - confidence
  - signals
  - prefer/avoid lists
  - tone
- Current scenario candidates include:
  - `family_kid`
  - `family_elderly`
  - `family_mixed`
  - `couple_date`
  - `couple_birthday`
  - `friend_drink`
  - `friend_party`
  - `solo_healing`
  - `solo_fun`
  - `solo_work_leisure`
  - cross-cutting `health_diet`, `nearby_quick`, `relax`
- Venue/restaurant search and planner prompt now read the structured scenario instead of scattering keyword checks everywhere.

### Recommendation Reason Enrichment

- Planner prompt now requires each `play/eat/extra` description to explain why it fits the current user.
- Added backend fallback enrichment for vague descriptions.
- Family/kid examples should mention:
  - kid can move/play
  - parents can participate
  - relaxed family interaction
- Restaurant reasons should mention:
  - nearby transfer
  - kid-friendly
  - light/healthy when relevant
  - low queue or stable taste when relevant

### Parallel Context Fetching

- Backend planning after intent parsing now runs outer context fetches in parallel:
  - venue search
  - restaurant search
  - weather query
  - mock availability
- This replaced the previous mostly serial chain.

### Fast Execution Mode

- 2026-06-04: Added `execution_mode` alongside `planning_mode`.
- Current modes:
  - `fast`: direct Amap POI candidate pool, fewer search-Agent calls, location coordinates locked to real POI candidates when possible.
  - `agent`: original multi-agent deep-search chain, better for explaining the full agent architecture.
- Home page now exposes a lightweight switch:
  - `极速生成`
  - `深度思考`
- Nearby quick defaults to `fast`; detailed planning defaults to `agent`.
- Fast mode still uses the Planner Agent for final timeline composition, but venue/restaurant search context comes from structured POI candidates instead of free-form search-agent text.

### Rule-Based Plan Quality Validation

- Added first-layer rule validator after Planner.
- It checks:
  - structure completeness
  - timeline validity
  - city/location consistency
  - activity composition
  - executable action coverage
  - scenario constraints
  - budget sanity
  - copy/safety issues
- Result is attached as `quality_report`.
- Frontend result page displays quality score and pass/fail status.

### LLM Review Placeholder

- Added placeholder field `llm_quality_report`.
- Full LLM semantic validator is not implemented yet.

### Server Timing

- Backend records end-to-end time from receiving POST to final response.
- Result is attached as `server_timing`.
- Result page displays backend planning time.

### Result Page Local-Life UI

- Result page redesigned toward Meituan/local-life order confirmation style.
- Top summary is compact.
- Map and budget are compressed into overview cards.
- Timeline cards look more like merchant cards.
- Bottom action bar uses orange confirmation style.

### One-Click Execution Closure

- Result page emphasizes executable action confirmation.
- Main flow:
  - confirm plan
  - one-click arrange
  - mock booking/order/query actions

### Order-Like Execution Status

- Backend action results now include order-like status fields:
  - `status`
  - `status_text`
  - `started_at`
  - `completed_at`
  - `timeline`
- Frontend shows:
  - pending
  - processing
  - success/failed

### Retry And Fallback Execution

- Failed actions now include:
  - `retryable`
  - `fallback_action`
  - `fallback_reason`
- Frontend failed action cards show:
  - `重试`
  - `改用备选`
- Restaurant booking failure can propose an alternate restaurant action.

### Graph Memory RAG MVP

- 2026-06-04: Added lightweight `user_id` to planning requests.
- Home page now has a small memory identity control, defaulting to `demo_user`.
- Added SQLite memory service:
  - `backend/app/services/memory_service.py`
  - database path: `backend/data/activity_memory.db`
- SQLite stores:
  - `memory_events`
  - `user_profile_memory`
  - `scenario_memory`
  - `object_memory`
- Added natural-language feedback API:
  - `POST /api/activity/memory/feedback`
  - `GET /api/activity/memory/summary`
- Result page now shows natural-language feedback boxes under each recommendation card.
- Feedback is parsed by rules into:
  - scenario-level preference/avoid memory
  - object-level place like/dislike memory
  - cross-scenario user-level stable memory when repeated across scenarios
- Planning now performs memory retrieval before Planner:
  - ScenarioDetector identifies the current scene.
  - MemoryService retrieves user-level, scene-level, and object-level memories.
  - Planner prompt receives the retrieved memory as Graph Memory RAG context.
- Result page displays memory hits, e.g. `本次参考了你的偏好：少排队、亲子友好`.

### Neo4j Graph Memory Layer

- 2026-06-04: Neo4j remains optional; SQLite is the reliable base.
- Added graph write synchronization in `backend/app/services/graph_memory_service.py`.
- 2026-06-04: Main Neo4j graph was simplified into a clean user profile view; raw feedback events remain in SQLite.
- 2026-06-04: Place-specific feedback now hangs under the place node instead of sitting beside places on the scenario node.
- Graph shape:
  - `(User)-[:HAS_SCENARIO]->(UserScenario)`
  - `(UserScenario)-[:LIKES_PLACE]->(Place)`
  - `(UserScenario)-[:DISLIKES_PLACE]->(Place)`
  - `(Place)-[:HAS_POSITIVE_FEEDBACK]->(Preference)`
  - `(Place)-[:HAS_NEGATIVE_FEEDBACK]->(Preference)`
  - `(UserScenario)-[:PREFERS]->(Preference)` only for generic scenario preferences without a concrete place
  - `(UserScenario)-[:AVOIDS]->(Preference)` only for generic scenario avoids without a concrete place
- `UserScenario` is the key design decision: it isolates each user's scene memory and prevents family/kid preferences from leaking into date/drink/solo scenarios.
- Neo4j Browser should show one user node, e.g. `WMY`, directly connected to Chinese scene nodes such as `约会场景` and `亲子场景`; each scene then expands to places, and each place expands to feedback labels.

### Build/Compatibility Fixes

- Frontend build passes with `npm.cmd run build`.
- Backend edited files pass `py_compile`.
- Removed unused Ant Design Vue global registration because local icon package caused Vite build issues and app did not use Ant Design components.

## Not Completed Yet

### Memory System Hardening

Needed:

- Add a memory clear/export API for demos.
- Improve `MemoryExtractor` with an optional LLM extraction step after the rule extractor.
- Add stronger Unicode/encoding verification on Windows console tests; browser JSON submissions are the main path.

### LLM Semantic Validator

Needed as second validation layer after rule validator.

It should judge:

- whether the plan really matches the user message
- whether tone is appropriate
- whether recommendation reasons are convincing
- whether the plan feels like a real local-life arrangement

Should support at most one repair loop.

### Repair Loop

Needed:

```text
Planner -> RuleValidator -> if error, repair once -> LLMReview -> if bad, repair once -> final
```

Avoid infinite retries.

### Demo Failure Switch

Execution fallback exists, but mock success rate is high.

Needed for competition demo:

- add optional `force_fail_action=true`
- or action param `debug_force_fail`
- so fallback UI can be demonstrated reliably.

### Competition Design Document

Needed near the end:

```text
docs/competition_design.md
```

Must cover:

- planning strategy
- tool call chain
- parallel context fetching
- validation
- execution closure
- fallback/retry
- memory
- exception handling

Keep within 2 pages.

## Important Notes

- Continue adding dated comments for meaningful changes, e.g. `2026-06-04`.
- Preserve existing detailed form mode.
- Do not build a full login system before memory MVP.
- Prefer lightweight `user_id` first, then real auth later if needed.
- Current git root may not be initialized at `E:\Aprocess\TripProject`; use direct file references instead of relying on git diff.
