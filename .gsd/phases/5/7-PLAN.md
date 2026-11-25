---
phase: 5
plan: 7
wave: 4
depends_on:
  - "3"
  - "6"
files_modified:
  - backend/tests/test_100_ticks_invariants.py
  - .github/workflows/ci.yml
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`backend/tests/test_100_ticks_invariants.py` executes a 100-tick offline full-stack cognitive simulation with `MockProvider(seed=42)` and verifies zero crashes, zero wall collisions, valid 4-way A* paths, zero stationary tile overlaps at every tick, valid hierarchical plans + event-triggered replans, exact `GET /metrics` vs SQLite `llm_calls` accounting within budget, valid monotonic `GET /replay/1` JSONL integrity without `metrics` frames, and bit-for-bit cross-run `seed=42` determinism"
    - "`.github/workflows/ci.yml` runs parallel `backend` (`ubuntu-latest`, Python 3.12, CPU-only PyTorch index `--extra-index-url https://download.pytorch.org/whl/cpu`, `ruff`, `mypy`, `pytest`) and `frontend` (`ubuntu-latest`, Node 22, `npm ci`, `typecheck`, `build`) checks on `push` and `pull_request`"
    - "Complete local CI verification (`ruff`, `mypy`, `pytest`, `npm run typecheck`, `npm run build`, and live `scripts/verify_phase1_ws.py`) passes offline"
  artifacts:
    - "backend/tests/test_100_ticks_invariants.py verifies 100-tick behavior invariants and fixed-seed determinism"
    - ".github/workflows/ci.yml configures GitHub Actions backend and frontend CI"
  key_links:
    - "backend/tests/test_100_ticks_invariants.py exercises `create_app`, `SimulationEngine.step_once`, `POST /events`, `GET /relationships`, `GET /metrics`, `GET /replay`, and `GET /replay/1`"
    - ".github/workflows/ci.yml matches local `backend/pyproject.toml` (`pythonpath = ['.']`, `working-directory: backend`) and `frontend/package-lock.json` (`npm ci`)"
---

# Plan 5.7: 100-Tick Invariant Suite, GitHub Actions CI & Full Verification

## Objective
Author the deterministic 100-tick simulation integration & behavior invariant test suite (`backend/tests/test_100_ticks_invariants.py`), create the GitHub Actions CI workflow (`.github/workflows/ci.yml`), and run the full end-to-end verification gate across backend, scripts, and frontend (`REQ-16`, `NFR-03`, `NFR-04`, `NFR-05`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/REQUIREMENTS.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/5/RESEARCH.md
- backend/pyproject.toml
- backend/sim/engine.py
- backend/sim/replay.py
- backend/llm/gateway.py
- backend/api/rest.py
- backend/tests/test_phase3_integration.py
- backend/tests/test_phase4_integration.py
- frontend/package.json
- scripts/verify_phase1_ws.py

## Tasks

<task type="auto">
  <name>Author deterministic 100-tick integration & invariant test suite in backend/tests/test_100_ticks_invariants.py</name>
  <files>
    backend/tests/test_100_ticks_invariants.py
  </files>
  <action>
    Create `backend/tests/test_100_ticks_invariants.py` thoroughly verifying all simulation, spatial, plan, replay, metrics, and determinism invariants across 100 simulated ticks offline.

    Steps:
    1. Implement `test_100_ticks_full_stack_spatial_plan_metrics_and_replay_invariants(tmp_path: Path)`:
       - Create FastAPI app with `Settings(sim_auto_start=False, sim_tick_seconds=0.05, sim_seed=42, llm_provider="mock", embedding_provider="mock", database_url=f"sqlite+aiosqlite:///{(tmp_path / 'sim_100.db').as_posix()}", replay_log_dir=str(tmp_path / "logs"))`.
       - Inside `with TestClient(app) as client:`, step `engine.step_once()` from tick 1 through tick 100 (`client.portal.call(engine.step_once)`), injecting a localized god-mode event via `POST /events` at tick 35 (e.g. `{"text": "Sudden spice caravan arrived at the Market", "location": "Market"}`).
       - Assert at EVERY tick `step_idx` in `1..100`:
         - `payload.tick == step_idx` and `len(payload.agents) == 8`.
         - **Zero wall collisions:** `world.is_walkable(agent.x, agent.y)` for all 8 agents.
         - **Valid active paths:** for every agent with non-empty `agent.path`, assert every step `tile` in `agent.path` satisfies `world.is_walkable(*tile)` and `manhattan(prev, tile) == 1` starting from `(agent.x, agent.y)`.
         - **Zero stationary tile overlaps:** `len({(a.x, a.y) for a in engine.agents.values()}) == 8` (and confirm any non-moving / dwelling / conversing agents never share a tile).
         - **Plan lifecycle validity:** once initialized (`step_idx >= 1`), every agent's `brain.plan_state` contains valid `daily_items` (`0 <= start_hour < end_hour <= 24` and `block.location in world.locations`), `json.loads(engine.get_serialized_plan_json(agent.id))` is a valid list, and affected agents from the tick-35 event clear `needs_replan` cleanly within `<= 6` ticks (unless in conversation hold until free, and cleared well before tick 100).
       - Assert post-100-tick outcomes:
         - Majority of agents moved and visited `>= 2` distinct village locations (`sum(len(a.visited_locations) >= 2 for a in engine.agents.values()) >= 6`).
         - Conversations occurred (`len(conversations) >= 1`) and `GET /relationships` contains valid canonical edges (`agent_a < agent_b`) with non-empty notes.
         - `GET /metrics` matches SQLite `llm_calls` row totals (`total_calls`, `cache_hits`, `tokens_in`, `tokens_out`, `total_tokens`, `cost_est`), verifies `total_calls > 0`, `total_calls < 400` (bounded decision-point calls across 800 agent-ticks!), `avg_latency_ms >= 0.0`, `max_latency_ms >= avg_latency_ms`, non-empty `by_purpose`, `by_model`, and `history` ending with `cumulative_tokens == tokens_in + tokens_out`.
         - `GET /replay` returns day `1` (`tick_count == 101` including tick 0, `first_tick == 0`, `last_tick == 100`), and `GET /replay/1` returns ordered frames containing ticks `0..100` monotonically, the injected `"event"` frame, emitted `"dialogue"` frames, and ZERO `"metrics"` frames.
    2. Implement `test_deterministic_mock_reproducibility_across_runs(tmp_path: Path)`:
       - Run two fresh isolated `create_app(...)` simulations for 40 ticks each with `sim_seed=42`, `llm_provider="mock"`, `embedding_provider="mock"`, and an identical `POST /events` call at tick 15.
       - Assert bit-for-bit identical final agent positions `(x, y)`, `current_action`, `mood`, `current_plan_json`, conversation counts, relationship affinities/notes, `llm_calls` counts + `tokens_in` + `tokens_out`, and replay `tick`/`dialogue`/`event`/`reflection` frame sequences (comparing structured content excluding volatile `latency_ms`).

    AVOID: Asserting exact wall-clock timings (`latency_ms`) across deterministic runs or leaving temp SQLite/JSONL files in repo root.
    USE: `tmp_path` isolation, `MockProvider(seed=42)`, and `EmbeddingService.from_mode("mock")`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_100_ticks_invariants.py
    .venv\Scripts\ruff.exe check tests/test_100_ticks_invariants.py
    .venv\Scripts\mypy.exe tests/test_100_ticks_invariants.py
  </verify>
  <done>
    `backend/tests/test_100_ticks_invariants.py` passes all 100-tick invariant and deterministic reproducibility assertions offline with zero `ruff` or `mypy` issues.
  </done>
</task>

<task type="auto">
  <name>Create GitHub Actions CI workflow in .github/workflows/ci.yml</name>
  <files>
    .github/workflows/ci.yml
  </files>
  <action>
    Author `.github/workflows/ci.yml` automating backend linting, static typing, and pytest plus frontend typecheck and production build on every push and pull request.

    Steps:
    1. Configure workflow triggers and safety defaults:
       - `name: CI`
       - `on: push` and `pull_request`
       - `permissions: contents: read`
       - `concurrency: { group: "${{ github.workflow }}-${{ github.ref }}", cancel-in-progress: true }`
    2. Define `backend` job (`runs-on: ubuntu-latest`, `timeout-minutes: 15`):
       - `actions/checkout@v4`
       - `actions/setup-python@v5` with `python-version: "3.12"`, `cache: "pip"`, `cache-dependency-path: "backend/pyproject.toml"`
       - Install dependencies with CPU-only PyTorch wheel index:
         `python -m pip install --upgrade pip`
         `python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -e "backend[dev]"`
       - Lint with ruff:
         - `ruff check .` (`working-directory: backend`)
         - `ruff check --config backend/pyproject.toml scripts`
       - Typecheck with strict mypy:
         - `mypy .` (`working-directory: backend`)
         - `mypy --config-file backend/pyproject.toml scripts`
       - Run offline deterministic pytest suite:
         - `pytest -v` (`working-directory: backend`)
    3. Define `frontend` job (`runs-on: ubuntu-latest`, `timeout-minutes: 10`):
       - `actions/checkout@v4`
       - `actions/setup-node@v4` with `node-version: "22"`, `cache: "npm"`, `cache-dependency-path: "frontend/package-lock.json"`
       - `npm --prefix frontend ci`
       - `npm --prefix frontend run typecheck`
       - `npm --prefix frontend run build`

    AVOID: Omitting `--extra-index-url https://download.pytorch.org/whl/cpu` (which causes `sentence-transformers` to pull ~2.5 GB CUDA wheels on Linux CI), or running `mypy` from repo root without `working-directory: backend` (which breaks `pythonpath = ["."]` relative module imports).
    USE: Parallel `backend` and `frontend` jobs matching `backend/pyproject.toml` and `frontend/package-lock.json`.
  </action>
  <verify>
    Run from repo root:
    backend\.venv\Scripts\python.exe -c "from pathlib import Path; text = Path('.github/workflows/ci.yml').read_text(encoding='utf-8'); required = ['push:', 'pull_request:', 'https://download.pytorch.org/whl/cpu', 'ruff check .', 'mypy .', 'pytest -v', 'working-directory: backend', 'npm --prefix frontend ci', 'npm --prefix frontend run typecheck', 'npm --prefix frontend run build']; missing = [r for r in required if r not in text]; assert not missing, missing; print('ci_yml_ok')"
  </verify>
  <done>
    `.github/workflows/ci.yml` is valid YAML defining parallel `backend` and `frontend` jobs covering every lint, typecheck, test, and build gate.
  </done>
</task>

<task type="auto">
  <name>Run complete offline CI verification suite and live WebSocket end-to-end check</name>
  <files>
    backend/tests/test_100_ticks_invariants.py
    .github/workflows/ci.yml
  </files>
  <action>
    Execute every single CI command locally plus `scripts/verify_phase1_ws.py` (using separate single-command invocations) to verify zero regressions across the entire repository and ensure no stray `logs/*.jsonl` files remain in workspace root.

    Steps:
    1. Run backend `ruff check .`, `mypy .`, and `pytest -v` from `backend/`.
    2. Run `ruff` and `mypy` on `scripts/` from repo root.
    3. Run `npm --prefix frontend run typecheck` and `npm --prefix frontend run build`.
    4. Run `backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py` and confirm `e2e_ws_ok`.

    AVOID: Chaining commands with `&&` or `||`, or skipping any check after edits.
    USE: Separate command invocations per `PROJECT_RULES.md` shell discipline.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check .
    .venv\Scripts\mypy.exe .
    .venv\Scripts\pytest.exe -v
    Run from repo root (separate commands):
    backend\.venv\Scripts\ruff.exe check --config backend\pyproject.toml scripts
    backend\.venv\Scripts\mypy.exe --config-file backend\pyproject.toml scripts
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
    backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py
  </verify>
  <done>
    Every backend test, `ruff`, `mypy`, frontend `typecheck`, frontend `vite build`, and live `verify_phase1_ws.py` check passes offline with zero errors.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `backend/tests/test_100_ticks_invariants.py` passes all 100-tick spatial, cognitive plan, metrics, replay, and fixed-seed determinism assertions offline
- [ ] `.github/workflows/ci.yml` covers `ruff`, `mypy`, `pytest` (CPU PyTorch), `npm ci`, `typecheck`, and `build`
- [ ] Full backend `pytest`, `ruff`, `mypy`, `scripts/` checks, frontend `typecheck` + `build`, and `scripts/verify_phase1_ws.py` pass locally

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero regressions across Phases 1–5
