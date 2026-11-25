---
phase: 5
plan: 3
completed_at: 2026-11-25T12:22:00+05:00
duration_minutes: 9
---

# Summary: Plan 5.3 — Backend Engine Replay & Metrics Integration and REST Endpoints

## Results
- 3 tasks completed
- All verifications passed offline (`pytest`, `ruff check`, `mypy`, and `scripts/verify_phase1_ws.py`)
- Exact JSON contract alignment confirmed across `/metrics`, `/replay`, `/replay/{day}`, WebSocket `metrics` frames, and `frontend/src/types/sim.ts`

## Tasks Completed
| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Wire `ReplayLogger` and rolling WS `metrics` broadcasts into `SimulationEngine` and `app/main.py` | `796b3f3` | ✅ |
| 2 | Implement `GET /metrics`, `GET /replay`, and `GET /replay/{day}` in `backend/api/rest.py` | `bfc2f3c` | ✅ |
| 3 | Update WS frame allowlists, isolate replay dirs in tests/scripts, and add Phase 5 REST/WS tests | `bba69f4` | ✅ |

## Deviations Applied
None — executed as planned.

## Files Changed
- `backend/sim/engine.py` — Added optional `replay_logger: ReplayLogger | None = None`, tick-0 idempotent anchor in `initialize_persistence()`, `log_frame()` on `inject_event()`, `log_frames([*pending_event_payloads, tick_dict])` outside `_step_lock` in `step_once()`, and conditional `{"type": "metrics", ...}` broadcast whenever `llm_gateway.total_recorded_calls` advances.
- `backend/app/main.py` — Instantiated `ReplayLogger` from `resolved_settings.resolved_replay_log_dir()`, passed it into `SimulationEngine`, and registered `app.state.replay_logger`.
- `backend/api/rest.py` — Added `ReplayDaysResponse`, `_get_llm_gateway`, `_get_replay_logger`, `GET /metrics` (`MetricsSnapshot`), `GET /replay` (`ReplayDaysResponse`), and `GET /replay/{day}` (`ReplayDayLog` with `Annotated[int, FastAPIPath(ge=1)]` -> HTTP 422 / missing day -> HTTP 404).
- `scripts/verify_phase1_ws.py` — Allowed `"metrics"` WS frames in `verify_live_server()` and set `env["REPLAY_LOG_DIR"]` inside `TemporaryDirectory`.
- `backend/tests/test_api_ws.py` — Isolated `replay_log_dir` in `tmp_path`, allowed `"metrics"` frames in WS loop, and added `test_metrics_and_replay_endpoints_and_ws_metrics`.
- `backend/tests/test_phase4_integration.py` — Isolated `replay_log_dir` in all `Settings(...)` instances and updated WS allowlists to accept `"metrics"`.
- `backend/tests/test_phase3_integration.py` — Isolated `replay_log_dir` in `test_post_events_global_radius_and_validation`.

## Verification
- `ruff check sim/engine.py app/main.py` (in `backend/`): ✅ Passed (`All checks passed!`)
- `mypy sim/engine.py app/main.py` (in `backend/`): ✅ Passed (`Success: no issues found in 2 source files`)
- `ruff check api/rest.py` (in `backend/`): ✅ Passed (`All checks passed!`)
- `mypy api/rest.py` (in `backend/`): ✅ Passed (`Success: no issues found in 1 source file`)
- `pytest -v tests/test_api_ws.py tests/test_phase3_integration.py tests/test_phase4_integration.py tests/test_engine.py` (in `backend/`): ✅ Passed (`18 passed in 14.67s`)
- `ruff check .` (in `backend/`): ✅ Passed (`All checks passed!`)
- `mypy app sim api agents memory llm tests` (in `backend/`): ✅ Passed (`Success: no issues found in 53 source files`)
- `backend\.venv\Scripts\ruff.exe check --config backend\pyproject.toml scripts\verify_phase1_ws.py`: ✅ Passed (`All checks passed!`)
- `backend\.venv\Scripts\mypy.exe --config-file backend\pyproject.toml scripts\verify_phase1_ws.py`: ✅ Passed (`Success: no issues found in 1 source file`)
- `pytest -v` (in `backend/`): ✅ Passed (`115 passed in 14.98s`)
- `backend\.venv\Scripts\python.exe scripts\verify_phase1_ws.py`: ✅ Passed (`e2e_ws_ok ticks=[0, 1, 2, 3, 4, 5] moved_agents=7`)
- `Test-Path logs` (repo root): ✅ Confirmed `False` (zero stray workspace replay logs)
