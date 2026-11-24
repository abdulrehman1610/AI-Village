---
phase: 4
plan: 4
wave: 2
depends_on:
  - "1"
  - "2"
files_modified:
  - backend/agents/reflection.py
  - backend/agents/planner.py
  - backend/agents/agent.py
  - backend/agents/conversation.py
  - backend/tests/test_reflection.py
  - backend/tests/test_planner_and_agent.py
  - backend/tests/test_conversation.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`ReflectionManager` triggers only when `accumulated_importance >= reflection_threshold`, generates 3 salient questions, retrieves evidence via `MemoryRetriever`, synthesizes cited insights grounded to valid candidate memory IDs (with safe fallback), stores `reflection` memories (`importance=8`, `cited_memory_ids` in `metadata_json`), and emits `reflection` WS payloads"
    - "`AgentBrain` tracks `accumulated_importance` across observations, newly created daily plans/replans (when `memory_store` persists them), and conversations, tracks `mood` and `last_reflection_tick`, and resets `accumulated_importance = 0` after reflecting without self-cascading"
    - "`ConversationManager` forwards existing `(affinity, notes)` into `build_conversation_summary_prompt`, persists canonical pairwise relationship updates, and updates both participants' `mood` from `ConversationSummaryResponse` (with deterministic fallback)"
  artifacts:
    - "backend/agents/reflection.py implements `ReflectionOutcome` and `ReflectionManager`"
    - "backend/agents/planner.py exposes `PLAN_MEMORY_IMPORTANCE = 6` and `REPLAN_MEMORY_IMPORTANCE = 7`"
    - "backend/agents/agent.py extends `AgentBrain` with `mood`, `last_reflection_tick`, `reflection_threshold`, `add_importance`, `should_reflect`, `reset_reflection_counter`, and plan/replan importance accounting in `decide`"
    - "backend/agents/conversation.py extends `DialogueParticipant` and `DialogueOutcome` with mood support, passes prior relationship context into summaries, and updates participant `mood`"
    - "backend/tests/test_reflection.py, backend/tests/test_planner_and_agent.py, and backend/tests/test_conversation.py verify reflection, citation grounding, mood updates, and importance accounting offline"
  key_links:
    - "backend/agents/reflection.py calls `LLMGateway.generate_salient_questions`, `LLMGateway.generate_reflections`, `MemoryRetriever.retrieve`, and `MemoryStore.add_memories_batch` using prompts from `llm.prompts.reflection`"
    - "backend/agents/conversation.py passes prior `RelationshipRecord` context to `build_conversation_summary_prompt` and calls canonical `MemoryStore.upsert_relationship`"
---

# Plan 4.4: Reflection Engine & Conversation/Agent Mood + Importance Wiring

## Objective
Implement the threshold-triggered `ReflectionManager` (`backend/agents/reflection.py`), extend `AgentBrain` and `DailyPlanner` importance accounting so observations, plans, and conversations advance the reflection accumulator without self-cascading, and wire prior relationship context and mood updates into `ConversationManager` (`REQ-09`, `REQ-10`, `REQ-11`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/4/RESEARCH.md
- backend/llm/schemas.py
- backend/llm/gateway.py
- backend/llm/prompts/reflection.py
- backend/llm/prompts/conversation.py
- backend/memory/models.py
- backend/memory/store.py
- backend/memory/retrieval.py
- backend/agents/planner.py
- backend/agents/agent.py
- backend/agents/conversation.py
- backend/tests/test_planner_and_agent.py
- backend/tests/test_conversation.py

## Tasks

<task type="auto">
  <name>Implement ReflectionManager in backend/agents/reflection.py</name>
  <files>
    backend/agents/reflection.py
  </files>
  <action>
    Create `backend/agents/reflection.py` encapsulating the Stanford Generative Agents reflection pipeline: salient question generation -> evidence retrieval -> cited insight synthesis -> `reflection` memory persistence -> WS payload creation.

    Steps:
    1. Define `@dataclass(frozen=True)` `ReflectionOutcome`:
       - `agent_id: str`
       - `agent_name: str`
       - `questions: list[str]`
       - `insights: list[str]`
       - `cited_memory_ids_per_insight: list[list[int]]`
       - `mood: str`
       - `ws_payloads: list[dict[str, Any]]`
    2. Define `ReflectionManager`:
       - `__init__(self, *, llm_gateway: LLMGateway, memory_store: MemoryStore, retriever: MemoryRetriever | None = None, reflection_threshold: int = 150, recent_memory_limit: int = 20, evidence_top_k: int = 8, reflection_importance: int = 8) -> None` (validate positive `reflection_threshold >= 1`, `recent_memory_limit >= 1`, `evidence_top_k >= 1`, `1 <= reflection_importance <= 10`).
       - `should_reflect(self, accumulated_importance: int) -> bool`: return `accumulated_importance >= self.reflection_threshold`.
       - `async def run_reflection(self, *, agent_id: str, persona: AgentPersona, tick: int, sim_time: str) -> ReflectionOutcome | None`:
         1. Fetch recent memories via `await self.memory_store.list_memories(agent_id, limit=self.recent_memory_limit)`. If empty, return `None`.
         2. Build prompt via `build_salient_questions_prompt(persona=persona, sim_time=sim_time, recent_memories=[m.text for m in recent_memories])` and call `questions_resp = await self.llm_gateway.generate_salient_questions(questions_prompt, tick=tick, agent_id=agent_id)`.
         3. Collect candidate evidence `MemoryRecord`s:
            - If `self.retriever is not None`: for each `question` in `questions_resp.questions`, call `await self.retriever.retrieve(agent_id, question, tick, top_k=self.evidence_top_k)` and gather unique memories by `MemoryRecord.id`.
            - Always fall back to `recent_memories` (those with non-None `id`) if retrieved candidates are empty.
            - Sort/cap candidate evidence cleanly (up to `max(12, self.evidence_top_k * 2)`) and build `valid_id_set` plus `evidence_pairs: list[tuple[int, str]]`. If `evidence_pairs` is empty, return `None`.
         4. Build insights prompt via `build_reflection_insights_prompt(persona=persona, sim_time=sim_time, questions=questions_resp.questions, evidence_memories=evidence_pairs)` and call `reflection_resp = await self.llm_gateway.generate_reflections(insights_prompt, tick=tick, agent_id=agent_id)`.
         5. For each `item` in `reflection_resp.insights[:3]`:
            - Filter `item.cited_memory_ids` to unique ints present in `valid_id_set`.
            - If filtered list is empty, fall back deterministically to `[evidence_pairs[0][0]]` (up to 2 IDs if available).
            - Prepare `MemoryCreate(agent_id=agent_id, memory_type="reflection", text=item.insight.strip(), importance=self.reflection_importance, created_tick=tick, metadata_json=json.dumps({"cited_memory_ids": valid_cited_ids, "questions": list(questions_resp.questions)}))`.
         6. Persist insights in one batch via `await self.memory_store.add_memories_batch(memory_items)`.
         7. Resolve `resolved_mood = reflection_resp.mood.strip() or "reflective"`.
         8. Build `ws_payloads` with one dict per persisted insight:
            `{"type": "reflection", "tick": tick, "sim_time": sim_time, "agent_id": agent_id, "agent_name": persona.name, "insight": item.text, "cited_memory_ids": valid_cited_ids, "mood": resolved_mood}`.
         9. Return `ReflectionOutcome(...)`.

    AVOID: Re-rating reflection importance via an extra `rate_importance_batch` call (wastes LLM budget), adding `reflection_importance` back into `accumulated_importance` (would cause self-cascading loops), or persisting unvalidated LLM-hallucinated memory IDs.
    USE: Fixed `reflection_importance=8`, strict `valid_id_set` filtering with deterministic fallback, and one `add_memories_batch` call.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check agents/reflection.py
    .venv\Scripts\mypy.exe agents/reflection.py
  </verify>
  <done>
    `backend/agents/reflection.py` implements `ReflectionManager` and `ReflectionOutcome`, passing `ruff` and strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Extend AgentBrain reflection tracking and ConversationManager relationship/mood updates</name>
  <files>
    backend/agents/planner.py
    backend/agents/agent.py
    backend/agents/conversation.py
  </files>
  <action>
    Update `planner.py`, `agent.py`, and `conversation.py` to track mood, plan/replan importance accumulation, and prior relationship context across interactions.

    Steps:
    1. In `backend/agents/planner.py`:
       - Define module constants `PLAN_MEMORY_IMPORTANCE = 6` and `REPLAN_MEMORY_IMPORTANCE = 7` and use them in `generate_daily_plan` and `replan_remaining_day` when calling `memory_store.add_memory(...)`.
    2. In `backend/agents/agent.py`:
       - Import `PLAN_MEMORY_IMPORTANCE` and `REPLAN_MEMORY_IMPORTANCE` from `agents.planner`.
       - Extend `AgentBrain` with fields:
         - `mood: str = "calm"`
         - `last_reflection_tick: int = -1`
         - `reflection_threshold: int = 150`
       - Add helper methods:
         - `add_importance(self, amount: int) -> None`: adds `max(0, amount)` to `self.accumulated_importance`.
         - `should_reflect(self) -> bool`: returns `self.accumulated_importance >= self.reflection_threshold`.
         - `reset_reflection_counter(self, *, tick: int) -> None`: sets `self.accumulated_importance = 0` and `self.last_reflection_tick = tick`.
       - In `AgentBrain.decide(...)`:
         - When `self.plan_state is None or self.plan_state.day != clock.day`: after `generate_daily_plan(...)`, if `memory_store is not None`, call `self.add_importance(PLAN_MEMORY_IMPORTANCE)`.
         - Else when `needs_replan`: after `replan_remaining_day(...)`, if `memory_store is not None`, call `self.add_importance(REPLAN_MEMORY_IMPORTANCE)`.
    3. In `backend/agents/conversation.py`:
       - Add `mood: str` to `DialogueParticipant` protocol (using `getattr(agent, "mood", "calm")` when reading, and setting `agent_a.mood` / `agent_b.mood` cleanly).
       - Add `moods: tuple[str, str] = ("warm", "warm")` to `DialogueOutcome`.
       - Inside `run_conversation`:
         - Fetch `id_1, id_2 = pair` and `existing_rel = await self.memory_store.get_relationship(id_1, id_2)` BEFORE calling `build_conversation_summary_prompt`.
         - Pass `existing_affinity=existing_rel.affinity if existing_rel is not None else None` and `existing_notes=existing_rel.notes if existing_rel is not None else ""` into `build_conversation_summary_prompt(...)`.
         - Call `upsert_relationship` directly with canonical `(id_1, id_2)` (since `pair = _pair_key(agent_a.id, agent_b.id)`).
         - Resolve `mood_a = summary_resp.speaker_a_mood.strip() or ("concerned" if importance >= _REPLAN_IMPORTANCE_THRESHOLD else "warm")` and `mood_b = summary_resp.speaker_b_mood.strip() or ("concerned" if importance >= _REPLAN_IMPORTANCE_THRESHOLD else "warm")`.
         - Assign `agent_a.mood = mood_a`, `agent_b.mood = mood_b`, and return `DialogueOutcome(..., moods=(mood_a, mood_b))`.

    AVOID: Calling `memory_store.get_relationship` twice in `run_conversation` or forgetting to pass `moods` cleanly when constructing `DialogueOutcome`.
    USE: Shared constants `PLAN_MEMORY_IMPORTANCE` / `REPLAN_MEMORY_IMPORTANCE` and canonical `(id_1, id_2)` relationship keys.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check agents/planner.py agents/agent.py agents/conversation.py
    .venv\Scripts\mypy.exe agents/planner.py agents/agent.py agents/conversation.py
  </verify>
  <done>
    `AgentBrain` tracks `mood` and accumulates importance across observations and plan/replan creations, `ConversationManager` passes prior relationship context and updates participant moods, and `ruff` + strict `mypy` pass cleanly.
  </done>
</task>

<task type="auto">
  <name>Add offline tests for ReflectionManager, AgentBrain counters, and ConversationManager moods</name>
  <files>
    backend/tests/test_reflection.py
    backend/tests/test_planner_and_agent.py
    backend/tests/test_conversation.py
  </files>
  <action>
    Create `backend/tests/test_reflection.py` and extend `backend/tests/test_planner_and_agent.py` and `backend/tests/test_conversation.py` to test all reflection, grounding, importance-counter, and mood behaviors offline.

    Steps:
    1. Create `backend/tests/test_reflection.py`:
       - Test 1 (`test_reflection_manager_threshold_retrieval_and_cited_memories`):
         - Seed `maya` with multiple memories in an in-memory `Database` + `MemoryStore` + `MemoryRetriever` + `MockProvider(seed=42)`.
         - Verify `should_reflect(149) is False` and `should_reflect(150) is True`.
         - Run `run_reflection(...)` and assert:
           - 3 salient questions generated, >=1 `"reflection"` memory persisted with `importance == 8`.
           - `json.loads(mem.metadata_json)["cited_memory_ids"]` is non-empty and every cited ID exists in Maya's non-reflection memories.
           - `ws_payloads` match `{"type": "reflection", "tick": ..., "sim_time": ..., "agent_id": "maya", "agent_name": "Maya", "insight": ..., "cited_memory_ids": [...], "mood": ...}`.
       - Test 2 (`test_reflection_manager_filters_hallucinated_citations_with_fallback`):
         - Use a scripted `LLMProvider` returning `SalientQuestionsResponse` + `ReflectionResponse` containing nonexistent IDs `[999999, -1]`.
         - Assert persisted `cited_memory_ids` filters out `[999999, -1]` and deterministically falls back to genuine candidate memory IDs from Maya's memory stream.
    2. In `backend/tests/test_planner_and_agent.py`:
       - Add `test_agent_brain_accumulates_plan_importance_and_resets_reflection_counter`:
         - Confirm `brain.decide(...)` adds `PLAN_MEMORY_IMPORTANCE` on initial plan and `REPLAN_MEMORY_IMPORTANCE` on replan when `memory_store` is attached, `should_reflect()` respects `reflection_threshold`, and `reset_reflection_counter(tick=...)` zeroes `accumulated_importance` and updates `last_reflection_tick`.
    3. In `backend/tests/test_conversation.py`:
       - Update `_FakeParticipant` dataclass with `mood: str = "calm"` to satisfy the updated `DialogueParticipant` protocol.
       - Add assertions / test verifying `ConversationManager.run_conversation` passes prior relationship `affinity` and `notes` into `build_conversation_summary_prompt`, persists canonical `agent_a < agent_b` relationship keys, and updates `maya.mood`, `liam.mood`, and `outcome.moods`.

    AVOID: Modifying existing test behavior assertions unnecessarily or relying on external network calls.
    USE: `MockProvider(seed=42)`, `EmbeddingService.from_mode("mock")`, scripted offline fake providers, and `:memory:` SQLite.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_reflection.py tests/test_planner_and_agent.py tests/test_conversation.py
    .venv\Scripts\ruff.exe check agents tests/test_reflection.py tests/test_planner_and_agent.py tests/test_conversation.py
    .venv\Scripts\mypy.exe agents tests/test_reflection.py tests/test_planner_and_agent.py tests/test_conversation.py
  </verify>
  <done>
    All tests in `test_reflection.py`, `test_planner_and_agent.py`, and `test_conversation.py` pass offline with zero `ruff` or strict `mypy` errors.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `ReflectionManager` generates 3 salient questions, retrieves evidence via `MemoryRetriever`, persists cited `reflection` memories (`importance=8`), and produces `reflection` WS payloads
- [ ] Hallucinated or empty `cited_memory_ids` are filtered against candidate memories with deterministic fallback
- [ ] `AgentBrain` accumulates importance from observations, plans, and replans, and resets counters after reflection
- [ ] `ConversationManager` includes prior relationship context in summaries and updates participant `mood`

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero regressions in `test_planner_and_agent.py` or `test_conversation.py`
