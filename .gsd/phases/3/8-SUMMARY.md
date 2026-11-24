---
phase: 3
plan: 8
completed_at: 2026-11-24T16:06:00+05:00
duration_minutes: 6
---

# Summary: Plan 3.8 — Gap Closure — Eliminate Seeded Persona Bio False-Positive Rumor & Replan Cascade

## Results
- 2 tasks completed atomically with per-task commits (`d9e643f`, `17dc7b5`)
- Eliminated the false-positive urgent keyword trigger on Maya's seeded persona bio (`"fire the village ovens"`) and added structural persona-memory filtering in `MockProvider`
- Verified 80-tick baseline `SimulationEngine` runs with `MockProvider(seed=42)` produce zero spontaneous replans (`5..8` plan blocks and `1` `"plan"` memory per agent) and zero bio-rumor leaks across all 12 baseline conversations while preserving 2-hop `[EVENT]` rumor propagation
- All backend tests (`88 passed`), `ruff check .`, `mypy .`, `scripts/verify_phase1_ws.py`, and `npm --prefix frontend run build` passed

## Tasks Completed
| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Eliminate persona-bio false positives in `personas.py` and `MockProvider` | `d9e643f` | ✅ |
| 2 | Add regression guards in `test_llm_gateway.py` and tighten baseline assertions in `test_phase3_integration.py` | `17dc7b5` | ✅ |

## Deviations Applied
None — executed as planned.

## Files Changed
- `backend/agents/personas.py` — Updated Maya's `bio` phrasing from `"to fire the village ovens"` to `"to heat the village ovens"` while preserving `home_location`, `default_routine`, `id`, and `sprite_index`.
- `backend/llm/providers/mock.py` — Added `_NON_SEEDED_MEMORY_MARKERS`, `_SEEDED_GOAL_PATTERN`, and `_is_seeded_persona_memory(line)` to ignore seeded persona summary (`lives at ... Traits: ... Starting goals: ...`) and starting-goal (`<Name>'s goal: ...`) memories in `_extract_salient_topic()`, `_build_replan()`, and `_build_importance_batch()` unless an explicit event/conversation/rumor marker is present.
- `backend/tests/test_llm_gateway.py` — Updated `test_mock_provider_rumor_propagation_and_neutral_persona_guard` to pass `maya.summary_text()`, Maya's starting goal, and synthetic `"lives at Home_Test. Traits: ... fire ... Starting goals: ..."` / `"'s goal:"` memories containing `"fire"` directly against `MockProvider` (`ConversationDecisionResponse` and `ImportanceBatchResponse`) and `LLMGateway.rate_importance_batch`.
- `backend/tests/test_phase3_integration.py` — Tightened `test_engine_80_ticks_cognitive_loop_and_dialogue` to assert strict `5 <= len(parsed_plan) <= 8`, `len(plan_memories) == 1` per agent, and zero `"Traits:"` or `"lives at Home_"` leaks in emitted dialogue payloads or persisted `ConversationRecord.summary` entries.

## Verification
- `Set-Location backend; .venv\Scripts\ruff.exe check agents/personas.py llm/providers/mock.py`: ✅ `All checks passed!`
- `Set-Location backend; .venv\Scripts\mypy.exe agents/personas.py llm/providers/mock.py`: ✅ `Success: no issues found in 2 source files`
- 80-tick baseline `SimulationEngine` + `MockProvider(seed=42)` diagnostic: ✅ 8/8 agents maintained `5..8` blocks (`plan_mems: 1` each), 12/12 conversations recorded `"Exchanged updates about daily routines and village happenings."`, `usage: {'total_calls': 132, 'cache_hits': 18, 'tokens_in': 43960, 'tokens_out': 4577, 'total_tokens': 48537, 'cost_est': 0.0}`
- `Set-Location backend; .venv\Scripts\pytest.exe -v`: ✅ `88 passed in 10.94s`
- `Set-Location backend; .venv\Scripts\ruff.exe check .`: ✅ `All checks passed!`
- `Set-Location backend; .venv\Scripts\mypy.exe .`: ✅ `Success: no issues found in 47 source files`
- `backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py`: ✅ `e2e_ws_ok ticks=[0, 1, 2, 3, 4, 5] moved_agents=7`
- `npm --prefix frontend run build`: ✅ `✓ 13 modules transformed.` / `✓ built in 9.26s`

## Deferred
None.
