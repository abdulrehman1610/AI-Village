---
phase: 3
plan: 6
wave: 3
depends_on:
  - "1"
  - "2"
  - "4"
  - "5"
files_modified:
  - backend/sim/engine.py
  - backend/api/rest.py
  - backend/app/main.py
  - backend/tests/test_engine.py
  - backend/tests/test_api_ws.py
  - backend/tests/test_phase3_integration.py
  - scripts/verify_phase1_ws.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`SimulationEngine` executes the async `Perceive -> Remember -> Converse -> Decide` cognitive loop before the synchronous `reserved_tiles` A* step when `llm_gateway` is attached, while preserving pure routine cycling when `llm_gateway is None`"
    - "`SimulationEngine.inject_event(text, location=None)` uses `NamedLocation.anchor` tile coordinates (plus location tile bounds / target match) for radius checks, persists `EventRecord` + high-importance witness memories, sets `needs_replan = True`, and broadcasts WS `event` payloads without blocking on `_step_lock`"
    - "`POST /events` validates input and optional location, and WebSocket `/ws` broadcasts live `dialogue`, `event`, and `tick` frames"
    - "100% of backend tests, `ruff`, `mypy`, and live `/ws` verification pass offline with `MockProvider` and zero spatial invariant violations"
  artifacts:
    - "backend/sim/engine.py integrates `AgentBrain`, `DailyPlanner`, `ConversationManager`, `register_event_callback`, and `inject_event`"
    - "backend/api/rest.py exposes `POST /events` (`InjectEventRequest`, `InjectEventResponse`)"
    - "backend/app/main.py wires `engine.register_event_callback(ws_manager.broadcast_json)`"
    - "backend/tests/test_phase3_integration.py verifies cognitive planning, WS dialogue/event broadcasts, `POST /events` global & radius delivery, replanning, and 2-hop rumor propagation"
    - "backend/tests/test_engine.py, backend/tests/test_api_ws.py, and scripts/verify_phase1_ws.py remain green with structured `current_plan_json` and mixed WS frame types"
  key_links:
    - "backend/sim/engine.py coordinates `AgentBrain`, `DailyPlanner`, and `ConversationManager` across `asyncio.gather` before `_step_agent`"
    - "backend/api/rest.py `POST /events` delegates to `engine.inject_event`"
    - "backend/app/main.py connects both `register_tick_callback` and `register_event_callback` to `ws_manager.broadcast_json`"
---

# Plan 3.6: SimulationEngine Cognitive Integration, POST /events API & Phase 3 Backend Verification

## Objective
Wire `AgentBrain`, `DailyPlanner`, and `ConversationManager` into `SimulationEngine` (`backend/sim/engine.py`), implement `POST /events` god-mode injection (`backend/api/rest.py`), broadcast `dialogue` and `event` frames over `/ws` (`backend/app/main.py`), update existing Phase 1/2 tests for structured plans and multi-type WS streams, and prove full Phase 3 backend behavior via offline integration tests.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/3/RESEARCH.md
- backend/sim/engine.py
- backend/sim/world.py
- backend/agents/planner.py
- backend/agents/agent.py
- backend/agents/conversation.py
- backend/api/rest.py
- backend/api/ws.py
- backend/app/main.py
- backend/tests/test_engine.py
- backend/tests/test_api_ws.py
- scripts/verify_phase1_ws.py

## Tasks

<task type="auto">
  <name>Integrate cognitive loop, conversations, event callbacks, and inject_event into SimulationEngine</name>
  <files>
    backend/sim/engine.py
  </files>
  <action>
    Update `backend/sim/engine.py` to run the two-phase cognitive + spatial tick loop when `llm_gateway` is configured and support non-blocking god-mode event injection.

    Steps:
    1. Extend `AgentEntity` with runtime cognitive fields (defaulted cleanly so existing constructors keep working):
       - `conversation_hold_ticks: int = 0`
       - `needs_replan: bool = False`
       - `replan_reason: str = ""`
       - `active_plan_action: str = ""`
    2. Add `EventCallback = Callable[[dict[str, Any]], Awaitable[None]]` and `self._event_callbacks: list[EventCallback] = []` with `register_event_callback(self, callback: EventCallback) -> None`.
    3. Initialize `self.planner = DailyPlanner()`, `self.brains: dict[str, AgentBrain] = {agent_id: AgentBrain(agent_id=agent_id, persona=agent.persona) for agent_id, agent in self.agents.items()}`, and `self.conversation_manager: ConversationManager | None` (constructed when `llm_gateway is not None and memory_store is not None`). Add helper `get_serialized_plan_json(self, agent_id: str) -> str` delegating to `self.brains[agent_id].serialized_plan_json(self.agents[agent_id].routine)`.
    4. In `initialize_persistence()` and `persist_tick_state()`: persist `self.get_serialized_plan_json(agent.id)` into `AgentRecord.current_plan_json` (which stays `json.dumps(agent.routine)` until a structured plan exists or when `llm_gateway is None`).
    5. Implement two-phase `step_once()`:
       - Phase A (runs inside `async with self._step_lock:` ONLY when `self.llm_gateway is not None`):
         1. Tick down `agent.conversation_hold_ticks` (`max(0, agent.conversation_hold_ticks - 1)`).
         2. Gather nearby peers (`manhattan <= 4`) and call `brain.perceive(...)` per agent; batch ALL non-empty new observations across agents into ONE `await self.llm_gateway.rate_importance_batch(...)` + ONE `await self.memory_store.add_memories_batch(...)` (when `memory_store` attached), then call `brain.record_importance(...)` to update `needs_replan` / `replan_reason`!
         3. Select disjoint free pairs via `self.conversation_manager.select_candidate_pairs(...)` and execute conversations concurrently with `asyncio.gather(...)`, collecting `DialogueOutcome.ws_payload` items to emit after `_step_lock` releases.
         4. Run `brain.decide(...)` concurrently via `asyncio.gather(...)` for non-conversing agents (`agent.conversation_hold_ticks == 0`). If `target_location` changed, set `agent.target_location = target_location`, `agent.path = []`, `agent.dwell_ticks_remaining = 0`, and set `agent.active_plan_action = action_text`! Also keep `agent.routine` synced with unique plan locations.
       - Phase B (synchronous spatial step over `reserved_tiles`):
         - Update `_step_agent` so `self._advance_routine_target(agent)` runs ONLY when `self.llm_gateway is None`; when `self.llm_gateway is not None`, `agent.target_location` is owned by `AgentBrain.decide()`, `_step_agent` computes A* paths directly to `agent.target_location` without overwriting it via `routine`, and `MAX_STALL_TICKS` clears `agent.path = []` without erasing `target_location`.
         - For each `agent_id in sorted(self.agents)`: if `agent.conversation_hold_ticks > 0`, skip stepping (keep `"Talking with ..."`). Else run `_step_agent(agent, reserved_tiles)` (updating `_mark_arrived` to call `brain.mark_arrived(...)` and display `agent.active_plan_action` on arrival if non-empty!).
         - Advance `self.clock.advance()`, snapshot `payload`, and `await self.persist_tick_state()`.
       - After releasing `_step_lock`: invoke `_tick_callbacks` with `payload`, then invoke `_event_callbacks` with each pending `dialogue` payload (both wrapped in `try/except` logging exceptions cleanly).
    6. Implement `async def inject_event(self, text: str, location: str | None = None, *, radius: int = 10) -> dict[str, Any]`:
       - Strip `text` (raise `ValueError` if empty).
       - If `location` is non-empty: resolve case-insensitively against `self.world.locations` (raising `KeyError` if unknown).
       - Determine `affected_agents`: all sorted agent IDs if `resolved_location is None`; else agents whose tile `(agent.x, agent.y)` has `manhattan <= radius` from `loc.anchor` OR falls inside `loc`'s tile bounding box (`loc.x // tile_size .. (loc.x + loc.width) // tile_size`, `loc.y // tile_size .. (loc.y + loc.height) // tile_size`) OR `agent.target_location == resolved_location`.
       - Persist `EventRecord(tick=self.clock.tick, kind="god_event", text=clean_text, location=resolved_location, source="god")` if `memory_store` attached.
       - Format observation `f"[EVENT]{' at ' + resolved_location if resolved_location else ''}: {clean_text}"`, persist `MemoryCreate(..., importance=8, created_tick=self.clock.tick)` via `add_memories_batch` for affected agents (so DB/memory state updates immediately even when paused), and set `agent.needs_replan = True` and `agent.replan_reason = obs_text` on affected agents!
       - Emit `event_payload = {"type": "event", "id": event_id, "tick": self.clock.tick, "sim_time": self.clock.sim_time_str, "text": clean_text, "location": resolved_location, "affected_agents": affected}` to `_event_callbacks` and return `event_payload`.

    AVOID: Holding `_step_lock` inside `inject_event`, using `NamedLocation.x/y` pixel values directly for tile distance, or awaiting inside `_step_agent`.
    USE: `loc.anchor` tile coordinates, `asyncio.gather` in Phase A, synchronous `reserved_tiles` in Phase B, and Phase 1 routine fallback when `llm_gateway is None`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check sim/engine.py
    .venv\Scripts\mypy.exe sim/engine.py
  </verify>
  <done>
    `backend/sim/engine.py` runs the full cognitive loop, conversations, and `inject_event` cleanly and passes `ruff` + strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Add POST /events endpoint in rest.py and wire event WS broadcasts in main.py</name>
  <files>
    backend/api/rest.py
    backend/app/main.py
  </files>
  <action>
    Expose `POST /events` in `backend/api/rest.py` and register `SimulationEngine` event callbacks on `ConnectionManager` in `backend/app/main.py`.

    Steps:
    1. In `backend/api/rest.py`:
       - Add `InjectEventRequest(BaseModel)`: `text: str = Field(min_length=1, max_length=500)` and `location: str | None = None`.
       - Add `InjectEventResponse(BaseModel)`: `id: int | None`, `tick: int`, `sim_time: str`, `text: str`, `location: str | None`, `affected_agents: list[str]`.
       - Add `@router.post("/events", response_model=InjectEventResponse)`:
         - Strip `payload.text`; if empty, raise `HTTPException(status_code=422, detail="Event text must not be blank.")`.
         - Normalize `location = payload.location.strip() if payload.location and payload.location.strip() else None`.
         - Call `await engine.inject_event(clean_text, location=normalized_location)`; catch `KeyError` (unknown location) and raise `HTTPException(status_code=400, detail=...)`.
         - Return `InjectEventResponse(**result)`.
    2. In `backend/app/main.py`:
       - Inside `lifespan`, register `async def _broadcast_event(payload: dict[str, Any]) -> None: await ws_manager.broadcast_json(payload)` via `engine.register_event_callback(_broadcast_event)`.

    AVOID: Allowing unknown location strings to cause an unhandled 500 `KeyError` or blank whitespace-only event injections.
    USE: Explicit `HTTPException(status_code=400)` / `422` validation and `ws_manager.broadcast_json`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check api/rest.py app/main.py
    .venv\Scripts\mypy.exe api/rest.py app/main.py
  </verify>
  <done>
    `POST /events` validates inputs and delegates to `SimulationEngine.inject_event`, `app/main.py` broadcasts both ticks and events/dialogues to `/ws`, and `ruff` + `mypy` pass.
  </done>
</task>

<task type="auto">
  <name>Update existing tests/verify script and add Phase 3 end-to-end integration tests</name>
  <files>
    backend/tests/test_engine.py
    backend/tests/test_api_ws.py
    backend/tests/test_phase3_integration.py
    scripts/verify_phase1_ws.py
  </files>
  <action>
    Update Phase 1/2 test expectations for structured plans and multi-message `/ws` streams, and create `backend/tests/test_phase3_integration.py` covering all Phase 3 P0 MVP behaviors offline.

    Steps:
    1. In `backend/tests/test_engine.py`:
       - At line 183 (`test_engine_persists_agents_memories_and_sim_state`), update `assert json.loads(record.current_plan_json) == agent.routine` to assert `record.current_plan_json == engine.get_serialized_plan_json(agent_id)` and verify the parsed plan list contains 5–8 structured daily plan items with `start_hour`, `end_hour`, `location`, and `description`.
       - Keep `test_engine_150_ticks_spatial_invariants` (`llm_gateway=None`) completely intact to verify backwards-compatible routine cycling.
    2. In `backend/tests/test_api_ws.py`:
       - In `test_websocket_streams_advancing_ticks_and_moving_agents`, collect `"tick"` messages from `ws.receive_json()` skipping any interleaved `"dialogue"` or `"event"` payloads so the test never flakes if agents converse early.
    3. In `scripts/verify_phase1_ws.py`:
       - In `verify_live_server`, read from `ws.recv()` in a loop until 6 `"tick"` messages are collected, ignoring valid `"dialogue"` or `"event"` frames instead of raising on non-`"tick"` messages.
    4. Create `backend/tests/test_phase3_integration.py`:
       - Test 1 (`test_engine_80_ticks_cognitive_loop_and_dialogue`): run 80 ticks with `SimulationEngine` + `MockProvider` + `:memory:` `Database` (placing two agents or letting natural routing bring pairs within 2 tiles, plus asserting zero wall collisions, zero tile overlaps, structured plans persisted for all 8 agents, bounded LLM calls without per-tick explosion, and `dialogue` WS callback + `ConversationRecord` persisted).
       - Test 2 (`test_post_events_global_radius_and_validation`): via FastAPI `TestClient(create_app(...))` with isolated `tmp_path` DB and `sim_auto_start=False`, test:
         - `POST /events` with empty whitespace -> `422`, unknown location `"Mars"` -> `400`.
         - `POST /events` with `{"text": "A fire broke out in the ovens", "location": "Bakery"}` -> `200`, affects agents near `Bakery` (`aria`, etc.) while excluding distant agents (`elena` at `Home_Elena`), persists `EventRecord` + witness memories, marks `needs_replan = True`, and broadcasts WS `event` frame.
         - `POST /events` with `{"text": "Festival announced tonight", "location": null}` -> `200`, affects all 8 agents, broadcasts WS `event` frame.
       - Test 3 (`test_event_triggers_replan_and_multi_hop_rumor_spread`): inject a localized event near Maya, step ticks so Maya replans (`"plan"` memory created, `needs_replan` cleared), bring Liam adjacent to Maya (`ConversationManager` triggers dialogue spreading the event text to Liam's memory), then move Liam adjacent to Clara so Clara receives the rumor on hop 2!

    AVOID: Calling external APIs or leaving SQLite test files in repo directories.
    USE: `MockProvider(seed=42)`, `EmbeddingService.from_mode("mock")`, `:memory:` DBs, and `tmp_path`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v
    .venv\Scripts\ruff.exe check .
    .venv\Scripts\mypy.exe app sim api agents memory llm tests
    Run from repo root (separate commands):
    backend\.venv\Scripts\ruff.exe check --config backend\pyproject.toml scripts\verify_phase1_ws.py
    backend\.venv\Scripts\mypy.exe --config-file backend\pyproject.toml scripts\verify_phase1_ws.py
    backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py
  </verify>
  <done>
    Entire backend `pytest` suite passes offline with zero failures, `ruff` and strict `mypy` pass across all backend packages and scripts, and `scripts/verify_phase1_ws.py` prints `e2e_ws_ok`.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `SimulationEngine` runs cognitive `Perceive -> Remember -> Converse -> Decide` asynchronously before synchronous `reserved_tiles` A* stepping, with pure routine fallback when `llm_gateway is None`
- [ ] `POST /events` and `SimulationEngine.inject_event` deliver global or tile-anchor-radius observations, set `needs_replan`, persist `EventRecord` + memories, and broadcast `event` frames on `/ws`
- [ ] All backend unit and Phase 3 integration tests, `ruff`, `mypy`, and live `/ws` verification pass offline

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero regressions in Phase 1 and Phase 2 test suites
