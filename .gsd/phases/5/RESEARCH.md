---
phase: 5
researched_at: 2026-11-25
discovery_level: 2
---

# Phase 5 Research: Cost Dashboard, Replay, Relationship Graph, Tests & CI

## Objective
Answer the four Phase 5 technical discovery questions covering:
1. `LLMCallRecord` (`llm_calls`) telemetry aggregation for `GET /metrics` and WebSocket `metrics` broadcasts.
2. `SimClock` / `SimulationEngine` day calculation, payload emission order, non-blocking JSONL event-log writing (`logs/day_{day}.jsonl`), and `GET /replay` + `GET /replay/{day}` contracts.
3. Frontend dependency setup (`chart.js`, `cytoscape`, `@types/cytoscape`), DOM/CSS z-index layering, and clean mode switching between live WebSocket updates and recorded Day Replay frames.
4. Existing backend/frontend test and lint/typecheck setup, the 100-tick deterministic integration + invariant suite (`REQ-16`, `NFR-03`, `NFR-05`), and `.github/workflows/ci.yml`.

## Discovery Level
**Level 2** — Standard research (new frontend visualization libraries, replay state-mode coordination, async JSONL I/O, and GitHub Actions CI pipeline design).

---

## Key Decisions

### Decision 1: Telemetry Aggregation Source & WS `metrics` Cadence (`REQ-14`)
**Question:** Where should `GET /metrics` and WS `metrics` compute totals, breakdowns (`by_purpose`, `by_model`), latency statistics, and rolling tick history, and when should WS `metrics` broadcast?
**Options Considered:**
1. **Extend `LLMGateway` with `get_metrics_snapshot()` querying `llm_calls` (with in-memory fallback when `db is None`) + emit WS `metrics` from `SimulationEngine` when LLM call count advances (and via `GET /metrics` on demand):** Single source of truth aligned with `LLMGateway._record_call()` (`backend/llm/gateway.py:493-514`); avoids noisy duplicate WS frames on pure movement ticks while pushing live updates immediately whenever any planning, conversation, importance, or reflection call occurs.
2. **Add separate SQL queries in `MemoryStore` and broadcast WS `metrics` on every single tick:** Duplicates `LLMGateway`'s existing `db` access (`backend/llm/gateway.py:98, 431-453`) and doubles WebSocket frame volume during quiet movement ticks.
3. **Maintain all breakdown/history arrays purely in memory on `LLMGateway`:** Loses historical `llm_calls` rows across process restarts even when SQLite persistence is active.

**Decision:** **Option 1** — Add `get_metrics_snapshot()` on `LLMGateway` (`backend/llm/gateway.py`) backed by `LLMCallRecord` (`backend/memory/models.py:76-90`) when `self.db is not None` (and an in-memory call buffer fallback when `self.db is None`), expose `GET /metrics` in `backend/api/rest.py`, and emit `{"type": "metrics", ...}` from `SimulationEngine.step_once()` via `_event_callbacks` whenever new `llm_calls` were recorded during that tick (plus initial fetch on dashboard open via `GET /metrics`). Update existing WS frame-type allowlists in `scripts/verify_phase1_ws.py:130`, `backend/tests/test_api_ws.py:110`, and `backend/tests/test_phase4_integration.py:110, 268, 282, 303` to include `"metrics"`.
**Confidence:** High

### Decision 2: Non-Blocking JSONL Replay Writer & Configurable Directory (`REQ-13`)
**Question:** How should structured simulation frames be written to `logs/day_{day}.jsonl` without blocking the asyncio loop or polluting the workspace during tests?
**Options Considered:**
1. **Dedicated `ReplayLogger` (`backend/sim/replay.py`) using `asyncio.Lock` + `asyncio.to_thread` batched per tick, configured via `Settings.replay_log_dir` defaulting to `REPO_ROOT / "logs"`:** Zero new Python dependencies, matches `.gitignore:28` (`logs/*.jsonl`), performs at most one worker-thread append per tick for `[tick_payload, *event_payloads]`, and lets tests pass `Settings(replay_log_dir=str(tmp_path / "logs"))`.
2. **Add `aiofiles` dependency and open/write per event callback:** Requires adding a new runtime package and types stub for simple append-only JSONL writes.
3. **Synchronous `Path.open("a")` on the event loop thread:** Risks event-loop jitter at `16x` speed (`0.0625s`/tick) on Windows filesystem flushes.

**Decision:** **Option 1** — Implement `ReplayLogger` with `asyncio.Lock` + `asyncio.to_thread`, configure `replay_log_dir: str = ""` + `resolved_replay_log_dir() -> Path` in `backend/app/config.py:12-53` (defaulting to `REPO_ROOT / "logs"`), log advancing `step_once()` tick snapshots and `dialogue`/`event`/`reflection` payloads keyed by `SimClock` day (`((clock.start_minute_of_day + payload_tick) // 1440) + 1`), and expose `GET /replay` (available days metadata) + `GET /replay/{day}` (parsed frames for `day >= 1`).
**Confidence:** High

### Decision 3: Frontend Overlay Architecture & Live vs. Replay Isolation (`REQ-10`, `REQ-13`, `REQ-14`)
**Question:** How should the Cytoscape.js Relationship Graph, Chart.js Cost Dashboard, and Day Replay UI mount and coordinate with Phaser 3, `AgentInspector`, `ActivityFeed`, and `VillageWsClient`?
**Options Considered:**
1. **HUD tool toggles (`Relationships`, `Metrics`, `Replay`) + mutually exclusive `#stage` modal drawers (`z-index: 35`) for Graph/Metrics + a Replay scrubber bar that gates `wsClient` visual callbacks behind `replayController.isActive()` while caching `lastLiveTick`:** Keeps the live WebSocket connected and server simulation undisturbed, prevents live ticks from overwriting replay playback, snaps sprites cleanly when scrubbing (`immediate` mode), and restores `lastLiveTick` immediately on exiting replay.
2. **Disconnect `VillageWsClient` and `POST /sim/pause` whenever Replay opens:** Mutates authoritative server simulation state for all viewers just to inspect a recorded log.
3. **Create a second Phaser `Scene` for Replay:** Duplicates tilemap, spritesheet, speech-bubble, and camera code from `VillageScene.ts` (`639` lines).

**Decision:** **Option 1** — Reuse `VillageScene` with a replay-aware `applyTick(tickMsg, { immediate?: boolean })` + public `resetTransientVisuals()` wrapper around `cleanupTransientVisuals()` (`frontend/src/scenes/VillageScene.ts:448-463`), gate live `onTick`/`onDialogue`/`onEvent`/`onReflection` rendering in `frontend/src/main.ts:203-232` while replay is active (still forwarding `onMetrics` to the Cost Dashboard and caching `lastLiveTick`), and mount Graph and Cost Dashboard as mutually exclusive `z-index: 35` overlays inside `#stage`.
**Confidence:** High

### Decision 4: CI Toolchain & PyTorch CPU Index (`REQ-16`, `NFR-03`, `NFR-04`)
**Question:** How should `.github/workflows/ci.yml` install backend and frontend dependencies and execute checks quickly and deterministically?
**Options Considered:**
1. **Standard `actions/setup-python@v5` (`3.12`, pip cache) with `pip install --extra-index-url https://download.pytorch.org/whl/cpu -e "backend[dev]"` + `actions/setup-node@v4` (`22`, npm cache on `frontend/package-lock.json`) with `npm --prefix frontend ci`:** Matches the repo's PEP 621 `backend/pyproject.toml` (no `uv.lock` exists) and `frontend/package-lock.json`, avoids downloading ~2.5 GB CUDA wheels on `ubuntu-latest`, and runs `ruff`, `mypy`, `pytest`, `npm run typecheck`, and `npm run build` in parallel or fast sequential jobs.
2. **Plain `pip install -e "backend[dev]"` on `ubuntu-latest`:** Pulls full CUDA `torch` via `sentence-transformers>=3.2.0` (`backend/pyproject.toml:20`), bloating install time and runner disk usage.

**Decision:** **Option 1** — Use two parallel GitHub Actions jobs (`backend` on Python 3.12 with `--extra-index-url https://download.pytorch.org/whl/cpu` + `ruff check`, `mypy`, `pytest`; `frontend` on Node 22 with `npm ci`, `npm run typecheck`, `npm run build`), plus lint/typecheck coverage of `scripts/`.
**Confidence:** High

---

## Findings

### 1. `llm_calls` Schema & Telemetry Aggregation (`Question 1`)
- **`LLMCallRecord` columns (`backend/memory/models.py:76-90`):**
  - `id: int | None` (PK), `tick: int` (indexed), `agent_id: str | None` (indexed), `purpose: str` (indexed), `model: str`, `tokens_in: int = 0`, `tokens_out: int = 0`, `latency_ms: float = 0.0`, `cost_est: float = 0.0`, `cache_hit: bool = False`.
- **How calls are recorded (`backend/llm/gateway.py:155-226, 493-514`):**
  - Prompt-cache hits (`backend/llm/gateway.py:155-174`) insert an `LLMCallRecord` with `tokens_in=0`, `tokens_out=0`, `cost_est=0.0`, `cache_hit=True`, and measured deserialization `latency_ms`.
  - Live/mock provider calls (`backend/llm/gateway.py:193-226`) insert one `LLMCallRecord` per attempt (including failed first attempts before retry repair) with `tokens_in`, `tokens_out`, `latency_ms`, `cost_est` (via `estimate_cost_usd` at `backend/llm/gateway.py:57-76`), and `cache_hit=False`.
  - Known `purpose` values across gateway helpers (`backend/llm/gateway.py:35-43, 252-427`): `"daily_plan"`, `"replan"`, `"hourly_plan"`, `"conversation_decision"`, `"dialogue_turn"`, `"conversation_summary"`, `"importance_batch"`, `"salient_questions"`, `"reflection"`.
- **Current query surface:**
  - `MemoryStore` (`backend/memory/store.py:42-454`) has **zero** methods querying `LLMCallRecord`.
  - `LLMGateway.get_usage_summary(self, *, tick: int | None = None)` (`backend/llm/gateway.py:429-478`) returns only flat scalars (`total_calls`, `cache_hits`, `tokens_in`, `tokens_out`, `total_tokens`, `cost_est`). It does **not** yet compute `latency_ms` aggregates (`avg_latency_ms`, `max_latency_ms`), `by_purpose` / `by_model` breakdowns, budget utilization fields, or rolling per-tick history needed by Chart.js.
  - Note: `LLMGateway.day_for_tick(tick)` (`backend/llm/gateway.py:116-118`) uses `(max(0, tick) // 1440) + 1` for internal budget gating, whereas `SimClock.day` (`backend/sim/clock.py:46-48`) uses `((360 + tick) // 1440) + 1`. Preserve `LLMGateway.day_for_tick` for existing budget unit tests in `backend/tests/test_llm_gateway.py:337`, and include authoritative `tick`, `sim_time`, `day` from `SimClock` on the `/metrics` and WS `metrics` envelope.
- **WS Frame-Type Allowlist Catch:**
  - `scripts/verify_phase1_ws.py:130` (`if msg_type in {"dialogue", "event", "reflection"}: continue`) and `backend/tests/test_api_ws.py:110` + `backend/tests/test_phase4_integration.py:110, 268, 282, 303` explicitly assert `frame_type in {"tick", "dialogue", "event", "reflection"}`. Any WS `{"type": "metrics", ...}` broadcast will fail those checks unless `"metrics"` is added to those sets.

**Sources:**
- `backend/memory/models.py:76-90`
- `backend/memory/store.py:42-454`
- `backend/llm/gateway.py:35-119, 155-226, 429-514`
- `scripts/verify_phase1_ws.py:129-134`
- `backend/tests/test_api_ws.py:108-111`
- `backend/tests/test_phase4_integration.py:108-111, 267-269, 281-283, 302-304`

---

### 2. `SimClock`, `SimulationEngine` Emission Order & JSONL Replay (`Question 2`)
- **Day calculation (`backend/sim/clock.py:9, 16-69`):**
  - `TICKS_PER_DAY = 1440`, `start_minute_of_day = 360` (`Day 1 06:00`).
  - `total_minutes = self.start_minute_of_day + self.tick` (`backend/sim/clock.py:43`); `day = (self.total_minutes // 1440) + 1` (`backend/sim/clock.py:48`). Ticks `0..1079` map to Day 1; tick `1080` (`Day 2 00:00`) begins Day 2.
- **Payload shapes & exact `step_once()` ordering (`backend/sim/engine.py:844-876`):**
  1. Cognitive phase runs **before** `self.clock.advance()` (`backend/sim/engine.py:726-735, 851-854`), so `dialogue` (`backend/agents/conversation.py:368-377`) and `reflection` (`backend/agents/reflection.py:167-178`) payloads carry pre-advance `tick = T` and `sim_time`.
  2. Movement runs (`backend/sim/engine.py:856-861`), then `self.clock.advance()` increments to `tick = T + 1` (`backend/sim/engine.py:863`), and `_build_live_tick_payload()` creates `TickPayload` (`type="tick"`, `tick=T+1`, `sim_time`, `day`, `speed`, `running`, `agents` at `backend/sim/engine.py:45-55, 326-334`).
  3. Outside `_step_lock`, `_broadcast_tick_payload(payload)` fires (`backend/sim/engine.py:871`), followed by `_emit_event_payload(event_payload)` for each pending `dialogue` and `reflection` (`backend/sim/engine.py:873-874`).
  4. Out-of-band `inject_event()` (`backend/sim/engine.py:756-842`) builds `{"type": "event", "id": ..., "tick": current_tick, "sim_time": ..., "text": ..., "location": ..., "affected_agents": [...]}` and calls `_emit_event_payload(event_payload)`.
  5. Playback control methods (`start_simulation`, `pause_simulation`, `set_simulation_speed` at `backend/sim/engine.py:878-898`) call `broadcast_current_tick()`, which re-broadcasts the current `tick` without advancing `self.clock.tick`.
- **Cleanest JSONL writer & REST contract:**
  - `.gitignore:28` already ignores `logs/*.jsonl`.
  - Add `replay_log_dir: str = ""` and `resolved_replay_log_dir() -> Path` (default `REPO_ROOT / "logs"`) to `Settings` (`backend/app/config.py:12-53`) and `REPLAY_LOG_DIR=` to `.env.example`.
  - Log ticks **only** on initialization (optional tick-0 anchor if file is new) and inside `step_once()` + `inject_event()`, not inside `broadcast_current_tick()`, so `Pause`/`Play`/`Speed` clicks never write duplicate same-tick snapshots to `day_{day}.jsonl`.
  - Compute each JSONL record's target file day from `((self.clock.start_minute_of_day + record_tick) // 1440) + 1` so pre-advance `T = 1079` cognitive events stay in `day_1.jsonl` when `T + 1 = 1080` writes the first tick of `day_2.jsonl`.
  - Expose `GET /replay` (`ReplayDaysResponse`: available recorded days sorted ascending with `day`, `tick_count`, `first_tick`, `last_tick`, `first_sim_time`, `last_sim_time`, plus `current_day`) and `GET /replay/{day}` (`ReplayLogResponse`: `day`, `frames` list of typed `tick`/`dialogue`/`event`/`reflection` objects, returning `404` if `day_{day}.jsonl` is missing and `422` if `day < 1`).

**Sources:**
- `backend/sim/clock.py:8-69`
- `backend/sim/engine.py:31-55, 326-367, 726-748, 756-898`
- `backend/agents/conversation.py:368-377`
- `backend/agents/reflection.py:167-178`
- `backend/app/config.py:7-53`
- `.gitignore:25-29`

---

### 3. Frontend Packages, Layout & Live/Replay Mode Switching (`Question 3`)
- **Packages in `frontend/package.json` (`frontend/package.json:12-18`):**
  - Currently installed: `"phaser": "^3.85.2"`, `"typescript": "^5.6.3"`, `"vite": "^5.4.11"`.
  - Missing and required for Phase 5:
    - Runtime `dependencies`: `"chart.js": "^4.4.8"` (latest `4.6.2`, ships built-in TS types; register required Chart.js components explicitly) and `"cytoscape": "^3.30.4"` (latest `3.35.0`).
    - Dev `devDependencies`: `"@types/cytoscape": "^3.21.9"` (latest `3.31.0`, required under `"strict": true` in `frontend/tsconfig.json`).
- **Vite dev proxy (`frontend/vite.config.ts:6-36`):**
  - Currently proxies `/ws`, `/health`, `/world`, `/agents`, `/events`, `/sim`, `/relationships`.
  - Must add `/metrics` and `/replay` proxy entries targeting `http://127.0.0.1:8000` (`changeOrigin: true`); `/replay` prefix-matches both `GET /replay` and `GET /replay/{day}`.
- **DOM structure & CSS layering (`frontend/index.html:10-61`, `frontend/src/style.css:17-35, 198-263`):**
  - `#hud` (`frontend/index.html:11-26`) contains `.hud-brand`, `.hud-clock` (`#sim-time`, `#sim-tick`, `#time-controls`), and `#agents-bar`. Adding a `.hud-nav` / `.hud-tools` container in `#hud` gives one-click toggle buttons for **Relationships**, **Cost / Metrics**, and **Replay**.
  - `#stage` (`frontend/index.html:27-35`) hosts `#game-container` (Phaser canvas), `#activity-feed` (`z-index: 20`, right), and `#agent-inspector` (`z-index: 25`, left).
  - Mounting `#relationship-panel` (Cytoscape.js) and `#metrics-panel` (Chart.js) inside `#stage` at `z-index: 35` avoids colliding with Phaser drag/click handlers, `#activity-feed`, or `#agent-inspector`. Clicking a Cytoscape agent node can invoke `selectAgent(agentId)` (`frontend/src/main.ts:152-156`) to inspect that villager directly.
  - Because `#agent-inspector.hidden, .hidden { display: none; }` (`frontend/src/style.css:260-263`) gives hidden containers `0x0` layout size, Cytoscape (`cy.resize(); cy.fit()`) and Chart.js (`chart.resize()`) must be resized on `requestAnimationFrame` after removing `.hidden`.
- **Clean Live vs. Replay coordination (`frontend/src/main.ts:203-235`, `frontend/src/scenes/VillageScene.ts:180-283, 448-463, 557-638`):**
  - When entering Replay Mode:
    1. Fetch `GET /replay` (and `GET /replay/{day}` for the selected day), index frames by `tick` (storing the latest `TickMessage` at or before each tick plus associated `dialogue`/`event`/`reflection` frames at that tick).
    2. Mark `replayActive = true` in `main.ts`: `wsClient` stays connected, caches incoming `tickMsg` into `lastLiveTick`, still forwards `onMetrics` to the Cost Dashboard, and skips mutating `villageScene`, HUD clock, `timeControls`, `agentChips`, `activityFeed`, and `agentInspector` with live ticks.
    3. Visually disable live `#time-controls` and `#god-mode-bar` (replacing/overlaying with a Replay Control Bar: Day `<select>`, Play/Pause, `1x`/`4x`/`16x` client timer, `<input type="range">` scrubber, and `Exit Replay / Back to Live` button).
    4. Expose `resetTransientVisuals()` and `applyTick(tickMsg, { immediate?: boolean })` on `VillageScene` (`frontend/src/scenes/VillageScene.ts:180, 448, 618-634`): manual scrubber jumps pass `immediate: true` + `resetTransientVisuals()` so sprites snap directly without stale tweens/bubbles, while sequential replay playback steps tween smoothly and trigger `showDialogue` / `showEvent` / `showReflection` + `activityFeed` entries.
    5. On Exit Replay: stop client replay timer, call `villageScene.resetTransientVisuals()`, clear replay feed items (`activityFeed.clear()`), re-apply `lastLiveTick` immediately, and re-enable live controls.

**Sources:**
- `frontend/package.json:1-19`
- `frontend/vite.config.ts:1-38`
- `frontend/index.html:10-63`
- `frontend/src/style.css:17-35, 198-263`
- `frontend/src/main.ts:136-244`
- `frontend/src/scenes/VillageScene.ts:180-283, 448-463, 557-638`
- `frontend/src/ui/activityFeed.ts:10-38`
- `frontend/src/net/wsClient.ts:15-21, 80-101`
- `frontend/src/net/apiClient.ts:87-163`

---

### 4. Test Suite, Determinism, Linters & GitHub Actions CI (`Question 4`)
- **Lockfiles & tooling state:**
  - **Backend (`backend/pyproject.toml:1-61`):** Uses PEP 621 `pyproject.toml` with `setuptools` (`requires-python = ">=3.12"`). **No `uv.lock` exists** anywhere in the repository. Local environment uses `backend/.venv` installed with `--extra-index-url https://download.pytorch.org/whl/cpu -e "backend[dev]"` (`.gsd/phases/2/1-PLAN.md:76`).
  - **Frontend (`frontend/package-lock.json`):** Lockfile exists (`npm --prefix frontend ci` supported; must be updated via `npm --prefix frontend install ...` when adding `chart.js`, `cytoscape`, and `@types/cytoscape`).
  - **Linters & typecheckers:**
    - `ruff check .` in `backend/` (`line-length = 100`, `target-version = "py312"`, rules `E, F, I, UP, B` at `backend/pyproject.toml:42-48`) plus `ruff check --config backend/pyproject.toml scripts`.
    - `mypy .` in `backend/` (`strict = true`, `python_version = "3.12"` at `backend/pyproject.toml:49-61`) plus `mypy --config-file backend/pyproject.toml scripts`.
    - `npm --prefix frontend run typecheck` (`tsc --noEmit`) and `npm --prefix frontend run build` (`vite build`) (`frontend/package.json:6-11`).
- **Existing tests (`backend/tests/`):**
  - 16 test files (`107` tests passing in ~`12.3s` offline in Phase 4 verification).
  - `test_engine.py:57` covers 150 movement-only ticks (no LLM/DB); `test_phase3_integration.py:102` covers 80 cognitive ticks (`:memory:` DB, no replay log, no `/metrics`, no cross-run determinism assertion).
  - `MockProvider` (`backend/llm/providers/mock.py:1-95`) derives outputs purely via deterministic `hashlib` hashing over `(seed, schema, prompt)` with zero mutable RNG state, and `SimulationEngine` iterates `sorted(self.agents)` (`backend/sim/engine.py:582, 639, 699, 857`). Therefore two independent runs with `seed=42` are bit-for-bit deterministic!
- **100-Tick Deterministic Integration & Invariant Suite Design (`REQ-16`, `NFR-03`, `NFR-05`):**
  - Add `backend/tests/test_phase5_integration.py` testing:
    1. **100-tick full-stack cognitive simulation** (`MockProvider(seed=42)`, `EmbeddingService.from_mode("mock")`, SQLite DB in `tmp_path`, `ReplayLogger` in `tmp_path / "logs"`, mid-run salient event injection + threshold/natural cognitive execution):
       - **Spatial invariants on all 100 ticks:** every agent `(x, y)` is walkable (`world.is_walkable`), every active `agent.path` step is 4-way adjacent and walkable, and all 8 agent positions are pairwise distinct at the end of every tick (`len(set(positions)) == 8`).
       - **Plan & state invariants:** every agent maintains a valid structured plan (`5..8` blocks or valid replanned remainder) whose locations exist in `world.locations`; injected salient event triggers clean replanning (`needs_replan` cleared once decided); zero unhandled exceptions.
       - **Metrics & Replay invariants:** `GET /metrics` matches `llm_calls` rows (`total_calls`, `tokens_in`, `tokens_out`, `by_purpose`, `by_model`, `history`), `total_calls` stays well within daily call budget, and `GET /replay/1` returns all 100 monotonic `tick` frames plus emitted `dialogue`/`event`/`reflection` records from `day_1.jsonl`.
    2. **Offline seed determinism check (`NFR-03`):** run a fixed-seed (`seed=42`) multi-tick cognitive simulation twice in isolated `tmp_path` DBs/logs and assert identical final agent coordinates, plans, conversation counts, and `llm_calls` counts.
- **GitHub Actions CI (`.github/workflows/ci.yml`):**
  - Trigger on `push` (all branches / `master` / `main`) and `pull_request`.
  - Job 1 `backend` (`ubuntu-latest`, `actions/setup-python@v5` with `python-version: "3.12"`, `cache: "pip"`, `cache-dependency-path: "backend/pyproject.toml"`):
    - `python -m pip install --upgrade pip`
    - `python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -e "backend[dev]"`
    - `ruff check backend` & `ruff check --config backend/pyproject.toml scripts`
    - `mypy --config-file backend/pyproject.toml backend/app backend/sim backend/api backend/agents backend/memory backend/llm backend/tests` (run with `working-directory: backend` as `mypy .` plus `mypy --config-file backend/pyproject.toml scripts` from root so `pythonpath = ["."]` imports resolve identically to local runs!)
    - `pytest -v` (`working-directory: backend`)
  - Job 2 `frontend` (`ubuntu-latest`, `actions/setup-node@v4` with `node-version: "22"`, `cache: "npm"`, `cache-dependency-path: "frontend/package-lock.json"`):
    - `npm --prefix frontend ci`
    - `npm --prefix frontend run typecheck`
    - `npm --prefix frontend run build`

**Sources:**
- `backend/pyproject.toml:1-61`
- `backend/llm/providers/mock.py:1-95`
- `backend/tests/test_engine.py:56-94`
- `backend/tests/test_phase3_integration.py:101-163`
- `.gsd/phases/2/1-PLAN.md:75-77`
- `.gsd/phases/4/VERIFICATION.md:17-21, 87-102`

---

## Patterns to Follow
- **Runtime Type Guards on Every Frontend Payload:** Follow `frontend/src/types/sim.ts:250-528` and `frontend/src/net/apiClient.ts:87-104` (`requestJson(path, init, guard)`) by adding strict `isMetricsSnapshot`, `isReplayDaysResponse`, and `isReplayLogResponse` guards before passing JSON to Chart.js, Cytoscape.js, or `VillageScene`.
- **DOM Construction Without `innerHTML`:** Follow `ActivityFeed` (`frontend/src/ui/activityFeed.ts:9-10`) and `AgentInspector` (`frontend/src/ui/agentInspector.ts:35-47`) using `document.createElement` + `textContent` across all new modal headers, tables, badges, and replay controls.
- **Temporary Isolated Paths in All Tests:** Pass `database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"` and `replay_log_dir=str(tmp_path / "logs")` in every API/integration test (and `REPLAY_LOG_DIR` in `scripts/verify_phase1_ws.py:200-205`) so workspace `logs/` stays clean.
- **Working-Directory Discipline for `mypy` and `pytest`:** Backend imports use top-level package names (`from app.config import ...`, `from sim.engine import ...` with `pythonpath = ["."]` in `backend/pyproject.toml:39`), so CI must run `mypy .` and `pytest -v` with `working-directory: backend`.

## Anti-Patterns to Avoid
- **Logging Control Re-Broadcasts to Replay JSONL:** Do not hook `ReplayLogger` into `broadcast_current_tick()` (`backend/sim/engine.py:362-366`); otherwise clicking Pause/Play/16x writes duplicate `tick` entries with the same tick number into `day_{day}.jsonl`.
- **Initializing Cytoscape or Chart.js Inside `display: none` Without Resize:** Rendering into a `.hidden` element yields a `0x0` canvas; always initialize on first open or trigger `resize()` / `fit()` inside `requestAnimationFrame` after un-hiding.
- **Mutating Live Server Playback During Client Replay:** Never send `/sim/pause` or `/sim/speed` when scrubbing a replay; keep replay playback speed and pause state purely client-side while caching live WS ticks in the background.
- **Installing Unscoped PyTorch in GitHub Actions:** Never omit `--extra-index-url https://download.pytorch.org/whl/cpu` on Linux CI runners, or `sentence-transformers` will pull ~2.5 GB of CUDA wheels.

## Dependencies Identified
| Package | Version | Purpose |
|---------|---------|---------|
| `chart.js` | `^4.4.8` (latest `4.6.2`) | Frontend Cost, Token & Latency charts (`REQ-14`, bundled with own TS types) |
| `cytoscape` | `^3.30.4` (latest `3.35.0`) | Interactive villager Relationship Graph (`REQ-10`) |
| `@types/cytoscape` | `^3.21.9` (latest `3.31.0`) | Strict TypeScript definitions (`devDependencies`) for `cytoscape` |

## Risks
- **Existing WS Tests Failing on New `metrics` Frame Type:** `scripts/verify_phase1_ws.py:130`, `backend/tests/test_api_ws.py:110`, and `backend/tests/test_phase4_integration.py:110, 268, 282, 303` hardcode `{"tick", "dialogue", "event", "reflection"}`. **Mitigation:** Update those allowlists in the same plan that introduces WS `metrics` broadcasts, and only emit WS `metrics` when new `llm_calls` occur on a tick so quiet ticks stay lean.
- **Day-Boundary Split Between Pre-Advance Events and Post-Advance Ticks:** In `step_once()`, cognitive events at `tick = 1079` (`Day 1 23:59`) are emitted right after `clock.advance()` moves `clock.tick` to `1080` (`Day 2 00:00`). **Mitigation:** Always derive the JSONL filename `day_{day}.jsonl` from each payload's own `tick` field via `((clock.start_minute_of_day + payload["tick"]) // 1440) + 1` rather than `self.clock.day`.
- **Vite Bundle Size Warning With Phaser + Cytoscape + Chart.js:** Phaser already produces a ~1.52 MB bundle (`.gsd/phases/4/VERIFICATION.md:21`). **Mitigation:** Tree-shake Chart.js v4 imports (or register only `LineController`, `BarController`, `DoughnutController`, scales, and elements needed) or configure `build.rollupOptions.output.manualChunks` in `frontend/vite.config.ts` if desired.

## Recommendations for Planning
1. **Wave 1 (Parallel Backend Foundations + Frontend Package/Type Scaffolding):**
   - *Plan 5.1 (Backend Metrics & Replay Logger):* Extend `Settings` (`replay_log_dir`), implement non-blocking `ReplayLogger` (`backend/sim/replay.py`), and add `LLMGateway.get_metrics_snapshot()` (totals, latency stats, `by_purpose`, `by_model`, rolling tick `history`, budget status) with unit tests.
   - *Plan 5.2 (Frontend Packages, Types, API/WS Clients & Vite Proxies):* Install `chart.js`, `cytoscape`, and `@types/cytoscape` (updating `frontend/package-lock.json`), add `/metrics` and `/replay` proxies in `frontend/vite.config.ts`, extend `frontend/src/types/sim.ts` with `MetricsMessage` / `MetricsSnapshot` / `ReplayLogResponse` + runtime guards, update `apiClient.ts` (`fetchMetrics`, `fetchReplayDays`, `fetchReplayDay`) and `wsClient.ts` (`onMetrics`).
2. **Wave 2 (Backend Engine/REST Wiring + Frontend UI Components):**
   - *Plan 5.3 (Backend Engine Integration & `/metrics` + `/replay` Endpoints):* Wire `ReplayLogger` and WS `metrics` broadcasts into `SimulationEngine` and `app/main.py`, expose `GET /metrics`, `GET /replay`, and `GET /replay/{day}` in `backend/api/rest.py`, update WS frame-type allowlists in existing tests and `scripts/verify_phase1_ws.py`, and add API/WS tests.
   - *Plan 5.4 (Cytoscape.js Relationship Graph & Chart.js Cost Dashboard):* Build `frontend/src/ui/relationshipGraph.ts` (affinity-colored/weighted edges, mood badges, edge note tooltips/details, click-node-to-inspect) and `frontend/src/ui/metricsDashboard.ts` (KPI cards + Chart.js token/cost trend, purpose breakdown, latency charts fed by `GET /metrics` + live WS `metrics`).
   - *Plan 5.5 (Frontend Day Replay Controller & Scrubber UI):* Add `resetTransientVisuals()` and `immediate` snap mode to `VillageScene.ts`, `clear()` to `ActivityFeed`, build `frontend/src/ui/replayControls.ts` (Day selector, Play/Pause, 1x/4x/16x, range timeline scrubber, Exit to Live), and wire HUD tool buttons + live/replay gating in `main.ts`, `index.html`, and `style.css`.
3. **Wave 3 (100-Tick Deterministic Integration Suite & GitHub Actions CI):**
   - *Plan 5.6 (100-Tick Suite, Invariant Verification & `.github/workflows/ci.yml`):* Implement `backend/tests/test_phase5_integration.py` (100-tick cognitive + spatial + plan + metrics + replay invariants and cross-run `seed=42` determinism), author `.github/workflows/ci.yml` (`ruff`, `mypy`, `pytest` with CPU PyTorch index + `npm ci`, `typecheck`, `build`), and run full local CI gate verification.
