---
phase: 2
verified: 2026-11-24T12:41:00+05:00
status: passed
score: 6/6 must-haves verified
is_re_verification: false
---

# Phase 2 Verification

## Summary

- **Phase Goal:** Implement the full SQLite schema (`SQLModel` + `aiosqlite` for all 7 tables), build the schema-enforcing LLM gateway (`gateway.py`, Pydantic schemas, prompt cache, call budget, cost logging, deterministic mock provider, and Gemini Flash provider), expand to 6–10 rich agent personas, and implement the memory stream with local embeddings (`all-MiniLM-L6-v2` + deterministic test embedding) and weighted retrieval scoring (`recency + importance + relevance`).
- **Result:** **6/6** consolidated must-haves verified with direct empirical evidence (`pytest`: `67 passed in 10.87s`, `ruff check .` in `backend/`: `All checks passed!`, `mypy .` in `backend/`: `Success: no issues found in 38 source files`, `ruff` & `mypy` on `scripts/`: 0 errors, `tsc --noEmit`: 0 errors, `vite build`: `built in 16.86s`, `scripts/verify_phase1_ws.py`: `e2e_ws_ok ticks=[4, 5, 6, 7, 8, 9] moved_agents=8`).
- **Requirements Covered:** `REQ-03`, `REQ-04`, `REQ-05`, `REQ-15`, `NFR-02`, `NFR-03`, `NFR-04`, plus constraints `CON-01`–`CON-05`.

---

## Must-Haves

### Truths

| Truth | Status | Evidence |
|-------|--------|----------|
| 1. CPU-only Phase 2 dependencies install cleanly and extended `Settings` + `.env.example` resolve DB URL, embedding mode, Gemini tiers, budgets, and retrieval weights with zero committed secrets | ✓ VERIFIED | Dependency check printed `deps_ok torch=2.15.0+cpu cuda_available=False sqlmodel=0.0.50 numpy=2.5.5 sentence_transformers=6.3.0`; `backend/pyproject.toml` declares all Phase 2 deps, `packages.find` (`app*`, `sim*`, `api*`, `agents*`, `memory*`, `llm*`), and `sentence_transformers.*` mypy override; `tests/test_config.py` (7/7) passed; `git ls-files .env*` returned only `.env.example`. |
| 2. Async `Database` initializes all 7 PRD SQLite tables (`agents`, `memories`, `relationships`, `events`, `conversations`, `llm_calls`, `sim_state`) with WAL on file DBs, `StaticPool` + serialization lock on `:memory:`, and clean disposal | ✓ VERIFIED | `backend/app/db.py` imports `memory.models` in `init_models()`, configures `PRAGMA foreign_keys=ON` + WAL/NORMAL/busy_timeout for file SQLite and `StaticPool` + `asyncio.Lock` for `:memory:`, auto-creates parent dirs, and calls `engine.dispose()`; `backend/memory/models.py` defines all 7 `SQLModel` `table=True` schemas; `tests/test_db.py` (8/8) verified table creation, CRUD roundtrips, 1,536-byte `LargeBinary` embeddings, composite PK / FK `IntegrityError`, singleton `sim_state`, concurrent `:memory:` access, and WAL persistence across dispose/reopen. |
| 3. Single schema-enforcing `LLMGateway` validates Pydantic v2 outputs (`extra="forbid"`), retries once on validation failure, hits SHA-256 prompt cache at zero cost, enforces daily token/USD budget fallback, rates importance in batch, and logs every call to `llm_calls` | ✓ VERIFIED | `backend/llm/schemas.py` defines 9 strict Pydantic v2 models; `backend/llm/providers/mock.py` implements deterministic zero-network `MockProvider`; `backend/llm/providers/gemini.py` lazily wraps `google.genai` `aio.models.generate_content` with `response_schema`; `backend/llm/gateway.py` implements prompt cache, `max_retries=1` repair prompt, daily token/USD budget fallback to `MockProvider`, `rate_importance_batch()`, and `LLMCallRecord` persistence; `tests/test_llm_gateway.py` (7/7) verified all paths offline; SDK scan confirmed `google.genai` only appears in `backend/llm/providers/gemini.py`. |
| 4. Embedding pipeline (`DeterministicEmbeddingProvider` zero-torch + lazy thread-offloaded `SentenceTransformerEmbeddingProvider`), `MemoryStore`, and weighted `MemoryRetriever` (`recency + importance + relevance`, `0.995^hours`, top-$k=8$, selective `last_access_tick` refresh) operate accurately offline | ✓ VERIFIED | `backend/memory/embeddings.py` implements 384-d `float32` packing (`1,536` bytes), signed BLAKE2b token/bigram `DeterministicEmbeddingProvider`, and lazy thread-safe `SentenceTransformerEmbeddingProvider` (`all-MiniLM-L6-v2`) offloaded via `asyncio.to_thread`; `backend/memory/store.py` implements async CRUD and batched embedding inserts; `backend/memory/retrieval.py` implements `min_max_normalize` (zero-range guard), `cosine_similarity_batch`, and `MemoryRetriever`; `tests/test_embeddings_retrieval.py` (6/6) verified `"torch" not in sys.modules` in mock mode, lazy worker-thread local encoding via fake module, recency/importance/relevance ranking, and top-8 selective touch. |
| 5. Eight rich `AgentPersona` villagers map onto valid walkable Tiled locations without modifying `map.json`, `sprites.png` expands to 8 distinct rows (`128x256`), and `VillageScene.ts` safely wraps sprite frames with a clean frontend build | ✓ VERIFIED | `backend/agents/personas.py` defines frozen `AgentPersona` and 8 `SEEDED_PERSONAS` (`maya`, `liam`, `elena`, `noah`, `clara`, `marcus`, `aria`, `sam`, `sprite_index` `0..7`); `tests/test_personas.py` (4/4) validated all personas and walkable/reachable Tiled anchors; `scripts/generate_village_map.py` (`SPRITE_ROWS = 8`) regenerated `frontend/public/assets/sprites.png` (`(128, 256)`, 1,799 bytes, identical in `frontend/dist/assets/sprites.png`); `git diff -- frontend/public/assets/map.json frontend/public/assets/tileset.png` was empty; `frontend/src/scenes/VillageScene.ts` wraps `sprite_index` via `getFrameNames().length`; `npm --prefix frontend run typecheck` and `build` exited 0. |
| 6. `SimulationEngine` and FastAPI `lifespan` wire 8 personas, `Database`, `EmbeddingService`, `MemoryStore`, `MemoryRetriever`, and `LLMGateway` cleanly, maintaining spatial invariants, live `/ws` & REST sync, and clean shutdown disposal | ✓ VERIFIED | `backend/sim/engine.py` uses `SEEDED_PERSONAS` (with injectable `personas=`), adds idempotent `initialize_persistence()` and `persist_tick_state()`, and preserves `_pre_step_payload` during async persistence; `backend/app/main.py` initializes all Phase 2 services onto `app.state` and calls `await engine.stop_loop()` before `await db.dispose()`; `tests/test_engine.py` (6/6) verified 150 ticks with 8 agents, 0 overlaps, 0 wall collisions, persistence, and retrieval; `tests/test_api_ws.py` (2/2) verified `/health`, `/world`, `/agents`, `/ws`, and SQLite state; `scripts/verify_phase1_ws.py` exited 0 (`e2e_ws_ok ticks=[4, 5, 6, 7, 8, 9] moved_agents=8`). |

---

### Artifacts

| Path | Exists | Substantive | Wired | Notes |
|------|--------|-------------|-------|-------|
| `backend/pyproject.toml` | ✓ | ✓ | ✓ | Phase 2 runtime deps, expanded `packages.find`, `sentence_transformers.*` mypy override |
| `.env.example` | ✓ | ✓ | ✓ | Non-secret defaults for `DATABASE_URL`, `EMBEDDING_PROVIDER`, Gemini models, budgets, retrieval weights |
| `backend/app/config.py` | ✓ | ✓ | ✓ | `DEFAULT_DB_PATH`, `resolved_database_url()`, `resolved_embedding_provider()`, retrieval & budget settings |
| `backend/app/db.py` | ✓ | ✓ | ✓ | Async `Database` (`init_models`, `session`, `dispose`, WAL pragmas, `:memory:` `StaticPool` + `asyncio.Lock`) |
| `backend/memory/__init__.py` | ✓ | ✓ | ✓ | Package marker for `memory` |
| `backend/memory/models.py` | ✓ | ✓ | ✓ | All 7 `SQLModel` tables (`AgentRecord`, `MemoryRecord`, `RelationshipRecord`, `EventRecord`, `ConversationRecord`, `LLMCallRecord`, `SimStateRecord`) |
| `backend/llm/__init__.py` | ✓ | ✓ | ✓ | Package marker for `llm` |
| `backend/llm/prompts/__init__.py` | ✓ | ✓ | ✓ | Package marker for `llm.prompts` |
| `backend/llm/providers/__init__.py` | ✓ | ✓ | ✓ | Package marker for `llm.providers` |
| `backend/llm/schemas.py` | ✓ | ✓ | ✓ | 9 strict Pydantic v2 schemas (`ConfigDict(extra="forbid")`) |
| `backend/llm/providers/base.py` | ✓ | ✓ | ✓ | `ProviderResult` dataclass & `@runtime_checkable class LLMProvider` |
| `backend/llm/providers/mock.py` | ✓ | ✓ | ✓ | Deterministic SHA-256 `MockProvider` supporting all schemas and `Item count: (\d+)` batch parsing |
| `backend/llm/providers/gemini.py` | ✓ | ✓ | ✓ | Lazy `GeminiProvider` wrapping `google.genai` `aio.models.generate_content` |
| `backend/llm/gateway.py` | ✓ | ✓ | ✓ | `LLMGateway`, `LLMGatewayError`, `MODEL_PRICING_PER_MILLION`, `estimate_cost_usd`, cache, retry, budget, DB logging |
| `backend/memory/embeddings.py` | ✓ | ✓ | ✓ | `EMBEDDING_DIM = 384`, `pack_embedding`, `unpack_embedding`, `DeterministicEmbeddingProvider`, lazy `SentenceTransformerEmbeddingProvider`, `EmbeddingService` |
| `backend/memory/store.py` | ✓ | ✓ | ✓ | `MemoryType`, `MemoryCreate`, async `MemoryStore` CRUD across memories, agents, sim_state, events, relationships |
| `backend/memory/retrieval.py` | ✓ | ✓ | ✓ | `ScoredMemory`, `min_max_normalize`, `cosine_similarity_batch`, `MemoryRetriever` |
| `backend/agents/__init__.py` | ✓ | ✓ | ✓ | Package marker for `agents` |
| `backend/agents/personas.py` | ✓ | ✓ | ✓ | `AgentPersona`, 8 `SEEDED_PERSONAS`, `SEEDED_PERSONA_BY_ID`, `get_persona()` |
| `scripts/generate_village_map.py` | ✓ | ✓ | ✓ | Expanded `SPRITE_ROWS = 8` with 8 distinct palettes; map & tileset generation unchanged |
| `frontend/public/assets/sprites.png` | ✓ | ✓ | ✓ | `128x256` RGBA PNG (8 villager rows x 4 poses, 1,799 bytes), copied identically into `frontend/dist/assets/sprites.png` |
| `frontend/src/scenes/VillageScene.ts` | ✓ | ✓ | ✓ | Defensive `sprite_index` wrapping using `getFrameNames().length / FRAMES_PER_AGENT` |
| `backend/sim/engine.py` | ✓ | ✓ | ✓ | 8 seeded `AgentPersona` villagers, `initialize_persistence()`, `persist_tick_state()`, snapshot consistency guard |
| `backend/app/main.py` | ✓ | ✓ | ✓ | `lifespan` initializes & exposes `db`, `embedding_service`, `memory_store`, `memory_retriever`, `llm_gateway`, `engine` |
| `scripts/verify_phase1_ws.py` | ✓ | ✓ | ✓ | Isolated temp SQLite DB + 8-agent REST & `/ws` e2e check |
| `backend/tests/test_*.py` | ✓ | ✓ | ✓ | 10 test modules (67 tests total, including `test_db.py`, `test_llm_gateway.py`, `test_embeddings_retrieval.py`, `test_personas.py`) |

---

### Key Links

| From | To | Via | Status |
|------|----|-----|--------|
| `backend/app/db.py` | `backend/memory/models.py` | `init_models()` imports `memory.models` before `SQLModel.metadata.create_all` | ✓ WIRED |
| `backend/memory/models.py` | `agents.id` | Foreign keys on `MemoryRecord.agent_id` and `RelationshipRecord.agent_a`/`agent_b` | ✓ WIRED |
| `backend/llm/gateway.py` | `backend/app/db.py` & `LLMCallRecord` | `_record_call()` persists provider attempts and cache hits via `self.db.session()` | ✓ WIRED |
| `backend/llm/gateway.py` | `backend/llm/providers/` | Gateway delegates completion solely to `LLMProvider` (`MockProvider` / `GeminiProvider`) | ✓ WIRED |
| `backend/memory/store.py` | `backend/memory/embeddings.py` & `Database` | `add_memories_batch()` embeds texts via `EmbeddingService` and packs via `pack_embedding()` | ✓ WIRED |
| `backend/memory/retrieval.py` | `backend/memory/store.py` & `embeddings.py` | `retrieve()` embeds query, unpacks blobs, normalizes scores, and calls `store.touch_memories()` | ✓ WIRED |
| `backend/agents/personas.py` | `frontend/public/assets/map.json` | All 8 homes and routines map onto valid `WorldMap` locations | ✓ WIRED |
| `scripts/generate_village_map.py` | `frontend/src/scenes/VillageScene.ts` | Generates `4x8` (`128x256`) `sprites.png` consumed with `getFrameNames().length` row wrapping | ✓ WIRED |
| `backend/sim/engine.py` | `agents.personas`, `memory.*`, `llm.gateway` | Seeds 8 `AgentPersona` entities and syncs state/memories via `MemoryStore` | ✓ WIRED |
| `backend/app/main.py` | `SimulationEngine` & `Database` | `lifespan` wires `Database` → `EmbeddingService`/`MemoryStore`/`MemoryRetriever`/`LLMGateway` → `SimulationEngine` and disposes on exit | ✓ WIRED |

---

## Command Verification Evidence

1. **Backend Test Suite (`pytest`)** (cwd: `backend/`):
   - Command: `backend\.venv\Scripts\python.exe -c "import pathlib, subprocess, sys; sys.exit(subprocess.call([str(pathlib.Path('backend/.venv/Scripts/pytest.exe').resolve()), '-v', '--durations=10'], cwd='backend'))"`
   - Output: `67 passed in 10.87s` (exit code 0) — all tests passed across `test_api_ws.py` (2), `test_astar.py` (9), `test_clock.py` (11), `test_config.py` (7), `test_db.py` (8), `test_embeddings_retrieval.py` (6), `test_engine.py` (6), `test_llm_gateway.py` (7), `test_personas.py` (4), and `test_world.py` (7).
2. **Backend Linter (`ruff check .`)** (cwd: `backend/`):
   - Command: `backend\.venv\Scripts\python.exe -c "import pathlib, subprocess, sys; sys.exit(subprocess.call([str(pathlib.Path('backend/.venv/Scripts/ruff.exe').resolve()), 'check', '.'], cwd='backend'))"`
   - Output: `All checks passed!` (exit code 0).
3. **Backend Static Type Check (`mypy .`)** (cwd: `backend/`):
   - Command: `backend\.venv\Scripts\python.exe -c "import pathlib, subprocess, sys; sys.exit(subprocess.call([str(pathlib.Path('backend/.venv/Scripts/mypy.exe').resolve()), '.'], cwd='backend'))"`
   - Output: `Success: no issues found in 38 source files` (exit code 0).
4. **Scripts Lint & Static Type Check**:
   - Command: `backend\.venv\Scripts\ruff.exe check --config backend\pyproject.toml scripts` → `All checks passed!` (exit code 0).
   - Command: `backend\.venv\Scripts\mypy.exe --config-file backend\pyproject.toml scripts` → `Success: no issues found in 2 source files` (exit code 0).
5. **Frontend TypeScript Check (`tsc --noEmit`) & Production Build (`vite build`)**:
   - Command: `npm --prefix frontend run typecheck` → `tsc --noEmit` exited 0 with zero errors.
   - Command: `npm --prefix frontend run build` → `✓ 10 modules transformed.`, emitted `dist/index.html` (`1.02 kB`), `dist/assets/index-Bjh7sn2g.css` (`1.98 kB`), `dist/assets/index-B6YZgwL8.js` (`1,487.67 kB`), `✓ built in 16.86s` (exit code 0).
6. **Phase 2 Dependency & CPU Torch Check**:
   - Command: `backend\.venv\Scripts\python.exe -c "import sqlmodel, aiosqlite, sqlalchemy, numpy, sentence_transformers, google.genai, torch; print('deps_ok', 'torch=' + torch.__version__, 'cuda_available=' + str(torch.cuda.is_available()), 'sqlmodel=' + sqlmodel.__version__, 'numpy=' + numpy.__version__, 'sentence_transformers=' + sentence_transformers.__version__)"`
   - Output: `deps_ok torch=2.15.0+cpu cuda_available=False sqlmodel=0.0.50 numpy=2.5.5 sentence_transformers=6.3.0` (exit code 0).
7. **Asset & Unchanged Map Verification**:
   - Sprite dimensions check: `public_sprites (128, 256) bytes 1799`, `dist_sprites (128, 256) bytes 1799`, `identical True` (exit code 0).
   - Map & tileset diff: `git diff -- frontend/public/assets/map.json frontend/public/assets/tileset.png` produced zero output (unchanged).
8. **Live Server + WebSocket `/ws` Verification**:
   - Command: `backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py`
   - Output: `e2e_ws_ok ticks=[4, 5, 6, 7, 8, 9] moved_agents=8` (exit code 0).
9. **Anti-Pattern, Secret & SDK Boundary Scans**:
   - Scanned 44 `.py`/`.ts` files across `backend/`, `frontend/src/`, and `scripts/` for `TODO|FIXME|XXX|HACK|PLACEHOLDER|coming soon|lorem ipsum|NotImplementedError|console.log`: `antipattern_hits []`.
   - `google.genai` import scan across all `.py` files: found exclusively in `backend/llm/providers/gemini.py` (lines 13, 38, 53), confirming `CON-02`.
   - `git ls-files .env*`: returned `.env.example` only.
   - Leftover SQLite DB check outside `.venv` and `.mypy_cache`: zero `.db`/`.sqlite` artifacts left in repo.

---

## Anti-Patterns & Non-Blocking Findings

- ℹ️ **Info — Full suite wall-clock runtime (`10.87s`) vs Plan 2.5 aspirational `<5s` note:** `pytest` runs all 67 unit/integration tests in `10.87s` offline (cold `google.genai.types` import accounts for `1.88s`, plus live ASGI lifespan and 150-tick simulations). No network calls or `torch` imports occur in default mock/test execution, and there is no `<5s` ceiling in `SPEC.md` or `REQUIREMENTS.md`.
- ℹ️ **Info — `pytest-asyncio` fixture loop scope warning:** `pytest` emits a `PytestDeprecationWarning` that `asyncio_default_fixture_loop_scope` is unset; non-blocking and worth setting explicitly in `backend/pyproject.toml` before Phase 5 CI hardening.
- ℹ️ **Info — `LLMGateway` daily budget counters are per-process:** `_daily_tokens` and `_daily_cost` track usage in memory per simulation day; if future phases add mid-day SQLite resume across server restarts, seeding those counters from `llm_calls` on startup would preserve cumulative daily caps.

---

## Human Verification Needed

### 1. Visual Browser Review of 8 Distinct Villager Sprites in Phaser 3
**Test:** Start the backend (`backend/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000` in `backend/`) and frontend (`npm --prefix frontend run dev`), then open `http://localhost:5173` in a desktop browser.
**Expected:** All 8 villagers (`Maya`, `Liam`, `Elena`, `Noah`, `Clara`, `Marcus`, `Aria`, `Sam`) appear on the map with 8 distinct color palettes and walking animation poses, moving smoothly along roads without clipping or overlapping.
**Why human:** No interactive browser rendering tool is available in this headless verification context to capture a live canvas screenshot.

### 2. Optional Live External Model Smoke Test (`all-MiniLM-L6-v2` & Gemini API)
**Test:** When online with `EMBEDDING_PROVIDER=local` and/or `LLM_PROVIDER=gemini` + a valid `GEMINI_API_KEY` in `.env`, run a short startup smoke check outside offline CI.
**Expected:** `SentenceTransformerEmbeddingProvider` downloads/caches `all-MiniLM-L6-v2` (384-d) and encodes without blocking `/ws` ticks; `GeminiProvider` returns schema-valid structured JSON logged to `llm_calls`.
**Why human:** `NFR-03` forbids external network calls in the automated test suite; real HuggingFace weights and Gemini API keys are intentionally excluded from offline verification.

---

## Verdict

**PASS** — All 6 Phase 2 must-haves and requirements (`REQ-03`, `REQ-04`, `REQ-05`, `REQ-15`, `NFR-02`, `NFR-03`, `NFR-04`) are verified with empirical test, lint, static-type, build, and live WebSocket execution proof. Zero blocker gaps found; ready to proceed to Phase 3 planning (`/plan 3`).
