---
phase: 2
plan: 1
wave: 1
depends_on: []
files_modified:
  - backend/pyproject.toml
  - .env.example
  - backend/app/config.py
  - backend/app/db.py
  - backend/memory/__init__.py
  - backend/memory/models.py
  - backend/tests/test_config.py
  - backend/tests/test_db.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "Phase 2 dependencies (`sqlmodel`, `aiosqlite`, `sqlalchemy[asyncio]`, `numpy`, `sentence-transformers` with CPU-only `torch`, `google-genai`) install and import cleanly without CUDA bloat"
    - "Extended `Settings` resolves `database_url`, `embedding_provider`, `gemini_*`, daily LLM budget caps, and retrieval weights while keeping all Phase 1 defaults intact"
    - "Async `Database` initializes all 7 PRD SQLite tables (`agents`, `memories`, `relationships`, `events`, `conversations`, `llm_calls`, `sim_state`), enforces WAL on file DBs and StaticPool on `:memory:`, and disposes cleanly"
  artifacts:
    - "backend/pyproject.toml declares Phase 2 dependencies, expands `packages.find` for `agents*`, `memory*`, `llm*`, and configures `sentence_transformers.*` mypy override"
    - ".env.example documents safe non-secret defaults for database, embeddings, Gemini models, LLM budgets, and retrieval weights"
    - "backend/app/config.py extends `Settings` with `resolved_database_url()` and `resolved_embedding_provider()`"
    - "backend/app/db.py defines `Database` with `init_models()`, `session()`, and `dispose()`"
    - "backend/memory/models.py defines all 7 `SQLModel` table classes matching PRD Section 8"
    - "backend/tests/test_db.py verifies all 7 tables, CRUD roundtrips, composite keys, binary `LargeBinary` embeddings, singleton `sim_state`, WAL pragmas, and disposal"
  key_links:
    - "backend/app/db.py imports `memory.models` during `init_models()` so `SQLModel.metadata.create_all` always creates all 7 tables"
    - "backend/memory/models.py links `memories.agent_id` and `relationships.agent_a`/`agent_b` via foreign keys to `agents.id`"
---

# Plan 2.1: Phase 2 Dependencies, Extended Config & Async SQLite Schema (7 Tables)

## Objective
Install the CPU-only Phase 2 Python dependencies (`sqlmodel`, `aiosqlite`, `sqlalchemy[asyncio]`, `numpy`, `sentence-transformers`, `google-genai`), extend `backend/app/config.py` and `.env.example`, implement the async `Database` wrapper in `backend/app/db.py`, and define all 7 PRD SQLite tables (`agents`, `memories`, `relationships`, `events`, `conversations`, `llm_calls`, `sim_state`) in `backend/memory/models.py` with comprehensive `:memory:` and WAL file DB unit tests.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/REQUIREMENTS.md
- .gsd/phases/2/RESEARCH.md
- backend/pyproject.toml
- backend/app/config.py
- .env.example

## Tasks

<task type="auto">
  <name>Update pyproject.toml, install CPU-only dependencies, and extend Settings</name>
  <files>
    backend/pyproject.toml
    .env.example
    backend/app/config.py
    backend/tests/test_config.py
  </files>
  <action>
    Update packaging metadata, install Phase 2 dependencies without CUDA bloat, document non-secret defaults in `.env.example`, and extend `Settings`.

    Steps:
    1. Edit `backend/pyproject.toml`:
       - Add runtime dependencies:
         - `"sqlmodel>=0.0.22"`
         - `"aiosqlite>=0.20.0"`
         - `"sqlalchemy[asyncio]>=2.0.36"`
         - `"numpy>=2.1.0"`
         - `"sentence-transformers>=3.2.0"`
         - `"google-genai>=1.0.0"`
       - Update `[tool.setuptools.packages.find]` `include` to `["app*", "sim*", "api*", "agents*", "memory*", "llm*"]`.
       - Add a second `[[tool.mypy.overrides]]` block:
         `module = ["sentence_transformers.*"]`
         `ignore_missing_imports = true`
    2. Install into `backend/.venv` using the CPU-only PyTorch wheel index (from repo root, one command per invocation):
       `backend\.venv\Scripts\python.exe -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -e "backend[dev]"`
    3. Update `.env.example` (no real secrets!) adding:
       - `DATABASE_URL=`
       - `EMBEDDING_PROVIDER=auto`
       - `GEMINI_ROUTINE_MODEL=gemini-2.5-flash`
       - `GEMINI_PLANNING_MODEL=gemini-2.5-pro`
       - `LLM_DAILY_BUDGET_USD=0.50`
       - `LLM_DAILY_TOKEN_LIMIT=250000`
       - `LLM_MAX_RETRIES=1`
       - `RETRIEVAL_W_RECENCY=1.0`
       - `RETRIEVAL_W_IMPORTANCE=1.0`
       - `RETRIEVAL_W_RELEVANCE=1.0`
       - `RETRIEVAL_DECAY_PER_HOUR=0.995`
       - `RETRIEVAL_TOP_K=8`
    4. Extend `Settings` in `backend/app/config.py` (preserving ALL existing fields/defaults and adding `DEFAULT_DB_PATH: Path = REPO_ROOT / "backend" / "ai_village.db"`):
       - `database_url: str = ""`
       - `embedding_provider: str = "auto"`
       - `gemini_api_key: str = ""`
       - `gemini_routine_model: str = "gemini-2.5-flash"`
       - `gemini_planning_model: str = "gemini-2.5-pro"`
       - `llm_daily_budget_usd: float = 0.50`
       - `llm_daily_token_limit: int = 250_000`
       - `llm_max_retries: int = 1`
       - `retrieval_w_recency: float = 1.0`
       - `retrieval_w_importance: float = 1.0`
       - `retrieval_w_relevance: float = 1.0`
       - `retrieval_decay_per_hour: float = 0.995`
       - `retrieval_top_k: int = 8`
       - Add `resolved_database_url(self) -> str`: returns `self.database_url.strip()` if non-empty, else `f"sqlite+aiosqlite:///{DEFAULT_DB_PATH.as_posix()}"`.
       - Add `resolved_embedding_provider(self) -> Literal["mock", "local"]`: normalizes `self.embedding_provider.strip().lower()`. If `"auto"`, returns `"mock"` when `self.llm_provider.strip().lower() == "mock"` else `"local"`. If `"mock"` or `"local"`, returns it; otherwise raises `ValueError`.
    5. Extend `backend/tests/test_config.py` (keeping all existing tests intact) to test the new defaults, `resolved_database_url()` default + override, `resolved_embedding_provider()` for `"auto"` (`llm_provider="mock"` vs `"gemini"`), explicit `"local"`, and invalid provider raising `ValueError`.

    AVOID: Plain `pip install` without `--extra-index-url https://download.pytorch.org/whl/cpu` (which can pull large CUDA wheels on Linux/CI) or breaking any Phase 1 default in `Settings`.
    USE: `DEFAULT_DB_PATH` under `REPO_ROOT / "backend"` so running from either repo root or `backend/` resolves the same SQLite path when `DATABASE_URL` is blank.
  </action>
  <verify>
    Run from repo root (separate commands, never chain with `&&`):
    backend\.venv\Scripts\python.exe -c "import sqlmodel, aiosqlite, sqlalchemy, numpy, google.genai, torch; print('deps_ok', torch.__version__)"
    Run in backend/ (Cwd: backend):
    .venv\Scripts\pytest.exe -v tests/test_config.py
    .venv\Scripts\ruff.exe check app/config.py tests/test_config.py
    .venv\Scripts\mypy.exe app/config.py tests/test_config.py
  </verify>
  <done>
    All Phase 2 packages import cleanly (`deps_ok` printed with CPU torch), `tests/test_config.py` passes with 0 failures, and `ruff` + strict `mypy` exit 0.
  </done>
</task>

<task type="auto">
  <name>Implement async Database wrapper and all 7 SQLModel table schemas</name>
  <files>
    backend/app/db.py
    backend/memory/__init__.py
    backend/memory/models.py
  </files>
  <action>
    Create the async SQLAlchemy/SQLModel `Database` manager and define all 7 PRD tables with strict `mypy` annotations.

    Steps:
    1. Create `backend/memory/__init__.py` as a minimal package marker (`"""Memory stream models, embeddings, storage, and weighted retrieval."""`).
    2. Implement `backend/memory/models.py` defining all 7 `SQLModel` (`table=True`) models matching PRD Section 8 (`__tablename__: ClassVar[str] = "..."` on every model for `mypy --strict`):
       - `AgentRecord` (`__tablename__ = "agents"`): `id: str = Field(primary_key=True)`, `name: str`, `persona_json: str`, `home_location: str`, `x: int`, `y: int`, `current_action: str = "Idle"`, `current_plan_json: str = "[]"`.
       - `MemoryRecord` (`__tablename__ = "memories"`): `id: int | None = Field(default=None, primary_key=True)`, `agent_id: str = Field(index=True, foreign_key="agents.id")`, `type: str = Field(index=True)`, `text: str`, `importance: int = Field(ge=1, le=10)`, `created_tick: int = Field(index=True)`, `last_access_tick: int`, `embedding: bytes = Field(sa_column=Column(LargeBinary, nullable=False))`, `metadata_json: str = "{}"`.
       - `RelationshipRecord` (`__tablename__ = "relationships"`): `agent_a: str = Field(primary_key=True, foreign_key="agents.id")`, `agent_b: str = Field(primary_key=True, foreign_key="agents.id")`, `affinity: float = 0.0`, `notes: str = ""`, `last_interaction_tick: int = 0`.
       - `EventRecord` (`__tablename__ = "events"`): `id: int | None = Field(default=None, primary_key=True)`, `tick: int = Field(index=True)`, `kind: str`, `text: str`, `location: str | None = Field(default=None)`, `source: str`.
       - `ConversationRecord` (`__tablename__ = "conversations"`): `id: int | None = Field(default=None, primary_key=True)`, `tick_start: int = Field(index=True)`, `participants: str`, `transcript_json: str`, `summary: str`.
       - `LLMCallRecord` (`__tablename__ = "llm_calls"`): `id: int | None = Field(default=None, primary_key=True)`, `tick: int = Field(index=True)`, `agent_id: str | None = Field(default=None, index=True)`, `purpose: str = Field(index=True)`, `model: str`, `tokens_in: int = 0`, `tokens_out: int = 0`, `latency_ms: float = 0.0`, `cost_est: float = 0.0`, `cache_hit: bool = False`.
       - `SimStateRecord` (`__tablename__ = "sim_state"`): `id: int = Field(default=1, primary_key=True)`, `tick: int = 0`, `sim_time: str = "Day 1 06:00"`, `speed: int = 1`, `seed: int = 42`.
    3. Implement `backend/app/db.py` with `Database`:
       - `__init__(self, database_url: str, *, echo: bool = False) -> None`:
         - Detects `self._is_memory = ":memory:" in database_url`.
         - Configures `StaticPool` and `connect_args={"check_same_thread": False}` when `self._is_memory` is True.
         - Creates `self.engine: AsyncEngine = create_async_engine(...)`.
         - For SQLite URLs (`database_url.startswith("sqlite")`), registers a `@event.listens_for(self.engine.sync_engine, "connect")` listener that executes `PRAGMA foreign_keys=ON;` on all SQLite connections, and additionally executes `PRAGMA journal_mode=WAL;`, `PRAGMA synchronous=NORMAL;`, `PRAGMA busy_timeout=5000;` when `not self._is_memory`.
         - Creates `self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)`.
         - Initializes `self._memory_lock = asyncio.Lock()` used inside `session()` only when `self._is_memory` is True so concurrent async tasks never collide on `:memory:` `StaticPool`'s single connection.
       - `async def init_models(self) -> None`: imports `memory.models` (ensuring metadata registration) and runs `await conn.run_sync(SQLModel.metadata.create_all)`. For file-backed SQLite URLs (`not self._is_memory`), reads `db_path = self.engine.url.database` and, when non-empty, calls `Path(db_path).parent.mkdir(parents=True, exist_ok=True)` before connecting.
       - `@asynccontextmanager async def session(self) -> AsyncIterator[AsyncSession]`: yields a session from `self._session_factory()` (acquiring `self._memory_lock` when `self._is_memory`).
       - `async def dispose(self) -> None`: calls `await self.engine.dispose()`.

    AVOID: Passing `nullable=False` or `default=...` inside `Field(...)` alongside `sa_column=Column(LargeBinary, nullable=False)` (SQLModel raises `RuntimeError` if `sa_column` is combined with other `Field` column kwargs) or omitting `expire_on_commit=False` (causes `MissingGreenlet` after commit).
    USE: `ClassVar[str]` for `__tablename__` and `sqlmodel.ext.asyncio.session.AsyncSession` for typed `.exec(select(...))` compatibility under `mypy --strict`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\ruff.exe check app/db.py memory/__init__.py memory/models.py
    .venv\Scripts\mypy.exe app/db.py memory/__init__.py memory/models.py
  </verify>
  <done>
    `backend/app/db.py` and `backend/memory/models.py` define `Database` and all 7 `SQLModel` tables and pass `ruff check` and strict `mypy` with zero errors.
  </done>
</task>

<task type="auto">
  <name>Write offline unit tests for all 7 SQLite tables, WAL mode, and async Database lifecycle</name>
  <files>
    backend/tests/test_db.py
  </files>
  <action>
    Create `backend/tests/test_db.py` testing schema creation, CRUD roundtrips, relational constraints, binary embeddings, and clean engine disposal.

    Steps:
    1. Provide an async fixture creating an `:memory:` `Database`, calling `await db.init_models()`, yielding `db`, and always calling `await db.dispose()` in `finally:`.
    2. Assert `sqlite_master` contains all 7 tables: `{"agents", "memories", "relationships", "events", "conversations", "llm_calls", "sim_state"}`.
    3. Test full async CRUD roundtrips for all 7 tables:
       - `AgentRecord`: insert, query via `session.get(AgentRecord, "maya")`, update `x`/`y`/`current_action`, verify persistence.
       - `MemoryRecord`: insert with a `1,536`-byte `np.float32` vector blob (`np.arange(384, dtype=np.float32).tobytes()`), reload, unpack via `np.frombuffer(..., dtype=np.float32)`, assert exact shape `(384,)` and byte equality.
       - `RelationshipRecord`: insert composite key `("maya", "liam")` with `affinity=0.45`, verify querying by composite PK, and verify duplicate composite PK raises `IntegrityError` (and foreign key violation raises `IntegrityError`).
       - `EventRecord`, `ConversationRecord`, `LLMCallRecord`: insert and query via `select(...)` + `col(...)` ordering.
       - `SimStateRecord`: insert singleton `id=1`, update `tick` and `sim_time` in-place, assert only 1 row exists in `sim_state`.
    4. Add a file-backed `tmp_path` SQLite test confirming `PRAGMA journal_mode;` returns `"wal"`, data persists across `Database.dispose()` and reopen on the same file path, and the reopened `Database` also disposes cleanly.

    AVOID: Leaving any `Database` engine undisposed (which causes `aiosqlite` threads to hang `pytest` on exit).
    USE: `try ... finally: await db.dispose()` in fixtures and file-backed tests.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\pytest.exe -v tests/test_db.py tests/test_config.py
    .venv\Scripts\ruff.exe check .
    .venv\Scripts\mypy.exe app sim api memory tests
  </verify>
  <done>
    All tests in `tests/test_db.py` and `tests/test_config.py` pass offline in <2s with clean exit, and `ruff` + strict `mypy` exit 0 across all modules.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] CPU-only Phase 2 dependencies installed in `backend/.venv` and declared in `backend/pyproject.toml`
- [ ] All 7 PRD tables (`agents`, `memories`, `relationships`, `events`, `conversations`, `llm_calls`, `sim_state`) implemented in `backend/memory/models.py` and verified by `backend/tests/test_db.py`
- [ ] Extended `Settings` in `backend/app/config.py` and `.env.example` pass all unit checks without regressions

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in existing Phase 1 tests (`pytest -v` in `backend/` passes)
