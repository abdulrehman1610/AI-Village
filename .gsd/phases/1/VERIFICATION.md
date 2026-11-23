---
phase: 1
verified: 2026-11-24T00:38:30+05:00
status: passed
score: 6/6 must-haves verified
is_re_verification: false
---

# Phase 1 Verification

## Summary

- **Phase Goal:** Scaffold the monorepo (`backend/` Python 3.12+ FastAPI + `frontend/` Phaser 3 TypeScript Vite), build the Tiled JSON village map with collision layer and named locations, implement custom `heapq` A* pathfinding and async simulation tick clock/engine, and synchronize 3+ moving agents in real time over WebSocket `/ws` to Phaser 3.
- **Result:** **6/6** consolidated must-haves verified with direct empirical evidence (`pytest`: 37 passed, `ruff`: 0 errors in `backend/` and `scripts/`, `mypy`: 0 errors across 18 backend + 2 script source files, `tsc --noEmit`: 0 errors, `vite build`: succeeded, `scripts/verify_phase1_ws.py`: `e2e_ws_ok ticks=[6, 7, 8, 9, 10, 11] moved_agents=4`).
- **Requirements Covered:** REQ-01, REQ-02, REQ-03 (initial 4 seeded agents), NFR-01, NFR-04, NFR-05.

---

## Must-Haves

### Truths

| Truth | Status | Evidence |
|-------|--------|----------|
| 1. Backend Python 3.12+ package installs cleanly and `Settings` loads offline with zero committed secrets | ✓ VERIFIED | `backend/pyproject.toml` targets `requires-python = ">=3.12"` with FastAPI, Uvicorn, Pydantic v2, pydantic-settings, websockets, pytest, ruff, mypy; `test_config.py` passed (4/4); `git ls-files .env*` returned only `.env.example`; `pytest` (37/37), `ruff` (in `backend/`), and `mypy` (in `backend/`) all exited 0. |
| 2. Frontend Phaser 3 + TypeScript + Vite workspace compiles cleanly, proxies `/ws` & REST routes, and shares strict payload contracts | ✓ VERIFIED | `npm --prefix frontend run typecheck` (`tsc --noEmit`) exited 0; `npm --prefix frontend run build` (`vite build`) exited 0 in `32.20s`; `frontend/vite.config.ts` proxies `/ws`, `/health`, `/world`, `/agents` to `127.0.0.1:8000`; `frontend/src/types/sim.ts` matches `TickPayload`, `AgentSnapshot`, `WorldResponse`, and `HealthResponse`. |
| 3. Valid Tiled v1.10 village map & PNG assets exist and `WorldMap` distinguishes walls from walkable tiles with all 10 named locations mutually reachable | ✓ VERIFIED | Asset check confirmed `tileset.png` `(256, 128)` (2804 bytes), `sprites.png` `(128, 128)` (970 bytes), and `map.json` (`1.10`, `orthogonal`, `40x30`, `32x32`, layers `ground`, `structures`, `collision`, `locations`, tileset `village_tiles`); `test_world.py` (7/7) proved all 10 anchors (`Cafe`, `Park`, `Market`, `Town Square`, `Bakery`, `Library`, `Home_Maya`, `Home_Liam`, `Home_Elena`, `Home_Noah`) are walkable and reachable via BFS from `Town Square`. |
| 4. Custom `heapq` A* pathfinder (Manhattan heuristic, 4-way) and `SimClock` (1 tick = 1 min, day rollover, 1x/4x/16x, pause/start) operate deterministically | ✓ VERIFIED | `backend/sim/astar.py` uses stdlib `heapq` + `itertools.count` + `manhattan` + `CARDINAL_DIRS`; `test_astar.py` (9/9) verified open optimal length, `start==goal`, U-barrier detours, enclosed goals, dynamic `blocked_tiles`, determinism, and `max_iterations`; `test_clock.py` (11/11) verified `Day 1 06:00` start, 1440-tick rollover, 1x/4x/16x intervals, pause/start, and validation guards. |
| 5. `SimulationEngine` moves 4 seeded agents via A* under zero-overlap / zero-wall-clipping invariants and streams ticks over `/ws` alongside `/health`, `/world`, `/agents` | ✓ VERIFIED | `test_engine.py` (4/4) verified A* paths across real named locations, 150 simulated ticks with 0 tile overlaps and 0 wall collisions (`>=2` locations visited per agent), callback isolation, and contested destination routing; `test_api_ws.py` (2/2) verified `/health`, `/world`, `/agents`, initial `/ws` snapshot, and advancing live `/ws` ticks; `scripts/verify_phase1_ws.py` exited 0 against live Uvicorn (`e2e_ws_ok ticks=[6, 7, 8, 9, 10, 11] moved_agents=4`). |
| 6. Phaser 3 `VillageScene` renders the Tiled map (`ground`, `structures`, toggleable `collision`, `locations`) and passive `VillageWsClient` drives 4 moving agent sprites from server ticks | ✓ VERIFIED | `frontend/src/scenes/VillageScene.ts` binds `"village_tiles"`, creates `ground`/`structures`/`collision` (`keydown-C` toggle) and `locations` text labels, and tweens sprites passively on `applyTick`; `frontend/src/net/wsClient.ts` validates payloads with `isTickMessage` and reconnects with `500ms..5000ms` backoff; `frontend/dist/assets` contains `map.json`, `tileset.png`, `sprites.png`, and bundled JS/CSS (`vite build` exit 0). Visual browser rendering flagged for human spot-check below. |

---

### Artifacts

| Path | Exists | Substantive | Wired | Notes |
|------|--------|-------------|-------|-------|
| `.gitignore` | ✓ | ✓ | ✓ | Ignores `.env`, `.venv/`, `node_modules/`, `frontend/dist/`, `*.db`, `*.sqlite*`, `logs/*.jsonl`; preserves `!.env.example` |
| `.env.example` | ✓ | ✓ | ✓ | Safe non-secret defaults (`SIM_TICK_SECONDS`, `SIM_SEED`, `LLM_PROVIDER=mock`, placeholder `GEMINI_API_KEY`) |
| `backend/pyproject.toml` | ✓ | ✓ | ✓ | Defines `ai-village-backend`, FastAPI/Pydantic/Uvicorn deps, `dev` tools, pytest/ruff/mypy config |
| `backend/app/config.py` | ✓ | ✓ | ✓ | `Settings(BaseSettings)`, `resolved_map_path()` -> `frontend/public/assets/map.json`, `parsed_cors_origins()` |
| `backend/app/main.py` | ✓ | ✓ | ✓ | `create_app()`, lifespan wiring `WorldMap`, `SimClock`, `SimulationEngine`, `ConnectionManager`, CORS, routers |
| `backend/sim/world.py` | ✓ | ✓ | ✓ | `NamedLocation`, `WorldMap.from_tiled_json`, `is_walkable`, `find_free_adjacent`, `reachable_from` |
| `backend/sim/astar.py` | ✓ | ✓ | ✓ | Custom `heapq` A* `find_path`, `manhattan`, `CARDINAL_DIRS` |
| `backend/sim/clock.py` | ✓ | ✓ | ✓ | `SimClock` (`VALID_SPEEDS = (1, 4, 16)`, `TICKS_PER_DAY = 1440`, `sim_time_str`, `tick_interval_seconds`) |
| `backend/sim/engine.py` | ✓ | ✓ | ✓ | `AgentSnapshot`, `TickPayload`, `AgentEntity`, 4 seeded agents, `SimulationEngine.step_once`, `_run_loop` |
| `backend/api/rest.py` | ✓ | ✓ | ✓ | `GET /health`, `GET /world`, `GET /agents` backed by `app.state` |
| `backend/api/ws.py` | ✓ | ✓ | ✓ | `ConnectionManager` and `@router.websocket("/ws")` sending initial snapshot and broadcasting ticks |
| `backend/tests/test_*.py` | ✓ | ✓ | ✓ | 6 test modules (`test_config.py`, `test_world.py`, `test_astar.py`, `test_clock.py`, `test_engine.py`, `test_api_ws.py`), 37 tests total |
| `scripts/generate_village_map.py` | ✓ | ✓ | ✓ | Deterministic stdlib PNG/Tiled JSON map generator with built-in BFS reachability assertion |
| `scripts/verify_phase1_ws.py` | ✓ | ✓ | ✓ | Live Uvicorn + `frontend/dist` + REST + 6-tick `/ws` e2e verification script |
| `frontend/public/assets/map.json` | ✓ | ✓ | ✓ | 40x30 orthogonal Tiled v1.10 map (`ground`, `structures`, `collision`, `locations`) |
| `frontend/public/assets/tileset.png` | ✓ | ✓ | ✓ | `256x128` RGBA PNG (`8x4` grid of 32x32 tiles) |
| `frontend/public/assets/sprites.png` | ✓ | ✓ | ✓ | `128x128` RGBA PNG (`4x4` grid of 32x32 frames) |
| `frontend/package.json` | ✓ | ✓ | ✓ | Declares `phaser`, `typescript`, `vite` and `typecheck`/`build`/`dev`/`preview` scripts |
| `frontend/tsconfig.json` | ✓ | ✓ | ✓ | Strict TypeScript (`strict`, `noUnusedLocals`, `noUnusedParameters`, `noEmit`) |
| `frontend/vite.config.ts` | ✓ | ✓ | ✓ | Port `5173`, proxies `/ws`, `/health`, `/world`, `/agents` to `127.0.0.1:8000` |
| `frontend/index.html` & `frontend/src/style.css` | ✓ | ✓ | ✓ | `#hud`, `#ws-status`, `#sim-time`, `#sim-tick`, `#agents-bar`, `#game-container`, `#controls-hint` |
| `frontend/src/types/sim.ts` | ✓ | ✓ | ✓ | `AgentSnapshot`, `TickMessage`, `NamedLocationInfo`, `WorldInfo`, `HealthInfo`, `isTickMessage` |
| `frontend/src/net/wsClient.ts` | ✓ | ✓ | ✓ | `VillageWsClient`, `resolveWsUrl`, JSON guard validation, exponential reconnect backoff |
| `frontend/src/scenes/VillageScene.ts` | ✓ | ✓ | ✓ | Phaser 3 `VillageScene` tilemap, `C` collision toggle, location labels, camera controls, agent tweening |
| `frontend/src/main.ts` | ✓ | ✓ | ✓ | Mounts `Phaser.Game` + `VillageScene`, wires `VillageWsClient` ticks and status to HUD and scene |

---

### Key Links

| From | To | Via | Status |
|------|----|-----|--------|
| `backend/app/config.py` | `frontend/public/assets/map.json` | `DEFAULT_MAP_PATH` (`REPO_ROOT / "frontend" / "public" / "assets" / "map.json"`) | ✓ WIRED |
| `scripts/generate_village_map.py` | `backend/sim/world.py` | Generates `map.json` parsed by `WorldMap.from_tiled_json` | ✓ WIRED |
| `backend/sim/engine.py` | `backend/sim/world.py`, `astar.py`, `clock.py` | `SimulationEngine` computes routes via `find_path` on `WorldMap` and ticks `SimClock` | ✓ WIRED |
| `backend/app/main.py` | `backend/api/ws.py` | `lifespan` registers `_broadcast` tick callback calling `ws_manager.broadcast_json` | ✓ WIRED |
| `frontend/vite.config.ts` | `backend/app/main.py` | Dev proxy routes `/ws`, `/health`, `/world`, `/agents` to `127.0.0.1:8000` | ✓ WIRED |
| `frontend/src/net/wsClient.ts` | `backend/api/ws.py` | `VillageWsClient` connects to `/ws`, validates `TickPayload` via `isTickMessage` | ✓ WIRED |
| `frontend/src/scenes/VillageScene.ts` | `frontend/public/assets/map.json` | Loads `/assets/map.json`, binds `"village_tiles"`, layers `"ground"`, `"structures"`, `"collision"`, `"locations"` | ✓ WIRED |
| `frontend/src/main.ts` | `frontend/src/scenes/VillageScene.ts` & DOM HUD | `onTick` invokes `villageScene.applyTick(tickMsg)` and updates `#sim-time`, `#sim-tick`, `#agents-bar` | ✓ WIRED |

---

## Command Verification Evidence

1. **Backend Test Suite (`pytest`)**:
   - Command: `& "backend\.venv\Scripts\pytest.exe" -c "backend\pyproject.toml" --rootdir="backend" "backend\tests" -v`
   - Output: `37 passed, 1 warning in 4.09s` (exit code 0) — all tests across `test_api_ws.py` (2), `test_astar.py` (9), `test_clock.py` (11), `test_config.py` (4), `test_engine.py` (4), and `test_world.py` (7) passed.
2. **Backend Linter (`ruff`)**:
   - Command (inside `backend/`): `& "backend\.venv\Scripts\python.exe" -c "import subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'ruff', 'check', '.'], cwd='backend'))"`
   - Output: `All checks passed!` (exit code 0).
   - Command (on `scripts/`): `& "backend\.venv\Scripts\ruff.exe" check --config "backend\pyproject.toml" "scripts"`
   - Output: `All checks passed!` (exit code 0).
3. **Backend Static Type Check (`mypy --strict`)**:
   - Command (inside `backend/`): `& "backend\.venv\Scripts\python.exe" -c "import subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'mypy', 'app', 'sim', 'api', 'tests'], cwd='backend'))"`
   - Output: `Success: no issues found in 18 source files` (exit code 0).
   - Command (on `scripts/`): `& "backend\.venv\Scripts\mypy.exe" --config-file "backend\pyproject.toml" "scripts"`
   - Output: `Success: no issues found in 2 source files` (exit code 0).
4. **Frontend TypeScript Check (`tsc --noEmit`)**:
   - Command: `npm --prefix frontend run typecheck`
   - Output: `> tsc --noEmit` (exit code 0, zero errors).
5. **Frontend Production Build (`vite build`)**:
   - Command: `npm --prefix frontend run build`
   - Output: `✓ 10 modules transformed.`, emitted `dist/index.html` (`1.02 kB`), `dist/assets/index-Bjh7sn2g.css` (`1.98 kB`), `dist/assets/index-BO-anwdC.js` (`1,487.58 kB`), `✓ built in 32.20s` (exit code 0).
6. **End-to-End Live Server + `/ws` Sync**:
   - Command: `& "backend\.venv\Scripts\python.exe" "scripts\verify_phase1_ws.py"`
   - Output: `e2e_ws_ok ticks=[6, 7, 8, 9, 10, 11] moved_agents=4` (exit code 0).
7. **Assets & Anti-Pattern Scan**:
   - PNG/JSON asset inspection: `tileset_png (256, 128) 2804`, `sprites_png (128, 128) 970`, `map_meta 1.10 orthogonal 40 30 32 32 ['ground:tilelayer', 'structures:tilelayer', 'collision:tilelayer', 'locations:objectgroup'] village_tiles tileset.png`, `dist_assets ['index-BO-anwdC.js', 'index-Bjh7sn2g.css', 'map.json', 'sprites.png', 'tileset.png']`.
   - Source scan (`TODO|FIXME|XXX|HACK|PLACEHOLDER|coming soon|lorem ipsum|NotImplementedError|console.log` across 24 `.py` and `.ts` files): `scanned_files 24 hits []`.
   - Tracked env files (`git ls-files .env*`): `.env.example` only.

---

## Anti-Patterns & Non-Blocking Findings

- ℹ️ **Info — Ruff `known-first-party` when invoked from repo root:** Running `ruff check --config backend\pyproject.toml backend` from repo root flags 8 `I001` import-sorting notices because `app`, `sim`, and `api` are only recognized as first-party when `cwd` is `backend/`. Running `ruff check .` inside `backend/` passes cleanly. Adding `[tool.ruff.lint.isort] known-first-party = ["app", "sim", "api"]` to `backend/pyproject.toml` would allow root-level `ruff` invocations in future CI scripts.
- ⚠️ **Warning — Minor HUD clock prefix duplication (`frontend/src/main.ts`):** `SimClock.sim_time_str` already formats `"Day {day} {hour:02d}:{minute:02d}"` (`backend/sim/clock.py:68`), and `updateHud` in `frontend/src/main.ts:29` prepends `Day ${tickMsg.day} · ${tickMsg.sim_time}`, rendering `"Day 1 · Day 1 06:00 · 1x"` in `#sim-time` (and `frontend/index.html:17` initializes `#sim-time` to `"Day 1 · 07:00"` while `SimClock` starts at `06:00`). Non-blocking cosmetic detail that can be cleaned up when Phase 4 builds the full HUD/time controls.

---

## Human Verification Needed

### 1. Visual Browser Review of Phaser 3 Village & Live Sprite Movement
**Test:** Start the backend (`backend/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000` in `backend/`) and frontend (`npm --prefix frontend run dev`), then open `http://localhost:5173` in a desktop browser.
**Expected:**
- Status badge switches from `Connecting...` to `Live`.
- Tilemap renders crisp 32x32 pixel-art grass, cobblestone roads, buildings, park pond, and all 10 named location badges (`Cafe`, `Park`, `Market`, `Town Square`, `Bakery`, `Library`, `Home_Maya`, `Home_Liam`, `Home_Elena`, `Home_Noah`).
- 4 distinct colored villager sprites smoothly tween along roads without walking through walls or overlapping, while HUD agent chips update coordinates in sync.
- Pressing `C` toggles the translucent red collision debug overlay; dragging pans and mouse wheel zooms cleanly.
**Why human:** No interactive browser rendering tool (`browser_subagent`) is available in this headless verification context to capture a live canvas screenshot.

---

## Verdict

**PASS** — All 6 Phase 1 must-haves are verified with empirical test, lint, static-type, build, and live WebSocket execution proof. Zero blocker gaps found; ready to proceed to Phase 2 planning (`/plan 2`).
