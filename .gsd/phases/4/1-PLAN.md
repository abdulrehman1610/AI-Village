---
phase: 4
plan: 1
wave: 1
depends_on: []
files_modified:
  - backend/llm/schemas.py
  - backend/llm/gateway.py
  - backend/llm/prompts/__init__.py
  - backend/llm/prompts/reflection.py
  - backend/llm/prompts/conversation.py
  - backend/llm/providers/mock.py
  - backend/tests/test_llm_gateway.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`ConversationSummaryResponse` and `ReflectionResponse` include optional mood fields with safe defaults so all existing Phase 2/3 schemas remain backwards-compatible"
    - "`LLMGateway` exposes `generate_salient_questions` (`purpose='salient_questions'`) and `generate_reflections` (`purpose='reflection'`), both routed to `planning_model`"
    - "`backend/llm/prompts/reflection.py` formats candidate evidence memories strictly as `[{memory_id}] {text}` without `[tick]` or `#N` markers or static urgent-keyword collisions, and `build_conversation_summary_prompt` accepts optional prior relationship context"
    - "`MockProvider` deterministically cites genuine memory IDs, populates mood labels on summaries/reflections, and preserves urgent topics in salient questions and insights"
  artifacts:
    - "backend/llm/schemas.py adds `speaker_a_mood` / `speaker_b_mood` to `ConversationSummaryResponse` and `mood` + `max_length=5` to `ReflectionResponse`"
    - "backend/llm/gateway.py exports `generate_salient_questions` and `generate_reflections`"
    - "backend/llm/prompts/reflection.py implements `build_salient_questions_prompt` and `build_reflection_insights_prompt` exported via `backend/llm/prompts/__init__.py`"
    - "backend/llm/prompts/conversation.py extends `build_conversation_summary_prompt` with `existing_affinity` and `existing_notes` plus mood guidance"
    - "backend/llm/providers/mock.py supports topic-aware `SalientQuestionsResponse`, `ReflectionResponse` (with `mood`), and `ConversationSummaryResponse` (with speaker moods)"
    - "backend/tests/test_llm_gateway.py verifies reflection prompts, gateway methods, planning-model routing, cited ID extraction, and mood outputs offline"
  key_links:
    - "backend/llm/gateway.py imports `SalientQuestionsResponse` and `ReflectionResponse` from `llm.schemas`"
    - "backend/llm/prompts/reflection.py is re-exported by `backend/llm/prompts/__init__.py`"
    - "backend/llm/providers/mock.py parses `[<memory_id>]` lines produced by `build_reflection_insights_prompt`"
---

# Plan 4.1: LLM Reflection Prompts, Schemas, Gateway Helpers & Mood-Aware MockProvider

## Objective
Extend the LLM schema, prompt, gateway, and deterministic mock provider layers for Phase 4 threshold-triggered reflections (`REQ-09`) and post-conversation/post-reflection mood updates (`REQ-10`, `REQ-11`), preserving full backwards compatibility with Phase 2 and Phase 3 tests.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/4/RESEARCH.md
- backend/llm/schemas.py
- backend/llm/gateway.py
- backend/llm/prompts/__init__.py
- backend/llm/prompts/conversation.py
- backend/llm/providers/mock.py
- backend/agents/personas.py
- backend/tests/test_llm_gateway.py

## Tasks

<task type="auto">
  <name>Extend LLM mood schemas and add reflection helpers to LLMGateway</name>
  <files>
    backend/llm/schemas.py
    backend/llm/gateway.py
  </files>
  <action>
    Update `backend/llm/schemas.py` and `backend/llm/gateway.py` with mood metadata fields and typed async reflection methods.

    Steps:
    1. In `backend/llm/schemas.py`:
       - Extend `ConversationSummaryResponse` (`ConfigDict(extra="forbid")` preserved) with two optional-default string fields:
         - `speaker_a_mood: str = ""`
         - `speaker_b_mood: str = ""`
       - Extend `ReflectionResponse` (`ConfigDict(extra="forbid")` preserved) with:
         - `insights: list[ReflectionInsight] = Field(min_length=1, max_length=5)`
         - `mood: str = ""`
    2. In `backend/llm/gateway.py`:
       - Import `ReflectionResponse` and `SalientQuestionsResponse` from `llm.schemas`.
       - Add two typed async helper methods on `LLMGateway`:
         - `generate_salient_questions(self, prompt: str, *, tick: int, agent_id: str, system_instruction: str | None = None) -> SalientQuestionsResponse` delegating to `self.generate(..., purpose="salient_questions", tick=tick, agent_id=agent_id, system_instruction=system_instruction)`.
         - `generate_reflections(self, prompt: str, *, tick: int, agent_id: str, system_instruction: str | None = None) -> ReflectionResponse` delegating to `self.generate(..., purpose="reflection", tick=tick, agent_id=agent_id, system_instruction=system_instruction)`.
       - Note that `"salient_questions"` and `"reflection"` are already in `_PLANNING_PURPOSES`, so `_resolve_requested_model` routes both to `self.planning_model`.

    AVOID: Making the new mood fields required without defaults, because existing unit tests construct `ConversationSummaryResponse(summary=..., affinity_delta=..., relationship_note=...)` and `ReflectionResponse(insights=...)` directly.
    USE: Default empty strings `""` with `ConfigDict(extra="forbid")` intact.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check llm/schemas.py llm/gateway.py
    .venv\Scripts\mypy.exe llm/schemas.py llm/gateway.py
  </verify>
  <done>
    `ConversationSummaryResponse` and `ReflectionResponse` carry optional mood fields, `LLMGateway` exposes `generate_salient_questions` and `generate_reflections`, and `ruff` + strict `mypy` pass cleanly.
  </done>
</task>

<task type="auto">
  <name>Create reflection prompt templates and extend conversation summary prompt</name>
  <files>
    backend/llm/prompts/reflection.py
    backend/llm/prompts/__init__.py
    backend/llm/prompts/conversation.py
  </files>
  <action>
    Implement `backend/llm/prompts/reflection.py`, export its builders from `backend/llm/prompts/__init__.py`, and enrich `build_conversation_summary_prompt` with prior relationship context and mood guidance.

    Steps:
    1. Create `backend/llm/prompts/reflection.py` with two pure prompt builder functions:
       - `build_salient_questions_prompt(*, persona: AgentPersona, sim_time: str, recent_memories: Sequence[str]) -> str`:
         - Formats `Persona: {persona.summary_text()}`, `Sim time: {sim_time}`, `Recent memories:` (bulleted `- ...` or `- (none)`), and neutral instructions asking for 3 salient high-level questions grounded in the memories.
       - `build_reflection_insights_prompt(*, persona: AgentPersona, sim_time: str, questions: Sequence[str], evidence_memories: Sequence[tuple[int, str]]) -> str`:
         - Formats `Persona: {persona.summary_text()}`, `Sim time: {sim_time}`, `Salient questions:` numbered strictly as `Q1. {q}`, `Q2. {q}`, `Q3. {q}` (never `#1` or `[1]`), and `Evidence memories:` formatted strictly as `- [{memory_id}] {text}` (or `- (none)` when empty).
         - Instructs the model to synthesize 1–3 concise insights, cite supporting `[id]` integers in `cited_memory_ids`, and return a single-word or short `mood` string reflecting the agent's current emotional state.
    2. Export `build_salient_questions_prompt` and `build_reflection_insights_prompt` from `backend/llm/prompts/__init__.py` (keep `__all__` sorted).
    3. In `backend/llm/prompts/conversation.py`:
       - Extend `build_conversation_summary_prompt` with optional keyword-only arguments:
         - `existing_affinity: float | None = None`
         - `existing_notes: str = ""`
       - When `existing_affinity is not None` or `existing_notes.strip()`, render `Prior relationship: affinity={existing_affinity:.2f}, notes={notes_or_none}` cleanly above `Transcript:`.
       - Extend the instructions block to also ask for concise single-word/short `speaker_a_mood` and `speaker_b_mood` labels reflecting each participant's mood after the exchange.

    AVOID: Putting `[<number>]`, `#<number>`, `ID:<number>`, or any `_URGENT_KEYWORDS` (`"fire"`, `"emergency"`, `"rumor"`, `"rumour"`, `"argument"`, `"secret"`, `"discovered"`) in static prompt template text, because `MockProvider._extract_cited_ids` scans `(?:\[|#|\bID[: ]+)(\d+)\b` and `_extract_salient_topic` scans non-metadata lines.
    USE: `Q1.`/`Q2.`/`Q3.` for question labels and `[{memory_id}]` exclusively for evidence memory lines.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check llm/prompts
    .venv\Scripts\mypy.exe llm/prompts
  </verify>
  <done>
    `backend/llm/prompts/reflection.py`, `__init__.py`, and `conversation.py` pass `ruff` and strict `mypy` with clean `[id]` evidence formatting and zero static keyword/citation collisions.
  </done>
</task>

<task type="auto">
  <name>Upgrade MockProvider for mood-aware summaries/reflections and add gateway tests</name>
  <files>
    backend/llm/providers/mock.py
    backend/tests/test_llm_gateway.py
  </files>
  <action>
    Enhance `MockProvider` in `backend/llm/providers/mock.py` to support topic-grounded reflections and mood labels deterministically, and expand `backend/tests/test_llm_gateway.py`.

    Steps:
    1. In `backend/llm/providers/mock.py`:
       - Update `_METADATA_LINE_PREFIXES` with the new static prompt prefixes from `reflection.py` and `conversation.py` (`"salient questions:"`, `"recent memories:"`, `"evidence memories:"`, `"prior relationship:"`, `"q1."`, `"q2."`, `"q3."`, `"synthesize "`, `"generate 3 "`, `"ask 3 "`) so `_extract_salient_topic(prompt)` never inspects static boilerplate lines.
       - Update `ConversationSummaryResponse` handling in `_build_payload`:
         - When `topic is not None`: include `"speaker_a_mood": "concerned"` and `"speaker_b_mood": "alert"`.
         - Otherwise: pick deterministic friendly moods from a small tuple `("warm", "cheerful", "engaged", "calm")` using `digest[1]` and `digest[2]`.
       - Update `SalientQuestionsResponse` handling in `_build_payload`:
         - Check `topic = _extract_salient_topic(prompt)`. If present, make question 1 reference `topic` (e.g., `f"How should I respond to {topic} given my daily priorities?"`) followed by 2 deterministic distinct questions from `_QUESTION_POOL`.
       - Update `ReflectionResponse` handling in `_build_payload`:
         - Extract `cited = _extract_cited_ids(prompt)` and `topic = _extract_salient_topic(prompt)`.
         - When `topic is not None`, include `f"The recent news about {topic} highlights how quickly village priorities shift."` as the first insight citing `cited`, plus 0–1 additional pooled insights, and return `"mood": "concerned"` (or `"attentive"`).
         - Otherwise generate 1–2 pooled insights citing `cited` and return `"mood": ("reflective", "calm", "hopeful")[digest[2] % 3]`.
    2. In `backend/tests/test_llm_gateway.py`:
       - Import `build_reflection_insights_prompt` and `build_salient_questions_prompt` from `llm.prompts`.
       - Add unit tests verifying:
         - `LLMGateway.generate_salient_questions` and `LLMGateway.generate_reflections` route to `planning_model`, log `LLMCallRecord` rows with `purpose="salient_questions"` and `purpose="reflection"`, and hit prompt cache on repeat calls.
         - `build_reflection_insights_prompt` + `MockProvider` produces `ReflectionResponse` whose `cited_memory_ids` contain ONLY genuine evidence memory IDs passed to the prompt (never question numbers `1, 2, 3`) and non-empty `mood`.
         - `build_conversation_summary_prompt` with `existing_affinity` and `existing_notes` + `MockProvider` produces valid `ConversationSummaryResponse` with non-empty `speaker_a_mood` and `speaker_b_mood`, preserving urgent topics when present.

    AVOID: Breaking existing `test_mock_provider_deterministic_and_schema_valid_across_all_schemas` assertions or returning out-of-range fields.
    USE: Deterministic `digest`-indexed pools and `_extract_salient_topic` / `_extract_cited_ids`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_llm_gateway.py
    .venv\Scripts\ruff.exe check llm tests/test_llm_gateway.py
    .venv\Scripts\mypy.exe llm tests/test_llm_gateway.py
  </verify>
  <done>
    All tests in `tests/test_llm_gateway.py` pass offline, `MockProvider` deterministically generates grounded reflections, cited IDs, and mood strings, and `ruff` + strict `mypy` pass with zero errors.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `ConversationSummaryResponse` and `ReflectionResponse` include backwards-compatible mood fields
- [ ] `LLMGateway` exposes `generate_salient_questions` and `generate_reflections` routed to `planning_model`
- [ ] `backend/llm/prompts/reflection.py` cleanly formats `[memory_id]` evidence lines and `Q1.`/`Q2.`/`Q3.` questions
- [ ] `MockProvider` deterministically cites genuine memory IDs and populates moods across offline tests

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero regressions in `backend/tests/test_llm_gateway.py`
