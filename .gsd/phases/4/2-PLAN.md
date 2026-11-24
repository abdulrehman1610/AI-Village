---
phase: 4
plan: 2
wave: 1
depends_on: []
files_modified:
  - backend/app/config.py
  - .env.example
  - backend/memory/models.py
  - backend/app/db.py
  - backend/memory/store.py
  - backend/tests/test_db.py
  - backend/tests/test_store_phase3.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`Settings.reflection_threshold` defaults to `150` (validated `>= 1`) and is documented in `.env.example`"
    - "`AgentRecord` persists `mood: str = 'calm'` while leaving `AgentRecord.current_plan_json` strictly a JSON list string, and `Database.init_models()` idempotently adds `agents.mood` to pre-existing SQLite DBs via `PRAGMA table_info('agents')`"
    - "`MemoryStore.upsert_relationship` enforces canonical lexicographical `(min(agent_a, agent_b), max(agent_a, agent_b))` pair keys, rejects self-loops (`ValueError`), and consolidates any legacy reversed row"
    - "`MemoryStore` supports `mood` persistence in `upsert_agent` / `update_agent_states(..., moods=...)` and batch lookup via `get_memories_by_ids`"
  artifacts:
    - "backend/app/config.py adds `reflection_threshold: int = Field(default=150, ge=1)` and `.env.example` documents `REFLECTION_THRESHOLD=150`"
    - "backend/memory/models.py adds `mood: str = 'calm'` on `AgentRecord`"
    - "backend/app/db.py implements idempotent `PRAGMA table_info('agents')` -> `ALTER TABLE agents ADD COLUMN mood` migration inside `Database.init_models()`"
    - "backend/memory/store.py updates `upsert_agent`, `update_agent_states`, `upsert_relationship`, and adds `get_memories_by_ids`"
    - "backend/tests/test_db.py and backend/tests/test_store_phase3.py verify schema migration, canonical relationships, mood updates, and memory ID lookups offline"
  key_links:
    - "backend/app/db.py migrates the `agents` table managed by `AgentRecord` in `backend/memory/models.py`"
    - "backend/memory/store.py persists `AgentRecord.mood` and canonical `RelationshipRecord` pairs matching `ConversationManager`"
---

# Plan 4.2: Persistence Schema (`AgentRecord.mood`), SQLite Migration & Canonical Relationships

## Objective
Add `Settings.reflection_threshold`, add `AgentRecord.mood` with an idempotent SQLite `ALTER TABLE` migration for existing local databases, canonicalize pairwise ordering inside `MemoryStore.upsert_relationship`, and add memory/mood persistence helpers required by Reflections, Relationships, and the Agent Inspector (`REQ-09`, `REQ-10`, `REQ-11`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/4/RESEARCH.md
- backend/app/config.py
- .env.example
- backend/memory/models.py
- backend/app/db.py
- backend/memory/store.py
- backend/tests/test_db.py
- backend/tests/test_store_phase3.py

## Tasks

<task type="auto">
  <name>Add Settings.reflection_threshold, AgentRecord.mood, and idempotent SQLite column migration</name>
  <files>
    backend/app/config.py
    .env.example
    backend/memory/models.py
    backend/app/db.py
  </files>
  <action>
    Extend application configuration, ORM schema, and SQLite initialization so `reflection_threshold` is configurable and `agents.mood` exists safely on both new and pre-existing databases.

    Steps:
    1. In `backend/app/config.py`:
       - Import `Field` from `pydantic` and add `reflection_threshold: int = Field(default=150, ge=1)` on `Settings`.
    2. In `.env.example`:
       - Append `REFLECTION_THRESHOLD=150`.
    3. In `backend/memory/models.py`:
       - Add `mood: str = "calm"` to `AgentRecord` (leaving `current_plan_json: str = "[]"` completely untouched).
    4. In `backend/app/db.py`:
       - Inside `Database.init_models()`, after `await conn.run_sync(SQLModel.metadata.create_all)`, run an idempotent SQLite column migration helper (when `self._database_url.startswith("sqlite")`):
         - Query `PRAGMA table_info('agents')` via `conn.exec_driver_sql(...)`.
         - Inspect column names (row index 1 in SQLite `PRAGMA table_info` tuple).
         - If `"mood"` is not present, execute `ALTER TABLE agents ADD COLUMN mood VARCHAR NOT NULL DEFAULT 'calm'`.

    AVOID: Modifying `AgentRecord.current_plan_json` to store a dict (which breaks `test_phase3_integration.py` expecting a JSON list) or assuming `create_all` alters pre-existing `ai_village.db` files.
    USE: Additive `AgentRecord.mood` column with `PRAGMA table_info('agents')` idempotent guard.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check app/config.py app/db.py memory/models.py
    .venv\Scripts\mypy.exe app/config.py app/db.py memory/models.py
  </verify>
  <done>
    `Settings.reflection_threshold` defaults to `150`, `AgentRecord.mood` defaults to `"calm"`, `Database.init_models()` idempotently migrates legacy `agents` tables, and `ruff` + strict `mypy` pass cleanly.
  </done>
</task>

<task type="auto">
  <name>Canonicalize MemoryStore.upsert_relationship, persist mood, and add get_memories_by_ids</name>
  <files>
    backend/memory/store.py
  </files>
  <action>
    Update `backend/memory/store.py` so `MemoryStore` persists `AgentRecord.mood`, supports batch ID lookup, and guarantees canonical undirected pairwise rows in `relationships`.

    Steps:
    1. Update `upsert_agent(self, record: AgentRecord)`:
       - Copy `existing.mood = record.mood` alongside the other mutable columns on existing records.
    2. Update `update_agent_states(self, states: Sequence[tuple[str, int, int, str, str]], *, moods: Mapping[str, str] | None = None)`:
       - Keep the existing 5-tuple signature backwards-compatible so all Phase 2/3 tests remain valid.
       - When `moods is not None` and `agent_id in moods`, update `agent.mood = moods[agent_id]`.
    3. Add `async def get_memories_by_ids(self, agent_id: str, memory_ids: Sequence[int]) -> list[MemoryRecord]`:
       - Deduplicate positive `int` IDs preserving input order (`unique_ids`), return `[]` if empty.
       - Query `MemoryRecord` where `agent_id == agent_id` and `id.in_(unique_ids)`, returning records ordered by `created_tick DESC, id DESC` (or input order — pick deterministic `created_tick DESC, id DESC` and document in docstring).
    4. Update `upsert_relationship(self, agent_a: str, agent_b: str, affinity: float = 0.0, notes: str = "", last_interaction_tick: int = 0) -> RelationshipRecord`:
       - Reject self-relationships: if `agent_a == agent_b`, raise `ValueError("Cannot create a relationship between an agent and itself.")`.
       - Canonicalize pair: `canon_a, canon_b = (agent_a, agent_b) if agent_a < agent_b else (agent_b, agent_a)`.
       - Clamp `bounded_affinity = max(-1.0, min(1.0, float(affinity)))`.
       - Inside `async with self.db.session() as session:`:
         - Fetch `rel = await session.get(RelationshipRecord, (canon_a, canon_b))` and `legacy = await session.get(RelationshipRecord, (canon_b, canon_a))`.
         - If `rel is None` and `legacy is not None`: delete `legacy` and create canonical `RelationshipRecord(agent_a=canon_a, agent_b=canon_b, ...)`; else if both exist, delete `legacy` and update `rel`; else insert/update `rel` with `bounded_affinity`, `notes`, and `last_interaction_tick`.
         - Commit and return the canonical `RelationshipRecord`.

    AVOID: Breaking existing 5-tuple callers of `update_agent_states` or allowing `"maya","liam"` and `"liam","maya"` to create duplicate rows in `relationships`.
    USE: Optional keyword `moods` mapping on `update_agent_states` and strict `(min, max)` canonicalization inside `upsert_relationship`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check memory/store.py
    .venv\Scripts\mypy.exe memory/store.py
  </verify>
  <done>
    `MemoryStore` persists `mood`, retrieves memories by ID, and strictly canonicalizes pairwise relationships without duplicates or self-loops, passing `ruff` and strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Add offline unit tests for mood migration, canonical relationships, and memory ID lookups</name>
  <files>
    backend/tests/test_db.py
    backend/tests/test_store_phase3.py
  </files>
  <action>
    Expand `backend/tests/test_db.py` and `backend/tests/test_store_phase3.py` to empirically verify all Plan 4.2 persistence and migration behaviors.

    Steps:
    1. In `backend/tests/test_db.py`:
       - Add `test_init_models_migrates_legacy_agents_table_missing_mood(tmp_path: Path)`:
         - Create a raw SQLite DB with `sqlite3.connect` containing a legacy `agents` table (without `mood`) and one inserted row (`id='maya'`, `name='Maya'`, etc.).
         - Instantiate `Database(f"sqlite+aiosqlite:///{db_path.as_posix()}")`, call `await database.init_models()` twice (verifying idempotency!), and assert `PRAGMA table_info('agents')` contains `mood` and reloaded `AgentRecord` for `'maya'` has `mood == "calm"`.
       - Assert `AgentRecord.mood` defaults to `"calm"` and roundtrips updated values like `"reflective"`.
    2. In `backend/tests/test_store_phase3.py`:
       - Add `test_upsert_relationship_canonicalizes_pair_and_rejects_self_loop(store: MemoryStore)`:
         - Call `await store.upsert_relationship("maya", "liam", affinity=0.4, notes="First chat", last_interaction_tick=10)` -> assert stored row has `agent_a == "liam"` and `agent_b == "maya"`.
         - Call `await store.upsert_relationship("liam", "maya", affinity=1.5, notes="Close friends", last_interaction_tick=25)` -> assert `len(await store.list_relationships()) == 1`, `affinity == pytest.approx(1.0)`, and `notes == "Close friends"`.
         - Assert `await store.upsert_relationship("maya", "maya", affinity=0.5)` raises `ValueError`.
       - Add `test_update_agent_states_with_moods_and_get_memories_by_ids(store: MemoryStore)`:
         - Verify `update_agent_states([...], moods={"maya": "cheerful"})` updates `maya.mood` while preserving default `"calm"` on other agents.
         - Verify `get_memories_by_ids("maya", [...])` filters strictly to `"maya"`'s IDs and handles empty/non-existent IDs cleanly.

    AVOID: Altering or relaxing existing assertions in `test_db.py` or `test_store_phase3.py`.
    USE: Isolated `tmp_path` and `:memory:` SQLite databases.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_db.py tests/test_store_phase3.py tests/test_embeddings_retrieval.py
    .venv\Scripts\ruff.exe check app memory tests/test_db.py tests/test_store_phase3.py
    .venv\Scripts\mypy.exe app memory tests/test_db.py tests/test_store_phase3.py
  </verify>
  <done>
    All DB migration, mood persistence, canonical relationship, and retrieval tests pass offline with zero `ruff` or `mypy` issues.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `Settings.reflection_threshold` defaults to `150` (`>= 1`)
- [ ] `AgentRecord.mood` exists with default `"calm"`, `current_plan_json` remains a JSON list, and `Database.init_models()` idempotently migrates legacy `agents` tables
- [ ] `MemoryStore.upsert_relationship` enforces `(min, max)` canonical keys and rejects self-relationships

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero regressions in `test_db.py`, `test_store_phase3.py`, and `test_embeddings_retrieval.py`
