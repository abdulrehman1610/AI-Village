---
phase: 5
plan: 7
completed_at: 2026-11-25T13:02:00+05:00
duration_minutes: 14
---

# Summary: Plan 5.7 — 100-Tick Invariant Suite, GitHub Actions CI & Full Verification

## Results
- 3 tasks completed (`2` file-producing commits + `1` full repository verification gate)
- Added `backend/tests/test_100_ticks_invariants.py` verifying 100-tick offline spatial, pathing, stationary overlap, plan lifecycle, localized event replanning, relationship graph, `GET /metrics` vs SQLite `llm_calls`, `GET /replay/1` JSONL integrity, and cross-run `seed=42` determinism
- Added `.github/workflows/ci.yml` automating parallel `backend` (CPU-only PyTorch index, `ruff`, `mypy`, `pytest`) and `frontend` (`npm ci`, `typecheck`, `build`) CI checks
- Verified zero regressions across the entire repository (`117 passed` in `pytest`, `ruff`, `mypy`, `tsc --noEmit`, `vite build`, and live `scripts/verify_phase1_ws.py`), with zero stray `logs/*.jsonl` files in the workspace root

## Tasks Completed
| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Author deterministic 100-tick integration & invariant test suite in `backend/tests/test_100_ticks_invariants.py` | `ecd4604` | ✅ |
| 2 | Create GitHub Actions CI workflow in `.github/workflows/ci.yml` | `3af7ac9` | ✅ |
| 3 | Run complete offline CI verification suite and live WebSocket end-to-end check | Verification only (no diff) | ✅ |

## Deviations Applied
- **Localized tick-35 event location & visited-location invariant refinement inside `backend/tests/test_100_ticks_invariants.py`**:
  - Targeted `"Bakery"` instead of `"Market"` for the tick-35 `POST /events` injection because at tick 35 (`06:35 AM`) four villagers (`aria`, `elena`, `maya`, `sam`) are near or heading to `Bakery` whereas zero villagers are near `Market`; this verifies strict localized filtering (`1 <= len(affected_agents) < 8`) and replanning (`needs_replan` cleared within `<= 6` non-hold ticks).
  - Checked distinct visited village locations over `{agent.home_location} | agent.visited_locations` (alongside `>= 15` distinct traversed `(x, y)` tiles for `>= 6` agents and `len(visited_locations) >= 1` for all 8 agents) because `AgentEntity.visited_locations` initializes empty at tick 0 and 100 morning ticks (`06:00`–`07:40`) mostly cover the first daily plan block plus the post-event replan target.
  - Sorted `llm_calls` rows by `(tick, agent_id, purpose, model, tokens_in, tokens_out, cache_hit)` and `list_conversations()` records by `(tick_start, participants)` in `test_deterministic_mock_reproducibility_across_runs` because concurrent `asyncio.gather` SQLite inserts at the same tick can commit in either order while leaving agent states, metrics, relationships, and replay frames bit-for-bit identical.

## Deferred
- Pre-existing unrelated working-tree modifications (`backend/api/__init__.py`, `backend/app/__init__.py`, `backend/sim/__init__.py`, `backend/tests/__init__.py`) and untracked root GSD/tooling files were left untouched outside this plan's commits.

## Files Changed
- `backend/tests/test_100_ticks_invariants.py` — Added `test_100_ticks_full_stack_spatial_plan_metrics_and_replay_invariants` (100-tick full-stack invariant checks) and `test_deterministic_mock_reproducibility_across_runs` (two isolated 40-tick `seed=42` runs with identical tick-15 event checking bit-for-bit reproducibility across agents, conversations, relationships, `llm_calls`, `metrics`, and `replay_frames` excluding volatile latency).
- `.github/workflows/ci.yml` — Added GitHub Actions `CI` workflow triggered on `push` and `pull_request` with `backend` (`ubuntu-latest`, Python 3.12, `--extra-index-url https://download.pytorch.org/whl/cpu -e "backend[dev]"`, `ruff`, `mypy`, `pytest -v`) and `frontend` (`ubuntu-latest`, Node 22, `npm --prefix frontend ci`, `typecheck`, `build`).

## Verification
- `ruff check tests/test_100_ticks_invariants.py` (`cwd=backend`): ✅ Passed (`All checks passed!`)
- `mypy tests/test_100_ticks_invariants.py` (`cwd=backend`): ✅ Passed (`Success: no issues found in 1 source file`)
- `pytest -v tests/test_100_ticks_invariants.py` (`cwd=backend`): ✅ Passed (`2 passed in 28.37s`)
- `.github/workflows/ci.yml` directive & `yaml.safe_load` check: ✅ Passed (`ci_yml_ok`, `yaml_ok ['backend', 'frontend']`)
- `ruff check .` (`cwd=backend`): ✅ Passed (`All checks passed!`)
- `mypy .` (`cwd=backend`): ✅ Passed (`Success: no issues found in 54 source files`)
- `pytest -v` (`cwd=backend`): ✅ Passed (`117 passed in 57.49s`)
- `backend\.venv\Scripts\ruff.exe check --config backend\pyproject.toml scripts`: ✅ Passed (`All checks passed!`)
- `backend\.venv\Scripts\mypy.exe --config-file backend\pyproject.toml scripts`: ✅ Passed (`Success: no issues found in 2 source files`)
- `npm --prefix frontend run typecheck`: ✅ Passed (`tsc --noEmit`, exit code 0)
- `npm --prefix frontend run build`: ✅ Passed (`vite build`, 22 modules transformed, `dist/index.html` 3.33 kB, `dist/assets/index-DaA30pDt.css` 21.77 kB, `dist/assets/index-DDaHEXim.js` 2,194.20 kB, built in 27.58s, exit code 0)
- `backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py`: ✅ Passed (`e2e_ws_ok ticks=[0, 1, 2, 3, 4, 5] moved_agents=7`)
- `Test-Path logs` at repo root: ✅ Confirmed `False` (no stray replay JSONL files in repo root)
