# AGENTS.md — AI Village Contributor & Coding-Agent Guide

> **Canonical Workflow Rules:** [`PROJECT_RULES.md`](PROJECT_RULES.md) is the authoritative GSD execution and shell-discipline specification for this repository. Files inside [`adapters/`](adapters/) (`CLAUDE.md`, `GEMINI.md`, `GPT_OSS.md`) contain optional model-specific enhancements only and never override `PROJECT_RULES.md` or this document.

---

## 1. Project Identity & Authoritative References

**AI Village** is a 2D server-authoritative multi-agent town simulation (inspired by Stanford's *Generative Agents*, built from scratch for a 6th-semester BSCS AI Lab Project at Superior University) combining classical AI (`heapq` A* grid search, three-tier hierarchical planning, SQLite/vector knowledge representation) with schema-constrained LLM reasoning.

Before modifying code, consult the authoritative specification documents:

| Document | Purpose |
| :--- | :--- |
| [`docs/PRD.md`](docs/PRD.md) | Canonical Product Requirements Document (synced copy of [`AI Village Product Requirements Document.md`](AI%20Village%20Product%20Requirements%20Document.md)) |
| [`.gsd/SPEC.md`](.gsd/SPEC.md) | Finalized Milestone v1.0 scope (`F1`–`F14`, P0 + P1) and constraints |
| [`.gsd/REQUIREMENTS.md`](.gsd/REQUIREMENTS.md) | Traceability matrix (`REQ-01`–`REQ-16`, `NFR-01`–`NFR-05`, `CON-01`–`CON-05`) |
| [`.gsd/ARCHITECTURE.md`](.gsd/ARCHITECTURE.md) | System component diagram and module responsibilities |
| [`PROJECT_RULES.md`](PROJECT_RULES.md) | Canonical GSD methodology, commit conventions, proof requirements, and shell discipline |
| [`docs/report.md`](docs/report.md) | Formal 6th-semester BSCS AI Lab Report grounded in 1,440-tick empirical telemetry |

---

## 2. Repository Map

```text
ai-village/
  AGENTS.md                  # Engineering rules, invariants, and test/lint commands
  PROJECT_RULES.md           # Canonical GSD execution & shell rules
  README.md                  # Portfolio overview, architecture, and <5-command quickstarts
  docker-compose.yml         # Multi-service runtime (backend:8000 + nginx frontend:5173)
  .dockerignore              # Excludes .venv, node_modules, .env, *.db while keeping map.json
  .env.example               # Committed defaults template (never commit .env)
  .github/workflows/ci.yml   # GitHub Actions CI (backend lint/type/pytest, frontend, compose)

  backend/
    pyproject.toml           # Python 3.12 packaging, ruff, strict mypy, pytest config
    Dockerfile               # CPU PyTorch + FastAPI image with /app/assets/map.json
    app/
      main.py                # FastAPI lifespan factory & provider/engine wiring
      config.py              # Pydantic BaseSettings & env resolution helpers
      db.py                  # Async SQLModel/aiosqlite manager with WAL pragmas
    sim/
      clock.py               # SimClock (1 tick = 1 min, Day 1 06:00 start, 1x/4x/16x)
      world.py               # Tiled map.json parser, walkability grid, NamedLocation anchors
      astar.py               # Hand-written heapq A* with Manhattan heuristic (4-way)
      engine.py              # Authoritative SimulationEngine, _step_lock, invariants & WS events
      replay.py              # Day-partitioned JSONL ReplayLogger (day_1.jsonl, day_2.jsonl, ...)
    agents/
      personas.py            # 8 immutable SEEDED_PERSONAS (Maya, Liam, Elena, Noah, Clara, Marcus, Aria, Sam)
      agent.py               # AgentBrain (Perceive -> Remember -> Decide, importance tracking)
      planner.py             # DailyPlanner (5-8 day blocks -> lazy hourly focus -> MinuteSteps + replan)
      conversation.py        # ConversationManager (Manhattan <=2, cooldowns 60/30, <=6 turns)
      reflection.py          # ReflectionManager (importance >=150 -> 3 questions -> cited insights)
    memory/
      models.py              # 7 SQLModel tables (agents, memories, relationships, events, conversations, llm_calls, sim_state)
      store.py               # Async SQLite CRUD & canonical (agent_a < agent_b) relationship upserts
      embeddings.py          # DeterministicEmbeddingProvider (BLAKE2b) & lazy all-MiniLM-L6-v2
      retrieval.py           # Vectorized recency (0.995^h) + importance + cosine relevance scoring
    llm/
      gateway.py             # Exclusive LLMGateway (Pydantic validation, 1-retry repair, SHA-256 cache, budget gate)
      schemas.py             # 9 strict Pydantic v2 response models (ConfigDict(extra="forbid"))
      prompts/               # conversation.py, planning.py, reflection.py prompt builders
      providers/             # base.py (Protocol), mock.py (deterministic), gemini.py (google-genai)
    api/
      rest.py                # 12 REST endpoints across 8 prefixes
      ws.py                  # ConnectionManager & live /ws endpoint
    tests/                   # 19 offline deterministic pytest modules (unit, integration, 100-tick, 1440-tick, Docker)

  frontend/
    Dockerfile               # Node 20 builder + Nginx 1.27 static/reverse-proxy image
    nginx.conf               # /ws WebSocket proxy + 8 REST route prefixes + SPA fallback
    package.json             # Phaser 3, Cytoscape.js, Chart.js, TypeScript 5.6, Vite 5.4
    tsconfig.json            # Strict TypeScript compiler settings
    vite.config.ts           # Dev server proxy on port 5173 -> backend:8000
    public/assets/           # map.json (40x30, 10 named locations), tileset.png, sprites.png
    src/
      main.ts                # Application bootstrap, state coordination, keyboard shortcuts
      style.css              # Dark observability HUD & modal styling
      types/sim.ts           # Typed DTOs & WebSocket frame type guards
      scenes/VillageScene.ts # Phaser 3 tilemap, smooth interpolation, speech bubbles
      net/apiClient.ts       # Typed REST fetch client
      net/wsClient.ts        # Auto-reconnecting passive WebSocket client
      ui/                    # activityFeed.ts, agentInspector.ts, eventInjector.ts,
                             # metricsDashboard.ts, relationshipGraph.ts, replayControls.ts, timeControls.ts

  scripts/
    generate_village_map.py  # Generates frontend/public/assets/map.json, tileset.png, sprites.png
    run_day_simulation.py    # 1,440-tick offline simulation runner & telemetry JSON exporter
    generate_docs_assets.py  # Generates docs/architecture.png and docs/demo.gif
    verify_phase1_ws.py      # Boots Uvicorn and validates frontend/dist + /health, /world, /agents, /ws

  docs/
    PRD.md                   # Synchronized Product Requirements Document
    architecture.png         # System architecture diagram (1400x820)
    demo.gif                 # Animated live-village demo preview (960x620)
    report.md                # Formal 6th-semester BSCS AI Lab Report
```

---

## 3. Non-Negotiable Engineering Rules (PRD Section 17)

Every contributor and coding agent must obey all 11 rules from [`docs/PRD.md`](docs/PRD.md) Section 17:

1. **Read the PRD first & respect milestone scope.** Review [`docs/PRD.md`](docs/PRD.md) and [`.gsd/SPEC.md`](.gsd/SPEC.md) before modifying code. Keep v1.0 changes strictly within `F1`–`F14` (do not silently pull `F15`–`F17` stretch goals into v1.0 patches).
2. **Server owns all simulation state.** `SimulationEngine` (`backend/sim/engine.py`) is the single source of truth. The Phaser/TypeScript frontend must remain strictly passive—never calculate pathfinding, memory scoring, dialogue outcomes, or clock ticks client-side.
3. **All LLM calls go through `backend/llm/gateway.py`.** Never import or call `google.genai`, HTTP LLM clients, or other provider SDKs outside `backend/llm/gateway.py` and `backend/llm/providers/`.
4. **Every LLM response must pass Pydantic v2 schema validation.** Define strict output contracts (`ConfigDict(extra="forbid")`) in `backend/llm/schemas.py` and let `LLMGateway.generate()` enforce validation + 1-retry repair. Never consume raw unvalidated LLM strings.
5. **Secrets hygiene.** Never hardcode API keys or commit `.env`. Keep `.env` gitignored and document any new setting with safe defaults in `.env.example` and `backend/app/config.py`.
6. **Offline mock tests for every module.** Every new or modified module requires automated tests in `backend/tests/` that pass 100% offline with `MockProvider` (`LLM_PROVIDER=mock`, `EMBEDDING_PROVIDER=mock`) and zero network access.
7. **Small, strictly typed functions + lint/type gates.** Keep functions focused and typed. Both `ruff check` and `mypy --strict` must pass with zero warnings/errors before considering any task finished.
8. **Never call the LLM inside a tight loop; check budget first.** Trigger LLM calls strictly at cognitive decision points (wake-up planning, interruption replanning, lazy block decomposition, batched tick observations, conversation decisions/turns/summaries, threshold reflections), and preserve `LLMGateway` daily token/USD budget checks.
9. **Log every LLM call.** Every call (including SHA-256 prompt cache hits) must persist to SQLite `llm_calls` with `tick`, `agent_id`, `purpose`, `model`, `tokens_in`, `tokens_out`, `latency_ms`, `cost_est`, and `cache_hit`.
10. **Justify any new dependency.** Never add a dependency to `backend/pyproject.toml` or `frontend/package.json` without a concise one-line rationale in the commit/PR description.
11. **Clarify before guessing.** When a requirement, API payload, or invariant is ambiguous, stop and inspect the spec or ask rather than inventing incompatible behavior.

---

## 4. Architectural, Docker & Tooling Invariants

Violating any of the invariants below breaks tests (`test_docker_packaging.py`, `test_config.py`, or CI):

- **`Settings` environment variable names (`backend/app/config.py`):**
  - Core path/runtime overrides must use exact names: `MAP_PATH`, `DATABASE_URL`, `REPLAY_LOG_DIR`, `LLM_PROVIDER`, `EMBEDDING_PROVIDER`, `CORS_ORIGINS`.
  - `Settings.resolved_embedding_provider()` resolves `"auto"` to `"mock"` when `LLM_PROVIDER=mock` and `"local"` (`all-MiniLM-L6-v2`) otherwise, keeping test runs fast and zero-network.
- **SQLite WAL directory volume rule (`docker-compose.yml`, `backend/app/db.py`):**
  - `Database` opens SQLite with `PRAGMA journal_mode=WAL;`, which creates `ai_village.db-wal` and `ai_village.db-shm` sidecar files alongside the database file.
  - Always mount the **parent directory** as a volume (`village_data:/app/data`), never a single-file bind mount to `/app/data/ai_village.db`.
- **Nginx reverse-proxy & FastAPI route parity (`frontend/nginx.conf`, `frontend/vite.config.ts`, `backend/tests/test_docker_packaging.py`):**
  - Both Nginx and Vite proxy `= /ws` (with WebSocket upgrade headers and `3600s` timeouts in Nginx) and all 8 REST route prefixes:
    `^/(health|world|agents|events|sim|relationships|metrics|replay)(/|$)`.
  - Adding a new top-level REST route prefix in `backend/api/rest.py` without updating `frontend/nginx.conf` (and `frontend/vite.config.ts`) causes `test_docker_packaging.py` to fail.
- **Strict `mypy` configuration across `backend/` and `scripts/` (`backend/pyproject.toml`):**
  - `[tool.mypy]` sets `strict = true` and `mypy_path = "$MYPY_CONFIG_FILE_DIR"`, and `[tool.ruff.lint.isort]` declares `known-first-party = ["app", "sim", "api", "agents", "memory", "llm"]`.
  - Keep all Python modules in both `backend/` and `scripts/` compatible with `mypy --strict` and `ruff` line-length `100` (`E`, `F`, `I`, `UP`, `B`).
- **Canonical relationship ordering (`backend/memory/store.py` & `backend/api/rest.py`):**
  - Pairwise relationships in `relationships` always store `agent_a < agent_b` lexicographically. Never write duplicate reversed pairs `(b, a)`.
- **Shell Discipline (`PROJECT_RULES.md`):**
  - **One command per invocation.** Never chain commands with `&&` or `||` in agent invocations or documented Windows PowerShell workflows (Windows PowerShell 5.1 rejects `&&`/`||` at parse time).

---

## 5. Exact Local & CI Verification Commands

All commands below match `.github/workflows/ci.yml` and run 100% offline. Execute them **one command per line/invocation**.

### PowerShell (Windows)

```powershell
# 1. Backend & scripts lint (ruff)
backend\.venv\Scripts\ruff.exe check backend
backend\.venv\Scripts\ruff.exe check --config backend/pyproject.toml scripts

# 2. Backend & scripts strict typecheck (mypy)
backend\.venv\Scripts\mypy.exe --config-file backend/pyproject.toml backend
backend\.venv\Scripts\mypy.exe --config-file backend/pyproject.toml scripts

# 3. Full offline pytest suite (from backend/)
Set-Location backend
.\.venv\Scripts\pytest.exe -v
Set-Location ..

# 4. Frontend typecheck & production build
npm --prefix frontend run typecheck
npm --prefix frontend run build

# 5. Live WebSocket & built-dist smoke check
backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py

# 6. Full 1,440-tick empirical runner (optional deep verification)
backend\.venv\Scripts\python.exe scripts/run_day_simulation.py --ticks 1440 --seed 42
```

### Bash (Linux / macOS / CI)

```bash
# 1. Backend & scripts lint (ruff)
ruff check backend
ruff check --config backend/pyproject.toml scripts

# 2. Backend & scripts strict typecheck (mypy)
mypy --config-file backend/pyproject.toml backend
mypy --config-file backend/pyproject.toml scripts

# 3. Full offline pytest suite
cd backend
pytest -v
cd ..

# 4. Frontend typecheck & production build
npm --prefix frontend run typecheck
npm --prefix frontend run build

# 5. Live WebSocket & built-dist smoke check + Docker Compose schema check
python scripts/verify_phase1_ws.py
docker compose config --quiet
```
