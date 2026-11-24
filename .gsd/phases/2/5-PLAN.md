---
phase: 2
plan: 5
wave: 3
depends_on:
  - "1"
  - "2"
  - "3"
  - "4"
files_modified:
  - backend/sim/engine.py
  - backend/app/main.py
  - backend/tests/test_engine.py
  - backend/tests/test_api_ws.py
  - scripts/verify_phase1_ws.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`SimulationEngine` initializes the 8 seeded `AgentPersona` villagers by default (keeping `personas=` injectable), maintains zero wall collisions and zero tile overlaps over 150 ticks, and syncs state to SQLite when `memory_store` is attached"
    - "FastAPI `lifespan` initializes `Database`, creates all 7 SQLite tables, constructs `EmbeddingService`, `MemoryStore`, `MemoryRetriever`, and `LLMGateway` (Mock or Gemini per config), seeds `agents`, initial persona memories, and `sim_state`, and disposes `Database` cleanly on shutdown"
    - "`GET /health`, `GET /agents`, and WebSocket `/ws` continue serving valid `AgentSnapshot` and `TickPayload` schemas for all 8 agents"
    - "Full offline backend test suite, `ruff`, `mypy`, and live server verification pass in under 5 seconds"
  artifacts:
    - "backend/sim/engine.py integrates `SEEDED_PERSONAS`, optional `memory_store`/`retriever`/`llm_gateway`, `initialize_persistence()`, and `persist_tick_state()`"
    - "backend/app/main.py wires `db`, `embedding_service`, `memory_store`, `memory_retriever`, and `llm_gateway` onto `app.state` with guaranteed `await db.dispose()` shutdown"
    - "backend/tests/test_engine.py verifies 8 agents across 150 ticks, spatial invariants, and DB/memory persistence"
    - "backend/tests/test_api_ws.py verifies 8 agents across `/health`, `/agents`, `/ws`, and SQLite persistence using isolated `tmp_path` DB"
    - "scripts/verify_phase1_ws.py validates 8 seeded agents and uses an isolated temporary DB"
  key_links:
    - "backend/sim/engine.py imports `SEEDED_PERSONAS` from `agents.personas`, `MemoryStore`/`MemoryCreate` from `memory.store`, `MemoryRetriever` from `memory.retrieval`, and `LLMGateway` from `llm.gateway`"
    - "backend/app/main.py instantiates `Database`, `EmbeddingService`, `MemoryStore`, `MemoryRetriever`, and `LLMGateway` from `Settings` and connects them to `SimulationEngine`"
---

# Plan 2.5: Engine & FastAPI Lifespan Integration of 8 Personas, Memory & LLM Gateway

## Objective
Wire the 8 rich agent personas (`agents/personas.py`), async SQLite `Database` (`app/db.py`), `EmbeddingService` (`memory/embeddings.py`), `MemoryStore` (`memory/store.py`), `MemoryRetriever` (`memory/retrieval.py`), and `LLMGateway` (`llm/gateway.py`) into `SimulationEngine` (`backend/sim/engine.py`) and FastAPI `lifespan` (`backend/app/main.py`), update Phase 1 4-agent assertions in `test_engine.py`, `test_api_ws.py`, and `scripts/verify_phase1_ws.py` cleanly to 8 agents, and add full end-to-end persistence and retrieval integration tests.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/REQUIREMENTS.md
- .gsd/phases/2/RESEARCH.md
- backend/sim/engine.py
- backend/app/main.py
- backend/tests/test_engine.py
- backend/tests/test_api_ws.py
- scripts/verify_phase1_ws.py

## Tasks

<task type="auto">
  <name>Integrate 8 personas, MemoryStore, MemoryRetriever, and LLMGateway into SimulationEngine</name>
  <files>
    backend/sim/engine.py
  </files>
  <action>
    Update `backend/sim/engine.py` to seed agents from `SEEDED_PERSONAS` and support async SQLite state and initial memory persistence without slowing down pure spatial tests.

    Steps:
    1. Replace the hardcoded 4-tuple `_SEEDED_AGENT_SPECS` with `SEEDED_PERSONAS` from `agents.personas`:
       - Extend `AgentEntity` with `persona: AgentPersona` (defaulting cleanly or passed during creation) while keeping `id`, `name`, `role`, `sprite_index`, `home_location`, `x`, `y`, `target_location`, `path`, `current_action`, `dwell_ticks_remaining`, `stall_ticks`, `routine`, `routine_index`, `visited_locations` intact.
       - Keep `AgentSnapshot` and `TickPayload` wire fields 100% identical so `frontend/src/types/sim.ts` requires zero schema changes.
       - Update `_create_initial_agents(world: WorldMap, personas: Sequence[AgentPersona] = SEEDED_PERSONAS)` to spawn each persona at `home_location` anchor (with `world.find_free_adjacent` fallback if shared) and populate `routine = list(persona.default_routine)`.
    2. Update `SimulationEngine.__init__`:
       - Accept optional keyword parameters:
         - `personas: Sequence[AgentPersona] | None = None`
         - `memory_store: MemoryStore | None = None`
         - `retriever: MemoryRetriever | None = None`
         - `llm_gateway: LLMGateway | None = None`
       - Store `self.memory_store = memory_store`, `self.retriever = retriever`, `self.llm_gateway = llm_gateway`.
    3. Add async persistence methods on `SimulationEngine`:
       - `async def initialize_persistence(self) -> None`:
         - If `self.memory_store is None`: return immediately.
         - Upsert `AgentRecord` for all agents (`persona_json=agent.persona.to_persona_json()`, `home_location`, `x`, `y`, `current_action`, `current_plan_json=json.dumps(agent.routine)`).
         - Seed initial persona memories idempotently: for each agent, check `existing = await self.memory_store.list_memories(agent.id, limit=1)`; if empty, batch-insert 1 biographical memory + 1 observation per `starting_goal` (`importance=6`, `created_tick=self.clock.tick`) via `add_memories_batch(...)`.
         - Ensure `sim_state` singleton exists via `get_or_create_sim_state(tick=self.clock.tick, sim_time=self.clock.sim_time_str, speed=self.clock.speed, seed=self.seed)`.
       - `async def persist_tick_state(self) -> None`:
         - If `self.memory_store is None`: return immediately.
         - Call `update_agent_states(...)` for all agents and `save_sim_state(tick=self.clock.tick, sim_time=self.clock.sim_time_str, speed=self.clock.speed, seed=self.seed)`.
    4. In `step_once()`:
       - Inside `async with self._step_lock:` step all agents and advance `self.clock.advance()`, build `payload = self.build_tick_payload()`, and if `self.memory_store is not None`, await `self.persist_tick_state()` before emitting `payload` to tick callbacks so REST queries right after a WS tick see consistent DB state.

    AVOID: Performing blocking `sqlite3` I/O on the event loop or breaking `AgentSnapshot` / `TickPayload` JSON compatibility with the frontend.
    USE: `personas=SEEDED_PERSONAS` by default and async `MemoryStore` batched writes only when `memory_store` is attached.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\ruff.exe check sim/engine.py
    .venv\Scripts\mypy.exe sim/engine.py
  </verify>
  <done>
    `backend/sim/engine.py` uses all 8 `SEEDED_PERSONAS`, integrates optional persistence/retrieval/LLM components, and passes `ruff check` + strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Wire Database, EmbeddingService, MemoryStore, MemoryRetriever, and LLMGateway in FastAPI lifespan</name>
  <files>
    backend/app/main.py
  </files>
  <action>
    Update `create_app()` and `lifespan()` in `backend/app/main.py` to manage the full Phase 2 dependency graph cleanly from startup through disposal.

    Steps:
    1. Build provider helper `_build_llm_provider(settings: Settings) -> LLMProvider`:
       - `mode = settings.llm_provider.strip().lower()`
       - If `mode == "mock"`: return `MockProvider(seed=settings.sim_seed)`.
       - If `mode == "gemini"`: return `GeminiProvider(api_key=settings.gemini_api_key, default_model=settings.gemini_routine_model)`.
       - Otherwise raise `ValueError(f"Unsupported llm_provider: {settings.llm_provider!r}")`.
    2. Inside `lifespan(app: FastAPI)`:
       - Create `db = Database(resolved_settings.resolved_database_url())` and `await db.init_models()`.
       - Create `embedding_service = EmbeddingService.from_mode(resolved_settings.resolved_embedding_provider())`.
       - Create `memory_store = MemoryStore(db=db, embedding_service=embedding_service)`.
       - Create `memory_retriever = MemoryRetriever(store=memory_store, embedding_service=embedding_service, w_recency=resolved_settings.retrieval_w_recency, w_importance=resolved_settings.retrieval_w_importance, w_relevance=resolved_settings.retrieval_w_relevance, decay_per_hour=resolved_settings.retrieval_decay_per_hour, default_top_k=resolved_settings.retrieval_top_k)`.
       - Create `llm_gateway = LLMGateway(provider=_build_llm_provider(resolved_settings), fallback_provider=MockProvider(seed=resolved_settings.sim_seed), db=db, daily_budget_usd=resolved_settings.llm_daily_budget_usd, daily_token_limit=resolved_settings.llm_daily_token_limit, max_retries=resolved_settings.llm_max_retries, routine_model=resolved_settings.gemini_routine_model, planning_model=resolved_settings.gemini_planning_model, seed=resolved_settings.sim_seed)`.
       - Create `engine = SimulationEngine(world=world, clock=clock, seed=resolved_settings.sim_seed, memory_store=memory_store, retriever=memory_retriever, llm_gateway=llm_gateway)`.
       - Call `await engine.initialize_persistence()`.
       - Attach `db`, `embedding_service`, `memory_store`, `memory_retriever`, and `llm_gateway` onto `app.state` alongside `settings`, `world`, `clock`, `engine`, and `ws_manager`.
       - In `finally:`: await `engine.stop_loop()` FIRST, then `await db.dispose()` inside a `try/finally` so background ticks never write after engine disposal.

    AVOID: Disposing `db` before `await engine.stop_loop()` completes (could race with an in-flight tick write) or calling `GeminiProvider` in default mock mode.
    USE: `await engine.stop_loop()` before `await db.dispose()` inside `lifespan`'s `finally:` block.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\ruff.exe check app/main.py
    .venv\Scripts\mypy.exe app/main.py
  </verify>
  <done>
    `backend/app/main.py` initializes and disposes the full Phase 2 stack cleanly and passes `ruff check` + strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Update 8-agent tests, add persistence integration tests, and run full Phase 2 verification</name>
  <files>
    backend/tests/test_engine.py
    backend/tests/test_api_ws.py
    scripts/verify_phase1_ws.py
  </files>
  <action>
    Update existing Phase 1 4-agent assertions to 8 seeded agents, add end-to-end engine + lifespan DB/memory/gateway integration tests, and run full backend + frontend + live `/ws` verification.

    Steps:
    1. Update `backend/tests/test_engine.py`:
       - In `test_engine_150_ticks_spatial_invariants`: update assertions from `4` to `8` (`assert len(engine.agents) == 8`, `assert len(set(initial_positions.values())) == 8`, `assert len(payload.agents) == 8`) while keeping zero wall-clipping, zero overlap, movement, and `>= 2` visited locations assertions across all 8 agents.
       - Verify `test_engine_contested_destination_routes_adjacent_without_overlap` continues passing cleanly with all 8 agents.
       - Add `test_engine_persists_agents_memories_and_sim_state`: create `:memory:` `Database`, `EmbeddingService.from_mode("mock")`, `MemoryStore`, `MemoryRetriever`, and `LLMGateway(provider=MockProvider())` attached to `SimulationEngine`, run `initialize_persistence()` and 5 ticks (`step_once()`), and verify SQLite contains 8 `AgentRecord`s, seeded `MemoryRecord`s (`>= 16`, each with `1536`-byte embedding blob), `SimStateRecord(tick=5)`, and working `retriever.retrieve(agent_id="maya", query="baking bread", current_tick=5)` returning relevant Maya memories!
    2. Update `backend/tests/test_api_ws.py`:
       - Pass isolated `database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test_api.db').as_posix()}"` to `Settings(...)` so tests never pollute repo files (`tmp_path` fixture on both test functions).
       - Update agent count assertions from `4` to `8` and sprite indices to `set(range(8))` (`{0..7}`).
       - Assert after `TestClient(app)` startup and ticks that `app.state.db`, `app.state.memory_store`, `app.state.memory_retriever`, and `app.state.llm_gateway` are populated, SQLite `agents` has 8 rows, and `sim_state` reflects advanced ticks.
    3. Update `scripts/verify_phase1_ws.py`:
       - Update lines 112-115 and 137-138 to expect `8` seeded agents (`len(agents_data) != 8` and `len(agents) != 8`).
       - Use a `tempfile.TemporaryDirectory()` for `env["DATABASE_URL"]` inside `main()` so running `verify_phase1_ws.py` leaves zero leftover `.db` files in the repository.
    4. Execute the entire verification suite (backend `pytest -v`, `ruff`, `mypy`, frontend `typecheck` & `build`, and `scripts/verify_phase1_ws.py`).

    AVOID: Writing test SQLite files to `backend/ai_village.db` during `pytest` or leaving any `Database` un-disposed.
    USE: `tmp_path` in `test_api_ws.py`, `:memory:` in `test_engine.py`, and `TemporaryDirectory()` in `scripts/verify_phase1_ws.py`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\pytest.exe -v
    .venv\Scripts\ruff.exe check .
    .venv\Scripts\mypy.exe app sim api agents memory llm tests
    Run from repo root (separate commands):
    backend\.venv\Scripts\ruff.exe check --config backend\pyproject.toml scripts\verify_phase1_ws.py
    backend\.venv\Scripts\mypy.exe --config-file backend\pyproject.toml scripts\verify_phase1_ws.py
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
    backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py
  </verify>
  <done>
    Full backend `pytest` suite passes offline in <5s with 0 failures, `ruff` and strict `mypy` pass with 0 issues across all packages and scripts, frontend builds cleanly, and live `/ws` verification passes with 8 moving agents (`e2e_ws_ok`).
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] 8 seeded `AgentPersona` villagers route cleanly across the map with zero wall collisions and zero tile overlaps over 150 ticks
- [ ] FastAPI `lifespan` initializes all 7 SQLite tables, seeds agents + initial memories + `sim_state`, attaches `MemoryStore`, `MemoryRetriever`, `EmbeddingService`, and `LLMGateway` to `app.state`, and disposes cleanly
- [ ] All backend unit/integration tests pass offline in <5s alongside clean `ruff`, `mypy`, frontend build, and `/ws` e2e check

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero regressions in existing tests or frontend rendering
