---
phase: 2
plan: 3
wave: 2
depends_on:
  - "1"
files_modified:
  - backend/memory/embeddings.py
  - backend/memory/store.py
  - backend/memory/retrieval.py
  - backend/tests/test_embeddings_retrieval.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`DeterministicEmbeddingProvider` generates L2-normalized 384-d `float32` vectors (`1,536` packed bytes) without importing `torch` or `sentence_transformers`, preserving lexical semantic similarity"
    - "`SentenceTransformerEmbeddingProvider` lazily loads `all-MiniLM-L6-v2` on first use and runs CPU encoding inside `asyncio.to_thread` without blocking the FastAPI event loop"
    - "`MemoryStore` persists observations, plans, conversations, and reflections into SQLite (`memories`) with binary `float32` blobs and supports batched inserts and access-tick updates"
    - "`MemoryRetriever` scores candidates using min-max normalized `w_r * recency + w_i * importance + w_v * relevance` (`0.995 ** hours` decay, NumPy cosine similarity, zero-range guard) and returns top-k (`k=8`) memories while refreshing `last_access_tick`"
  artifacts:
    - "backend/memory/embeddings.py defines `EMBEDDING_DIM = 384`, `EmbeddingProvider`, `DeterministicEmbeddingProvider`, `SentenceTransformerEmbeddingProvider`, `EmbeddingService`, `pack_embedding`, and `unpack_embedding`"
    - "backend/memory/store.py defines `MemoryType`, `MemoryCreate`, and `MemoryStore` async CRUD methods across memories, agents, relationships, events, and sim_state"
    - "backend/memory/retrieval.py defines `ScoredMemory`, `min_max_normalize`, `cosine_similarity_batch`, and `MemoryRetriever`"
    - "backend/tests/test_embeddings_retrieval.py proves 0-torch-import mock mode, semantic ranking, lazy local model loading, binary serialization, CRUD, and mathematical retrieval invariants"
  key_links:
    - "backend/memory/store.py calls `EmbeddingService` and `pack_embedding` to store `MemoryRecord.embedding` bytes via `Database.session()`"
    - "backend/memory/retrieval.py embeds query via `EmbeddingService`, unpacks `MemoryRecord.embedding` blobs via NumPy, and updates `last_access_tick` via `MemoryStore`"
---

# Plan 2.3: Embeddings, Memory Stream Store & Weighted Retrieval Scoring

## Objective
Implement the embedding pipeline (`backend/memory/embeddings.py`) with fast deterministic lexical-hash vectors for offline tests and lazy CPU `all-MiniLM-L6-v2` embeddings for production, the async `MemoryStore` (`backend/memory/store.py`) backed by SQLite `LargeBinary` blobs, and the weighted retrieval scorer (`backend/memory/retrieval.py`) implementing `w_r * recency + w_i * importance + w_v * relevance` (`0.995 ** hours` exponential decay, NumPy cosine similarity, min-max normalization, and top-$k=8$ retrieval with `last_access_tick` refresh).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/REQUIREMENTS.md
- .gsd/phases/2/RESEARCH.md
- backend/app/db.py
- backend/memory/models.py

## Tasks

<task type="auto">
  <name>Implement DeterministicEmbeddingProvider, lazy SentenceTransformerEmbeddingProvider, and binary float32 packing</name>
  <files>
    backend/memory/embeddings.py
  </files>
  <action>
    Implement `backend/memory/embeddings.py` providing interchangeable 384-d `float32` embeddings across offline tests and production `all-MiniLM-L6-v2`.

    Steps:
    1. Define constants & helpers:
       - `EMBEDDING_DIM = 384`
       - `EmbeddingVector = NDArray[np.float32]`
       - `pack_embedding(vec: EmbeddingVector) -> bytes`: flattens, verifies exact length `EMBEDDING_DIM` (raising `ValueError` otherwise), converts to `np.float32`, returns `.tobytes()` (`1,536` bytes).
       - `unpack_embedding(blob: bytes) -> EmbeddingVector`: validates `len(blob) == EMBEDDING_DIM * 4`, returns `np.frombuffer(blob, dtype=np.float32).copy()`.
    2. Define `@runtime_checkable class EmbeddingProvider(Protocol)` with `embed_batch(self, texts: Sequence[str]) -> list[EmbeddingVector]`.
    3. Implement `DeterministicEmbeddingProvider`:
       - Extracts lowercase alphanumeric tokens via `re.findall(r"[a-z0-9_]+", text.lower())` plus adjacent word bigrams `f"{a}_{b}"`.
       - For each feature, computes `digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()`, `h_val = int.from_bytes(digest, "little")`, bucket `idx = h_val % EMBEDDING_DIM`, sign `1.0 if ((h_val >> 16) & 1) == 0 else -1.0`, accumulates into `vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)`.
       - L2-normalizes (`norm = float(np.linalg.norm(vec))`); if `norm < 1e-12`, sets `vec[0] = 1.0` so empty strings still produce a valid unit vector.
       - Never imports `torch` or `sentence_transformers`.
    4. Implement `SentenceTransformerEmbeddingProvider`:
       - `__init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu") -> None` with `self._model: Any = None`.
       - `_get_model(self) -> Any`: lazily executes `from sentence_transformers import SentenceTransformer` only on first invocation and caches `SentenceTransformer(self.model_name, device=self.device)`.
       - `embed_batch(self, texts: Sequence[str]) -> list[EmbeddingVector]`: handles `[] -> []`, encodes via `self._get_model().encode(list(texts), convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)`, returns list of `np.asarray(row, dtype=np.float32)` vectors.
    5. Implement `EmbeddingService`:
       - `__init__(self, provider: EmbeddingProvider) -> None` plus `@classmethod def from_mode(cls, mode: Literal["mock", "local"], model_name: str = "all-MiniLM-L6-v2") -> EmbeddingService`.
       - `async def embed(self, text: str) -> EmbeddingVector`
       - `async def embed_batch(self, texts: Sequence[str]) -> list[EmbeddingVector]`: runs `SentenceTransformerEmbeddingProvider.embed_batch` via `await asyncio.to_thread(...)` (or runs directly/via thread without blocking the event loop).

    AVOID: Top-level `import torch` or `from sentence_transformers import SentenceTransformer` (adds 3-5s startup penalty to offline `pytest` runs) or pure whole-string hashing (which destroys lexical cosine similarity needed to test `REQ-05`).
    USE: Lazy model loading inside `_get_model()`, `asyncio.to_thread`, and signed BLAKE2b token/bigram hashing in `DeterministicEmbeddingProvider`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\ruff.exe check memory/embeddings.py
    .venv\Scripts\mypy.exe memory/embeddings.py
  </verify>
  <done>
    `backend/memory/embeddings.py` passes `ruff check` and strict `mypy` with zero errors.
  </done>
</task>

<task type="auto">
  <name>Implement MemoryStore and weighted MemoryRetriever with min-max normalization</name>
  <files>
    backend/memory/store.py
    backend/memory/retrieval.py
  </files>
  <action>
    Implement async SQLite persistence in `MemoryStore` and the weighted recency + importance + relevance retriever in `MemoryRetriever`.

    Steps:
    1. Implement `backend/memory/store.py`:
       - `MemoryType = Literal["observation", "plan", "reflection", "conversation"]`
       - `@dataclass(frozen=True) class MemoryCreate`: `agent_id: str`, `memory_type: MemoryType`, `text: str`, `importance: int`, `created_tick: int`, `metadata_json: str = "{}"`.
       - `class MemoryStore`: initialized with `db: Database` and `embedding_service: EmbeddingService`.
         - `async def add_memory(self, *, agent_id: str, memory_type: MemoryType, text: str, importance: int, created_tick: int, metadata_json: str = "{}") -> MemoryRecord`: validates `1 <= importance <= 10`, embeds text, packs `pack_embedding`, inserts `MemoryRecord(last_access_tick=created_tick, ...)`, commits, and returns record.
         - `async def add_memories_batch(self, items: Sequence[MemoryCreate]) -> list[MemoryRecord]`: single `embed_batch` call + bulk insert inside one `db.session()` transaction.
         - `async def list_memories(self, agent_id: str, *, memory_type: MemoryType | None = None, limit: int | None = None) -> list[MemoryRecord]`: queries `MemoryRecord` ordered by `col(MemoryRecord.created_tick).desc(), col(MemoryRecord.id).desc()`.
         - `async def touch_memories(self, memory_ids: Sequence[int], tick: int) -> None`: updates `last_access_tick = tick` on matching IDs in one transaction.
         - `async def upsert_agent(self, record: AgentRecord) -> AgentRecord`, `async def get_agent(self, agent_id: str) -> AgentRecord | None`, `async def list_agents(self) -> list[AgentRecord]`, `async def update_agent_states(self, states: Sequence[tuple[str, int, int, str, str]]) -> None` (`agent_id, x, y, current_action, current_plan_json`).
         - `async def get_or_create_sim_state(self, *, tick: int = 0, sim_time: str = "Day 1 06:00", speed: int = 1, seed: int = 42) -> SimStateRecord` and `async def save_sim_state(self, *, tick: int, sim_time: str, speed: int, seed: int) -> SimStateRecord`.
         - `async def log_event(self, *, tick: int, kind: str, text: str, location: str | None, source: str) -> EventRecord`, `async def upsert_relationship(...) -> RelationshipRecord`, `async def list_relationships(self, agent_id: str | None = None) -> list[RelationshipRecord]`.
    2. Implement `backend/memory/retrieval.py`:
       - `@dataclass(frozen=True) class ScoredMemory`: `memory: MemoryRecord`, `score: float`, `recency_score: float`, `importance_score: float`, `relevance_score: float`.
       - `def min_max_normalize(values: NDArray[np.float64]) -> NDArray[np.float64]`:
         - If `values.size == 0`, return `values`.
         - `min_v = float(np.min(values))`, `max_v = float(np.max(values))`, `span = max_v - min_v`.
         - If `span < 1e-9`: return `np.clip(values, 0.0, 1.0)` (finite bounded `[0, 1]` guard for single-memory or uniform arrays, zero `NaN`s).
         - Else: return `(values - min_v) / span`.
       - `def cosine_similarity_batch(matrix: NDArray[np.float32], query: NDArray[np.float32]) -> NDArray[np.float64]`:
         - Returns empty `float64` array if `matrix.shape[0] == 0`.
         - Computes `(matrix.astype(np.float64) @ query.astype(np.float64)) / np.maximum(norms * q_norm, 1e-12)`.
       - `class MemoryRetriever`:
         - `__init__(self, *, store: MemoryStore, embedding_service: EmbeddingService, w_recency: float = 1.0, w_importance: float = 1.0, w_relevance: float = 1.0, decay_per_hour: float = 0.995, default_top_k: int = 8) -> None`.
         - `async def retrieve(self, *, agent_id: str, query: str, current_tick: int, top_k: int | None = None, touch: bool = True) -> list[ScoredMemory]`:
           - Fetches candidates via `await self.store.list_memories(agent_id)`. Returns `[]` if empty.
           - Computes `query_vec = await self.embedding_service.embed(query)`.
           - Builds matrix `np.vstack([unpack_embedding(m.embedding) for m in candidates])`.
           - Computes:
             - `hours = np.maximum(0.0, (current_tick - last_access_ticks) / 60.0)`
             - `recency_raw = np.power(self.decay_per_hour, hours)`
             - `importance_raw = importances / 10.0`
             - `relevance_raw = cosine_similarity_batch(matrix, query_vec)`
           - Normalizes each component with `min_max_normalize(...)`.
           - `scores = w_r * rec_norm + w_i * imp_norm + w_v * rel_norm`.
           - Sorts descending by `(score, created_tick, m.id or 0)`, slices `[:k]`.
           - If `touch` is True, calls `await self.store.touch_memories(...)` for returned IDs and updates `last_access_tick = current_tick` on returned `MemoryRecord` objects.

    AVOID: Dividing by zero during min-max normalization when an agent has 1 memory or uniform timestamps/importances, or importing `llm.gateway` inside `memory/store.py` (which would break Wave 2 parallelism and couple memory to LLM).
    USE: `sqlmodel.col(...)` for typed queries, vectorized NumPy operations, and explicit deterministic tie-breaking.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\ruff.exe check memory/store.py memory/retrieval.py
    .venv\Scripts\mypy.exe memory/store.py memory/retrieval.py
  </verify>
  <done>
    `backend/memory/store.py` and `backend/memory/retrieval.py` pass `ruff check` and strict `mypy` with zero errors.
  </done>
</task>

<task type="auto">
  <name>Write offline unit tests for embeddings, MemoryStore, and retrieval scoring math</name>
  <files>
    backend/tests/test_embeddings_retrieval.py
  </files>
  <action>
    Create `backend/tests/test_embeddings_retrieval.py` verifying zero-torch mock mode, binary serialization, CRUD, and every retrieval scoring invariant.

    Steps:
    1. Test `DeterministicEmbeddingProvider`:
       - Verify `"torch" not in sys.modules` and `"sentence_transformers" not in sys.modules` after instantiating `EmbeddingService.from_mode("mock")` and calling `embed_batch`.
       - Verify output shape `(384,)`, dtype `np.float32`, L2 norm `pytest.approx(1.0, abs=1e-5)`, `pack_embedding` length `1536`, and `unpack_embedding` exact roundtrip.
       - Verify semantic separation: `cosine("fire at the Market", "Market fire and smoke") > cosine("fire at the Market", "quiet poetry reading at Library")`.
       - Verify empty string `""` produces valid unit vector without `NaN`.
    2. Test `SentenceTransformerEmbeddingProvider` lazy loading offline:
       - Verify instantiating `SentenceTransformerEmbeddingProvider()` does NOT import `sentence_transformers`.
       - Inject a fake `sentence_transformers` module via `monkeypatch.setitem(sys.modules, "sentence_transformers", ...)` and verify `EmbeddingService(provider).embed_batch(["hello", "world"])` returns two `(384,)` `float32` vectors via `asyncio.to_thread` with zero downloads.
    3. Test `MemoryStore` + `MemoryRetriever` on `:memory:` SQLite (with `await db.dispose()` cleanup):
       - Seed test `AgentRecord("maya", ...)` and test `add_memory`, `add_memories_batch`, `list_memories(memory_type=...)`.
       - Verify empty stream returns `[]`.
       - Verify single-memory & uniform-tick retrieval produces finite `[0.0, 3.0]` scores (zero `NaN`/`Inf`).
       - Verify exponential recency decay (`0.995 ** hours`): with equal importance and unrelated query, recently accessed memory (`tick=1200`) outranks stale memory (`tick=0`).
       - Verify importance weighting: with equal tick and equal unrelated text, `importance=9` outranks `importance=2`.
       - Verify relevance weighting: `"smoke rising near Market stalls"` outranks `"baking sourdough loaves"` for query `"Market smoke"` when ticks and importances match.
       - Verify top-$k=8$ truncation across 15 memories and confirm `last_access_tick` updates to `current_tick` ONLY on the 8 returned memories (non-retrieved memories keep original `last_access_tick`).

    AVOID: Triggering real `all-MiniLM-L6-v2` HuggingFace weight downloads or leaving `Database` undisposed.
    USE: `DeterministicEmbeddingProvider` for math/DB tests and a monkeypatched fake module for `SentenceTransformerEmbeddingProvider`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\pytest.exe -v tests/test_embeddings_retrieval.py
    .venv\Scripts\ruff.exe check .
    .venv\Scripts\mypy.exe app sim api memory tests
  </verify>
  <done>
    All tests in `tests/test_embeddings_retrieval.py` pass offline in <1s with zero `torch` imports in mock mode, and `ruff` + strict `mypy` exit 0.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `DeterministicEmbeddingProvider` outputs 384-d `float32` vectors (`1,536` bytes) with zero `torch` import overhead
- [ ] `SentenceTransformerEmbeddingProvider` loads lazily and runs via `asyncio.to_thread`
- [ ] `MemoryStore` persists binary embeddings and supports batched inserts + CRUD across tables
- [ ] `MemoryRetriever` computes min-max normalized `w_r * recency + w_i * importance + w_v * relevance` with `0.995^hours` decay, returns top-$k=8$, and updates `last_access_tick`

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in tests
