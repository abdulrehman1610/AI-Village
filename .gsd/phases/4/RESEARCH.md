---
phase: 4
researched_at: 2026-11-24
discovery_level: 2
---

# Phase 4 Research — Reflection, Relationships, Agent Inspector & Time Controls

## Objective

Determine how to implement and integrate all Phase 4 features — threshold-triggered reflections (`importance sum >= 150 -> 3 salient questions -> evidence retrieval -> cited insights -> reflection memories + WS broadcast`, `REQ-09`), pairwise relationship tracking & REST graph data (`GET /relationships`, `REQ-10` backend), clickable Agent Inspector (`GET /agents`, `GET /agents/{id}`, Phaser sprite/HUD click + side panel, `REQ-11`), and Simulation Time Controls (`POST /sim/start`, `POST /sim/pause`, `POST /sim/speed` for `1x/4x/16x` + HUD playback controls, `REQ-12`) — cleanly atop Phase 3's cognitive engine without breaking spatial invariants (`NFR-05`), LLM call budgets (`NFR-02`), keyboard focus guards, or existing Phase 1–3 tests.

## Discovery Level

**Level 2** — Standard codebase & integration research across `backend/llm/`, `backend/memory/`, `backend/agents/`, `backend/sim/`, `backend/api/`, and `frontend/src/`.

---

## Key Decisions

### Decision 1: Threshold-Triggered Reflection Pipeline & Importance Accounting (`REQ-09`, `NFR-02`)
**Question:** How should accumulated importance be tracked across memory types, when in the tick should reflections run, and how should cited memory IDs be grounded and stored?

**Options Considered:**
1. **Query `SUM(importance)` from SQLite on every tick for every agent:** Adds 8 DB queries per tick even on idle movement ticks.
2. **Track in-memory `AgentBrain.accumulated_importance` across observations, plans/replans, and conversations; trigger async `ReflectionManager` at the end of `_run_cognitive_phase()` when `accumulated_importance >= reflection_threshold` (`150` default), resetting `accumulated_importance = 0` after persisting `reflection` memories:** Zero per-tick DB overhead; fires strictly at threshold crossings; runs concurrently across qualifying agents via `asyncio.gather`.
3. **Run reflections as fire-and-forget background tasks outside `_step_lock`:** Risks concurrent session/state races with `step_once()` and non-deterministic tick ordering in offline tests (`NFR-03`).

**Decision:** **Option 2.**
- Extend importance accumulation so `AgentBrain.accumulated_importance` (`backend/agents/agent.py:39, 104`) also adds post-seed `plan` (`DailyPlanner.generate_daily_plan` importance `6` at `backend/agents/planner.py:260`; `replan_remaining_day` importance `7` at `backend/agents/planner.py:340`) and `conversation` (`ConversationManager.run_conversation` rated importance at `backend/agents/conversation.py:292`) memories — while **excluding** tick-0 seeded persona memories (`backend/sim/engine.py:218-240`) and `reflection` memories themselves so reflections never self-cascade.
- Make `reflection_threshold: int = 150` configurable on `Settings` (`backend/app/config.py:11-41`), `SimulationEngine`, and `AgentBrain` so unit/integration tests can test both exact `150` accumulation and custom thresholds cleanly.
- Store cited IDs inside `MemoryRecord.metadata_json` (`backend/memory/models.py:35`) as `{"cited_memory_ids": [...], "question": ...}` (filtering LLM-returned IDs against the retrieved candidate `MemoryRecord.id` set for that agent, with deterministic fallback to top retrieved evidence IDs if empty), assign importance `8` (avoiding an extra `rate_importance_batch` call per reflection), reset `brain.accumulated_importance = 0` and set `brain.last_reflection_tick = clock.tick`, and emit a `"type": "reflection"` WebSocket payload via `SimulationEngine._emit_event_payload` (`backend/sim/engine.py:620-630`).
**Confidence:** High

---

### Decision 2: Agent Mood Storage & Backward-Compatible SQLite Persistence (`REQ-09`, `REQ-10`, `REQ-11`)
**Question:** Where should agent `mood` live in SQLite, runtime state, and LLM schemas without breaking existing tests or pre-existing `ai_village.db` files?

**Options Considered:**
1. **Embed `mood` by changing `AgentRecord.current_plan_json` from a JSON list to a JSON object:** **Breaks** `backend/tests/test_phase3_integration.py:128-129` (`parsed_plan = json.loads(record.current_plan_json); assert isinstance(parsed_plan, list)`).
2. **Add `mood: str = Field(default="calm")` to `AgentRecord` (`backend/memory/models.py:7-20`), `AgentEntity` (`backend/sim/engine.py:56-80`), and `AgentSnapshot` (`backend/sim/engine.py:30-41`), plus an idempotent `PRAGMA table_info('agents')` column check in `Database.init_models()` (`backend/app/db.py:60-71`):** Keeps `current_plan_json` strictly a JSON `list`, keeps `test_db.py:59-70` green via default value, and auto-migrates any existing local `backend/ai_village.db` (`backend/app/config.py:8`) where `SQLModel.metadata.create_all` alone would not add new columns.
3. **Compute mood purely on the fly in `GET /agents/{id}` without storing it:** Loses post-conversation and post-reflection LLM mood updates across ticks/restarts.

**Decision:** **Option 2.** Add optional-default mood fields (`speaker_a_mood: str = ""` and `speaker_b_mood: str = ""` on `ConversationSummaryResponse` at `backend/llm/schemas.py:83-90`; `mood: str = ""` on `ReflectionResponse` at `backend/llm/schemas.py:110-115`) with deterministic fallback when empty so all Phase 2/3 schema tests (`backend/tests/test_llm_gateway.py:146-185`, `backend/tests/test_conversation.py:265-333`) remain 100% compatible.
**Confidence:** High

---

### Decision 3: Canonical Pairwise Relationship Ordering (`REQ-10`)
**Question:** How should `(agent_a, agent_b)` ordering be enforced in `MemoryStore` and exposed in `GET /relationships` and `GET /agents/{id}`?

**Options Considered:**
1. **Leave `MemoryStore.upsert_relationship` (`backend/memory/store.py:270-296`) directional while `get_relationship` (`backend/memory/store.py:315-326`) is symmetric:** Calling `upsert_relationship("maya", "liam", ...)` followed by `upsert_relationship("liam", "maya", ...)` inserts two distinct composite-PK rows `("maya", "liam")` and `("liam", "maya")`, duplicating undirected graph edges.
2. **Canonicalize `(agent_a, agent_b)` to lexicographical `(min(a, b), max(a, b))` inside `MemoryStore.upsert_relationship` (rejecting `agent_a == agent_b` with `ValueError`, and migrating/updating any legacy reversed row if present):** Guarantees at most one undirected row per pair in SQLite, matches `ConversationManager._pair_key` (`backend/agents/conversation.py:63-64`), and preserves both `backend/tests/test_store_phase3.py:170-196` (`"liam" < "maya"`) and `backend/tests/test_embeddings_retrieval.py:258-276` (which checks `len(rels) == 1` and `affinity`, not row key order).

**Decision:** **Option 2.** Expose `GET /relationships` with canonical undirected edges (`agent_a < agent_b`, `agent_a_name`, `agent_b_name`, `affinity`, `notes`, `last_interaction_tick`) plus `nodes` metadata (`id`, `name`, `role`, `mood`) so Phase 4 REST clients and Phase 5's Cytoscape.js graph (`REQ-10`) consume the exact same endpoint without breaking changes. In `GET /agents/{id}`, project each relationship relative to `{id}` (`peer_id`, `peer_name`, `affinity`, `notes`, `last_interaction_tick`).
**Confidence:** High

---

### Decision 4: Responsive Time Controls & Immediate WS State Broadcast (`REQ-12`, `NFR-01`)
**Question:** How should `/sim/start`, `/sim/pause`, and `/sim/speed` interact with `SimClock`, `SimulationEngine._run_loop()`, and connected WebSocket clients?

**Options Considered:**
1. **Mutate `engine.clock` fields directly in `rest.py` without waking `_run_loop()` or broadcasting:** While paused (`engine.py:792-793`), `_run_loop()` never emits a `TickPayload`, so WS clients never learn the simulation paused or changed speed until the next tick; switching from `1x` (`1.0s` sleep) to `16x` (`0.0625s`) waits out the remainder of the `1.0s` `asyncio.sleep`; apps started with `sim_auto_start=False` (`backend/app/main.py:113-114`) have `_loop_task = None` so `clock.start()` alone never starts ticking.
2. **Add engine control methods (`start_simulation()`, `pause_simulation()`, `set_simulation_speed(speed)`) backed by an interruptible `asyncio.Event` wake signal in `_run_loop()`, `sim_state` persistence, and immediate live `TickPayload` broadcast:** Instant UI synchronization across all tabs/clients, immediate interval adaptation on `1x -> 16x` or `Pause`, and safe loop startup when `POST /sim/start` is called.

**Decision:** **Option 2.** Note one subtle detail in `SimulationEngine.build_tick_payload()` (`backend/sim/engine.py:290-294`): while `self._stepping` is `True`, `_pre_step_payload` holds the `speed` and `running` values captured at step start (`engine.py:730`). Control responses and control-triggered broadcasts should overlay live `clock.speed` and `clock.running` onto the snapshot (`model_copy(update={"speed": self.clock.speed, "running": self.clock.running})`) so spatial state stays mid-step consistent while playback state is immediately accurate.
**Confidence:** High

---

### Decision 5: Frontend Sprite Click Disambiguation & Non-Overlapping DOM Layout (`REQ-11`, `REQ-12`)
**Question:** How should Phaser sprite clicks, Agent Inspector, and Time Controls integrate into `frontend/` without conflicting with camera drag-panning, keyboard shortcuts, `#hud`, `#activity-feed`, or `#god-mode-bar`?

**Decision:**
- **Click vs Drag Disambiguation (`frontend/src/scenes/VillageScene.ts:431-457`):** Currently `pointerdown` unconditionally sets `this.isDragging = true`. Track `hasPanned` (set `true` in `pointermove` only when pointer travel exceeds `DRAG_THRESHOLD_PX = 5`). Mark agent sprites interactive (`sprite.setInteractive({ useHandCursor: true })` at `VillageScene.ts:488`), and invoke `onAgentSelect(agent.id)` on `pointerup` only when `!this.hasPanned`. Also make HUD `.agent-chip` items (`frontend/src/main.ts:45-60`) clickable buttons so users can select agents from either the map or the top bar, and render a subtle highlight ring under the selected agent in `VillageScene`.
- **Non-Overlapping Layout (`frontend/index.html:11-51`, `frontend/src/style.css:24-255`):**
  - **Time Controls:** Mount inside `header#hud` adjacent to `.hud-clock` (`index.html:16-19`) — zero canvas overlap, directly beside `#sim-time` and `#sim-tick`.
  - **Agent Inspector:** Mount as `<aside id="agent-inspector">` inside `main#stage` anchored **top-left / left** (`left: 1rem; top: 1rem; bottom: 1rem; width: 340px; z-index: 25`), opposite `#activity-feed` (`right: 1rem; top: 1rem; width: 320px; max-height: 240px; z-index: 20` at `style.css:142-157`), with a close button and `Escape` shortcut (guarded by `!isTextInputFocused()`).
- **Vite Proxy (`frontend/vite.config.ts:6-28`):** Add `"/sim"` and `"/relationships"` proxy entries (`"/agents"` at `vite.config.ts:20-23` already prefix-matches `/agents/{id}`).
**Confidence:** High

---

## Findings

### 1. LLM Schemas, Prompts, Gateway & `MockProvider` (`backend/llm/`)
- **Existing Schemas (`backend/llm/schemas.py`):**
  - `ConversationSummaryResponse` (`backend/llm/schemas.py:83-90`): `summary: str = Field(min_length=1)`, `affinity_delta: float = Field(default=0.0, ge=-1.0, le=1.0)`, `relationship_note: str = ""` (`extra="forbid"`). Missing optional speaker mood fields.
  - `SalientQuestionsResponse` (`backend/llm/schemas.py:93-98`): `questions: list[str] = Field(min_length=3, max_length=3)` (`extra="forbid"`). Ready to use as-is.
  - `ReflectionInsight` (`backend/llm/schemas.py:101-107`): `insight: str = Field(min_length=1)`, `cited_memory_ids: list[int] = Field(default_factory=list)` (`extra="forbid"`). Ready to use as-is.
  - `ReflectionResponse` (`backend/llm/schemas.py:110-115`): `insights: list[ReflectionInsight] = Field(min_length=1)` (`extra="forbid"`). Can add optional `mood: str = ""` and `max_length=5` on `insights`.
- **Existing Gateway Routing (`backend/llm/gateway.py`):**
  - `_PLANNING_PURPOSES` (`backend/llm/gateway.py:33-41`) **already** contains `"reflection"` and `"salient_questions"`, routing both to `self.planning_model` (`gemini-2.5-pro` default, `backend/llm/gateway.py:451-452`).
  - `summarize_conversation` (`backend/llm/gateway.py:373-389`) already exists (`purpose="conversation_summary"` on `routine_model`).
  - **Missing Gateway Helpers:** `generate_salient_questions` and `generate_reflections` convenience wrappers (mirroring `generate_daily_plan` / `generate_replan` at `backend/llm/gateway.py:283-318`) do not exist yet, and `SalientQuestionsResponse` / `ReflectionResponse` are not yet imported in `backend/llm/gateway.py:18-26`.
- **Existing Prompts (`backend/llm/prompts/`):**
  - Only `planning.py` and `conversation.py` exist (`backend/llm/prompts/__init__.py:1-21`).
  - `build_conversation_summary_prompt` (`backend/llm/prompts/conversation.py:85-105`) asks for `summary`, `affinity_delta`, and `relationship_note`, without existing relationship context or mood instructions.
  - **Missing Prompt Module:** `backend/llm/prompts/reflection.py` (`build_salient_questions_prompt` and `build_reflection_insights_prompt`) must be created and exported in `backend/llm/prompts/__init__.py`.
- **Existing `MockProvider` (`backend/llm/providers/mock.py`):**
  - Already handles `SalientQuestionsResponse` (`backend/llm/providers/mock.py:287-293`), `ReflectionInsight` (`mock.py:294-299`), and `ReflectionResponse` (`mock.py:300-311`).
  - `_extract_cited_ids(prompt)` (`backend/llm/providers/mock.py:594-601`) uses regex `r"(?:\[|#|\bID[: ]+)(\d+)\b"` and returns up to 5 unique ints. **Critical formatting rule:** `build_reflection_insights_prompt` must format evidence lines as `[<memory_id>] <text>` and **avoid** `[<tick>]` or `#1` numbering elsewhere in the prompt so `_extract_cited_ids` extracts only genuine `MemoryRecord.id` integers.
  - Enriching `SalientQuestionsResponse` and `ReflectionResponse` in `MockProvider` with `_extract_salient_topic(prompt)` (`mock.py:502-526`) when present makes mock reflections reference injected village events/rumors while preserving determinism (`backend/tests/test_llm_gateway.py:146-185`).

### 2. Persistence Models, `MemoryStore` & `ConversationManager` (`backend/memory/`, `backend/agents/`)
- **SQLModel Tables (`backend/memory/models.py`):**
  - `AgentRecord` (`backend/memory/models.py:7-20`): `id`, `name`, `persona_json`, `home_location`, `x`, `y`, `current_action`, `current_plan_json`. Needs `mood: str = "calm"` (plus `upsert_agent` at `backend/memory/store.py:141-160` and `update_agent_states` at `backend/memory/store.py:173-196` updated to persist `mood`, and `Database.init_models` at `backend/app/db.py:60-71` updated to run `ALTER TABLE agents ADD COLUMN mood VARCHAR NOT NULL DEFAULT 'calm'` if missing).
  - `MemoryRecord` (`backend/memory/models.py:22-36`): `id`, `agent_id`, `type`, `text`, `importance` (`1..10`), `created_tick`, `last_access_tick`, `embedding` (`LargeBinary`), `metadata_json: str = "{}"`. `MemoryType` (`backend/memory/store.py:22`) already includes `"reflection"`. Cited memory IDs map cleanly into `metadata_json` (`{"cited_memory_ids": [int, ...]}`).
  - `RelationshipRecord` (`backend/memory/models.py:38-48`): composite PK `(agent_a, agent_b)`, `affinity: float = 0.0`, `notes: str = ""`, `last_interaction_tick: int = 0`.
- **`MemoryStore` Methods (`backend/memory/store.py`):**
  - `list_memories(agent_id, *, memory_type=None, limit=None)` (`backend/memory/store.py:103-124`) orders newest-first (`created_tick DESC, id DESC`). Useful for recent memories in reflection prompts and Agent Inspector; add an optional `get_memories_by_ids(agent_id, memory_ids)` or `list_top_memories` helper if needed, or sort/slice in Inspector endpoint.
  - `upsert_relationship` (`backend/memory/store.py:270-296`), `list_relationships(agent_id=None)` (`store.py:297-314`), and `get_relationship(agent_a, agent_b)` (`store.py:315-326`) already exist. `upsert_relationship` currently queries only `(agent_a, agent_b)` (`store.py:280`) without canonicalizing `(min(a, b), max(a, b))` or rejecting self-loops (`agent_a == agent_b`).
- **`ConversationManager` (`backend/agents/conversation.py`):**
  - Already computes `_pair_key(agent_a.id, agent_b.id)` (`backend/agents/conversation.py:63-64`), clamps `affinity` to `[-1.0, 1.0]` (`conversation.py:333-336`), updates `notes` and `last_interaction_tick`, and calls `memory_store.upsert_relationship(...)` (`conversation.py:342-348`).
  - **Gaps to wire in `ConversationManager` / `SimulationEngine._run_conversations`:**
    1. Pass existing relationship (`affinity`, `notes`) into `build_conversation_summary_prompt` so notes build contextually.
    2. Propagate conversation memory `importance` (`DialogueOutcome.importance`, `conversation.py:58, 292`) into both participants' `AgentBrain.accumulated_importance` in `SimulationEngine._run_conversations` (`backend/sim/engine.py:544-551`).
    3. Apply returned/fallback post-conversation moods (`mood_a`, `mood_b`) to `agent_a` and `agent_b`.

### 3. REST Endpoints, `SimClock` & `SimulationEngine` (`backend/api/rest.py`, `backend/sim/`)
- **`SimClock` (`backend/sim/clock.py`):**
  - `VALID_SPEEDS = (1, 4, 16)` (`backend/sim/clock.py:8`), `start()` (`clock.py:82-84`), `pause()` (`clock.py:86-88`), `set_speed(speed)` (`clock.py:90-94`), and `tick_interval_seconds` (`clock.py:71-73`) are **already implemented and unit-tested** (`backend/tests/test_clock.py:58-88`).
  - Note: in `backend/app/main.py:78-81`, `SimClock` is constructed with default `running=True` even when `resolved_settings.sim_auto_start` is `False` (`main.py:113-114`). Passing `running=resolved_settings.sim_auto_start` in `main.py` keeps `clock.running` honest without altering `SimClock`'s class default.
- **`SimulationEngine` (`backend/sim/engine.py`):**
  - `_run_loop()` (`backend/sim/engine.py:783-793`) currently loops on `await asyncio.sleep(self.clock.tick_interval_seconds)` when `running` and `await asyncio.sleep(0.1)` when paused. Replacing fixed sleeps with an `asyncio.Event` wakeup + broadcast helper makes pause/resume/speed transitions instantaneous.
  - Missing `backend/agents/reflection.py` integration at the end of `_run_cognitive_phase()` (`backend/sim/engine.py:610-619`) and emitting queued reflection WS payloads in `step_once()` (`backend/sim/engine.py:759-761`).
- **`backend/api/rest.py`:**
  - Currently implements `GET /health` (`rest.py:62-73`), `GET /world` (`rest.py:76-85`), `GET /agents` (`rest.py:88-92`), and `POST /events` (`rest.py:95-118`).
  - **Endpoints to add:**
    - `POST /sim/start` → starts clock & background loop if not running, broadcasts live `TickPayload`, returns `SimControlResponse`.
    - `POST /sim/pause` → pauses clock, broadcasts live `TickPayload`, returns `SimControlResponse`.
    - `POST /sim/speed` → validates `speed` in `{1, 4, 16}` (rejecting booleans/other ints with HTTP 422), updates `clock.set_speed(speed)`, persists `sim_state`, wakes loop, broadcasts live `TickPayload`, returns `SimControlResponse`.
    - `GET /agents/{agent_id}` → returns `AgentInspectorResponse` (404 if unknown `agent_id`) containing persona profile, coordinates, `target_location`, `current_action`, `mood`, `accumulated_importance`, `reflection_threshold`, structured `plan` (`daily_plan`, `active_block_index`, `hourly_focus`, `current_step`), `recent_memories` + `reflections` (with parsed `cited_memory_ids`, excluding binary `embedding`), and `relationships` (`peer_id`, `peer_name`, `affinity`, `notes`, `last_interaction_tick`).
    - `GET /relationships` → returns `RelationshipsGraphResponse` (`nodes` + canonical `edges`).

### 4. Frontend Scene, Overlays, WebSocket & Vite Proxy (`frontend/`)
- **Phaser Input & Tweening (`frontend/src/scenes/VillageScene.ts`):**
  - `applyTick` (`VillageScene.ts:146-158`) **already** scales movement tween duration dynamically with `tickMsg.speed` (`Math.min(450, Math.max(45, (1000 / safeSpeed) * 0.8))`).
  - `keydown-C` (`VillageScene.ts:98-105`) checks `isTextInputFocused()` (`VillageScene.ts:37-45`), and `setKeyboardEnabled` (`VillageScene.ts:124-128`) disables Phaser keyboard input while `#event-form` has focus (`frontend/src/main.ts:91-93`).
  - Camera drag (`VillageScene.ts:431-457`) binds `pointerdown`/`pointermove`/`pointerup` on `this.input`; agent visuals (`VillageScene.ts:487-512`) are `Container([sprite, nameText])` at depth `10 + agent.y` without `.setInteractive()`.
- **HUD & Overlays (`frontend/index.html`, `frontend/src/main.ts`, `frontend/src/style.css`):**
  - `updateHud` (`frontend/src/main.ts:34-61`) already formats `Paused` vs `${tickMsg.speed}x` in `#sim-time` (`main.ts:36-37`) and rebuilds `.agent-chip` elements on every tick (`main.ts:45-60`).
  - `#activity-feed` (`frontend/src/style.css:142-157`) occupies top-right of `#stage` (`top: 1rem; right: 1rem; width: 320px; max-height: 240px; z-index: 20`). Placing `#agent-inspector` on the left of `#stage` (`top: 1rem; left: 1rem; bottom: 1rem; width: 340px; z-index: 25`) and `#time-controls` inside `header#hud` (`style.css:24-34`) avoids all overlap.
  - All DOM builders (`frontend/src/ui/activityFeed.ts:5-34`, `frontend/src/main.ts:45-60`) construct elements strictly with `document.createElement` + `textContent` (`no innerHTML`). New `timeControls.ts` and `agentInspector.ts` modules in `frontend/src/ui/` should follow the same XSS-safe pattern.
- **Types, WS Client & REST Client (`frontend/src/types/sim.ts`, `frontend/src/net/`):**
  - `sim.ts` (`frontend/src/types/sim.ts:1-191`) uses explicit runtime type guards (`isTickMessage`, `isDialogueMessage`, `isEventMessage`) consumed by `VillageWsClient` (`frontend/src/net/wsClient.ts:86-93`) and `requestJson<T>` (`frontend/src/net/apiClient.ts:80-97`).
  - Add `ReflectionMessage` + `isReflectionMessage`, `SimControlState` + `isSimControlState`, `AgentInspectorData` + `isAgentInspectorData`, and `RelationshipsResponse` + `isRelationshipsResponse` in `sim.ts`, wire `onReflection` in `wsClient.ts`, and add `startSim()`, `pauseSim()`, `setSimSpeed(speed)`, `fetchAgentDetail(id)`, and `fetchRelationships()` in `apiClient.ts`.
- **Vite Dev Proxy (`frontend/vite.config.ts`):**
  - Currently proxies `/ws`, `/health`, `/world`, `/agents`, `/events` (`frontend/vite.config.ts:6-28`). Must add `"/sim"` and `"/relationships"` pointing to `"http://127.0.0.1:8000"`.

**Sources:**
- `backend/llm/schemas.py:83-115`, `backend/llm/gateway.py:33-41, 283-390, 442-454`, `backend/llm/providers/mock.py:272-312, 594-601`
- `backend/memory/models.py:7-48`, `backend/memory/store.py:22, 103-196, 270-326`, `backend/app/db.py:60-71`
- `backend/agents/agent.py:32-44, 96-197`, `backend/agents/conversation.py:63-65, 275-382`, `backend/agents/planner.py:254-263, 334-343`
- `backend/sim/clock.py:8-94`, `backend/sim/engine.py:30-93, 198-295, 427-630, 726-793`, `backend/api/rest.py:16-118`, `backend/app/main.py:78-122`
- `frontend/index.html:10-51`, `frontend/vite.config.ts:6-28`, `frontend/src/main.ts:34-120`, `frontend/src/scenes/VillageScene.ts:37-45, 98-158, 414-535`, `frontend/src/style.css:17-158, 250-360`

---

## Patterns to Follow

- **Runtime Type Guards on Every Boundary:** Match `frontend/src/types/sim.ts:113-191` and `frontend/src/net/apiClient.ts:80-97` by validating every new WS message (`reflection`) and REST response (`/sim/*`, `/agents/{id}`, `/relationships`) with strict TypeScript type-predicate functions before passing data to UI or Phaser.
- **`createElement` + `textContent` DOM Rendering:** Follow `frontend/src/ui/activityFeed.ts:16-122` and `frontend/src/ui/eventInjector.ts:25-182` — never use `innerHTML` when rendering LLM-generated plans, memories, insights, moods, or relationship notes.
- **Format Evidence Memories as `[<id>] <text>` Only:** In `build_reflection_insights_prompt`, prefix only candidate `MemoryRecord.id` values with `[<id>]` (and label questions `Q1.`, `Q2.`, `Q3.`) so `MockProvider._extract_cited_ids` (`backend/llm/providers/mock.py:594-601`) deterministically cites valid memory IDs.
- **Canonical Lexicographical Pair Keys:** Enforce `(min(id_a, id_b), max(id_a, id_b))` inside `MemoryStore.upsert_relationship` (`backend/memory/store.py:270-296`) so `relationships` rows are always canonical regardless of caller argument order.

## Anti-Patterns to Avoid

- **Mutating `current_plan_json` Shape:** Never wrap `current_plan_json` in a dict to store `mood` or `hourly_focus`; `backend/tests/test_phase3_integration.py:128-129` asserts `isinstance(json.loads(record.current_plan_json), list)`.
- **Serializing `MemoryRecord.embedding` Over REST:** `MemoryRecord.embedding` (`backend/memory/models.py:34`) is raw `bytes` (1536-byte float32 blob); always map memories to explicit Pydantic response DTOs in `backend/api/rest.py` rather than returning raw `MemoryRecord` ORM instances.
- **Triggering Agent Selection on Camera Drag Release:** In `VillageScene.ts:431-457`, always gate sprite `pointerup` selection on `Math.hypot(pointer.x - dragStartX, pointer.y - dragStartY) <= 5` so panning across the village does not accidentally open the Agent Inspector.
- **Binding Unconditional Global `Space` Shortcut:** Focusing a Time Control `<button>` and pressing `Space` already triggers a native click in browsers; an unguarded global `keydown-SPACE` listener will double-toggle Play/Pause.

## Dependencies Identified

| Package | Version | Purpose |
|---------|---------|---------|
| *(None — existing stack suffices)* | — | FastAPI, Pydantic v2, SQLModel + aiosqlite, Phaser 3.85, TypeScript 5.6, and Vite 5.4 already installed (`backend/pyproject.toml:10-22`, `frontend/package.json:12-18`). Cytoscape.js & Chart.js are deferred to Phase 5 (`.gsd/ROADMAP.md:82-86`). |

## Risks

- **Pre-existing Local `backend/ai_village.db` Missing `agents.mood` Column:** `SQLModel.metadata.create_all` (`backend/app/db.py:70`) does not alter existing tables. *Mitigation:* Check `PRAGMA table_info('agents')` inside `Database.init_models()` and run `ALTER TABLE agents ADD COLUMN mood VARCHAR NOT NULL DEFAULT 'calm'` when absent.
- **Stale Agent Inspector View During Live Play:** `GET /agents/{id}` is a point-in-time REST snapshot while ticks advance at up to `16x` (`16` ticks/sec). *Mitigation:* Patch live position/action/mood on incoming `tick` messages for the selected agent, and re-fetch `GET /agents/{id}` automatically on `dialogue`/`reflection` WS events involving that agent (plus a manual refresh / throttled poll every ~3–5s while open).
- **LLM Budget / Latency Spike if Multiple Agents Reflect on Same Tick:** Each reflection costs 2 `planning_model` calls (`salient_questions` + `reflection`). *Mitigation:* Assign fixed importance `8` to synthesized reflection memories (saving a 3rd `rate_importance_batch` call), reset `accumulated_importance = 0` immediately, and keep `insights` bounded (`1..3` items).

## Recommendations for Planning

1. **Wave 1 (Backend Foundation — Parallelizable):**
   - **Plan 4.1 (LLM Reflection & Mood Support):** Extend `ConversationSummaryResponse` & `ReflectionResponse` with optional mood fields (`backend/llm/schemas.py`), create `backend/llm/prompts/reflection.py` + extend `conversation.py`, add `generate_salient_questions` & `generate_reflections` to `LLMGateway` (`backend/llm/gateway.py`), and enrich `MockProvider` (`backend/llm/providers/mock.py`) with unit tests.
   - **Plan 4.2 (Persistence & Canonical Relationships):** Add `AgentRecord.mood` + idempotent SQLite column migration (`backend/memory/models.py`, `backend/app/db.py`, `backend/memory/store.py`), enforce canonical `(min, max)` ordering + self-pair validation in `MemoryStore.upsert_relationship`, and add unit tests.
   - **Plan 4.3 (Frontend Types, API/WS Clients & Vite Proxy):** Add Phase 4 DTOs and runtime type guards in `frontend/src/types/sim.ts`, REST methods in `frontend/src/net/apiClient.ts`, `onReflection` dispatch in `frontend/src/net/wsClient.ts`, and `/sim` + `/relationships` proxies in `frontend/vite.config.ts`.
2. **Wave 2 (Cognitive Reflection, Engine Controls & REST API):**
   - **Plan 4.4 (Reflection Module & Conversation Relationship/Mood Wiring):** Create `backend/agents/reflection.py`, wire plan/conversation importance into `AgentBrain.accumulated_importance`, pass existing relationship context & apply mood updates in `ConversationManager`, and integrate reflection execution + WS `"reflection"` payloads into `SimulationEngine`.
   - **Plan 4.5 (Sim Time Controls & Inspector/Relationships REST Endpoints):** Add interruptible wake event + `start_simulation` / `pause_simulation` / `set_simulation_speed` + live `TickPayload` broadcast on `SimulationEngine`, align `main.py` `clock.running` with `sim_auto_start`, and implement `POST /sim/start`, `POST /sim/pause`, `POST /sim/speed`, `GET /agents/{id}`, and `GET /relationships` in `backend/api/rest.py` with API & integration tests.
3. **Wave 3 (Frontend UI Integration & End-to-End Verification):**
   - **Plan 4.6 (Clickable Agent Inspector, Time Controls Bar & Reflection Feed):** Add drag-safe sprite click selection + selection highlight in `VillageScene.ts`, clickable HUD agent chips in `main.ts`, `timeControls.ts` in `#hud`, `agentInspector.ts` left-docked in `#stage`, and `REFLECTION` cards in `ActivityFeed`, verified with `tsc --noEmit` and `vite build`.
