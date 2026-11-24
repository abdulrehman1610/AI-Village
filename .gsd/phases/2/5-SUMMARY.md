---
phase: 2
plan: 5
completed_at: 2026-11-24T12:35:00+05:00
duration_minutes: 12
---

# Summary: Plan 2.5 — Engine & FastAPI Lifespan Integration of 8 Personas, Memory & LLM Gateway

## Results
- 3 tasks completed atomically
- All backend offline tests (`67 passed in 9.78s`), `ruff check`, strict `mypy` (38 backend files + verification script), frontend `tsc --noEmit` and `vite build`, and live `/ws` verification (`e2e_ws_ok ticks=[1, 2, 3, 4, 5, 6] moved_agents=8`) passed cleanly

## Tasks Completed
| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Integrate 8 personas, MemoryStore, MemoryRetriever, and LLMGateway into SimulationEngine | `39234d3` | ✅ |
| 2 | Wire Database, EmbeddingService, MemoryStore, MemoryRetriever, and LLMGateway in FastAPI lifespan | `4a81adb` | ✅ |
| 3 | Update 8-agent tests, add persistence integration tests, and run full Phase 2 verification | `0bed014` | ✅ |

## Deviations Applied
- `[Rule 1 - Bug]` Fixed an async snapshot race in `backend/sim/engine.py` where `build_tick_payload()` could return the post-`clock.advance()` tick while `step_once()` was still awaiting `persist_tick_state()`, causing `/ws` initial connect snapshots and the subsequent tick broadcast to emit duplicate tick numbers (`assert 1 > 1` in `test_websocket_streams_advancing_ticks_and_moving_agents`). Preserved `_pre_step_payload` while `_stepping` is true inside `step_once()` and added `test_engine_build_tick_payload_stays_consistent_during_persist` in `backend/tests/test_engine.py` to prevent regression.

## Files Changed
- `backend/sim/engine.py` - Replaced `_SEEDED_AGENT_SPECS` with `SEEDED_PERSONAS` (`personas=` injectable), attached `persona: AgentPersona` to `AgentEntity`, accepted optional `memory_store`/`retriever`/`llm_gateway`, added idempotent `initialize_persistence()` and `persist_tick_state()`, wired `persist_tick_state()` before tick callback emission in `step_once()`, and preserved pre-step snapshots during async persistence.
- `backend/app/main.py` - Added `_build_llm_provider(settings)` supporting `mock` and `gemini`, initialized `Database`, `EmbeddingService`, `MemoryStore`, `MemoryRetriever`, `LLMGateway`, and `SimulationEngine.initialize_persistence()` in `lifespan`, exposed them on `app.state`, and ensured `await engine.stop_loop()` runs before `await db.dispose()` in `finally`.
- `backend/tests/test_engine.py` - Updated 150-tick invariant assertions to 8 seeded agents, added `test_engine_persists_agents_memories_and_sim_state` verifying SQLite persistence (8 agents, `>= 16` memories with 1536-byte blobs, `SimStateRecord`, idempotency, and `MemoryRetriever`), and added `test_engine_build_tick_payload_stays_consistent_during_persist`.
- `backend/tests/test_api_ws.py` - Isolated SQLite DB per test via `tmp_path`, updated `/health`, `/agents`, and `/ws` assertions to 8 agents and sprite indices `{0..7}`, verified `app.state` wiring, and asserted SQLite `agents`, `memories`, and `sim_state` rows after `TestClient` lifecycle.
- `scripts/verify_phase1_ws.py` - Updated `/agents` and `/ws` checks from 4 to 8 agents and isolated server state using `tempfile.TemporaryDirectory()` for `DATABASE_URL`.

## Verification
- `pytest -q --durations=10` (in `backend/`): ✅ `67 passed in 9.78s`
- `ruff check .` (in `backend/`): ✅ `All checks passed!`
- `mypy app sim api agents memory llm tests` (in `backend/`): ✅ `Success: no issues found in 38 source files`
- `ruff check --config backend\pyproject.toml scripts\verify_phase1_ws.py`: ✅ `All checks passed!`
- `mypy --config-file backend\pyproject.toml scripts\verify_phase1_ws.py`: ✅ `Success: no issues found in 1 source file`
- `npm --prefix frontend run typecheck`: ✅ `tsc --noEmit` exited 0
- `npm --prefix frontend run build`: ✅ `vite build` succeeded (`built in 19.49s`)
- `backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py`: ✅ `e2e_ws_ok ticks=[1, 2, 3, 4, 5, 6] moved_agents=8`

## Deferred
None.
