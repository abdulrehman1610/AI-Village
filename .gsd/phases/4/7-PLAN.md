---
phase: 4
plan: 7
wave: 4
depends_on:
  - "5"
  - "6"
files_modified:
  - backend/api/rest.py
  - backend/tests/test_api_ws.py
  - backend/tests/test_phase4_integration.py
  - scripts/verify_phase1_ws.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`POST /sim/start`, `POST /sim/pause`, and `POST /sim/speed` (validating `1`, `4`, `16` and rejecting invalid ints/bools with HTTP 422) drive `SimulationEngine` time controls and return `SimControlResponse`"
    - "`GET /agents/{id}` returns persona profile, coordinates, current/target location, action, `mood`, reflection progress, structured `plan`, `recent_memories`, `top_memories`, `reflections` (with parsed `cited_memory_ids` and no raw `embedding` blob), and projected `relationships` (404 on unknown agent)"
    - "`GET /relationships` returns `nodes` and canonical undirected `edges` (`agent_a < agent_b`) enriched with agent names"
    - "Full backend `pytest`, `ruff`, `mypy`, frontend `tsc --noEmit` + `vite build`, and live `/ws` verification (`scripts/verify_phase1_ws.py`) pass offline with `MockProvider`"
  artifacts:
    - "backend/api/rest.py implements `POST /sim/start`, `POST /sim/pause`, `POST /sim/speed`, `GET /agents/{agent_id}`, and `GET /relationships` with strict Pydantic v2 DTOs"
    - "backend/tests/test_api_ws.py accepts `reflection` frames on `/ws` and tests all Phase 4 REST endpoints (including 404 and 422 validation)"
    - "backend/tests/test_phase4_integration.py verifies end-to-end threshold-150 reflection cycles, relationship & mood evolution, and live REST+WS time control roundtrips offline"
    - "scripts/verify_phase1_ws.py accepts `reflection` frames alongside `dialogue` and `event` frames on `/ws`"
  key_links:
    - "backend/api/rest.py `/sim/*` delegates to `SimulationEngine.start_simulation`, `pause_simulation`, and `set_simulation_speed`"
    - "backend/api/rest.py `/agents/{agent_id}` and `/relationships` read authoritative runtime state from `SimulationEngine` and persisted memories/relationships from `MemoryStore`"
---

# Plan 4.7: Phase 4 REST Endpoints, Integration Tests & Full-Stack Verification

## Objective
Implement the Phase 4 REST API endpoints (`POST /sim/start`, `POST /sim/pause`, `POST /sim/speed`, `GET /agents/{id}`, `GET /relationships`) in `backend/api/rest.py`, update WebSocket frame filters in `test_api_ws.py` and `scripts/verify_phase1_ws.py`, add end-to-end Phase 4 integration tests (`backend/tests/test_phase4_integration.py`), and verify the complete full-stack backend and frontend offline (`REQ-09`, `REQ-10`, `REQ-11`, `REQ-12`, `NFR-01`, `NFR-03`, `NFR-04`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/REQUIREMENTS.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/4/RESEARCH.md
- backend/api/rest.py
- backend/sim/engine.py
- backend/agents/planner.py
- backend/memory/store.py
- backend/tests/test_api_ws.py
- scripts/verify_phase1_ws.py
- frontend/src/types/sim.ts

## Tasks

<task type="auto">
  <name>Implement /sim/start, /sim/pause, /sim/speed, /agents/{id}, and /relationships in backend/api/rest.py</name>
  <files>
    backend/api/rest.py
  </files>
  <action>
    Add the Phase 4 simulation control, agent inspector, and relationship graph endpoints to `backend/api/rest.py` with strict Pydantic v2 request/response DTOs matching the frontend TypeScript contracts in `frontend/src/types/sim.ts`.

    Steps:
    1. Add time-control DTOs and routes:
       - `SimSpeedRequest(BaseModel)`: `speed: Literal[1, 4, 16]` with `@field_validator("speed", mode="before")` explicitly rejecting `isinstance(value, bool)` with `ValueError("speed must be 1, 4, or 16")` so `{"speed": true}` returns HTTP 422.
       - `SimControlResponse(BaseModel)`: `running: bool`, `speed: int`, `tick: int`, `sim_time: str`, `day: int`.
       - `POST /sim/start` -> `payload = await engine.start_simulation()`, return `SimControlResponse(...)`.
       - `POST /sim/pause` -> `payload = await engine.pause_simulation()`, return `SimControlResponse(...)`.
       - `POST /sim/speed` -> `payload = await engine.set_simulation_speed(body.speed)`, return `SimControlResponse(...)` (catch `ValueError` -> 422).
    2. Add Agent Inspector DTOs and `GET /agents/{agent_id}` route:
       - `AgentPersonaDTO`, `PlanStepDTO`, `PlanBlockDTO`, `AgentPlanDTO`, `AgentMemoryDTO`, `AgentRelationshipDTO`, and `AgentDetailResponse` matching `frontend/src/types/sim.ts` field names (`id`, `name`, `role`, `sprite_index`, `x`, `y`, `home_location`, `current_location`, `target_location`, `current_action`, `mood`, `accumulated_importance`, `reflection_threshold`, `persona`, `plan`, `recent_memories`, `top_memories`, `reflections`, `relationships`).
       - Add helper `_resolve_agent_location_label(agent: AgentEntity, world: WorldMap) -> str` (tile bounding box match -> Manhattan `<= 2` anchor match -> `"Village"`).
       - Add helper `_parse_cited_memory_ids(metadata_json: str) -> list[int]` safely parsing `json.loads(metadata_json).get("cited_memory_ids", [])`.
       - Add helper `_to_memory_dto(record: MemoryRecord) -> AgentMemoryDTO` (never exposing `record.embedding`).
       - In `GET /agents/{agent_id}`:
         - If `agent_id not in engine.agents`, raise `HTTPException(status_code=404, detail=f"Unknown agent: {agent_id!r}")`.
         - Fetch `all_memories = await memory_store.list_memories(agent_id, limit=60)` and `rels = await memory_store.list_relationships(agent_id)` if `memory_store` attached.
         - Slice `recent_memories = [_to_memory_dto(m) for m in all_memories[:20]]`.
         - Compute `top_memories = [_to_memory_dto(m) for m in sorted(all_memories, key=lambda m: (m.importance, m.created_tick, m.id or 0), reverse=True)[:8]]`.
         - Compute `reflections = [_to_memory_dto(m) for m in all_memories if m.type == "reflection"][:10]`.
         - Project `relationships` relative to `agent_id` (`peer_id`, `peer_name`, `affinity`, `notes`, `last_interaction_tick`) sorted by `(-abs(affinity), peer_name)`.
         - Build `plan` from `brain.plan_state` when present (`day`, `active_block_index`, `active_minute_index`, `hourly_focus_by_block.get(active_block_index)`, `current_step()`, and `daily_plan` blocks with `actions`); if `brain.plan_state is None`, return `AgentPlanDTO(day=None, active_block_index=0, active_minute_index=0, hourly_focus=None, current_step=None, daily_plan=[PlanBlockDTO(start_hour=6 + idx, end_hour=7 + idx, location=loc, description=f"Routine visit to {loc}") for idx, loc in enumerate(agent.routine[:18])])`.
    3. Add Relationships DTOs and `GET /relationships` route:
       - `RelationshipNodeDTO`: `id`, `name`, `role`, `mood`.
       - `RelationshipEdgeDTO`: `agent_a`, `agent_b`, `agent_a_name`, `agent_b_name`, `affinity`, `notes`, `last_interaction_tick`.
       - `RelationshipsResponse`: `nodes: list[RelationshipNodeDTO]`, `edges: list[RelationshipEdgeDTO]`.
       - Deduplicate/normalize edges so `agent_a < agent_b` and map names from `engine.agents`.

    AVOID: Returning raw SQLModel `MemoryRecord` instances (which contain raw `bytes` in `embedding` and fail JSON serialization) or accepting boolean `True` for `speed: Literal[1, 4, 16]`.
    USE: Explicit Pydantic DTOs, `_to_memory_dto`, and shared `_get_memory_store(request)` helper.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check api/rest.py
    .venv\Scripts\mypy.exe api/rest.py
  </verify>
  <done>
    `backend/api/rest.py` exposes `/sim/start`, `/sim/pause`, `/sim/speed`, `/agents/{agent_id}`, and `/relationships` with strict Pydantic v2 validation and passes `ruff` + strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Update test_api_ws.py and verify_phase1_ws.py for reflection frames and REST controls</name>
  <files>
    backend/tests/test_api_ws.py
    scripts/verify_phase1_ws.py
  </files>
  <action>
    Update WebSocket frame filters to accept `"reflection"` broadcasts and add API unit coverage for the new Phase 4 REST endpoints in `backend/tests/test_api_ws.py`.

    Steps:
    1. In `backend/tests/test_api_ws.py`:
       - Update line 110 in `test_websocket_streams_advancing_ticks_and_moving_agents`: `assert frame_type in {"tick", "dialogue", "event", "reflection"}`.
       - Add `test_sim_control_agent_detail_and_relationships_endpoints(tmp_path: Path)`:
         - Create app with `sim_auto_start=False`, `sim_tick_seconds=0.05`, isolated `tmp_path` DB.
         - Verify `POST /sim/speed` rejects `{"speed": 2}`, `{"speed": 0}`, and `{"speed": true}` with HTTP `422`.
         - Verify `POST /sim/speed` `{"speed": 4}` returns `200` with `speed == 4`, `running is False`.
         - Verify `POST /sim/start` -> `200` with `running is True`, `POST /sim/pause` -> `200` with `running is False`.
         - Verify `GET /agents/unknown_id` -> `404`.
         - Verify `GET /agents/maya` -> `200` with persona, `mood`, `plan`, `recent_memories`, `top_memories`, `reflections`, `relationships`, and assert `"embedding"` is NOT present in any memory dict.
         - Verify `GET /relationships` -> `200` with 8 `nodes` and valid `edges` list.
    2. In `scripts/verify_phase1_ws.py`:
       - Update line 130 so `if msg_type in {"dialogue", "event", "reflection"}:` skips valid cognitive frames while collecting 6 `"tick"` frames.

    AVOID: Weakening any existing assertion in `test_api_ws.py` or `verify_phase1_ws.py`.
    USE: Isolated `tmp_path` SQLite DBs and `TestClient(app)`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_api_ws.py
    .venv\Scripts\ruff.exe check tests/test_api_ws.py
    .venv\Scripts\mypy.exe tests/test_api_ws.py
  </verify>
  <done>
    `test_api_ws.py` and `verify_phase1_ws.py` handle `"reflection"` WS frames, all new REST endpoint validations pass, and `ruff` + `mypy` report zero issues.
  </done>
</task>

<task type="auto">
  <name>Add Phase 4 integration tests and run full-stack Phase 4 verification</name>
  <files>
    backend/tests/test_phase4_integration.py
  </files>
  <action>
    Create `backend/tests/test_phase4_integration.py` covering end-to-end Phase 4 requirements (`REQ-09`, `REQ-10` backend, `REQ-11`, `REQ-12`, `NFR-01`, `NFR-03`) offline with `MockProvider`, and run the complete backend + frontend verification suite.

    Steps:
    1. Create `backend/tests/test_phase4_integration.py`:
       - Test 1 (`test_threshold_150_reflection_cites_memories_and_emits_ws`):
         - Create app (`sim_auto_start=False`, default `reflection_threshold=150`, `MockProvider`, isolated `tmp_path` DB).
         - Seed/inject enough salient observations for Maya so stepping crosses exact default `150` accumulated importance (e.g., 19 injected/observed memories summing `>= 150` or stepping with injected events) while keeping LLM budget bounded.
         - Connect WS or step `engine.step_once()` and assert:
           - `"reflection"` WS message emitted with keys `{"type", "tick", "sim_time", "agent_id", "agent_name", "insight", "cited_memory_ids"}` (`type == "reflection"`, `agent_id == "maya"`, non-empty `cited_memory_ids`).
           - `GET /agents/maya` returns `reflections` containing the new reflection with matching `cited_memory_ids`, `accumulated_importance < 150` (accumulator reset!), and updated `mood`.
           - Stepping 3 additional quiet ticks does NOT trigger a duplicate cascade reflection.
       - Test 2 (`test_conversation_relationship_and_mood_exposed_by_rest_apis`):
         - Place Maya and Liam adjacent, step `engine.step_once()` so `ConversationManager` runs dialogue, then query `GET /relationships` and `GET /agents/maya` and `GET /agents/liam`:
           - Assert `GET /relationships` contains canonical edge `agent_a == "liam"`, `agent_b == "maya"` (`agent_a < agent_b`, `len(edges) == 1` for that pair), non-empty `notes`, `agent_a_name == "Liam"`, `agent_b_name == "Maya"`.
           - Assert `GET /agents/maya` shows `peer_id == "liam"` and `GET /agents/liam` shows `peer_id == "maya"`, plus updated non-empty `mood` and `current_action` / `plan`.
       - Test 3 (`test_time_controls_rest_and_ws_live_sync`):
         - Start app with `sim_auto_start=True`, `sim_tick_seconds=0.4`.
         - Connect `/ws`, verify initial `tick` frame, call `POST /sim/pause` -> receive WS `tick` frame with `running is False`.
         - Call `POST /sim/speed` `{"speed": 16}` -> receive WS `tick` frame with `speed == 16`, then call `POST /sim/start` -> receive WS `tick` frame with `running is True` and advancing `tick` values promptly at 16x.
    2. Run full verification across backend, scripts, and frontend (one command per invocation!).

    AVOID: Creating flaky wall-clock race assertions on CI runners (use generous bounded receive loops / timeouts while still proving fast wakeup vs 1x base tick).
    USE: `TestClient(app)`, `MockProvider(seed=42)`, `DeterministicEmbeddingProvider`, and isolated `tmp_path` DBs.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v
    .venv\Scripts\ruff.exe check .
    .venv\Scripts\mypy.exe app sim api agents memory llm tests
    Run from repo root (separate commands):
    backend\.venv\Scripts\ruff.exe check --config backend\pyproject.toml scripts\verify_phase1_ws.py
    backend\.venv\Scripts\mypy.exe --config-file backend\pyproject.toml scripts\verify_phase1_ws.py
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
    backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py
  </verify>
  <done>
    Entire backend `pytest` suite passes offline, `ruff` and strict `mypy` pass across all backend packages and `scripts/verify_phase1_ws.py`, frontend `tsc --noEmit` + `vite build` pass, and `scripts/verify_phase1_ws.py` prints `e2e_ws_ok`.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `POST /sim/start`, `POST /sim/pause`, and `POST /sim/speed` control the live clock and return `SimControlResponse`
- [ ] `GET /agents/{id}` returns full inspector state (persona, mood, location/action, plan, memories, reflections, relationships) without `embedding` blobs, and 404 on unknown IDs
- [ ] `GET /relationships` returns canonical undirected edges (`agent_a < agent_b`) with node metadata
- [ ] Full backend `pytest`, `ruff`, `mypy`, frontend `typecheck` + `build`, and live `verify_phase1_ws.py` pass offline

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero regressions in Phase 1–3 tests
