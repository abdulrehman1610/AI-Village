---
phase: 3
plan: 1
completed_at: 2026-11-24T13:43:15+05:00
duration_minutes: 8
---

# Summary: Plan 3.1 — LLM Planning & Dialogue Schemas, Prompt Templates, Gateway Helpers & Rumor-Aware MockProvider

## Results
- 3 tasks completed atomically with per-task commits
- All plan-specific and full-backend verifications passed offline with zero network calls (`pytest`: 70 passed, `ruff check .`: passed, `mypy .`: 0 issues across 40 files)

## Tasks Completed
| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Add Replan/Hourly schemas and typed LLMGateway helper methods | `5cfaa23` | ✅ |
| 2 | Create planning and conversation prompt template modules | `42f251a` | ✅ |
| 3 | Upgrade MockProvider for replanning, hourly actions, and rumor propagation plus unit tests | `4de3391` | ✅ |

## Deviations Applied
None — executed as planned.

## Files Changed
- `backend/llm/schemas.py` — Added strict `ConfigDict(extra="forbid")` schemas: `ReplanResponse` (`1..8` `DailyPlanItem` blocks), `MinuteActionItem` (`duration_minutes` `5..60`), and `HourlyActionPlanResponse` (`1..6` `MinuteActionItem` steps).
- `backend/llm/gateway.py` — Added typed async wrapper methods on `LLMGateway`: `generate_daily_plan`, `generate_replan`, `generate_hourly_actions` (`purpose="action_decomposition"` routed to `routine_model`), `decide_conversation`, `generate_dialogue_turn`, and `summarize_conversation`.
- `backend/llm/prompts/planning.py` — Added `build_daily_plan_prompt`, `build_hourly_action_prompt`, and `build_replan_prompt` with standardized parseable markers (`Block:`, `Current time:`, `Current hour:`, `Interruption:`) and neutral boilerplate.
- `backend/llm/prompts/conversation.py` — Added `build_conversation_decision_prompt`, `build_dialogue_turn_prompt`, and `build_conversation_summary_prompt` with neutral headings (`Participants:`, `Location:`, `Context memories:`, `Transcript:`).
- `backend/llm/prompts/__init__.py` — Exported all six planning and conversation prompt builders.
- `backend/llm/providers/mock.py` — Added `ReplanResponse` and `HourlyActionPlanResponse` builders, `_extract_salient_topic`, `_extract_prompt_location`, and `_extract_participants` helpers, updated `_build_importance_batch` for `[event]` / `heard ` / `discussed:` markers, and enabled deterministic multi-hop event/rumor propagation across conversation decisions, turns, and summaries while skipping persona metadata headers (e.g., Maya's `"fire the village ovens"` bio) and neutral routine conversation summaries.
- `backend/tests/test_llm_gateway.py` — Extended schema determinism tests to cover `ReplanResponse` and `HourlyActionPlanResponse`, and added tests for late-evening (`22:00`, `23:00`) replanning, hourly minute-action decomposition, gateway `routine_model`/`planning_model` routing, persona-bio false-positive immunity, and 2-hop non-keyword `[EVENT]` rumor propagation + importance scoring.

## Verification
- `python -m ruff check llm/schemas.py llm/gateway.py` (in `backend/`): ✅ All checks passed!
- `python -m mypy llm/schemas.py llm/gateway.py` (in `backend/`): ✅ Success: no issues found in 2 source files
- `python -m ruff check llm/prompts` (in `backend/`): ✅ All checks passed!
- `python -m mypy llm/prompts` (in `backend/`): ✅ Success: no issues found in 3 source files
- `python -m ruff check llm tests/test_llm_gateway.py` (in `backend/`): ✅ All checks passed!
- `python -m mypy llm tests/test_llm_gateway.py` (in `backend/`): ✅ Success: no issues found in 11 source files
- `python -m pytest -v tests/test_llm_gateway.py` (in `backend/`): ✅ 10 passed in 1.74s
- `python -m pytest` (in `backend/`): ✅ 70 passed in 4.10s
- `python -m ruff check .` (in `backend/`): ✅ All checks passed!
- `python -m mypy .` (in `backend/`): ✅ Success: no issues found in 40 source files
