---
phase: 2
plan: 2
completed_at: 2026-11-24T12:01:00+05:00
duration_minutes: 8
---

# Summary: Plan 2.2 — Schema-Enforced LLM Gateway, Providers, Cache & Budget Control

## Results
- 3/3 tasks completed
- Implemented strict Pydantic v2 LLM output schemas, `LLMProvider` protocol, deterministic `MockProvider`, lazy `GeminiProvider`, and `LLMGateway`
- Enforced SHA-256 prompt caching (`cache_hit=True`, zero tokens/cost), 1-retry validation repair, daily token/USD budget fallback to `MockProvider`, batched importance scoring, and `llm_calls` SQLite telemetry
- All offline unit tests (`7` new tests in `tests/test_llm_gateway.py`, `55` total backend tests), `ruff check`, and strict `mypy` passed with zero errors

## Tasks Completed
| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Define Pydantic v2 LLM schemas, LLMProvider protocol, and deterministic MockProvider | `e0b54ec` | ✅ |
| 2 | Implement GeminiProvider and LLMGateway with cache, 1-retry repair, budget, and SQLite logging | `3d56f40` | ✅ |
| 3 | Write offline unit tests for LLMGateway, MockProvider, and GeminiProvider | `344e20c` | ✅ |

## Deviations Applied
None — executed as planned.
- Note: `GeminiProvider.generate_raw()` lazily imports `from google.genai import types` alongside `from google import genai` inside `_get_client()` so non-Gemini callers and tests avoid the `~1.21s` cold `google.genai.types` import penalty.
- Note: When `fallback_provider=None` is passed to `LLMGateway.__init__`, it defaults to `MockProvider(seed=seed)` so daily budget exhaustion cleanly falls back without risking a `None` provider error.

## Deferred
- Pre-existing workspace modifications outside Plan 2.2 scope (`backend/api/__init__.py`, `backend/app/__init__.py`, `backend/sim/__init__.py`, `backend/tests/__init__.py`, and untracked GSD tooling files) were intentionally left out of task commits.

## Files Changed
- `backend/llm/__init__.py` — Added `llm` package marker.
- `backend/llm/prompts/__init__.py` — Added `llm.prompts` package marker.
- `backend/llm/providers/__init__.py` — Added `llm.providers` package marker.
- `backend/llm/schemas.py` — Defined strict (`extra="forbid"`) Pydantic v2 models: `ImportanceBatchResponse`, `DailyPlanItem`, `DailyPlanResponse`, `ConversationDecisionResponse`, `DialogueTurnResponse`, `ConversationSummaryResponse`, `SalientQuestionsResponse`, `ReflectionInsight`, and `ReflectionResponse`.
- `backend/llm/providers/base.py` — Defined `ProviderResult` dataclass and `@runtime_checkable class LLMProvider`.
- `backend/llm/providers/mock.py` — Implemented zero-network SHA-256-seeded `MockProvider` supporting all schemas and keyword-aware `ImportanceBatchResponse` slot parsing via `Item count: (\d+)`.
- `backend/llm/providers/gemini.py` — Implemented lazy `GeminiProvider` wrapping `google.genai` `aio.models.generate_content` with `GenerateContentConfig(response_mime_type="application/json", response_schema=...)` and `usage_metadata` extraction.
- `backend/llm/gateway.py` — Implemented `LLMGateway`, `LLMGatewayError`, `MODEL_PRICING_PER_MILLION`, `estimate_cost_usd()`, SHA-256 prompt cache, `asyncio.Lock`-guarded daily token/USD budget gate, 1-retry validation repair loop, `rate_importance_batch()`, `get_usage_summary()`, and `LLMCallRecord` SQLite persistence.
- `backend/tests/test_llm_gateway.py` — Added 7 offline async unit tests covering `MockProvider` determinism/validity, DB telemetry & cache hits, 1-retry repair & `LLMGatewayError`, daily token/USD budget fallback & Day 2 reset, `rate_importance_batch()`, and `GeminiProvider` offline behavior with an injected fake client.

## Verification
- `.venv\Scripts\pytest.exe -v tests/test_llm_gateway.py` (in `backend/`) → `7 passed in 1.51s` (exit 0)
- `.venv\Scripts\ruff.exe check .` (in `backend/`) → `All checks passed!` (exit 0)
- `.venv\Scripts\mypy.exe app sim api memory llm tests` (in `backend/`) → `Success: no issues found in 31 source files` (exit 0)
- `.venv\Scripts\pytest.exe -q` (in `backend/`) → `55 passed in 2.99s` (exit 0)
