---
phase: 3
plan: 2
wave: 1
depends_on: []
files_modified:
  - backend/memory/store.py
  - backend/tests/test_store_phase3.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`MemoryStore` persists and queries `ConversationRecord` transcripts/summaries with exact participant filtering"
    - "`MemoryStore` queries `EventRecord` entries ordered newest-first with optional `since_tick` and `limit`"
    - "`MemoryStore` exposes `get_relationship(agent_a, agent_b)` resolving pairwise relationships symmetrically"
  artifacts:
    - "backend/memory/store.py adds `add_conversation`, `list_conversations`, `list_events`, and `get_relationship`"
    - "backend/tests/test_store_phase3.py tests conversation, event, and relationship CRUD queries in-memory"
  key_links:
    - "backend/memory/store.py imports `ConversationRecord` from `memory.models` and uses async `self.db.session()`"
---

# Plan 3.2: MemoryStore Conversation, Event & Relationship Query Methods

## Objective
Extend `MemoryStore` (`backend/memory/store.py`) with async persistence and query methods for completed conversations (`add_conversation`, `list_conversations`), logged world/god-mode events (`list_events`), and pairwise relationship lookup (`get_relationship`), backed by isolated SQLite unit tests.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/3/RESEARCH.md
- backend/memory/models.py
- backend/memory/store.py
- backend/app/db.py

## Tasks

<task type="auto">
  <name>Add conversation, event, and relationship query methods to MemoryStore</name>
  <files>
    backend/memory/store.py
  </files>
  <action>
    Update `backend/memory/store.py` to support reading and writing `ConversationRecord`, querying `EventRecord`, and fetching a `RelationshipRecord`.

    Steps:
    1. Import `json` and `Any` (for turn payloads) and import `ConversationRecord` from `memory.models`.
    2. Add `add_conversation(self, *, tick_start: int, participants: Sequence[str], turns: Sequence[dict[str, Any]], summary: str) -> ConversationRecord`:
       - Serialize `participants=json.dumps(list(participants))` and `transcript_json=json.dumps(list(turns))`.
       - Persist via `async with self.db.session() as session: session.add(record); await session.commit()` and return `record` (primary key `.id` remains accessible thanks to `expire_on_commit=False`).
    3. Add `list_conversations(self, *, participant_id: str | None = None, limit: int | None = None) -> list[ConversationRecord]`:
       - If `limit is not None and limit <= 0`: return `[]`.
       - Query `select(ConversationRecord).order_by(col(ConversationRecord.tick_start).desc(), col(ConversationRecord.id).desc())`.
       - If `participant_id is not None`: filter rows in Python by exact membership in `json.loads(row.participants)` (avoids SQL substring false positives like `"sam"` matching `"samuel"`), then slice `[:limit]` if `limit is not None`.
       - Else if `limit is not None`: apply `.limit(limit)` in SQL.
    4. Add `list_events(self, *, since_tick: int | None = None, limit: int | None = None) -> list[EventRecord]`:
       - If `limit is not None and limit <= 0`: return `[]`.
       - Query `select(EventRecord)`; if `since_tick is not None`, filter `col(EventRecord.tick) >= since_tick`.
       - Order by `col(EventRecord.tick).desc(), col(EventRecord.id).desc()` and apply `.limit(limit)` if `limit is not None`.
    5. Add `get_relationship(self, agent_a: str, agent_b: str) -> RelationshipRecord | None`:
       - Look up `(agent_a, agent_b)` via `await session.get(RelationshipRecord, (agent_a, agent_b))`; if `None` and `agent_a != agent_b`, check `(agent_b, agent_a)` so symmetric lookups work cleanly regardless of ID order.

    AVOID: Using SQL `LIKE '%agent_id%'` for participant filtering without exact JSON membership checking, or modifying existing `add_memories_batch` / `list_memories` signatures.
    USE: Exact `json.loads(row.participants)` membership checks and newest-first ordering (`tick DESC, id DESC`).
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check memory/store.py
    .venv\Scripts\mypy.exe memory/store.py
  </verify>
  <done>
    `MemoryStore` exposes `add_conversation`, `list_conversations`, `list_events`, and `get_relationship`, passing `ruff` and strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Add offline unit tests for MemoryStore conversation, event, and relationship methods</name>
  <files>
    backend/tests/test_store_phase3.py
  </files>
  <action>
    Create `backend/tests/test_store_phase3.py` verifying all new `MemoryStore` methods against an in-memory async SQLite `Database`.

    Steps:
    1. Create an async fixture yielding initialized `Database("sqlite+aiosqlite:///:memory:")` + `MemoryStore` with `EmbeddingService.from_mode("mock")`, seeding sample `AgentRecord` rows (`maya`, `liam`, `sam`, `samuel`) so foreign keys validate.
    2. Test `add_conversation` + `list_conversations`:
       - Insert conversations at different `tick_start` values (`10`, `25`, `25`), including `("sam", "maya")` and `("samuel", "liam")`.
       - Assert `list_conversations()` returns newest-first (`tick_start DESC, id DESC`), `limit=1` returns `[latest]`, `limit=0` returns `[]`, and `participant_id="sam"` returns only `("sam", "maya")` (not `"samuel"`).
       - Assert JSON round-trip on `participants` and `transcript_json`.
    3. Test `log_event` + `list_events`:
       - Log events at ticks `5`, `12`, `20` and assert `list_events()` ordering, `since_tick=12` filtering, `limit=2`, and `limit=0`.
    4. Test `upsert_relationship` + `get_relationship`:
       - Upsert `("liam", "maya")` with `affinity=0.35`, verify `get_relationship("liam", "maya")` and symmetric `get_relationship("maya", "liam")` both return the record, and `get_relationship("maya", "noah")` returns `None`.

    AVOID: Writing to any persistent `.db` file on disk.
    USE: `sqlite+aiosqlite:///:memory:` with proper `try/finally: await db.dispose()`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_store_phase3.py
    .venv\Scripts\ruff.exe check tests/test_store_phase3.py
    .venv\Scripts\mypy.exe tests/test_store_phase3.py
  </verify>
  <done>
    All tests in `tests/test_store_phase3.py` pass offline and `ruff` + strict `mypy` pass with zero errors.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `MemoryStore` supports `add_conversation`, `list_conversations`, `list_events`, and `get_relationship`
- [ ] Participant filtering does not produce substring false positives
- [ ] Unit tests in `tests/test_store_phase3.py` pass offline against `:memory:` SQLite

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in existing memory/DB tests
