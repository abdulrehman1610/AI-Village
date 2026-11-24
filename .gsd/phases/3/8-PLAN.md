---
phase: 3
plan: 8
wave: 5
gap_closure: true
depends_on:
  - "1"
  - "6"
files_modified:
  - backend/agents/personas.py
  - backend/llm/providers/mock.py
  - backend/tests/test_llm_gateway.py
  - backend/tests/test_phase3_integration.py
autonomous: true
must_haves:
  truths:
    - "Seeded persona bios and persisted persona summary memories never trigger false-positive urgent/rumor mode in `MockProvider`"
    - "During an 80-tick baseline `SimulationEngine` run with `MockProvider` and zero injected events, zero spontaneous replans occur and every agent preserves its 5–8 block wake-up daily plan"
    - "Real god-mode events (`POST /events` / `inject_event`, both urgent-keyword and non-keyword) still trigger replanning and 2-hop rumor propagation (`Event -> Agent A -> Agent B -> Agent C`)"
  artifacts:
    - "backend/agents/personas.py eliminates accidental urgent-keyword collision in Maya's bio"
    - "backend/llm/providers/mock.py skips persisted persona summary/goal lines in `_extract_salient_topic` and `_build_importance_batch`"
    - "backend/tests/test_llm_gateway.py verifies `MockProvider` immunity when `persona.summary_text()` is passed inside `Context memories:`"
    - "backend/tests/test_phase3_integration.py enforces zero false-positive replans and clean 5–8 block plans across an 80-tick baseline simulation"
  key_links:
    - "backend/sim/engine.py `initialize_persistence()` seeds `persona.summary_text()` memories that `MemoryRetriever` returns into `llm.prompts` and `MockProvider`"
---

# Plan 3.8: Gap Closure — Eliminate Seeded Persona Bio False-Positive Rumor & Replan Cascade

## Objective
Fix the deferred defect from Phase 3 execution (`6-SUMMARY.md`) where Maya's seeded persona bio (`"fire the village ovens"`) persisted by `SimulationEngine.initialize_persistence()` is retrieved into `Context memories:`, matches `_URGENT_KEYWORD_PATTERN` in `MockProvider._extract_salient_topic()`, and triggers a village-wide cascade of fake bio-rumor dialogues and spontaneous daily replans even when zero events have been injected.

## Context
Load these files for context:
- .gsd/phases/3/VERIFICATION.md
- .gsd/phases/3/6-SUMMARY.md
- backend/agents/personas.py
- backend/llm/providers/mock.py
- backend/sim/engine.py
- backend/tests/test_llm_gateway.py
- backend/tests/test_phase3_integration.py

## Tasks

<task type="auto">
  <name>Eliminate persona-bio false positives in personas.py and MockProvider</name>
  <files>
    backend/agents/personas.py
    backend/llm/providers/mock.py
  </files>
  <action>
    Apply defense-in-depth across `backend/agents/personas.py` and `backend/llm/providers/mock.py` so seeded villager biographies and starting goals never trigger urgent-event or rumor propagation paths.

    Steps:
    1. In `backend/agents/personas.py`, update Maya's `bio` from `"to fire the village ovens"` to `"to heat the village ovens"` (removing the incidental urgent keyword `"fire"` from the seeded persona profile while preserving character meaning and length constraints).
    2. In `backend/llm/providers/mock.py`:
       - Add a helper `_is_seeded_persona_memory(line: str) -> bool` that identifies bulleted/plain persona summary and goal memories seeded by `SimulationEngine.initialize_persistence()` (e.g., matching `"lives at "` + `"traits:"` + `"starting goals:"`, or `"'s goal:"` without event/conversation markers like `"[event]"`, `"observed event:"`, `"discussed:"`, `"heard news:"`).
       - Skip `_is_seeded_persona_memory(line)` entries in `_extract_salient_topic(prompt)` before scanning `_URGENT_KEYWORD_PATTERN`, and treat seeded persona memories as routine (`is_urgent = False`) in `_build_importance_batch(...)`.

    AVOID: Suppressing genuine `[EVENT]` or `Conversation with ... discussed:` memories or altering `Maya`'s `home_location`, `default_routine`, `id`, or `sprite_index`.
    USE: Both neutral phrasing in `personas.py` and structural persona-memory filtering in `mock.py`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check agents/personas.py llm/providers/mock.py
    .venv\Scripts\mypy.exe agents/personas.py llm/providers/mock.py
  </verify>
  <done>
    `personas.py` and `mock.py` pass `ruff` and strict `mypy`, and no seeded persona bio/goal triggers `_extract_salient_topic` or urgent importance ratings.
  </done>
</task>

<task type="auto">
  <name>Add regression guards in test_llm_gateway.py and tighten baseline assertions in test_phase3_integration.py</name>
  <files>
    backend/tests/test_llm_gateway.py
    backend/tests/test_phase3_integration.py
  </files>
  <action>
    Prove empirically that baseline simulations with zero injected events do not falsely replan or spread persona bios as rumors, while real god-mode events continue to replan and propagate across hops.

    Steps:
    1. In `backend/tests/test_llm_gateway.py` (`test_mock_provider_rumor_propagation_and_neutral_persona_guard`):
       - Include `maya.summary_text()` and `f"{maya.name}'s goal: {maya.starting_goals[0]}"` inside `memories=[...]` on the routine `ConversationDecisionResponse` check, plus test a synthetic `"lives at Home_Test. Traits: ... fire ... Starting goals: ..."` memory directly against `MockProvider` (`ConversationDecisionResponse` + `ImportanceBatchResponse`) to verify `_is_seeded_persona_memory` blocks false positives even if a future persona uses an urgent word.
    2. In `backend/tests/test_phase3_integration.py` (`test_engine_80_ticks_cognitive_loop_and_dialogue`):
       - Restore strict `assert 5 <= len(parsed_plan) <= 8` for all 8 agents' `current_plan_json` (since no events were injected).
       - Assert every agent has exactly 1 `"plan"` memory (`len(plan_memories) == 1`, zero spontaneous replans) and zero dialogue summaries contain `"Traits:"` or `"lives at Home_"`.
    3. Run full backend `pytest`, `ruff check .`, `mypy .`, and `scripts/verify_phase1_ws.py`.

    AVOID: Weakening integration assertions to hide unexpected replans.
    USE: Strict 5–8 block plan assertions and zero-spontaneous-replan checks in the 80-tick baseline test.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v
    .venv\Scripts\ruff.exe check .
    .venv\Scripts\mypy.exe .
    Run from repo root (separate command):
    backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py
  </verify>
  <done>
    All backend tests pass with strict 5–8 block / zero false-replan assertions in baseline 80-tick simulation, `ruff` and strict `mypy` report zero issues, and `scripts/verify_phase1_ws.py` exits 0.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] Baseline 80-tick `SimulationEngine` run with `MockProvider` produces zero false-positive bio-rumor dialogues and zero spontaneous replans (`5 <= len(blocks) <= 8` for all 8 agents)
- [ ] `MockProvider` explicitly guards against seeded persona summary/goal memories while preserving 2-hop `[EVENT]` rumor spread
- [ ] Full `pytest`, `ruff check .`, `mypy .`, `scripts/verify_phase1_ws.py`, and `npm --prefix frontend run build` pass cleanly

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero regressions in Phase 1, Phase 2, or Phase 3 suites
