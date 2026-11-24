---
phase: 3
plan: 1
wave: 1
depends_on: []
files_modified:
  - backend/llm/schemas.py
  - backend/llm/gateway.py
  - backend/llm/prompts/__init__.py
  - backend/llm/prompts/planning.py
  - backend/llm/prompts/conversation.py
  - backend/llm/providers/mock.py
  - backend/tests/test_llm_gateway.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`ReplanResponse` validates 1..8 `DailyPlanItem` blocks (preventing late-day validation failures) and `HourlyActionPlanResponse` validates 1..6 `MinuteActionItem` steps (`duration_minutes` 5..60)"
    - "`LLMGateway` exposes typed planning and dialogue helper methods routing `action_decomposition` to `routine_model` and `daily_plan` / `replan` to `planning_model`"
    - "`backend/llm/prompts/planning.py` and `backend/llm/prompts/conversation.py` format grounded prompts without injecting false-positive urgent keywords into static template text"
    - "`MockProvider` deterministically generates `ReplanResponse` (starting from prompt's current hour), `HourlyActionPlanResponse`, and rumor-propagating dialogue/summaries across offline tests"
  artifacts:
    - "backend/llm/schemas.py defines `ReplanResponse`, `MinuteActionItem`, and `HourlyActionPlanResponse` with `ConfigDict(extra='forbid')`"
    - "backend/llm/gateway.py exposes `generate_daily_plan`, `generate_replan`, `generate_hourly_actions`, `decide_conversation`, `generate_dialogue_turn`, and `summarize_conversation`"
    - "backend/llm/prompts/planning.py and backend/llm/prompts/conversation.py provide pure typed prompt builders"
    - "backend/llm/providers/mock.py handles `ReplanResponse`, `HourlyActionPlanResponse`, and rumor-preserving conversation initiation, utterances, and summaries"
    - "backend/tests/test_llm_gateway.py verifies all new schemas, prompt builders, gateway helpers, late-hour replanning, and rumor preservation offline"
  key_links:
    - "backend/llm/gateway.py imports `ReplanResponse` and `HourlyActionPlanResponse` from `llm.schemas`"
    - "backend/llm/prompts/planning.py and backend/llm/prompts/conversation.py consume `AgentPersona` from `agents.personas` and `DailyPlanItem` from `llm.schemas`"
    - "backend/llm/providers/mock.py parses standardized prompt markers produced by `llm.prompts`"
---

# Plan 3.1: LLM Planning & Dialogue Schemas, Prompt Templates, Gateway Helpers & Rumor-Aware MockProvider

## Objective
Complete the LLM layer for Phase 3 so the hierarchical planner and conversation manager have strict Pydantic v2 schemas (`ReplanResponse`, `HourlyActionPlanResponse`, `MinuteActionItem`), clean prompt templates in `backend/llm/prompts/`, typed `LLMGateway` helper methods, and a context-aware `MockProvider` that supports partial-day replanning and preserves injected events/rumors across dialogue turns and summaries.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/3/RESEARCH.md
- backend/llm/schemas.py
- backend/llm/gateway.py
- backend/llm/providers/mock.py
- backend/agents/personas.py
- backend/tests/test_llm_gateway.py

## Tasks

<task type="auto">
  <name>Add Replan/Hourly schemas and typed LLMGateway helper methods</name>
  <files>
    backend/llm/schemas.py
    backend/llm/gateway.py
  </files>
  <action>
    Extend `backend/llm/schemas.py` and `backend/llm/gateway.py` with Phase 3 structured output models and gateway convenience wrappers.

    Steps:
    1. In `backend/llm/schemas.py`, add three strict `BaseModel` classes with `model_config = ConfigDict(extra="forbid")`:
       - `ReplanResponse`: `items: list[DailyPlanItem] = Field(min_length=1, max_length=8)` so late-day interruptions with fewer than 5 hours left validate cleanly.
       - `MinuteActionItem`: `duration_minutes: int = Field(ge=5, le=60)`, `location: str = Field(min_length=1)`, `action: str = Field(min_length=1)`.
       - `HourlyActionPlanResponse`: `hourly_focus: str = Field(min_length=1)`, `actions: list[MinuteActionItem] = Field(min_length=1, max_length=6)`.
    2. In `backend/llm/gateway.py`, import `ReplanResponse` and `HourlyActionPlanResponse` and add typed async helper methods on `LLMGateway` delegating to `self.generate(...)`:
       - `generate_daily_plan(self, prompt: str, *, tick: int, agent_id: str, system_instruction: str | None = None) -> DailyPlanResponse` (`purpose="daily_plan"`)
       - `generate_replan(self, prompt: str, *, tick: int, agent_id: str, system_instruction: str | None = None) -> ReplanResponse` (`purpose="replan"`)
       - `generate_hourly_actions(self, prompt: str, *, tick: int, agent_id: str, system_instruction: str | None = None) -> HourlyActionPlanResponse` (`purpose="action_decomposition"`, intentionally NOT in `_PLANNING_PURPOSES` and without `"plan"` in the string so `_resolve_requested_model` routes it to `routine_model`)
       - `decide_conversation(self, prompt: str, *, tick: int, agent_id: str, system_instruction: str | None = None) -> ConversationDecisionResponse` (`purpose="conversation_decide"`)
       - `generate_dialogue_turn(self, prompt: str, *, tick: int, agent_id: str, system_instruction: str | None = None) -> DialogueTurnResponse` (`purpose="dialogue_turn"`)
       - `summarize_conversation(self, prompt: str, *, tick: int, agent_id: str, system_instruction: str | None = None) -> ConversationSummaryResponse` (`purpose="conversation_summary"`)

    AVOID: Putting `"plan"` in the `purpose` string for `generate_hourly_actions` because `_resolve_requested_model` checks `if normalized_purpose in _PLANNING_PURPOSES or "plan" in normalized_purpose:` and would mistakenly route routine minute decomposition to the expensive `planning_model`.
    USE: `purpose="action_decomposition"` and strict `ConfigDict(extra="forbid")` on all schemas.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check llm/schemas.py llm/gateway.py
    .venv\Scripts\mypy.exe llm/schemas.py llm/gateway.py
  </verify>
  <done>
    `ReplanResponse`, `MinuteActionItem`, and `HourlyActionPlanResponse` exist in `llm/schemas.py`, `LLMGateway` exposes all 6 typed helper methods, and `ruff` + strict `mypy` pass with zero errors.
  </done>
</task>

<task type="auto">
  <name>Create planning and conversation prompt template modules</name>
  <files>
    backend/llm/prompts/__init__.py
    backend/llm/prompts/planning.py
    backend/llm/prompts/conversation.py
  </files>
  <action>
    Implement reusable, well-structured prompt builders in `backend/llm/prompts/` for hierarchical planning and grounded agent-to-agent conversations.

    Steps:
    1. Create `backend/llm/prompts/planning.py` with:
       - `build_daily_plan_prompt(*, persona: AgentPersona, sim_time: str, valid_locations: Sequence[str], memories: Sequence[str]) -> str`:
         Includes `persona.summary_text()`, `Sim time: {sim_time}`, `Valid locations: {', '.join(valid_locations)}`, bulleted `Context memories:` (or `(none)`), and asks for 5–8 contiguous `DailyPlanItem` blocks covering waking hours (`06:00`–`22:00` / `24:00`).
       - `build_hourly_action_prompt(*, persona: AgentPersona, block: DailyPlanItem, current_hour: int, current_minute: int, valid_locations: Sequence[str], memories: Sequence[str]) -> str`:
         Includes standardized parseable lines `Block: {block.start_hour:02d}:00-{block.end_hour:02d}:00 at {block.location}` and `Current time: {current_hour:02d}:{current_minute:02d}`, `Block goal: {block.description}`, `Valid locations: ...`, and recent `Context memories:`.
       - `build_replan_prompt(*, persona: AgentPersona, current_hour: int, sim_time: str, interruption_reason: str, remaining_blocks: Sequence[DailyPlanItem], valid_locations: Sequence[str], memories: Sequence[str]) -> str`:
         Includes standardized lines `Current hour: {current_hour}`, `Sim time: {sim_time}`, `Interruption: {interruption_reason}`, remaining scheduled items, `Valid locations: ...`, and `Context memories:`.
    2. Create `backend/llm/prompts/conversation.py` with:
       - `build_conversation_decision_prompt(*, speaker: AgentPersona, listener: AgentPersona, location: str, sim_time: str, speaker_action: str, listener_action: str, memories: Sequence[str]) -> str`
       - `build_dialogue_turn_prompt(*, speaker: AgentPersona, listener: AgentPersona, location: str, sim_time: str, turn_index: int, max_turns: int, memories: Sequence[str], transcript: Sequence[tuple[str, str]]) -> str`
       - `build_conversation_summary_prompt(*, speaker_a: AgentPersona, speaker_b: AgentPersona, location: str, sim_time: str, transcript: Sequence[tuple[str, str]]) -> str`
       - Keep static prompt wording concise and natural (`"Context memories:"`, `"Transcript:"`, `"Participants:"`, `"Location:"`).
    3. Export the six prompt builders from `backend/llm/prompts/__init__.py`.

    AVOID: Including any of `_URGENT_KEYWORDS` (`"fire"`, `"emergency"`, `"rumor"`, `"rumour"`, `"argument"`, `"secret"`, `"discovered"`) or `"[EVENT]"` in the static prompt boilerplate text, because `MockProvider` inspects prompts for those markers to detect real injected events/rumors.
    USE: Neutral structural headings (`"Context memories:"`, `"Interruption:"`, `"Transcript:"`) and canonical location lists.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check llm/prompts
    .venv\Scripts\mypy.exe llm/prompts
  </verify>
  <done>
    `backend/llm/prompts/planning.py`, `conversation.py`, and `__init__.py` cleanly compile and pass `ruff` + strict `mypy` with neutral boilerplate and standardized parseable lines.
  </done>
</task>

<task type="auto">
  <name>Upgrade MockProvider for replanning, hourly actions, and rumor propagation plus unit tests</name>
  <files>
    backend/llm/providers/mock.py
    backend/tests/test_llm_gateway.py
  </files>
  <action>
    Upgrade `MockProvider` in `backend/llm/providers/mock.py` to support all Phase 3 schemas and deterministic multi-hop rumor propagation, and expand `backend/tests/test_llm_gateway.py`.

    Steps:
    1. In `backend/llm/providers/mock.py`:
       - Import `HourlyActionPlanResponse` and `ReplanResponse` from `llm.schemas`.
       - Add a helper `_extract_salient_topic(prompt: str) -> str | None` that scans prompt lines for:
         a) explicit event/interruption/rumor markers (`"[event]"`, `"observed event:"`, `"interruption:"`, `"heard news:"`, `"discussed:"`, or `"conversation with "`) and extracts the substantive payload text (truncated cleanly to ~110 chars), OR
         b) any line matching `_URGENT_KEYWORDS` (excluding static instruction headers).
       - Add a helper `_extract_prompt_location(text: str) -> str | None` that checks `_LOCATIONS` case-insensitively inside a text snippet.
       - Update `_build_payload(...)`:
         - Handle `ReplanResponse`: parse `Current hour: (\d+)` (clamped `0..23`), build `1..min(4, max(1, 24 - start_hour))` contiguous `DailyPlanItem` blocks covering `[start_hour, 24]`; if `_extract_salient_topic` or `_extract_prompt_location` detects an event/location, point block 0 to that location and reference the topic in its description.
         - Handle `HourlyActionPlanResponse`: parse `Block: (\d+):00-(\d+):00 at ([^\n]+)` and `Current time: (\d+):(\d+)` (with safe defaults), returning `hourly_focus` and `1..3` `MinuteActionItem` steps (`duration_minutes` in `10..45`) anchored to that location (valid against `_LOCATIONS`).
         - Handle `ImportanceBatchResponse` (`_build_importance_batch`): give high importance (`7..9`) when item text contains `_URGENT_KEYWORDS` OR `"[event]"` / `"event at "` / `"heard "` / `"discussed:"` so non-keyword god-mode events and 2nd-hop rumors also rate high.
         - Handle `ConversationDecisionResponse`: if `_extract_salient_topic(prompt)` returns a topic, force `initiate=True`, explain `"Sharing important village news with nearby neighbor."`, and embed the topic into `opening_line` (`f"Have you heard? {topic}"`); otherwise preserve deterministic `(digest[0] % 2) == 0` fallback.
         - Handle `DialogueTurnResponse`: if `_extract_salient_topic(prompt)` returns a topic, embed the exact topic text into `utterance` (e.g. `f"Everyone should know about this: {topic}"` or `f"Wait, regarding {topic} — I'll adjust my plans."`); otherwise pick from `_DIALOGUE_POOL`.
         - Handle `ConversationSummaryResponse`: extract participant names (if present) and `_extract_salient_topic(prompt)` from prompt/transcript; when a salient topic is found, return `summary = f"{participants} discussed: {topic}"` (preserving the exact event/rumor phrase for 2-hop memory retrieval!); otherwise keep neutral routine summary.
    2. In `backend/tests/test_llm_gateway.py`:
       - Verify `test_mock_provider_deterministic_and_schema_valid_across_all_schemas` still passes and include `ReplanResponse` and `HourlyActionPlanResponse`.
       - Add tests for:
         - Late-evening replan (`Current hour: 22`) returning `1 <= len(items) <= 2` valid `DailyPlanItem`s with `start_hour >= 22`.
         - `HourlyActionPlanResponse` decomposition returning valid `MinuteActionItem`s (`5 <= duration_minutes <= 60`) and routing `generate_hourly_actions` to `routine_model` while `generate_daily_plan` / `generate_replan` route to `planning_model`.
         - Multi-hop rumor preservation in `MockProvider`: an `[EVENT]` prompt line triggers `ConversationDecisionResponse.initiate == True`, appears in `DialogueTurnResponse.utterance`, and survives in `ConversationSummaryResponse.summary`.

    AVOID: Breaking determinism (`seed=42` must remain byte-identical for identical prompts) or rejecting prompts without structured headers (keep safe defaults for raw unit-test prompts).
    USE: Regex header parsing with safe fallbacks and `_extract_salient_topic` preservation across decision, turn, and summary responses.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_llm_gateway.py
    .venv\Scripts\ruff.exe check llm tests/test_llm_gateway.py
    .venv\Scripts\mypy.exe llm tests/test_llm_gateway.py
  </verify>
  <done>
    All tests in `tests/test_llm_gateway.py` pass offline, `MockProvider` handles `ReplanResponse`, `HourlyActionPlanResponse`, and multi-hop rumor propagation deterministically, and `ruff` + strict `mypy` pass cleanly.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `ReplanResponse`, `MinuteActionItem`, and `HourlyActionPlanResponse` are strict Pydantic v2 schemas in `backend/llm/schemas.py`
- [ ] `LLMGateway` exposes typed planning and dialogue helpers with `action_decomposition` routed to `routine_model`
- [ ] Prompt templates in `backend/llm/prompts/` cleanly support planning and dialogue without false-positive urgent keyword collisions
- [ ] `MockProvider` deterministically preserves injected events/rumors through decision, dialogue turns, and conversation summary

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero regressions in existing `test_llm_gateway.py` cases
