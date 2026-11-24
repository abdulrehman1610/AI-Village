---
phase: 3
researched_at: 2026-11-24
discovery_level: 2
---

# Phase 3 Research — Daily Planning, Conversations & Event Injection (P0 MVP)

## Objective

Determine how to wire the Phase 3 P0 MVP features — hierarchical daily planning (`day -> hour -> minute` + interruption replanning, REQ-06), proximity-triggered multi-turn conversations (`<= 2` tiles, `<= 6` turns, WS `dialogue`, memory summary, REQ-07), and God-Mode event injection (`POST /events`, radius observation delivery, WS `event`, frontend input bar, REQ-08) — cleanly onto Phase 2's `LLMGateway`, `MemoryStore`, `MemoryRetriever`, `SimulationEngine`, and Phaser 3 / TypeScript frontend without violating spatial invariants (NFR-05) or LLM cost/tick budgets (NFR-01, NFR-02).

## Discovery Level

**Level 2** — Standard codebase & integration research across existing backend/frontend modules (`backend/llm/`, `backend/sim/`, `backend/memory/`, `backend/api/`, `frontend/src/`).

---

## Key Decisions

### Decision 1: Hierarchical Plan Representation & LLM Call Granularity (REQ-06, NFR-02)
**Question:** How should the 3-tier hierarchy (wake-up day plan of 5–8 broad items → hourly blocks → minute-level actions + remaining-day replanning) be represented and decomposed without exhausting the `$0.50` / `250k` daily LLM budget (`backend/app/config.py:33-34`) or failing late-day validation?

**Options Considered:**
1. **Separate LLM call per broad item, per hour, and per 15-minute slice:** 1 wake-up + 16 hourly + 64 minute calls per agent/day (~648 calls/day for 8 agents) — high latency and unnecessary token burn.
2. **Wake-up `DailyPlanResponse` (5–8 items) + lazy `HourlyDecompositionResponse` when entering a broad block (producing hourly blocks + 15–30 min `MinuteAction` steps in one call) + `ReplanResponse` (`min_length=1, max_length=8`) on interruption:** Calls the stronger `planning_model` (`backend/llm/gateway.py:25-33`) only at wake-up (`daily_plan`) and interruptions (`replan`), and uses routine-tier (`gemini-2.5-flash`) lazy decomposition (`action_decomposition`) when entering an unexpanded broad block.
3. **Wake-up `DailyPlanResponse` only, with purely deterministic string splitting for hours/minutes:** Cheapest, but hourly/minute actions lack LLM-grounded variety when using Gemini.

**Decision:** **Option 2.** Keep `DailyPlanResponse` (`5..8` items, `backend/llm/schemas.py:29-34`) for wake-up (`06:00`), add `ReplanResponse` (`items: list[DailyPlanItem]` with `min_length=1, max_length=8`) so late-evening interruptions (e.g. `21:00`–`24:00`) never fail `min_length=5` validation, and add `HourlyActionPlanResponse` (`hourly_blocks` + `minute_actions` of `10..60` minutes summing to the block span) evaluated lazily on routine model (`purpose="action_decomposition"`, not in `_PLANNING_PURPOSES` at `backend/llm/gateway.py:25-33`). Canonicalize LLM-returned location names against `WorldMap.locations` (`backend/sim/world.py:88-90`) with fallback to `agent.home_location`.
**Confidence:** High

---

### Decision 2: Non-Blocking Cognitive Tick Ordering & Spatial Invariant Preservation (REQ-06, REQ-07, NFR-01, NFR-05)
**Question:** How should `Perceive -> Remember -> Decide -> Act` and proximity conversations integrate into `SimulationEngine.step_once()` (`backend/sim/engine.py:388-411`) without causing tile overlaps or tick stalls?

**Options Considered:**
1. **Fire-and-forget background tasks mutating `AgentEntity` mid-tick outside `_step_lock`:** Risks race conditions on `agent.path`, `agent.target_location`, and `current_plan_json`.
2. **Two-phase tick inside `step_once()` — Phase A (Async Cognition via `asyncio.gather`) followed by Phase B (Synchronous Spatial Step over `reserved_tiles`):**
   - Phase A1 (`Perceive`): Deterministically gather queued world/god events + deduplicated nearby agent observations (`<= 4` Manhattan tiles).
   - Phase A2 (`Remember`): Batch all new observations across all agents in the tick into **one** `llm_gateway.rate_importance_batch()` call (`backend/llm/gateway.py:242-273`) and **one** `memory_store.add_memories_batch()` call (`backend/memory/store.py:72-99`).
   - Phase A3 (`Decide` & `Converse`): Match disjoint free agent pairs within Manhattan distance `<= 2` whose pair cooldown has elapsed; run conversation dialogues and wake-up/interruption/decomposition planning concurrently via `asyncio.gather(...)`. Conversing agents hold position (`conversation_hold_ticks` / action `"Talking with {peer}"`) rather than stepping.
   - Phase B (`Act`): Run existing synchronous `_step_agent(agent, reserved_tiles)` (`backend/sim/engine.py:333-387`) in `sorted(self.agents)` order for non-conversing agents, advance clock, persist state, and emit WS events (`event`, `dialogue`, `tick`).

**Decision:** **Option 2**, with graceful fallback to Phase 1/2 `routine` cycling whenever `self.llm_gateway is None` so existing pure-navigation tests (`backend/tests/test_engine.py:55-91`) continue to pass unchanged.
**Confidence:** High

---

### Decision 3: Pair Cooldown & Rumor Propagation in `MockProvider` (REQ-07, REQ-08, NFR-03)
**Question:** How do we prevent stationary neighbors from calling `ConversationDecisionResponse` on every tick when `initiate=False`, and ensure injected events spread deterministically through conversations in offline `MockProvider` tests?

**Options Considered:**
1. **Only set cooldown after a completed conversation; keep static `MockProvider` summary text:** Two agents dwelling at `Cafe` with `initiate=False` would re-invoke `ConversationDecisionResponse` on every tick, and `MockProvider`'s static `ConversationSummaryResponse.summary` (`backend/llm/providers/mock.py:174-179`) would drop injected event details from listener memories.
2. **Dual pair cooldown (`CONVERSATION_COOLDOWN_TICKS = 60` after dialogue, `DECLINE_COOLDOWN_TICKS = 30` after `initiate=False`) + context-aware `MockProvider` dialogue/summary extraction:** If the prompt contains an injected event / `[EVENT]` marker or `_URGENT_KEYWORDS` (`backend/llm/providers/mock.py:24-32`), `MockProvider` sets `initiate=True` and echoes the event/rumor line into both `DialogueTurnResponse.utterance` and `ConversationSummaryResponse.summary`.

**Decision:** **Option 2.** Guarantees zero tick-by-tick LLM spam and deterministic multi-hop rumor propagation (`Event -> Agent A observation -> A+B dialogue -> Agent B conversation memory`) with zero network calls.
**Confidence:** High

---

### Decision 4: God-Mode Event Delivery & Frontend Overlay Architecture (REQ-08)
**Question:** How should `POST /events` determine affected agents, and how should the frontend render `dialogue`, `event`, and the God-Mode injection bar?

**Options Considered:**
1. **Canvas-only Phaser UI forms and speech bubbles:** Hard to type free-text input in WebGL/Canvas; poor accessibility and clipboard support.
2. **Phaser world-space speech bubbles + location event pulse in `VillageScene.ts`, paired with modular DOM components in `frontend/src/ui/` (`eventInjector.ts` + `activityFeed.ts`):**
   - `POST /events` accepts `{ text: str, location: str | None = None }`. When `location` is `None`, all village agents observe the event; when `location` is a valid `NamedLocation` (`backend/sim/world.py:228-232`), agents within Manhattan distance `<= 10` of `loc.anchor` (or inside `loc`'s tile bounds / currently `"At {location}"`) observe it immediately and flag `needs_replan = True`.
   - `VillageScene.ts` renders timed bubbles above speaker sprites (`depth >= 60`, above location labels at `depth 20` and agents at `depth 10..39`) and an expanding highlight ring at the target location for `event` messages, while `frontend/src/ui/` handles the DOM God-Mode input bar + live dialogue/event feed.

**Decision:** **Option 2.** Clean separation between world-space Phaser visuals and accessible HTML form controls.
**Confidence:** High

---

## Findings

### 1. Existing LLM Schemas, Gateway Methods & `MockProvider` Branches (Question 1)

- **Existing Schemas (`backend/llm/schemas.py:10-88`)**:
  - `ImportanceBatchResponse` (`backend/llm/schemas.py:10-15`): `ratings: list[Annotated[int, Field(ge=1, le=10)]]` with `ConfigDict(extra="forbid")`.
  - `DailyPlanItem` (`backend/llm/schemas.py:18-26`): `start_hour: int (0..23)`, `end_hour: int (0..24)`, `location: str`, `description: str`.
  - `DailyPlanResponse` (`backend/llm/schemas.py:29-34`): `items: list[DailyPlanItem] = Field(min_length=5, max_length=8)`.
  - `ConversationDecisionResponse` (`backend/llm/schemas.py:37-44`): `initiate: bool`, `reason: str`, `opening_line: str = ""`.
  - `DialogueTurnResponse` (`backend/llm/schemas.py:47-53`): `utterance: str = Field(min_length=1)`, `continue_dialogue: bool = True`.
  - `ConversationSummaryResponse` (`backend/llm/schemas.py:56-63`): `summary: str = Field(min_length=1)`, `affinity_delta: float = Field(default=0.0, ge=-1.0, le=1.0)`, `relationship_note: str = ""`.
- **Existing Gateway (`backend/llm/gateway.py:68-394`)**:
  - `LLMGateway.generate(...)` (`backend/llm/gateway.py:110-240`) already implements SHA-256 prompt caching (`362-375`), daily USD/token budget gating with automatic fallback to `MockProvider` (`85-87`), 1-retry schema repair (`378-394`), and `LLMCallRecord` persistence (`339-359`).
  - `LLMGateway.rate_importance_batch(texts, *, tick, agent_id=None, purpose="importance_batch")` (`backend/llm/gateway.py:242-273`) already formats `Item count: {len(texts)}` + numbered lines and verifies `len(response.ratings) == len(texts)`.
  - `_PLANNING_PURPOSES` (`backend/llm/gateway.py:25-33`) routes `"daily_plan"`, `"replan"`, `"hourly_plan"`, `"reflection"`, and `"salient_questions"` to `planning_model` (`gemini-2.5-pro`), while all other purposes use `routine_model` (`gemini-2.5-flash`, `backend/app/config.py:31-32`).
- **Existing `MockProvider` (`backend/llm/providers/mock.py:80-310`)**:
  - Dispatches explicit branches for `ImportanceBatchResponse` (`136-137`, `207-218`), `DailyPlanResponse` (`138-139`, `220-243`), `DailyPlanItem` (`140-147`), `ConversationDecisionResponse` (`148-162`), `DialogueTurnResponse` (`163-172`), and `ConversationSummaryResponse` (`173-179`).
  - `_LOCATIONS` (`backend/llm/providers/mock.py:34-43`) uses 8 location names (`Home_Maya`, `Bakery`, `Cafe`, `Market`, `Town Square`, `Park`, `Library`, `Home_Liam`), all of which match valid anchors in `map.json` (`frontend/public/assets/map.json:3652-3924`, `backend/tests/test_world.py:13-24`).
- **New LLM Additions Needed in Phase 3**:
  - **Schemas (`backend/llm/schemas.py`)**:
    1. `ReplanResponse`: `items: list[DailyPlanItem] = Field(min_length=1, max_length=8)` so late-day interruptions (when `< 5` hours remain before midnight) validate cleanly.
    2. `MinuteActionItem`: `duration_minutes: int = Field(ge=5, le=60)`, `location: str = Field(min_length=1)`, `action: str = Field(min_length=1)` + `HourlyActionPlanResponse`: `hourly_focus: str = Field(min_length=1)`, `actions: list[MinuteActionItem] = Field(min_length=1, max_length=6)` to decompose active scheduled blocks into hourly + minute-level actions.
  - **Prompts (`backend/llm/prompts/`)**: Currently empty (`backend/llm/prompts/__init__.py:1`). Add `backend/llm/prompts/planning.py` (wake-up plan, block decomposition, interruption replan) and `backend/llm/prompts/conversation.py` (initiation check, turn generation with retrieved top-8 memories + running transcript, post-dialogue summary), always injecting valid location names (`world.list_locations()`) and concise `persona.summary_text()` (`backend/agents/personas.py:28-35`).
  - **`MockProvider` updates (`backend/llm/providers/mock.py`)**:
    1. Add `ReplanResponse` and `HourlyActionPlanResponse` branches (parsing `"Current hour: HH"` and any mentioned target location from the prompt rather than hardcoding `start_hour = 6` as in `_build_daily_plan` at `backend/llm/providers/mock.py:222`).
    2. Update `ConversationDecisionResponse`, `DialogueTurnResponse`, and `ConversationSummaryResponse` (`backend/llm/providers/mock.py:148-179`) so prompts containing `Observed event` / `_URGENT_KEYWORDS` deterministically initiate (`initiate=True`) and propagate the event topic string into both the spoken utterance and stored conversation summary.

**Sources:**
- `backend/llm/schemas.py:10-88`
- `backend/llm/gateway.py:25-33`, `backend/llm/gateway.py:110-273`
- `backend/llm/providers/mock.py:24-62`, `backend/llm/providers/mock.py:129-273`
- `backend/llm/providers/gemini.py:43-70`
- `backend/llm/prompts/__init__.py:1`

---

### 2. `SimulationEngine` Tick Loop, Cognitive Integration & WebSocket Broadcasting (Question 2)

- **Current Tick Execution (`backend/sim/engine.py:388-411`)**:
  - Acquires `self._step_lock` (`390`), snapshots `self._pre_step_payload` (`391`) for lock-free concurrent readers (`build_tick_payload()` at `258-262`), builds `reserved_tiles = {(a.x, a.y) for a in self.agents.values()}` (`394`), calls synchronous `self._step_agent` in `sorted(self.agents)` order (`395-396`), calls `self.clock.advance()` (`397`), awaits `self.persist_tick_state()` (`399-400`), and invokes `self._tick_callbacks` outside `_step_lock` (`405-409`).
  - `SimClock` (`backend/sim/clock.py:16-69`) starts at `tick=0`, `start_minute_of_day=360` (`Day 1 06:00`), advancing 1 simulated minute per tick (`TICKS_PER_DAY = 1440`).
- **Current WebSocket Plumbing (`backend/app/main.py:90-96`, `backend/api/ws.py:14-52`)**:
  - `ConnectionManager.broadcast_json(payload: dict[str, Any])` (`backend/api/ws.py:29-35`) accepts arbitrary JSON dicts, but `SimulationEngine` only exposes `register_tick_callback(Callable[[TickPayload], Awaitable[None]])` (`backend/sim/engine.py:134, 244-246`).
  - Adding `register_event_callback(Callable[[dict[str, Any]], Awaitable[None]])` (wired to `ws_manager.broadcast_json` in `backend/app/main.py:92-96`) enables emitting `{"type": "dialogue", ...}` and `{"type": "event", ...}` payloads without breaking existing `register_tick_callback` tests (`backend/tests/test_engine.py:94-112`).
- **Agent Brain Modules to Create (`backend/agents/`)**:
  - Currently only `backend/agents/personas.py` (`1-202`) exists. Following `.gsd/ARCHITECTURE.md:67-70`, Phase 3 should add:
    - `backend/agents/planner.py`: Hierarchical plan state (`AgentPlanState`: `day`, `daily_items`, `hourly_actions_by_block`, `current_minute_action`, `action_end_tick`) + async wake-up generation, lazy block decomposition, and remaining-day replanning.
    - `backend/agents/conversation.py`: `ConversationManager` tracking pair cooldowns (`pair_cooldown_until: dict[tuple[str, str], int]`), Manhattan distance `<= 2` eligibility, `ConversationDecisionResponse` gate, up to 6 `DialogueTurnResponse` turns grounded in `MemoryRetriever.retrieve(..., top_k=8)` (`backend/memory/retrieval.py:74-139`), `ConversationSummaryResponse`, DB persistence, and WS `dialogue` emission.
    - `backend/agents/agent.py`: Per-agent cognitive coordinator (`perceive`, `remember`, `decide`, `apply_action_target`) bridging `AgentEntity` (`backend/sim/engine.py:54-85`) with `planner.py`, `MemoryStore`, and `MemoryRetriever`.
- **Backwards-Compatibility Invariants in Existing Tests (`backend/tests/test_engine.py`)**:
  - `test_engine_150_ticks_spatial_invariants` (`backend/tests/test_engine.py:55-91`) instantiates `SimulationEngine(world=world, clock=clock, seed=42, dwell_ticks=4)` with `llm_gateway=None` and asserts all 8 agents move without tile overlap and visit `>= 2` locations. Keeping `_advance_routine_target` (`backend/sim/engine.py:264-275`) active when `llm_gateway is None` preserves this test 100%.
  - **Watchout (`backend/tests/test_engine.py:183`)**: `test_engine_persists_agents_memories_and_sim_state` passes a `MockProvider` `llm_gateway` (`155-164`) and asserts `assert json.loads(record.current_plan_json) == agent.routine` (`183`). When Phase 3 persists structured daily plans into `current_plan_json` (`backend/sim/engine.py:186, 232`), `agent.serialized_plan_json()` should be used in both `SimulationEngine` and updated in `test_engine.py:183` (or `agent.routine` updated from plan locations).

**Sources:**
- `backend/sim/engine.py:54-85`, `backend/sim/engine.py:170-246`, `backend/sim/engine.py:313-411`
- `backend/sim/clock.py:13-80`
- `backend/api/ws.py:14-52`
- `backend/app/main.py:81-96`
- `backend/tests/test_engine.py:55-91`, `backend/tests/test_engine.py:146-185`

---

### 3. `MemoryStore` / SQLModel CRUD Coverage & `POST /events` Persistence (Question 3)

- **SQLModel Schema (`backend/memory/models.py:7-101`)**:
  - All 7 tables already exist: `AgentRecord` (`7-20`, includes `current_plan_json: str = "[]"` at `19`), `MemoryRecord` (`22-36`), `RelationshipRecord` (`38-48`), `EventRecord` (`50-61`: `id`, `tick`, `kind`, `text`, `location`, `source`), `ConversationRecord` (`63-73`: `id`, `tick_start`, `participants`, `transcript_json`, `summary`), `LLMCallRecord` (`75-90`), `SimStateRecord` (`92-101`).
  - `Database._session_factory` already configures `expire_on_commit=False` and SQLite WAL + `busy_timeout=5000` (`backend/app/db.py:48-58`), so primary keys (`event.id`, `conversation.id`, `memory.id`) remain accessible post-commit.
- **Existing `MemoryStore` Methods (`backend/memory/store.py:40-311`)**:
  - Memories: `add_memory` (`47-70`), `add_memories_batch` (`72-99`), `list_memories` (`101-121`), `touch_memories` (`123-137`).
  - Agents: `upsert_agent` (`139-157`), `get_agent` (`159-162`), `list_agents` (`164-169`), `update_agent_states` (`171-194`, updates `current_plan_json` at `191`).
  - Sim state: `get_or_create_sim_state` (`195-216`), `save_sim_state` (`218-244`).
  - Events: `log_event(*, tick, kind, text, location=None, source) -> EventRecord` (`246-266`).
  - Relationships: `upsert_relationship` (`268-293`), `list_relationships` (`295-311`).
- **Missing Repository & API Methods Needed in Phase 3**:
  1. **`MemoryStore.add_conversation(...) -> ConversationRecord`** (`backend/memory/store.py` currently does not import `ConversationRecord` at `12-18`): persists `tick_start`, `participants=json.dumps(list(participants))`, `transcript_json=json.dumps(turns)`, `summary=summary`.
  2. **`MemoryStore.list_conversations(*, participant_id: str | None = None, limit: int | None = None) -> list[ConversationRecord]`**: queries `conversations` ordered by `tick_start DESC, id DESC` (filtering on participant if requested).
  3. **`MemoryStore.list_events(*, since_tick: int | None = None, limit: int | None = None) -> list[EventRecord]`**: queries `events` ordered by `tick DESC, id DESC` for inspection and test assertions.
  4. **`MemoryStore.get_relationship(agent_a: str, agent_b: str) -> RelationshipRecord | None`** (optional small helper around `(agent_a, agent_b)` so `ConversationSummaryResponse.affinity_delta` at `backend/llm/schemas.py:62` can increment existing affinity cleanly via `upsert_relationship`).
  5. **`POST /events` in `backend/api/rest.py` + `SimulationEngine.inject_event(...)`**:
     - Important coordinate detail: in `NamedLocation` (`backend/sim/world.py:17-35, 167-210`), `x`, `y`, `width`, `height` are in **pixels**, whereas `anchor_x` and `anchor_y` (`loc.anchor`) are in **tiles**! Radius checks MUST compare agent tile `(agent.x, agent.y)` against `loc.anchor` in tile units (e.g., `abs(agent.x - loc.anchor_x) + abs(agent.y - loc.anchor_y) <= radius`, or tile-converted bounding box `loc.x // tile_size <= agent.x <= (loc.x + loc.width) // tile_size`), never raw pixel `loc.x`/`loc.y`.
     - Validate `location` if provided (`422`/`400` if not in `world.locations`), persist `EventRecord(kind="god_event", source="god", ...)`, queue/deliver high-priority observation memories to witnesses, mark witnesses `needs_replan = True`, and broadcast `{"type": "event", ...}` over WebSocket.

**Sources:**
- `backend/memory/models.py:7-73`
- `backend/memory/store.py:12-33`, `backend/memory/store.py:47-311`
- `backend/app/db.py:48-58`
- `backend/sim/world.py:17-35`, `backend/sim/world.py:167-210`
- `backend/api/rest.py:44-74`

---

### 4. Frontend Types, Network Clients, `VillageScene` Visuals & DOM HUD (Question 4)

- **Shared Types (`frontend/src/types/sim.ts:1-97`)**:
  - Currently only validates `AgentSnapshot` (`60-77`) and `TickMessage` (`80-97`).
  - Needs `DialogueMessage`, `EventMessage`, `EventInjectRequest`, `EventInjectResponse`, and runtime type guards `isDialogueMessage` and `isEventMessage`.
- **Network Layer (`frontend/src/net/wsClient.ts:1-169` & `frontend/vite.config.ts:1-26`)**:
  - `VillageWsClient` (`frontend/src/net/wsClient.ts:74-79`) parses incoming JSON and checks `if (isTickMessage(parsed))` only; extend `VillageWsClientCallbacks` (`5-8`) with `onDialogue?: (msg: DialogueMessage) => void` and `onEvent?: (msg: EventMessage) => void`.
  - Add `frontend/src/net/apiClient.ts` for `fetchWorld()` (`GET /world`) and `injectEvent()` (`POST /events`).
  - **Vite Proxy Gap (`frontend/vite.config.ts:6-24`)**: Currently proxies `/ws`, `/health`, `/world`, and `/agents` — `/events` is **missing** and MUST be added so `POST /events` works from `http://localhost:5173`.
- **Phaser 3 Visuals (`frontend/src/scenes/VillageScene.ts:1-240`)**:
  - Layer depths: `ground` = `0` (`54`), `structures` = `1` (`57`), `collision` = `5` (`60`), `AgentVisual.container` = `10 + agent.y` (`207, 223`, i.e. `10..39` on the 40×30 map), location labels = `20` (`113`).
  - Speech bubbles must render at `depth >= 60` (either as a separate world-space container following `speakerVisual.container.x/y` in `update()` / tween, or elevated container) so bubbles are never occluded by `depth 20` location labels or southern agents (`depth 10..39`).
  - **Keyboard Focus Bug Risk (`frontend/src/scenes/VillageScene.ts:62-66`)**: `this.input.keyboard?.on("keydown-C", ...)` is bound globally without checking `document.activeElement`. Typing `"Cafe"` in the God-Mode `<input>` will toggle the red collision layer unless guarded when `document.activeElement` is an `HTMLInputElement`, `HTMLTextAreaElement`, or `HTMLSelectElement` (and setting `input: { keyboard: { capture: [] } }` in `Phaser.Game` config at `frontend/src/main.ts:57-67` so Phaser never swallows `Space` or arrow keys inside form inputs).
- **DOM Layout & New `frontend/src/ui/` Modules (`frontend/index.html:10-28`, `frontend/src/style.css:17-134`)**:
  - `frontend/src/ui/` does not exist yet.
  - `#stage` (`frontend/index.html:22-24`, `frontend/src/style.css:117-125`) wraps `#game-container`; adding `position: relative` on `#stage` allows an absolute-positioned live `ActivityFeed` overlay (`frontend/src/ui/activityFeed.ts`) in the top-right corner for recent `event` banners and `dialogue` lines without shifting canvas layout.
  - Add a compact `#god-mode-bar` section in `frontend/index.html` (between `#stage` and `#controls-hint`, wired by `frontend/src/ui/eventInjector.ts`) containing a location `<select>` (populated from `GET /world` `locations` plus an `"All Village"` default), free-text `<input>`, and `"Inject Event"` submit button.

**Sources:**
- `frontend/src/types/sim.ts:1-97`
- `frontend/src/net/wsClient.ts:5-8`, `frontend/src/net/wsClient.ts:67-82`
- `frontend/vite.config.ts:6-24`
- `frontend/src/scenes/VillageScene.ts:53-70`, `frontend/src/scenes/VillageScene.ts:94-116`, `frontend/src/scenes/VillageScene.ts:177-235`
- `frontend/index.html:10-28`
- `frontend/src/main.ts:55-77`
- `frontend/src/style.css:17-34`, `frontend/src/style.css:117-135`

---

## Patterns to Follow

- **Gateway-Only Structured LLM Calls (CON-02, CON-03)**: Every planning, importance, and conversation call goes through `LLMGateway.generate()` or `LLMGateway.rate_importance_batch()` (`backend/llm/gateway.py:110, 242`) using strict `ConfigDict(extra="forbid")` schemas in `backend/llm/schemas.py`.
- **Cross-Agent Tick Batching**: Collect all newly perceived observations across all agents in a tick and rate them in a single `rate_importance_batch()` call + persist in a single `add_memories_batch()` transaction (`backend/memory/store.py:72-99`).
- **Location Name Canonicalization**: Normalize LLM-generated `location` strings (case-insensitive / substring match against `world.locations`, fallback to `agent.home_location`) before calling `world.get_location()` (`backend/sim/world.py:228-232`).
- **Tile-Coordinate Math Only**: Always use `loc.anchor` (`anchor_x`, `anchor_y`) for tile distance calculations; never mix `NamedLocation.x/y/width/height` pixel values (`backend/sim/world.py:167-170`) with tile coordinates without dividing by `world.tile_size`.

## Anti-Patterns to Avoid

- **Calling LLMs on Every Tick**: Never run `ConversationDecisionResponse` every tick for adjacent agents who just declined (`initiate=False`) or repeat identical neighbor perceptions every tick without deduplication/cooldown.
- **Awaiting Inside `_step_agent` Movement**: Never `await` while mutating `reserved_tiles` (`backend/sim/engine.py:394-396`); keep all async LLM/DB work before or after the synchronous movement loop.
- **Hardcoding `start_hour = 6` or `min_length = 5` on Partial-Day Replans**: Late-day replans (e.g. `20:00`–`24:00`) have fewer than 5 hours left; use `ReplanResponse` (`min_length=1, max_length=8`) starting at `clock.hour`.
- **Unguarded Global Keyboard Shortcuts in Phaser**: Do not let `keydown-C` (`frontend/src/scenes/VillageScene.ts:62-66`) or Phaser key capture intercept keystrokes while typing in `#god-mode-bar` inputs.

## Dependencies Identified

No new npm or PyPI packages are required for Phase 3 (`backend/pyproject.toml` and `frontend/package.json` already include `fastapi`, `pydantic`, `sqlmodel`, `aiosqlite`, `numpy`, `google-genai`, and `phaser`).

| Package | Version | Purpose |
|---------|---------|---------|
| None (existing stack suffices) | — | All Phase 3 backend & frontend features build on Phase 1–2 dependencies |

## Risks

- **Existing Persistence Test Assertion (`backend/tests/test_engine.py:183`)**: `test_engine_persists_agents_memories_and_sim_state` asserts `json.loads(record.current_plan_json) == agent.routine` with `MockProvider` enabled. *Mitigation:* Update `current_plan_json` serialization cleanly (e.g. storing structured plan JSON and updating `test_engine.py:183` to assert against `agent.serialized_plan()` while preserving `agent.routine` fallback when `llm_gateway is None`).
- **Missing `/events` Proxy in Vite (`frontend/vite.config.ts:6-24`)**: Frontend `fetch("/events")` would 404 in Vite dev mode. *Mitigation:* Add `"/events"` to `vite.config.ts` proxy alongside `/world` and `/agents`.
- **Speech Bubble Z-Index Clipping (`frontend/src/scenes/VillageScene.ts:113, 207`)**: Attaching speech bubbles inside `AgentVisual.container` (`depth 10 + agent.y`) causes northern agents (`y < 10`, `depth < 20`) to render behind `depth 20` location labels. *Mitigation:* Render speech bubbles in a dedicated top-layer container (`depth >= 60`) positioned from the speaker's container coordinates.
- **Live Gemini Latency at 16x Speed**: At `16x` (`62.5ms`/tick), real network LLM calls take longer than one tick interval (`500–1500ms`). *Mitigation:* `asyncio.gather` keeps FastAPI responsive, `_pre_step_payload` (`backend/sim/engine.py:258-262`) keeps `/agents` and `/ws` snapshots non-blocking, and `POST /events` can enqueue into `_pending_events` without blocking on `_step_lock`.

## Recommendations for Planning

1. **Wave 1 (Parallel Schemas/Prompts/Mock + Store/REST Foundations)**:
   - **Plan 3.1 (LLM Planning & Dialogue Schemas, Prompts, and Context-Aware `MockProvider`)**: Add `ReplanResponse`, `MinuteActionItem`, `HourlyActionPlanResponse` in `backend/llm/schemas.py`, author `backend/llm/prompts/planning.py` and `backend/llm/prompts/conversation.py`, and upgrade `MockProvider` (`backend/llm/providers/mock.py`) for partial-day replanning, block decomposition, and rumor-preserving dialogue/summaries + unit tests.
   - **Plan 3.2 (`MemoryStore` Conversation/Event Queries & Frontend Shared Types/Clients)**: Add `add_conversation`, `list_conversations`, `list_events`, and `get_relationship` to `backend/memory/store.py` + unit tests; in parallel (or separate frontend plan), add `DialogueMessage` / `EventMessage` types in `frontend/src/types/sim.ts`, `apiClient.ts`, `wsClient.ts` callbacks, and `/events` proxy in `frontend/vite.config.ts`.
2. **Wave 2 (Agent Brain Modules — `planner.py`, `conversation.py`, `agent.py`)**:
   - **Plan 3.3 (Hierarchical Planner & Agent Cognitive Wrapper)**: Implement `backend/agents/planner.py` (wake-up day plan → lazy hourly/minute action decomposition → interruption replanning + location canonicalization) and `backend/agents/agent.py` (`Perceive` deduplication, `Remember` batch collection, `Decide` target/action resolution) with offline deterministic tests.
   - **Plan 3.4 (Proximity Conversation Manager)**: Implement `backend/agents/conversation.py` (`<= 2` Manhattan tiles, both free, dual initiate/decline pair cooldowns, `<= 6` turn dialogue grounded in `MemoryRetriever`, `ConversationRecord` + dual `conversation` memory persistence, relationship affinity delta, and WS `dialogue` payload emission) with offline deterministic tests including rumor transfer.
3. **Wave 3 (SimulationEngine Integration, `POST /events`, & Phaser/DOM UI)**:
   - **Plan 3.5 (`SimulationEngine` Cognitive Loop & `POST /events` God-Mode API)**: Wire `agent.py`, `planner.py`, `conversation.py`, batched `rate_importance_batch`, `inject_event()` (global + tile-anchor radius delivery + replan trigger), and `register_event_callback` into `backend/sim/engine.py`, `backend/api/rest.py`, and `backend/app/main.py`, updating `backend/tests/test_engine.py:183` and adding `POST /events` + WS `dialogue`/`event` integration tests.
   - **Plan 3.6 (Frontend Speech Bubbles, Event Visuals & God-Mode Injection UI)**: Add `depth >= 60` speech bubbles, location event pulse, and `keydown-C` input focus guard in `frontend/src/scenes/VillageScene.ts`, build `frontend/src/ui/eventInjector.ts` and `frontend/src/ui/activityFeed.ts`, wire in `frontend/src/main.ts` / `frontend/index.html` / `frontend/src/style.css`, and verify with `tsc --noEmit` + `vite build`.
