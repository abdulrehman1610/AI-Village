---
phase: 6
researched_at: 2026-11-26
discovery_level: 2
---

# Phase 6 Research: Packaging, Documentation, Lab Report & Demo Readiness

## Objective
Determine the exact configuration, routing, tooling, and repository artifact requirements needed to package AI Village with Docker (`Dockerfile`s + `docker-compose.yml` + Nginx reverse proxy), generate deterministic visual assets (`docs/architecture.png` and `docs/demo.gif`), run an empirical 1,440-tick (24-hour) simulated village day, and author all PRD Section 11/15/16 deliverables (`docs/PRD.md`, `docs/report.md`, `AGENTS.md`, `README.md`) without breaking strict CI gates (`ruff`, `mypy`, `pytest`, `tsc`, `vite build`).

## Discovery Level
**Level 2** — Standard research across existing codebase configuration, API/WebSocket proxy contracts, host CLI/runtime capabilities, and PRD compliance rules.

---

## Key Decisions

### Decision 1: Container Build Context & `Settings` Path Resolution
**Question:** How should `backend/Dockerfile` and `docker-compose.yml` handle `Settings` path resolution (`map_path`, `database_url`, `replay_log_dir`, `.env`) when `REPO_ROOT` (`Path(__file__).resolve().parents[2]`) shifts inside a container?
**Options Considered:**
1. Rely on default `REPO_ROOT`-relative paths inside `/app`: Breaks in Docker because `/app/app/config.py` makes `REPO_ROOT` resolve to `/`, looking for `/frontend/public/assets/map.json` and `/backend/ai_village.db`.
2. Require host bind-mounts only for `map.json`: Works in `docker compose`, but makes `backend` image non-self-contained if run standalone.
3. Build `backend` from repo root context (`.` with `dockerfile: backend/Dockerfile`), bake `frontend/public/assets/map.json` into `/app/assets/map.json`, set explicit container `ENV` defaults (`MAP_PATH=/app/assets/map.json`, `DATABASE_URL=sqlite+aiosqlite:////app/data/ai_village.db`, `REPLAY_LOG_DIR=/app/logs`), and mount persistent volumes for `/app/data` and `/app/logs` in `docker-compose.yml`.

**Decision:** **Option 3.** Baking `map.json` into `/app/assets/map.json` while setting explicit `ENV` defaults in `backend/Dockerfile` makes the backend container self-contained, avoids Windows bind-mount path issues, and persists SQLite WAL files (`/app/data`) and JSONL replay logs (`/app/logs`) cleanly across restarts.
**Confidence:** High

### Decision 2: Frontend Production Serving & API/WebSocket Routing
**Question:** How should the containerized frontend serve static Phaser/Vite assets and route REST + `/ws` traffic to `backend:8000`?
**Options Considered:**
1. Bake `VITE_API_BASE_URL=http://localhost:8000` at build time: Requires cross-origin CORS and dual-port browser traffic; breaks if accessed via another hostname/IP.
2. Multi-stage `frontend/Dockerfile` (`node:22-alpine` build → `nginx:1.27-alpine` runtime) with empty `VITE_API_BASE_URL`/`VITE_WS_URL` (same-origin relative URLs) and `frontend/nginx.conf` proxying all 8 backend route prefixes + `/ws` WebSocket upgrade to `http://backend:8000`, exposed on host port `5173:80`.

**Decision:** **Option 2.** Both `resolveApiBaseUrl()` (`frontend/src/net/apiClient.ts:24-30`) and `resolveWsUrl()` (`frontend/src/net/wsClient.ts:30-37`) already default to same-origin (`""` and `ws://${window.location.host}/ws`), mirroring `frontend/vite.config.ts:6-44`. Exposing Nginx on `5173:80` keeps `http://localhost:5173` identical between `docker compose up --build` and local Vite dev.
**Confidence:** High

### Decision 3: Generating `docs/architecture.png` and `docs/demo.gif` Without Adding Python Dependencies
**Question:** What tooling on this Windows host should generate `docs/architecture.png` and `docs/demo.gif` while honoring PRD Rule 10 ("Do not add dependencies without a one-line reason")?
**Options Considered:**
1. Install `Pillow` / `matplotlib` / `playwright` into `backend/.venv`: Adds unrequested dependencies.
2. Combine existing host capabilities: Microsoft Edge Headless (`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`) + `ffmpeg` 8.1.2 (`palettegen`/`paletteuse` in PATH) + pure-Python `struct`/`zlib` PNG rendering (`scripts/generate_village_map.py:139-163`).

**Decision:** **Option 2.** Use deterministic HTML/SVG rendered via headless Edge (or pure-Python PNG fallback) for a high-DPI `docs/architecture.png`, and generate sequential PNG frames from a real simulation run (or live browser capture + pure-Python sprite/tilemap frame renderer reading `day_1.jsonl`, `map.json`, `tileset.png`, and `sprites.png`) encoded into an optimized palette `docs/demo.gif` via `ffmpeg`.
**Confidence:** High

### Decision 4: Empirical Verification When Docker CLI Is Absent on Host
**Question:** Since `docker` CLI is not installed on this Windows machine, how do we verify Docker artifacts and the full simulated village day?
**Options Considered:**
1. Skip Docker files or leave them untested: Violates REQ-16 and empirical validation rules.
2. Author complete Docker artifacts, verify them locally via an automated static/contract pytest suite (checking Dockerfile stages, `.dockerignore`, Compose service/env/volume wiring, and Nginx proxy coverage against `app.routes`), add `docker compose config` validation to `.github/workflows/ci.yml` (`ubuntu-latest` includes Docker Compose v2), and run full-stack e2e + 1,440-tick day verification locally via `backend/.venv` + Vite.

**Decision:** **Option 2.** Provides maximum local empirical rigor, CI validation of `docker-compose.yml`, and transparent documentation of the host boundary.
**Confidence:** High

---

## Findings

### 1. `Settings` Resolution (`backend/app/config.py`) & Container Volume/Env Wiring
- **Exact field & env var names (`backend/app/config.py:22-45`, `.env.example:1-23`):**
  - Map path field is **`map_path: str = ""`** (`MAP_PATH`), **not** `map_json_path` (`backend/app/config.py:27`, `resolved_map_path()` at `backend/app/config.py:46-49`).
  - Database URL field is `database_url: str = ""` (`DATABASE_URL`, `resolved_database_url()` at `backend/app/config.py:30,51-54`).
  - Replay directory field is `replay_log_dir: str = ""` (`REPLAY_LOG_DIR`, `resolved_replay_log_dir()` at `backend/app/config.py:31,56-59`).
  - CORS origins field is `cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"` (`CORS_ORIGINS`, `parsed_cors_origins()` at `backend/app/config.py:28,75-77`), wired into `CORSMiddleware` at `backend/app/main.py:133-138`.
  - LLM & embedding providers: `llm_provider: str = "mock"` (`LLM_PROVIDER`, supports `"mock"` or `"gemini"` in `_build_llm_provider` at `backend/app/main.py:29-39`, always paired with `fallback_provider=MockProvider(seed=...)` at `backend/app/main.py:68`) and `embedding_provider: str = "auto"` (`EMBEDDING_PROVIDER`, resolves `"auto"` → `"mock"` when `llm_provider == "mock"` else `"local"` `all-MiniLM-L6-v2` at `backend/app/config.py:61-73`).
- **`REPO_ROOT` behavior in local dev vs Docker (`backend/app/config.py:7-10,16-20`):**
  - `REPO_ROOT = Path(__file__).resolve().parents[2]`.
  - In local dev (`<repo>/backend/app/config.py`), `REPO_ROOT` is `<repo>`, so defaults resolve to `<repo>/frontend/public/assets/map.json`, `<repo>/backend/ai_village.db`, `<repo>/logs`, and `<repo>/.env`.
  - Inside a container where `backend/` is copied into `/app` (`/app/app/config.py`), `.parents[2]` resolves to `/`. Without env overrides, `WorldMap.from_tiled_json()` (`backend/app/main.py:78`) would fail looking for `/frontend/public/assets/map.json`.
- **SQLite & Replay directory auto-creation:**
  - `Database.init_models()` (`backend/app/db.py:69-72`) automatically runs `Path(db_path).parent.mkdir(parents=True, exist_ok=True)` and sets `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;` (`backend/app/db.py:54-56`). Because SQLite WAL mode creates `-wal` and `-shm` sibling files alongside `ai_village.db`, Docker must mount a **directory volume** (e.g., `village_data:/app/data` with `DATABASE_URL=sqlite+aiosqlite:////app/data/ai_village.db`), never a single-file bind mount.
  - `ReplayLogger._append_grouped_sync()` (`backend/sim/replay.py:193-194`) and `_ensure_initial_tick_sync()` (`backend/sim/replay.py:202-204`) automatically create `self.log_dir` via `mkdir(parents=True, exist_ok=True)`. Mounting `./logs:/app/logs` with `REPLAY_LOG_DIR=/app/logs` shares recorded `day_1.jsonl`, `day_2.jsonl`, etc. directly with the host (`logs/*.jsonl` is already gitignored at `.gitignore:28`).
- **PyTorch CPU wheel size in `backend/Dockerfile`:**
  - `backend/pyproject.toml:20` requires `sentence-transformers>=3.2.0`. Just like `.github/workflows/ci.yml:33`, `backend/Dockerfile` must install with `--extra-index-url https://download.pytorch.org/whl/cpu` on `python:3.12-slim` to avoid downloading multi-gigabyte CUDA packages.

**Sources:**
- `backend/app/config.py:7-78`
- `backend/app/main.py:29-87,133-138`
- `backend/app/db.py:49-73`
- `backend/sim/replay.py:193-205`
- `.github/workflows/ci.yml:30-34`

---

### 2. Complete REST & WebSocket Route Contract for `frontend/nginx.conf`
- **All 12 REST endpoints in `backend/api/rest.py`:**
  1. `GET /health` (`backend/api/rest.py:301`) — health & clock/world summary (ideal for Docker `healthcheck`).
  2. `GET /world` (`backend/api/rest.py:315`) — **critical:** called on startup by `fetchWorld()` (`frontend/src/net/apiClient.ts:113-115`) and proxied in `frontend/vite.config.ts:16-19`; must be included in `nginx.conf` alongside the routes listed in the prompt!
  3. `GET /agents` (`backend/api/rest.py:327`) — list all agent snapshots.
  4. `GET /agents/{agent_id}` (`backend/api/rest.py:334`) — Agent Inspector payload (`frontend/src/net/apiClient.ts:160`).
  5. `GET /relationships` (`backend/api/rest.py:492`) — Cytoscape graph nodes & canonical edges (`frontend/src/net/apiClient.ts:168`).
  6. `POST /sim/start` (`backend/api/rest.py:542`) — resume/start loop (`frontend/src/net/apiClient.ts:132`).
  7. `POST /sim/pause` (`backend/api/rest.py:550`) — pause loop (`frontend/src/net/apiClient.ts:137`).
  8. `POST /sim/speed` (`backend/api/rest.py:558`) — set 1x/4x/16x (`frontend/src/net/apiClient.ts:143`).
  9. `POST /events` (`backend/api/rest.py:572`) — god-mode event injection (`frontend/src/net/apiClient.ts:120`).
  10. `GET /metrics` (`backend/api/rest.py:598`) — LLM cost/token/latency telemetry (`frontend/src/net/apiClient.ts:173`).
  11. `GET /replay` (`backend/api/rest.py:633`) — list recorded replay days (`frontend/src/net/apiClient.ts:178`).
  12. `GET /replay/{day}` (`backend/api/rest.py:642`) — full day replay frames (`frontend/src/net/apiClient.ts:186`).
- **WebSocket endpoint (`backend/api/ws.py:38-52`):**
  - `@router.websocket("/ws")` accepts connection, sends initial `TickPayload` JSON immediately (`backend/api/ws.py:46`), and loops on `await websocket.receive_text()` (`backend/api/ws.py:48`) while broadcasting `tick`, `dialogue`, `event`, `reflection`, and `metrics` frames.
  - Because `VillageWsClient` (`frontend/src/net/wsClient.ts:40-150`) is passive (receives broadcasts without sending client ping frames) and simulation ticks pause when `POST /sim/pause` is active, Nginx's default `proxy_read_timeout 60s` would drop paused `/ws` connections unless extended (e.g. `proxy_read_timeout 3600s; proxy_send_timeout 3600s;`).
- **Frontend static assets (`frontend/src/scenes/VillageScene.ts:93-95`):**
  - Phaser loads `/assets/map.json`, `/assets/tileset.png`, and `/assets/sprites.png`, which Vite copies from `frontend/public/assets/` into `dist/assets/`.
  - Nginx `root /usr/share/nginx/html; location / { try_files $uri $uri/ /index.html; }` serves `index.html`, bundled JS/CSS, and `/assets/*` directly while forwarding `^/(health|world|agents|events|sim|relationships|metrics|replay)(/|$)` and `/ws` to `http://backend:8000`.

**Sources:**
- `backend/api/rest.py:301-655`
- `backend/api/ws.py:38-52`
- `frontend/vite.config.ts:4-45`
- `frontend/src/net/apiClient.ts:24-30,113-187`
- `frontend/src/net/wsClient.ts:30-37`
- `frontend/src/scenes/VillageScene.ts:93-95`

---

### 3. Host Tooling Availability (Docker, Python Venv, Headless Edge, FFmpeg) & CI Script Gate
- **Docker CLI on Windows host:**
  - `docker --version` → `CommandNotFoundException` (`docker` not in PATH; `C:\Program Files\Docker\Docker\resources\bin\docker.exe` does not exist; `podman` not installed).
  - Live `docker compose up --build` execution cannot run on this host machine, so local runtime verification must use `backend/.venv` + Vite while Docker files are verified via automated structural/contract tests + GitHub Actions CI (`docker compose config`).
- **Python packages in `backend/.venv`:**
  - Python 3.12 venv includes `fastapi 0.165.0`, `uvicorn 0.54.0`, `pydantic 2.14.4`, `sqlmodel 0.0.50`, `aiosqlite 0.22.1`, `numpy 2.5.5`, `sentence-transformers 6.3.0`, `torch 2.15.0+cpu`, `google-genai 3.6.1`, `pytest 9.2.0`, `ruff 0.17.6`, `mypy 2.4.1`.
  - `Pillow`, `matplotlib`, and `imageio` are **not** installed.
- **Available host visual rendering tools (zero new Python dependencies needed):**
  - **Pure-Python PNG writer:** `scripts/generate_village_map.py:139-163` (`write_png`) encodes RGBA bytearrays to standard PNG using stdlib `struct` + `zlib`.
  - **Microsoft Edge Headless:** `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` is present (`True`), supporting `--headless=new --screenshot=<path> --window-size=<W>,<H>` for crisp HTML/SVG → `docs/architecture.png` rendering or live UI screenshot capture.
  - **FFmpeg 8.1.2:** `ffmpeg.exe` is installed in PATH (`ffmpeg version 8.1.2-full_build` with `palettegen` and `paletteuse`), enabling high-quality animated `docs/demo.gif` generation from PNG frame sequences (`-vf "fps=10,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"`).
- **Critical CI Constraint on `scripts/` (`.github/workflows/ci.yml:39-47`):**
  - CI runs `ruff check --config backend/pyproject.toml scripts` and **`mypy --config-file backend/pyproject.toml scripts`** (`strict = true` in `backend/pyproject.toml:49-52`) across the entire `scripts/` folder. Any new simulation benchmark or visual generator script in `scripts/` **must** be fully type-annotated and pass both `ruff` and strict `mypy`.

**Sources:**
- `scripts/generate_village_map.py:139-163`
- `backend/pyproject.toml:10-53`
- `.github/workflows/ci.yml:35-52`

---

### 4. Repository Audit & PRD Deliverables Mapping (Sections 1, 5, 6, 11, 15, 16 + 1440-Tick Day)
- **Existing vs Missing Files:**
  - **Present at repo root:** `AI Village Product Requirements Document.md` (lines 1–287), `.env.example`, `.gitignore`, `PROJECT_RULES.md`, `GSD-STYLE.md`, `model_capabilities.yaml`, `VERSION`, `adapters/`, `backend/`, `frontend/`, `scripts/`.
  - **Missing (must be created in Phase 6):**
    - `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `.dockerignore`, `docker-compose.yml` (PRD Section 11:218, REQ-16).
    - `docs/PRD.md` (PRD Section 11:217 — copy from `AI Village Product Requirements Document.md` while preserving the root file so `.gsd/` links remain valid).
    - `docs/architecture.png` (PRD Section 11:217, Section 16:269).
    - `docs/demo.gif` (PRD Section 2:19, Section 3:34, Section 13:241, Section 16:269).
    - `docs/report.md` (PRD Section 11:217, Section 16:271 — academic AI Lab Report for AbdulRehman, 6th Semester BSCS, Superior University, structured around PRD Sections 1 [Overview], 5 [Simulation Design: 5.1 Time, 5.2 Agent Loop, 5.3 Memory & Retrieval Formula, 5.4 Hierarchical Planning, 5.5 Conversation, 5.6 Reflection, 5.7 God-Mode Events, 5.8 A* Movement], 6 [Architecture], and 15 [Mapping to AI Course Concepts], backed by empirical metrics from a full 1,440-tick simulated day).
    - `AGENTS.md` (PRD Section 11:220, REQ-16 — repository map, authoritative-server & LLM-gateway rules from PRD Section 17:275-287, offline mock testing rules, `ruff`/`mypy`/`pytest`/`tsc` commands, and links to `PROJECT_RULES.md` and `adapters/`).
    - `README.md` (PRD Section 11:219, Section 16:269,273 — `docs/demo.gif` hero banner, 30-second overview, `docs/architecture.png`, `<5 commands` quickstart for both Docker Compose [2 commands: `cp .env.example .env` + `docker compose up --build`] and local Python/Node dev, feature table F1–F14, API/WS summary, verification/CI suite, 2-minute demo walkthrough script/flow for PRD Section 16:270, and the resume bullet from PRD line 273).
- **1,440-Tick Simulated Day Mechanics (`backend/sim/clock.py` & `backend/sim/replay.py`):**
  - `TICKS_PER_DAY = 1440` (`backend/sim/clock.py:9`) and `start_minute_of_day = 360` (`Day 1 06:00`, `backend/sim/clock.py:17`).
  - Advancing 1,440 ticks (`step_once()` for `tick = 1..1440`) runs a full 24-hour cycle from `Day 1 06:00` through midnight rollover at `tick = 1080` (`Day 2 00:00`, partitioning logs across `day_1.jsonl` and `day_2.jsonl` via `replay_day_for_tick` in `backend/sim/replay.py:47-59`) to `Day 2 06:00`, including Day 2 morning wake-up replanning (`self.plan_state.day != clock.day` at `backend/agents/agent.py:180`).
  - Using `MockProvider(seed=42)` + `DeterministicEmbeddingProvider` in-process (same pattern as `backend/tests/test_100_ticks_invariants.py:38-70`), 1,440 ticks executes deterministically in ~30–45 seconds with zero API cost, producing authentic SQLite/gateway/replay metrics for `docs/report.md` and real replay frames for `docs/demo.gif`.

**Sources:**
- `AI Village Product Requirements Document.md:5-133,202-287`
- `backend/sim/clock.py:8-69`
- `backend/sim/replay.py:47-60`
- `backend/agents/agent.py:180-195`
- `backend/tests/test_100_ticks_invariants.py:38-90`

---

## Patterns to Follow
- **Nginx WebSocket Upgrade Map:** Define `map $http_upgrade $connection_upgrade { default upgrade; '' close; }` in `frontend/nginx.conf` with `proxy_http_version 1.1` and `proxy_read_timeout 3600s` on `location /ws`.
- **Self-Contained Container Defaults + Compose Overrides:** Copy `frontend/public/assets/map.json` into `/app/assets/map.json` inside `backend/Dockerfile` (`context: .`, `dockerfile: backend/Dockerfile`) and set `ENV MAP_PATH=/app/assets/map.json`, `ENV DATABASE_URL=sqlite+aiosqlite:////app/data/ai_village.db`, `ENV REPLAY_LOG_DIR=/app/logs`, `ENV LLM_PROVIDER=mock`.
- **Strict Type Annotations in `scripts/`:** Run `ruff check --config backend/pyproject.toml scripts` and `mypy --config-file backend/pyproject.toml scripts` after adding any helper script in `scripts/`.
- **Empirical Metrics Extraction:** Write a deterministic runner script (e.g., `scripts/run_day_simulation.py`) that executes 1,440 ticks (with 1–2 timed god-mode events for rumor/replan observation), verifies zero spatial/plan invariant violations, and outputs a JSON summary of real metrics (LLM calls by purpose, cache hits, tokens, memories by type, conversations, reflections, relationship affinities, replay frame counts) so `docs/report.md` cites 100% real numbers.

## Anti-Patterns to Avoid
- **Using `MAP_JSON_PATH` instead of `MAP_PATH`:** `Settings` defines `map_path` (`MAP_PATH`), so `MAP_JSON_PATH` would be silently ignored due to `extra="ignore"` (`backend/app/config.py:19,27`).
- **Omitting `/world` from `frontend/nginx.conf`:** `fetchWorld()` (`frontend/src/net/apiClient.ts:113`) calls `GET /world` at boot; omitting it returns `index.html` via SPA fallback and fails JSON type guard validation.
- **Single-file SQLite bind mount in Docker:** Mounting `./ai_village.db:/app/ai_village.db` breaks SQLite WAL mode (`-wal`/`-shm` creation) and fails when the host file doesn't exist yet (Docker creates a directory instead). Always mount a directory (`/app/data`).
- **Installing default PyPI `torch` in `backend/Dockerfile`:** Without `--extra-index-url https://download.pytorch.org/whl/cpu`, Linux Docker builds pull ~2.5 GB of NVIDIA CUDA libraries.

## Dependencies Identified
| Package / Tool | Version | Purpose |
|----------------|---------|---------|
| `python:3.12-slim` | Docker base | Backend container runtime matching `requires-python >= 3.12` |
| `node:22-alpine` + `nginx:1.27-alpine` | Docker multi-stage | Frontend TypeScript/Vite build + static/reverse-proxy server |
| `ffmpeg` (host CLI) | 8.1.2 (installed) | Palette-optimized `docs/demo.gif` encoding from PNG frames |
| `msedge.exe` (host CLI) / stdlib `zlib` | Installed / Python 3.12 | High-DPI `docs/architecture.png` & frame rendering without new pip deps |

## Risks
- **Host lacks Docker CLI (`docker` not installed):** Mitigate by adding automated pytest verification of `Dockerfile`s, `docker-compose.yml`, and `frontend/nginx.conf` route parity with FastAPI `app.routes`, plus adding `docker compose config` validation in `.github/workflows/ci.yml`.
- **1,440-Tick Simulation Runtime in Pytest Suite:** Running 1,440 ticks takes ~30–45s (vs ~2.5s for 100 ticks). Keep the fast 100-tick test in `pytest` for rapid CI feedback, and run the 1,440-tick full-day verification via a dedicated CLI script (`scripts/run_day_simulation.py`) + targeted smoke test so `pytest` stays fast while Phase 6 captures full-day empirical proof.
- **Root PRD Filename Compatibility:** Existing `.gsd/` files reference `AI Village Product Requirements Document.md` while PRD Section 11 specifies `docs/PRD.md`. Keep the root file intact and place an identical copy at `docs/PRD.md`.

## Recommendations for Planning
1. **Wave 1 — Containerization & CI Config Validation (Plan 6.1):** Create `.dockerignore`, `backend/Dockerfile` (CPU PyTorch, baked `/app/assets/map.json`, `/app/data`, `/app/logs`, `/health` healthcheck), `frontend/nginx.conf` (all 8 REST prefixes including `/world` + long-timeout `/ws` upgrade), `frontend/Dockerfile`, and `docker-compose.yml` (`5173:80` + `8000:8000`, `.env` passthrough defaulting to `mock`). Add `backend/tests/test_docker_packaging.py` asserting Nginx-to-FastAPI route parity and Compose/env invariants, and add `docker compose config` check to `.github/workflows/ci.yml`.
2. **Wave 1 — 1,440-Tick Full-Day Empirical Runner & Visual Assets (Plan 6.2):** Create strict-typed `scripts/run_day_simulation.py` to execute a full 1,440-tick simulated day (`Day 1 06:00` → `Day 2 06:00` with god-mode rumor/event injection), asserting spatial/plan/replay invariants and exporting empirical JSON telemetry; create `scripts/generate_docs_assets.py` (using stdlib PNG/tilemap renderer + headless Edge / `ffmpeg`) to deterministically generate `docs/architecture.png` and `docs/demo.gif`; copy `AI Village Product Requirements Document.md` to `docs/PRD.md`.
3. **Wave 2 — Academic Lab Report, `AGENTS.md`, `README.md` & Final Verification Gate (Plan 6.3):** Author `docs/report.md` (covering PRD Sections 1, 5, 6, 15 + real 1,440-tick empirical tables & evaluation analysis), `AGENTS.md` (PRD Section 17 rules, repo map, dev/test commands), and `README.md` (`docs/demo.gif` top banner, `docs/architecture.png`, `<5 commands` Docker & local setup, 2-minute demo script, resume bullet); run full verification gate (`ruff`, `mypy` on `backend` + `scripts`, `pytest`, `npm run typecheck`, `npm run build`, live backend+frontend e2e smoke check).
