---
phase: 2
researched_at: 2026-11-24
discovery_level: 2
---

# Phase 2 Research: Memory Stream, Embeddings, Retrieval Scoring & LLM Gateway

## Objective
Answer the four Phase 2 technical integration questions:
1. Exact Phase 1 files, config settings, agent models/dataclasses, spritesheet constraints, test assertions, and named Tiled locations that Phase 2's SQLite persistence and 6–10 personas must integrate with.
2. Exact Python packages/versions in `backend/pyproject.toml` and new dependencies (`sqlmodel`, `aiosqlite`, `sqlalchemy`, `numpy`, `sentence-transformers`, `google-genai`) required on Windows (Python 3.12+ / local `.venv` Python 3.13) without CUDA bloat or `mypy --strict` regressions.
3. Cleanest async `SQLModel` + `aiosqlite` session pattern (`AsyncEngine` / `AsyncSession`) and binary `float32` embedding storage (`bytes` / `np.float32.tobytes()`) across all 7 PRD tables (`agents`, `memories`, `relationships`, `events`, `conversations`, `llm_calls`, `sim_state`).
4. Exact structure for `GeminiProvider` (`google-genai` async structured JSON output) and `EmbeddingService` (`all-MiniLM-L6-v2` lazy load + deterministic lexical hash embedding provider) so offline unit tests execute in `<2s` with zero network calls and pass `mypy --strict` and `ruff`.

## Discovery Level
**Level 2** — Standard research (codebase contract mapping, dry-run Windows dependency verification, async ORM + `mypy --strict` pattern validation, and `google-genai` / `sentence-transformers` interface design).

---

## Key Decisions

### Decision 1: 8 Seeded Personas Sharing Existing Homes + Expanded 8-Row Spritesheet
**Question:** How should Phase 2 expand from 4 to 6–10 agent personas without breaking the validated Tiled map, A* reachability tests, or Phaser sprite rendering?
**Options Considered:**
1. **Add 4–6 new `Home_*` buildings to `map.json`**: Gives every villager a private building, but alters `40x30` collision layout and breaks `backend/tests/test_world.py:41` (`assert len(world.list_locations()) == 10`) and `backend/tests/test_api_ws.py:10-21,44`.
2. **Seed 8 rich personas across existing 10 locations (household pairs in `Home_*` or shop residences) + expand `sprites.png` to 8 rows (`128x256`)**: Preserves `map.json` and all world tests untouched, leverages existing BFS spawn fallback (`backend/sim/engine.py:124-129`), and gives all 8 villagers distinct sprite palettes.
3. **Seed 8 personas but modulo `sprite_index % 4`**: Avoids touching `sprites.png`, but duplicates sprite colors across villagers.

**Decision:** **Option 2** — Seed 8 rich personas (midpoint of `6–10` in `REQ-03`, `.gsd/REQUIREMENTS.md:20`) mapped onto valid existing named locations (`Home_Maya`, `Home_Liam`, `Home_Elena`, `Home_Noah`, `Bakery`, `Cafe`, `Library`, `Market`), update `SPRITE_ROWS = 8` + 4 new palettes in `scripts/generate_village_map.py:50,500-509` to regenerate `frontend/public/assets/sprites.png` (`128x256`, 32 frames), add defensive frame clamping in `frontend/src/scenes/VillageScene.ts:185`, and update hardcoded `== 4` agent count assertions in `backend/tests/test_api_ws.py:32,49-50,60` and `backend/tests/test_engine.py:51,55,63`.
**Confidence:** High

### Decision 2: CPU-Only PyTorch Wheel Index for `sentence-transformers` + Targeted Mypy Override
**Question:** How should Phase 2 dependencies be declared in `backend/pyproject.toml` and installed on Windows & CI without multi-GB CUDA bloat or `mypy --strict` failures?
**Options Considered:**
1. **Plain `pip install -e ".[dev]"` from PyPI only**: Works on Windows x64 (where default PyPI `torch` wheel is CPU-only), but downloads ~2.5 GB of `nvidia-cuda-*` / `nvidia-cudnn-*` wheels on Linux Docker/GitHub Actions CI.
2. **Keep standard PEP 621 dependencies in `pyproject.toml` and install with `--extra-index-url https://download.pytorch.org/whl/cpu` (or pre-install `torch` from `https://download.pytorch.org/whl/cpu`)**: Selects `torch+cpu` (`~180 MB`, zero `nvidia-*` packages) across both Windows and Linux CI while keeping `pyproject.toml` compliant with standard `setuptools` / `pip` / `uv`.
3. **Replace `sentence-transformers` with `fastembed` / `onnxruntime` only**: Deviates from explicit PRD stack requirement (`AI Village Product Requirements Document.md:144`: `sentence-transformers (all-MiniLM-L6-v2), local`).

**Decision:** **Option 2** — Declare `sqlmodel>=0.0.22`, `aiosqlite>=0.20.0`, `sqlalchemy[asyncio]>=2.0.36`, `numpy>=2.1.0`, `sentence-transformers>=3.2.0`, and `google-genai>=1.0.0` in `backend/pyproject.toml:10-16`, expand `[tool.setuptools.packages.find]` `include` (`backend/pyproject.toml:29`) to include `agents*`, `memory*`, `llm*`, add `[[tool.mypy.overrides]]` for `sentence_transformers.*` (`ignore_missing_imports = true`), and install `torch` via `https://download.pytorch.org/whl/cpu`.
**Confidence:** High

### Decision 3: Per-App `Database` Wrapper (`async_sessionmaker[AsyncSession]`, `expire_on_commit=False`, Explicit `dispose()`) + Raw `float32` `LargeBinary` Blobs
**Question:** How should async SQLite sessions and 384-d embeddings be structured across the 7 PRD tables?
**Options Considered:**
1. **Module-level global `AsyncEngine` + JSON-encoded float arrays in `TEXT`**: Global engines leak `aiosqlite` worker threads across `TestClient` tests and hang `pytest`; JSON text embeddings are ~5x larger and ~20x slower to parse than `np.frombuffer`.
2. **Instance-scoped `Database` object on `app.state.db` (`async_sessionmaker` with `sqlmodel.ext.asyncio.session.AsyncSession`, `expire_on_commit=False`, WAL pragmas, `StaticPool` for `:memory:`, `await db.dispose()` in FastAPI `lifespan`) + `LargeBinary` `bytes` via `np.float32.tobytes()` / `np.frombuffer(..., dtype=np.float32)`**: Zero `MissingGreenlet` errors, zero hanging `aiosqlite` threads, strict mypy compliance, and `1,536`-byte fixed-width blobs (`384 * 4` bytes) enabling sub-millisecond vectorized matrix dot-products.

**Decision:** **Option 2**.
**Confidence:** High

### Decision 4: Protocol-Driven `LLMProvider` & Lazy `EmbeddingService` with Signed N-Gram Feature Hashing in Mock Mode
**Question:** How do we guarantee `<2s` offline unit test execution while supporting real `google-genai` structured outputs and `all-MiniLM-L6-v2` embeddings?
**Options Considered:**
1. **Import `SentenceTransformer` and `genai.Client()` at module import time and mock via `unittest.mock.patch`**: Still pays ~3–5s `torch`/`transformers` import penalty on every pytest run and risks accidental network calls if a patch is missed.
2. **Protocol boundaries (`LLMProvider`, `EmbeddingProvider`) + lazy `import sentence_transformers` inside `SentenceTransformerEmbeddingProvider._get_model()` + `DeterministicEmbeddingProvider` using signed BLAKE2b token/bigram hashing into L2-normalized `float32[384]`**: Zero `torch` import during mock/unit tests (`<0.2s` test startup), identical `(384,)` `float32` shape (`1,536` bytes), and lexical cosine similarity preserved offline so retrieval ranking tests verify real semantic separation without a neural model load.

**Decision:** **Option 2**.
**Confidence:** High

---

## Findings

### 1. Phase 1 Codebase Integration Surface (`backend/`, `frontend/`, `scripts/`)

#### Existing Backend Files & Symbols
- **`backend/pyproject.toml:27-29`**: `[tool.setuptools.packages.find]` currently has `include = ["app*", "sim*", "api*"]`. New Phase 2 packages (`agents/`, `memory/`, `llm/`, per `.gsd/ARCHITECTURE.md:45-47` and `AI Village Product Requirements Document.md:209-211`) **must** be added to `include`.
- **`backend/app/config.py:9-39`**: `Settings(BaseSettings)` loads `.env` from `REPO_ROOT / ".env"` (`app/config.py:5,12-16`) with `extra="ignore"`. Existing fields (`app/config.py:18-25`):
  - `app_env: str = "development"`
  - `sim_tick_seconds: float = 1.0`
  - `sim_speed: int = 1`
  - `sim_seed: int = 42`
  - `sim_auto_start: bool = True`
  - `map_path: str = ""`
  - `cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"`
  - `llm_provider: str = "mock"`
  - Note: `.env.example:9` already lists `GEMINI_API_KEY=your_gemini_api_key_here`, which `Settings` currently ignores. Phase 2 should extend `Settings` with `database_url`, `embedding_provider` (`"mock"` when `llm_provider == "mock"` or explicit `"mock" | "local"`), `gemini_api_key`, `gemini_routine_model`, `gemini_planning_model`, `llm_daily_budget_usd`, `llm_daily_token_limit`, and retrieval weights (`retrieval_w_recency`, `retrieval_w_importance`, `retrieval_w_relevance`, `retrieval_top_k = 8`), while keeping all existing defaults intact (`backend/tests/test_config.py:8-19`).
- **`backend/app/main.py:19-65`**: `create_app(settings)` wires `world`, `clock`, `engine`, and `ws_manager` inside `lifespan(app)` (`app/main.py:24-54`) and attaches them to `app.state` (`app/main.py:42-46`). Phase 2 should initialize `db` (`await db.init_models()`), seed/load `agents` and `sim_state`, attach `app.state.db`, `app.state.memory_store`, `app.state.embedding_service`, and `app.state.llm_gateway`, and call `await db.dispose()` inside the `finally:` block (`app/main.py:52-54`).
- **`backend/sim/clock.py:12-94`**: `SimClock` (`tick: int = 0`, `start_minute_of_day: int = 360` = `Day 1 06:00`, `speed: int = 1`, `VALID_SPEEDS = (1, 4, 16)`, `sim_time_str` property at `sim/clock.py:66-68`). Maps directly to `sim_state` (`tick`, `sim_time`, `speed`, `seed`).
- **`backend/sim/engine.py:21-150`**:
  - `_SEEDED_AGENT_SPECS` (`sim/engine.py:21-54`): currently hardcodes 4 tuples (`maya`, `liam`, `elena`, `noah`).
  - `AgentSnapshot(BaseModel)` (`sim/engine.py:57-68`): wire contract (`id: str`, `name: str`, `role: str`, `sprite_index: int`, `x: int`, `y: int`, `target_location: str | None`, `current_action: str`). Validated strictly on the frontend by `isAgentSnapshot` (`frontend/src/types/sim.ts:60-77`); do **not** rename or remove any of these 8 fields.
  - `AgentEntity` (`sim/engine.py:82-114`): mutable runtime state (`id`, `name`, `role`, `sprite_index`, `home_location`, `x`, `y`, `target_location`, `path`, `current_action`, `dwell_ticks_remaining`, `stall_ticks`, `routine`, `routine_index`, `visited_locations`).
  - `_create_initial_agents(world)` (`sim/engine.py:116-150`): already supports multiple agents sharing the same `home_location` by falling back to `world.find_free_adjacent(anchor[0], anchor[1], occupied, max_radius=5)` (`sim/engine.py:124-129`) when a home anchor tile is already occupied.
- **`backend/api/rest.py:44-74` & `backend/api/ws.py:38-52`**: `GET /health` returns `agents=len(engine.agents)` (`api/rest.py:52`), `GET /world` returns `world.list_locations()` (`api/rest.py:66`), `GET /agents` returns `engine.build_tick_payload().agents` (`api/rest.py:74`), and `WS /ws` broadcasts `TickPayload.model_dump()` (`app/main.py:38`, `api/ws.py:46`).

#### Named Locations in `frontend/public/assets/map.json`
Parsed by `WorldMap.from_tiled_json` (`backend/sim/world.py:93-218`) into `NamedLocation` (`sim/world.py:17-35`):

| # | Exact `name` | `category` | `anchor` `(x, y)` | `map.json` Lines |
|---|--------------|------------|-------------------|------------------|
| 1 | `Cafe` | `cafe` | `(16, 6)` | `frontend/public/assets/map.json:3651-3677` |
| 2 | `Park` | `park` | `(19, 23)` | `frontend/public/assets/map.json:3679-3705` |
| 3 | `Market` | `market` | `(34, 15)` | `frontend/public/assets/map.json:3707-3733` |
| 4 | `Town Square` | `plaza` | `(19, 14)` | `frontend/public/assets/map.json:3735-3761` |
| 5 | `Bakery` | `bakery` | `(24, 6)` | `frontend/public/assets/map.json:3763-3789` |
| 6 | `Library` | `library` | `(5, 15)` | `frontend/public/assets/map.json:3791-3817` |
| 7 | `Home_Maya` | `home` | `(5, 6)` | `frontend/public/assets/map.json:3819-3845` |
| 8 | `Home_Liam` | `home` | `(34, 6)` | `frontend/public/assets/map.json:3847-3873` |
| 9 | `Home_Elena` | `home` | `(5, 24)` | `frontend/public/assets/map.json:3875-3901` |
| 10 | `Home_Noah` | `home` | `(34, 24)` | `frontend/public/assets/map.json:3903-3929` |

#### Spritesheet & Test Couplings to Address When Scaling to 6–10 Agents
1. **Spritesheet bounds**: `frontend/public/assets/sprites.png` is `128x128` (`4 cols x 4 rows = 16 frames`, `scripts/generate_village_map.py:49-52,497-522`). `frontend/src/scenes/VillageScene.ts:185` computes `const baseFrame = Math.max(0, agent.sprite_index) * FRAMES_PER_AGENT;` with no upper-bound modulo. For 8 agents (`sprite_index` `0..7`), update `SPRITE_ROWS = 8` (or `10`) and `palettes` in `scripts/generate_village_map.py:50,500-509`, re-run `scripts/generate_village_map.py` to regenerate `sprites.png`, and optionally wrap `sprite_index` by available rows in `VillageScene.ts:185`.
2. **Hardcoded 4-agent assertions in Phase 1 tests**:
   - `backend/tests/test_api_ws.py:32,49,50,60` asserts `health_data["agents"] == 4`, `len(agents_data) == 4`, `sprite_index == {0, 1, 2, 3}`, and `len(initial_msg["agents"]) == 4`.
   - `backend/tests/test_engine.py:51,55,63` asserts `len(engine.agents) == 4` and `len(payload.agents) == 4`.
   - Updating default seeded personas to 8 requires updating those assertions to `8` (and `{0..7}`) while keeping `SimulationEngine(..., personas=...)` injectable.

---

### 2. Python Dependencies, Windows CPU-Only Resolution & `mypy --strict`

#### Current `backend/pyproject.toml` (`backend/pyproject.toml:9-25`) & Local `.venv`
- `requires-python = ">=3.12"` (`backend/pyproject.toml:9`). Local `backend/.venv/Scripts/python.exe` runs **Python 3.13.13 (MSC v.1942 64-bit AMD64)** (`pip 26.0.1`, `mypy 2.4.1`, `ruff 0.17.6`, `pytest 9.2.0`, `pytest-asyncio 1.5.0`, `fastapi 0.165.0`, `pydantic 2.14.4`, `pydantic-settings 2.16.3`, `uvicorn 0.54.0`, `websockets 17.4`, `httpx 0.28.1`). `uv` is not on host `PATH` (`.gsd/phases/1/3-SUMMARY.md:21`), so commands run via `backend\.venv\Scripts\python.exe`.

#### Empirically Verified Phase 2 Package Additions
Dry-run resolution (`backend\.venv\Scripts\python.exe -m pip install --dry-run --extra-index-url https://download.pytorch.org/whl/cpu ...`) succeeded cleanly with prebuilt `win_amd64` / `py3-none-any` wheels and **zero `nvidia-*` CUDA dependencies**:

| Package Spec for `pyproject.toml` | Resolved Wheel (Win AMD64) | Typing (`mypy --strict`) |
|-----------------------------------|----------------------------|--------------------------|
| `sqlmodel>=0.0.22` | `sqlmodel-0.0.50-py3-none-any.whl` | Ships `py.typed` (see patterns below) |
| `aiosqlite>=0.20.0` | `aiosqlite-0.22.1-py3-none-any.whl` | Ships `py.typed` |
| `sqlalchemy[asyncio]>=2.0.36` | `sqlalchemy-2.1.9` + `greenlet-3.5.6` (`win_amd64`) | Ships PEP 561 types |
| `numpy>=2.1.0` | `numpy-2.5.5` (`win_amd64`) | Ships `numpy.typing` (`NDArray[np.float32]`) |
| `sentence-transformers>=3.2.0` | `sentence_transformers-6.3.0` + `torch-2.15.0+cpu` | Add `[[tool.mypy.overrides]]` for `sentence_transformers.*` |
| `google-genai>=1.0.0` | `google_genai-3.6.1-py3-none-any.whl` | Ships `py.typed` (`google.genai.types`) |

**Install command without CUDA bloat (PowerShell, single command per invocation):**
```powershell
& "backend\.venv\Scripts\python.exe" -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -e "backend[dev]"
```

**`mypy` config addition (`backend/pyproject.toml:48-55`):**
```toml
[[tool.mypy.overrides]]
module = ["sentence_transformers.*"]
ignore_missing_imports = true
```
*(Avoid adding `sqlmodel.mypy` plugin unless required; standard `SQLModel` annotations with `ClassVar[str]` and `sqlmodel.col()` pass `mypy 2.x --strict` cleanly without plugin version-skew fragility.)*

---

### 3. Async `SQLModel` + `aiosqlite` & Binary `float32` Schema Pattern (7 PRD Tables)

#### Clean `Database` & Session Factory (`backend/app/db.py`)
```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


class Database:
    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        is_memory = ":memory:" in database_url
        kwargs: dict[str, object] = {"echo": echo}
        if is_memory:
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = StaticPool

        self.engine: AsyncEngine = create_async_engine(database_url, **kwargs)  # type: ignore[arg-type]
        if not is_memory and database_url.startswith("sqlite"):
            @event.listens_for(self.engine.sync_engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn: object, _record: object) -> None:
                cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=5000;")
                cursor.close()

        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_models(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
```

#### Exact Mapping of All 7 PRD Tables (`AI Village Product Requirements Document.md:160-169`)
Declare `__tablename__: ClassVar[str] = "..."` on every table class so `mypy --strict` does not flag `Incompatible types in assignment`:

1. **`agents`** (`AgentRecord`): `id: str` (PK), `name: str`, `persona_json: str`, `home_location: str`, `x: int`, `y: int`, `current_action: str = "Idle"`, `current_plan_json: str = "[]"`.
2. **`memories`** (`MemoryRecord`): `id: int | None = Field(default=None, primary_key=True)`, `agent_id: str = Field(index=True, foreign_key="agents.id")`, `type: str = Field(index=True)` (`observation | plan | reflection | conversation`), `text: str`, `importance: int = Field(ge=1, le=10)`, `created_tick: int = Field(index=True)`, `last_access_tick: int`, `embedding: bytes = Field(sa_column=Column(LargeBinary, nullable=False))`, plus optional `metadata_json: str = "{}"` (for cited memory IDs in Phase 4 reflections).
3. **`relationships`** (`RelationshipRecord`): composite PK `agent_a: str = Field(primary_key=True, foreign_key="agents.id")`, `agent_b: str = Field(primary_key=True, foreign_key="agents.id")`, `affinity: float = 0.0`, `notes: str = ""`, `last_interaction_tick: int = 0`.
4. **`events`** (`EventRecord`): `id: int | None = Field(default=None, primary_key=True)`, `tick: int = Field(index=True)`, `kind: str`, `text: str`, `location: str | None = None`, `source: str` (`god | agent`).
5. **`conversations`** (`ConversationRecord`): `id: int | None = Field(default=None, primary_key=True)`, `tick_start: int = Field(index=True)`, `participants: str` (JSON list of agent IDs), `transcript_json: str`, `summary: str`.
6. **`llm_calls`** (`LLMCallRecord`): `id: int | None = Field(default=None, primary_key=True)`, `tick: int = Field(index=True)`, `agent_id: str | None = Field(default=None, index=True)`, `purpose: str = Field(index=True)`, `model: str`, `tokens_in: int = 0`, `tokens_out: int = 0`, `latency_ms: float = 0.0`, `cost_est: float = 0.0`, `cache_hit: bool = False`.
7. **`sim_state`** (`SimStateRecord`): singleton row `id: int = Field(default=1, primary_key=True)` alongside PRD fields `tick: int = 0`, `sim_time: str = "Day 1 06:00"`, `speed: int = 1`, `seed: int = 42` (using fixed `id=1` PK lets `session.get(SimStateRecord, 1)` update `tick` in-place rather than inserting a new row per tick).

#### Binary Embedding Serialization & Retrieval Scoring (`REQ-04`, `REQ-05`)
- **Pack**: `np.asarray(vec, dtype=np.float32).reshape(-1).tobytes()` → `1,536` bytes for `EMBEDDING_DIM = 384`.
- **Unpack (single)**: `np.frombuffer(blob, dtype=np.float32).copy()`.
- **Unpack (batch matrix for cosine relevance)**: `matrix = np.vstack([np.frombuffer(m.embedding, dtype=np.float32) for m in memories])` (`shape (N, 384)`).
- **Weighted Retrieval Formula (`PRD 5.3`, `REQ-05`)**:
  - `hours_since_access = np.maximum(0.0, (current_tick - last_access_ticks) / 60.0)`
  - `recency_raw = np.power(0.995, hours_since_access)`
  - `importance_raw = importances / 10.0`
  - `relevance_raw = cosine_similarity_batch(matrix, query_vec)`
  - Min-max normalize each component across candidate memories with zero-range guard (`if max_v - min_v < 1e-9: return np.ones_like(arr)` — or preserve bounded `[0, 1]` value — so 1-memory or uniform-tick queries never divide by zero / emit `NaN`).
  - `score = w_r * recency_norm + w_i * importance_norm + w_v * relevance_norm`, sort descending (tie-break deterministically by `created_tick` desc, `id` desc), return top-$k$ ($k=8$), and update `last_access_tick = current_tick` on retrieved records.

---

### 4. `LLMGateway`, `GeminiProvider` & `EmbeddingService` for `<2s` Offline Tests

#### `LLMProvider` + `GeminiProvider` + `MockProvider` (`backend/llm/`)
- **Provider Contract (`backend/llm/providers/base.py`)**:
  Define a `ProviderResult` dataclass (`raw_text: str`, `model: str`, `tokens_in: int`, `tokens_out: int`) and `@runtime_checkable class LLMProvider(Protocol)` with:
  ```python
  async def generate_raw(
      self,
      *,
      prompt: str,
      response_model: type[BaseModel],
      system_instruction: str | None = None,
      model_override: str | None = None,
      temperature: float = 0.2,
      seed: int | None = None,
  ) -> ProviderResult: ...
  ```
- **`GeminiProvider` (`backend/llm/providers/gemini.py`)**:
  - Uses `from google import genai` and `from google.genai import types`.
  - Instantiates `genai.Client(api_key=api_key)` lazily or only when `GeminiProvider` is constructed (accepting an optional injected `client: Any | None = None` for `<10ms` offline unit tests of `GeminiProvider` itself).
  - Calls:
    ```python
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=response_model,
        temperature=temperature,
        seed=seed,
    )
    response = await client.aio.models.generate_content(
        model=target_model,
        contents=prompt,
        config=config,
    )
    usage = response.usage_metadata
    tokens_in = (usage.prompt_token_count or 0) if usage is not None else 0
    tokens_out = (usage.candidates_token_count or 0) if usage is not None else 0
    raw_text = response.text or ""
    ```
- **`LLMGateway` (`backend/llm/gateway.py`)**:
  - Single entry point `async def generate(self, prompt: str, response_model: type[T], *, purpose: str, tick: int, agent_id: str | None = None, system_instruction: str | None = None, temperature: float = 0.2) -> T`.
  - Enforces:
    1. **Exact-match prompt cache** (SHA-256 of `model + purpose + response_model.__qualname__ + system_instruction + prompt`): on cache hit, parses cached JSON into `T`, logs `LLMCallRecord(..., tokens_in=0, tokens_out=0, cost_est=0.0, cache_hit=True)`, and returns immediately.
    2. **Daily token/cost budget gate** (`REQ-15`, `NFR-02`): checks simulated day's accumulated cost/tokens; on budget exhaustion, routes routine/planning calls down to `MockProvider` fallback (or cheaper model tier) so simulation never crashes mid-day.
    3. **Pydantic v2 validation + 1-retry repair**: validates `raw_text` via `response_model.model_validate_json(raw_text)`. On `ValidationError`, appends validation error details into a repair prompt and retries **once** (`max_retries=1`), logging each underlying provider call to `llm_calls`.
    4. **Batched importance helper** (`rate_importance_batch(texts: Sequence[str], ...)`): scores multiple memories in a single `ImportanceBatchResponse` call (`PRD 10`, `REQ-15`).
- **`MockProvider` (`backend/llm/providers/mock.py`)**:
  - Dispatches on `response_model` class + deterministic `hashlib.sha256(f"{seed}:{prompt}".encode())` to synthesize valid JSON payloads (including Phase 2 `ImportanceBatchResponse` and forward-compatible schemas in `backend/llm/schemas.py` for planning, conversation, and reflection). Zero network, `<0.1ms`/call.

#### `EmbeddingService` (`backend/memory/embeddings.py`)
- **`DeterministicEmbeddingProvider` (default in test/mock mode)**:
  - Tokenizes lowercase words + word bigrams via regex `r"[a-z0-9_]+"`, hashes each feature with `hashlib.blake2b(token.encode("utf-8"), digest_size=8)` to pick an index `idx = h_int % 384` and sign `+1.0 / -1.0`, accumulates into `np.zeros(384, dtype=np.float32)`, and L2-normalizes (`vec / norm`, defaulting index 0 to `1.0` on empty input).
  - Runs in **~0.03 ms/text**, imports **zero** `torch`/`sentence_transformers` modules, outputs `(384,)` `float32` (`1,536` bytes), and gives high cosine similarity to lexically related memories (e.g., `"fire at Market"` vs `"Market fire smoke"`) and ~0 similarity to unrelated memories — making `REQ-05` retrieval tests meaningful and deterministic offline.
- **`SentenceTransformerEmbeddingProvider` (production `all-MiniLM-L6-v2`)**:
  - Defers `from sentence_transformers import SentenceTransformer` until `_get_model()` is first called.
  - Wraps synchronous CPU `.encode(..., convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)` inside `await asyncio.to_thread(...)` in async `EmbeddingService.embed` / `embed_batch` so FastAPI's event loop never stalls during ticks (`NFR-01`).

**Sources:**
- Codebase: `backend/pyproject.toml:1-51`, `backend/app/config.py:1-39`, `backend/app/main.py:1-67`, `backend/sim/engine.py:1-362`, `backend/sim/world.py:1-294`, `backend/sim/clock.py:1-94`, `backend/api/rest.py:1-74`, `backend/api/ws.py:1-52`, `frontend/public/assets/map.json:3648-3963`, `frontend/src/scenes/VillageScene.ts:15-42,177-236`, `frontend/src/types/sim.ts:1-97`, `scripts/generate_village_map.py:49-53,497-523`.
- Specs: `AI Village Product Requirements Document.md:78-221`, `.gsd/SPEC.md:30-66`, `.gsd/REQUIREMENTS.md:20-58`, `.gsd/ROADMAP.md:41-46`.
- SDK & Library Docs: Google GenAI Python SDK (`google-genai` `client.aio.models.generate_content` + `GenerateContentConfig`), SQLModel / SQLAlchemy 2.x AsyncIO (`create_async_engine`, `async_sessionmaker`, `StaticPool`), PyTorch CPU wheel index (`https://download.pytorch.org/whl/cpu`).

---

## Patterns to Follow
- **Instance-scoped `Database` with explicit `await db.dispose()`**: Always dispose `AsyncEngine` on app shutdown and test teardown so `aiosqlite` worker threads exit cleanly.
- **`expire_on_commit=False` on `async_sessionmaker`**: Prevents `MissingGreenlet` crashes when reading model fields (`record.id`, `record.text`) after `await session.commit()`.
- **`__tablename__: ClassVar[str]` & `sqlmodel.col(...)`**: Keeps `SQLModel` table classes and `.order_by(col(MemoryRecord.created_tick).desc())` queries 100% clean under `mypy --strict`.
- **Constant `384`-d `np.float32` vectors across both `Mock` and `Local` embedding providers**: Guarantees SQLite `embedding` blobs are always `1,536` bytes regardless of provider.
- **Min-max normalization epsilon guard (`max - min < 1e-9`)**: Prevents `NaN` scores when an agent has 0, 1, or uniform-timestamp/uniform-importance memories.

## Anti-Patterns to Avoid
- **Top-level `from sentence_transformers import SentenceTransformer`**: Adds 3–5 seconds of `torch`/`transformers` import overhead to every `pytest` invocation even when using mock embeddings.
- **Top-level `genai.Client()` instantiation**: Raises authentication errors when `GEMINI_API_KEY` is unset in offline CI.
- **Whole-string SHA-256 random embeddings in tests**: Produces orthogonal vectors for nearly identical sentences, preventing offline unit tests from verifying semantic relevance ranking (`w_v * relevance`).
- **Using `tick` as Primary Key of `sim_state`**: Forces row-per-tick inserts instead of updating a single authoritative state row (`id=1`).
- **Assigning `sprite_index >= 4` without expanding `sprites.png`**: Breaks Phaser frame lookups (`VillageScene.ts:185`) while `sprites.png` is `4x4` (16 frames).

## Dependencies Identified
| Package | Version Constraint | Verified Wheel (Win AMD64) | Purpose |
|---------|--------------------|----------------------------|---------|
| `sqlmodel` | `>=0.0.22` | `0.0.50` | ORM + Pydantic table models for 7 SQLite tables |
| `aiosqlite` | `>=0.20.0` | `0.22.1` | Async SQLite driver for SQLAlchemy/SQLModel |
| `sqlalchemy[asyncio]` | `>=2.0.36` | `2.1.9` + `greenlet 3.5.6` | `AsyncEngine`, `async_sessionmaker`, `LargeBinary`, `StaticPool` |
| `numpy` | `>=2.1.0` | `2.5.5` | `float32` binary packing & vectorized cosine similarity |
| `torch` (via CPU index) | `>=2.4.0` (transitive) | `2.15.0+cpu` | CPU-only backend for `sentence-transformers` (zero CUDA bloat) |
| `sentence-transformers` | `>=3.2.0` | `6.3.0` | Local `all-MiniLM-L6-v2` 384-d embeddings |
| `google-genai` | `>=1.0.0` | `3.6.1` | Official async Gemini SDK with Pydantic `response_schema` |

## Risks
- **SQLite `database is locked` under concurrent tick writes + REST reads**: Mitigate by enabling `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;` on file-backed SQLite connections in `Database.__init__`.
- **Hanging `pytest` process after async DB tests**: Caused by unclosed `aiosqlite` threads. Mitigate with an `async def db_ fixture` using `try: yield db finally: await db.dispose()` and `await db.dispose()` in `app/main.py` `lifespan`.
- **Phase 1 regression on hardcoded 4-agent count & 4-row spritesheet**: Mitigate by regenerating `sprites.png` for 8 rows in the same plan that expands personas from 4 to 8, and updating `test_api_ws.py` and `test_engine.py` assertions atomically.

## Recommendations for Planning
1. **Wave 1 (Foundation — Parallelizable)**:
   - **Plan 2.1 — Dependencies, Config & Async SQLite Schema (`app/config.py`, `app/db.py`, `memory/models.py`)**: Install CPU-only dependencies, expand `pyproject.toml` (`dependencies`, `packages.find`, `mypy.overrides`), extend `Settings`, implement `Database` (`AsyncEngine` + `AsyncSession` + WAL/`StaticPool`), and define all 7 `SQLModel` table classes with CRUD/persistence unit tests on `:memory:`.
   - **Plan 2.2 — Schema-Enforced LLM Gateway & Providers (`llm/schemas.py`, `llm/providers/`, `llm/gateway.py`)**: Define Pydantic v2 LLM schemas (batched importance + core agent schemas), `LLMProvider` protocol, deterministic `MockProvider`, `GeminiProvider` (`client.aio.models.generate_content` + `response_schema`), and `LLMGateway` (SHA-256 prompt cache, 1-retry validation repair, daily token/USD budget fallback, `llm_calls` logging) with offline unit tests (including retry-on-malformed-JSON, cache hit, and budget cap tests).
2. **Wave 2 (Memory & Embeddings — Depends on Wave 1)**:
   - **Plan 2.3 — Embeddings, Memory Stream Store & Weighted Retrieval (`memory/embeddings.py`, `memory/store.py`, `memory/retrieval.py`)**: Implement `DeterministicEmbeddingProvider` (signed token/bigram BLAKE2b hashing, 384-d `float32`) + lazy `SentenceTransformerEmbeddingProvider` (`all-MiniLM-L6-v2` via `asyncio.to_thread`), `MemoryStore` (binary `tobytes()`/`frombuffer()` persistence, batched importance integration), and weighted min-max retrieval (`0.995^hours` recency + importance + cosine relevance, `k=8`, `last_access_tick` update) with mathematical unit tests.
3. **Wave 3 (Personas & Engine Persistence Wiring — Depends on Wave 1 & 2)**:
   - **Plan 2.4 — 8 Rich Agent Personas, 8-Row Spritesheet & Engine/App Lifespan Integration (`agents/personas.py`, `sim/engine.py`, `app/main.py`, `scripts/generate_village_map.py`)**: Define 8 rich personas (age, role, traits, home_location, starting_goals, sprite_index `0..7`), regenerate 8-row `sprites.png` (+ defensive clamping in `VillageScene.ts`), wire `Database` + `MemoryStore` + `EmbeddingService` + `LLMGateway` into `SimulationEngine` and `create_app` `lifespan` (seeding `agents` and `sim_state` into SQLite and syncing state), and update/extend `test_engine.py` and `test_api_ws.py`.
