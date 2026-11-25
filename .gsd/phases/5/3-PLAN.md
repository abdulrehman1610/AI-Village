---
phase: 5
plan: 3
wave: 2
depends_on:
  - "1"
files_modified:
  - backend/sim/engine.py
  - backend/app/main.py
  - backend/api/rest.py
  - scripts/verify_phase1_ws.py
  - backend/tests/test_api_ws.py
  - backend/tests/test_phase4_integration.py
  - backend/tests/test_phase3_integration.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`SimulationEngine` wires optional `ReplayLogger` (logging tick-0 idempotently at initialization, advancing `[events, tick]` frames on `step_once()`, and `inject_event()` payloads without logging `broadcast_current_tick()` control clicks or `metrics` frames) and broadcasts WS `metrics` whenever `llm_gateway.total_recorded_calls` advances"
    - "`backend/app/main.py` instantiates `ReplayLogger` from `resolved_settings.resolved_replay_log_dir()`, attaches it to `SimulationEngine` and `app.state.replay_logger`"
    - "`backend/api/rest.py` exposes `GET /metrics`, `GET /replay`, and `GET /replay/{day}` (returning 404 when day log is absent and 422 for `day < 1`)"
    - "All WebSocket allowlists in `scripts/verify_phase1_ws.py`, `test_api_ws.py`, and `test_phase4_integration.py` accept `'metrics'` frames, and all test apps isolate `replay_log_dir` in temp paths"
  artifacts:
    - "backend/sim/engine.py supports `replay_logger`, logs frames non-blockingly, and emits WS `metrics` frames"
    - "backend/app/main.py constructs and registers `ReplayLogger` on engine and `app.state`"
    - "backend/api/rest.py implements `GET /metrics`, `GET /replay`, and `GET /replay/{day}` with strict Pydantic v2 DTOs"
    - "backend/tests/test_api_ws.py, test_phase3_integration.py, test_phase4_integration.py, and scripts/verify_phase1_ws.py pass with isolated replay dirs and updated WS allowlists"
  key_links:
    - "backend/sim/engine.py calls `replay_logger.log_frames` and `llm_gateway.get_metrics_snapshot` outside `_step_lock`"
    - "backend/api/rest.py reads `app.state.llm_gateway` for `/metrics` and `app.state.replay_logger` for `/replay` and `/replay/{day}`"
---

# Plan 5.3: Backend Engine Replay & Metrics Integration and REST Endpoints

## Objective
Integrate `ReplayLogger` and rolling WebSocket `metrics` emissions into `SimulationEngine` and `app/main.py`, expose `GET /metrics`, `GET /replay`, and `GET /replay/{day}` in `backend/api/rest.py`, update WebSocket frame allowlists and temp log isolation in existing tests and `scripts/verify_phase1_ws.py`, and add API/WS tests (`REQ-13`, `REQ-14`, `NFR-03`, `NFR-04`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/5/RESEARCH.md
- backend/sim/engine.py
- backend/sim/replay.py
- backend/llm/gateway.py
- backend/app/main.py
- backend/api/rest.py
- scripts/verify_phase1_ws.py
- backend/tests/test_api_ws.py
- backend/tests/test_phase4_integration.py
- backend/tests/test_phase3_integration.py

## Tasks

<task type="auto">
  <name>Wire ReplayLogger and rolling WS metrics broadcasts into SimulationEngine and app/main.py</name>
  <files>
    backend/sim/engine.py
    backend/app/main.py
  </files>
  <action>
    Connect `ReplayLogger` and `LLMGateway.get_metrics_snapshot()` into `SimulationEngine` lifecycle and `FastAPI` lifespan.

    Steps:
    1. In `backend/sim/engine.py`:
       - Import `ReplayLogger` from `sim.replay`.
       - Add optional `replay_logger: ReplayLogger | None = None` keyword parameter to `SimulationEngine.__init__` and store `self.replay_logger = replay_logger`.
       - In `initialize_persistence()`: after `get_or_create_sim_state(...)`, if `self.replay_logger is not None and self.clock.tick == 0`, await `self.replay_logger.ensure_initial_tick(self._build_live_tick_payload().model_dump(), start_minute_of_day=self.clock.start_minute_of_day)`.
       - In `inject_event(...)`: after `await self._emit_event_payload(event_payload)`, if `self.replay_logger is not None`, await `self.replay_logger.log_frame(event_payload, start_minute_of_day=self.clock.start_minute_of_day)`.
       - In `step_once()`:
         - Capture `calls_before = self.llm_gateway.total_recorded_calls if self.llm_gateway is not None else 0` before running `_run_cognitive_phase`.
         - After releasing `self._step_lock`:
           - Serialize `tick_dict = payload.model_dump()`.
           - If `self.replay_logger is not None`, await `self.replay_logger.log_frames([*pending_event_payloads, tick_dict], start_minute_of_day=self.clock.start_minute_of_day)` so pre-advance `T` cognitive events precede post-advance `T+1` tick frames in strictly monotonic tick order and accurate day files.
           - Call `await self._broadcast_tick_payload(payload)` and `await self._emit_event_payload(event_payload)` for each item in `pending_event_payloads`.
           - If `self.llm_gateway is not None and self.llm_gateway.total_recorded_calls > calls_before`, fetch `metrics_snapshot = await self.llm_gateway.get_metrics_snapshot(tick=payload.tick, sim_time=payload.sim_time, day=payload.day)` and emit `await self._emit_event_payload({"type": "metrics", **metrics_snapshot.model_dump()})`.
    2. In `backend/app/main.py`:
       - Import `ReplayLogger` from `sim.replay`.
       - Instantiate `replay_logger = ReplayLogger(resolved_settings.resolved_replay_log_dir(), start_minute_of_day=clock.start_minute_of_day)` after `clock`.
       - Pass `replay_logger=replay_logger` into `SimulationEngine(...)`.
       - Set `app.state.replay_logger = replay_logger`.

    AVOID: Logging inside `broadcast_current_tick()` (which would duplicate same-tick records when clicking Pause/Play/Speed) or writing `"metrics"` frames into `.jsonl` files.
    USE: `self.replay_logger.log_frames` outside `_step_lock` and `calls_before` delta check for WS `metrics` broadcast.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check sim/engine.py app/main.py
    .venv\Scripts\mypy.exe sim/engine.py app/main.py
  </verify>
  <done>
    `SimulationEngine` and `app/main.py` integrate `ReplayLogger` and conditional WS `metrics` broadcasts cleanly with zero `ruff` or strict `mypy` issues.
  </done>
</task>

<task type="auto">
  <name>Implement GET /metrics, GET /replay, and GET /replay/{day} in backend/api/rest.py</name>
  <files>
    backend/api/rest.py
  </files>
  <action>
    Expose the telemetry metrics and day-replay REST endpoints with strict Pydantic v2 response validation.

    Steps:
    1. In `backend/api/rest.py`, import `Annotated` from `typing`, `Path as FastAPIPath` from `fastapi`, `LLMGateway, MetricsSnapshot` from `llm.gateway`, and `ReplayDayLog, ReplayDaySummary, ReplayLogger` from `sim.replay`.
    2. Add `ReplayDaysResponse(BaseModel)`: `current_day: int`, `days: list[ReplayDaySummary]`.
    3. Add helper `_get_llm_gateway(request: Request) -> LLMGateway | None` and `_get_replay_logger(request: Request) -> ReplayLogger | None`.
    4. Implement `@router.get("/metrics", response_model=MetricsSnapshot)`:
       - Read `engine = _get_engine(request)` and `gateway = _get_llm_gateway(request)`.
       - If `gateway is not None`, return `await gateway.get_metrics_snapshot(tick=engine.clock.tick, sim_time=engine.clock.sim_time_str, day=engine.clock.day)`.
       - Otherwise return a zeroed `MetricsSnapshot(tick=engine.clock.tick, sim_time=engine.clock.sim_time_str, day=engine.clock.day, total_calls=0, cache_hits=0, cache_hit_rate=0.0, tokens_in=0, tokens_out=0, total_tokens=0, cost_est=0.0, avg_latency_ms=0.0, max_latency_ms=0.0, daily_budget_usd=0.0, daily_token_limit=0, budget_day=1, budget_tokens_used=0, budget_cost_used=0.0, by_purpose=[], by_model=[], history=[])`.
    5. Implement `@router.get("/replay", response_model=ReplayDaysResponse)`:
       - Read `engine = _get_engine(request)` and `replay_logger = _get_replay_logger(request)`.
       - Fetch `days = await replay_logger.list_days()` if `replay_logger is not None` else `[]`.
       - Return `ReplayDaysResponse(current_day=engine.clock.day, days=days)`.
    6. Implement `@router.get("/replay/{day}", response_model=ReplayDayLog)`:
       - Validate `day: Annotated[int, FastAPIPath(ge=1)]`.
       - Read `replay_logger = _get_replay_logger(request)`.
       - Fetch `day_log = await replay_logger.read_day(day)` if `replay_logger is not None` else `None`.
       - If `day_log is None`, raise `HTTPException(status_code=404, detail=f"Replay log for day {day} not found.")`.
       - Return `day_log`.

    AVOID: Returning raw file strings without JSON validation or allowing `day <= 0` without HTTP 422.
    USE: `Annotated[int, FastAPIPath(ge=1)]`, `MetricsSnapshot`, `ReplayDaysResponse`, and `ReplayDayLog`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check api/rest.py
    .venv\Scripts\mypy.exe api/rest.py
  </verify>
  <done>
    `backend/api/rest.py` serves `GET /metrics`, `GET /replay`, and `GET /replay/{day}` with strict Pydantic v2 schemas and passes `ruff` and strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Update WS frame allowlists, isolate replay dirs in tests/scripts, and add Phase 5 REST/WS tests</name>
  <files>
    scripts/verify_phase1_ws.py
    backend/tests/test_api_ws.py
    backend/tests/test_phase4_integration.py
    backend/tests/test_phase3_integration.py
  </files>
  <action>
    Update hardcoded WS frame-type allowlists for `"metrics"`, prevent existing tests/scripts from writing into the workspace `logs/` folder, and test `/metrics`, `/replay`, `/replay/{day}`, and WS `metrics` broadcasts.

    Steps:
    1. In `scripts/verify_phase1_ws.py`:
       - Line 130: update `if msg_type in {"dialogue", "event", "reflection", "metrics"}: continue`.
       - In `main()`: set `env["REPLAY_LOG_DIR"] = str(Path(tmp_dir) / "logs")` alongside `DATABASE_URL`.
    2. In `backend/tests/test_phase4_integration.py`:
       - Update lines 110, 268, 282, 303 to accept `{"tick", "dialogue", "event", "reflection", "metrics"}`.
       - Pass `replay_log_dir=str(tmp_path / "logs")` in all `Settings(...)` calls.
    3. In `backend/tests/test_phase3_integration.py`:
       - Pass `replay_log_dir=str(tmp_path / "logs")` in `test_post_events_global_radius_and_validation`'s `Settings(...)` call.
    4. In `backend/tests/test_api_ws.py`:
       - Pass `replay_log_dir=str(tmp_path / "logs")` in all `Settings(...)` calls.
       - Update line 110 to `assert frame_type in {"tick", "dialogue", "event", "reflection", "metrics"}`.
       - Add `test_metrics_and_replay_endpoints_and_ws_metrics(tmp_path: Path)`:
         - Boot app with `sim_auto_start=False`, isolated `tmp_path` DB and `replay_log_dir`.
         - Verify initial `GET /metrics` returns HTTP `200` with `total_calls == 0`, `by_purpose == []`, `by_model == []`, `history == []`.
         - Verify `GET /replay` lists day `1` (`tick_count == 1`, `first_tick == 0`, `last_tick == 0`), `GET /replay/1` returns the tick-0 frame, `GET /replay/99` returns `404`, and `GET /replay/0` returns `422`.
         - Connect `/ws`, step `engine.step_once()` twice via `client.portal.call(...)` and inject one event via `POST /events`.
         - Assert `/ws` emits at least one `"metrics"` frame with `total_calls > 0`, `tokens_in > 0`, `tokens_out > 0`, `by_purpose`, `by_model`, and `history`.
         - Assert `GET /metrics` matches the SQLite `llm_calls` row counts/tokens and `GET /replay/1` contains ordered frames for ticks `0, 1, 2` plus the injected `"event"` frame and zero `"metrics"` frames.

    AVOID: Leaving any test writing into the repo root `logs/` directory or weakening any existing Phase 1–4 assertions.
    USE: Isolated `tmp_path / "logs"` directories and `client.portal.call` for deterministic stepping.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_api_ws.py tests/test_phase3_integration.py tests/test_phase4_integration.py tests/test_engine.py
    .venv\Scripts\ruff.exe check .
    .venv\Scripts\mypy.exe app sim api agents memory llm tests
    Run from repo root (separate commands):
    backend\.venv\Scripts\ruff.exe check --config backend\pyproject.toml scripts\verify_phase1_ws.py
    backend\.venv\Scripts\mypy.exe --config-file backend\pyproject.toml scripts\verify_phase1_ws.py
  </verify>
  <done>
    All existing and new Phase 5 REST/WS/integration tests pass offline, no stray `logs/*.jsonl` files are written to workspace root during pytest, and `ruff` + `mypy` report zero issues across backend and `scripts/verify_phase1_ws.py`.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `SimulationEngine` writes advancing simulation frames to `ReplayLogger` and broadcasts WS `metrics` whenever new LLM calls are recorded
- [ ] `GET /metrics`, `GET /replay`, and `GET /replay/{day}` return validated Pydantic v2 payloads and proper 404/422 errors
- [ ] Existing WS verification tests and `scripts/verify_phase1_ws.py` handle `"metrics"` frames cleanly without polluting workspace `logs/`
- [ ] All backend unit and integration tests plus `ruff` and `mypy` pass offline

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in Phase 1–4 tests
