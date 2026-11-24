---
phase: 2
plan: 2
wave: 2
depends_on:
  - "1"
files_modified:
  - backend/llm/__init__.py
  - backend/llm/schemas.py
  - backend/llm/prompts/__init__.py
  - backend/llm/providers/__init__.py
  - backend/llm/providers/base.py
  - backend/llm/providers/mock.py
  - backend/llm/providers/gemini.py
  - backend/llm/gateway.py
  - backend/tests/test_llm_gateway.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "Every LLM call goes through `LLMGateway`, validates output against Pydantic v2 schemas, and retries once (`max_retries=1`) with a validation-error repair prompt before failing"
    - "Identical prompts hit the SHA-256 prompt cache and log `cache_hit=True`, `tokens_in=0`, `tokens_out=0`, and `cost_est=0.0` to SQLite `llm_calls`"
    - "Exhausting daily token or USD budget routes uncached calls cleanly to the fallback `MockProvider` without crashing"
    - "`MockProvider` produces deterministic schema-valid JSON offline, while `GeminiProvider` wraps `google.genai` `aio.models.generate_content` with `response_schema`"
  artifacts:
    - "backend/llm/schemas.py defines Pydantic v2 response schemas including `ImportanceBatchResponse`, planning, conversation, and reflection schemas"
    - "backend/llm/providers/base.py defines `ProviderResult` and `@runtime_checkable class LLMProvider`"
    - "backend/llm/providers/mock.py implements deterministic zero-network `MockProvider`"
    - "backend/llm/providers/gemini.py implements lazy `GeminiProvider` supporting injected clients for offline unit tests"
    - "backend/llm/gateway.py implements `LLMGateway`, `LLMGatewayError`, cost calculation, cache, retry repair, budget gate, `rate_importance_batch()`, and SQLite logging"
    - "backend/tests/test_llm_gateway.py verifies schemas, cache hit, 1-retry repair, error handling, budget fallback, batch importance scoring, and `GeminiProvider` offline"
  key_links:
    - "backend/llm/gateway.py persists every provider attempt and cache hit to `LLMCallRecord` via `Database.session()`"
    - "backend/llm/gateway.py enforces CON-02/CON-03 by keeping all provider SDK invocations inside `backend/llm/providers/`"
---

# Plan 2.2: Schema-Enforced LLM Gateway, Providers, Cache & Budget Control

## Objective
Implement the schema-enforcing `LLMGateway` (`backend/llm/gateway.py`), Pydantic v2 structured output schemas (`backend/llm/schemas.py`), the `LLMProvider` protocol (`backend/llm/providers/base.py`), deterministic offline `MockProvider` (`backend/llm/providers/mock.py`), and `google-genai` `GeminiProvider` (`backend/llm/providers/gemini.py`) with SHA-256 prompt caching, 1-retry validation repair, daily token/USD budget fallback, batched importance scoring, and SQLite `llm_calls` logging.

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
  <name>Define Pydantic v2 LLM schemas, LLMProvider protocol, and deterministic MockProvider</name>
  <files>
    backend/llm/__init__.py
    backend/llm/schemas.py
    backend/llm/prompts/__init__.py
    backend/llm/providers/__init__.py
    backend/llm/providers/base.py
    backend/llm/providers/mock.py
  </files>
  <action>
    Create the `llm` package layout, strict Pydantic v2 output schemas, provider protocol, and zero-network deterministic `MockProvider`.

    Steps:
    1. Create package markers `backend/llm/__init__.py`, `backend/llm/prompts/__init__.py`, and `backend/llm/providers/__init__.py`.
    2. Implement `backend/llm/schemas.py` with strict Pydantic v2 models (`ConfigDict(extra="forbid")`):
       - `ImportanceBatchResponse`: `ratings: list[Annotated[int, Field(ge=1, le=10)]]`
       - `DailyPlanItem`: `start_hour: int = Field(ge=0, le=23)`, `end_hour: int = Field(ge=0, le=24)`, `location: str = Field(min_length=1)`, `description: str = Field(min_length=1)`
       - `DailyPlanResponse`: `items: list[DailyPlanItem] = Field(min_length=5, max_length=8)`
       - `ConversationDecisionResponse`: `initiate: bool`, `reason: str`, `opening_line: str = ""`
       - `DialogueTurnResponse`: `utterance: str = Field(min_length=1)`, `continue_dialogue: bool = True`
       - `ConversationSummaryResponse`: `summary: str = Field(min_length=1)`, `affinity_delta: float = Field(default=0.0, ge=-1.0, le=1.0)`, `relationship_note: str = ""`
       - `SalientQuestionsResponse`: `questions: list[str] = Field(min_length=3, max_length=3)`
       - `ReflectionInsight`: `insight: str = Field(min_length=1)`, `cited_memory_ids: list[int] = Field(default_factory=list)`
       - `ReflectionResponse`: `insights: list[ReflectionInsight] = Field(min_length=1)`
    3. Implement `backend/llm/providers/base.py`:
       - `@dataclass(frozen=True) class ProviderResult`: `raw_text: str`, `model: str`, `tokens_in: int = 0`, `tokens_out: int = 0`.
       - `@runtime_checkable class LLMProvider(Protocol)`: property `name: str` and `async def generate_raw(self, *, prompt: str, response_model: type[BaseModel], system_instruction: str | None = None, model_override: str | None = None, temperature: float = 0.2, seed: int | None = None) -> ProviderResult`.
    4. Implement `backend/llm/providers/mock.py` (`MockProvider`):
       - `__init__(self, *, seed: int = 42, model_name: str = "mock-flash") -> None`.
       - Uses `hashlib.sha256(f"{effective_seed}:{response_model.__qualname__}:{prompt}".encode("utf-8")).digest()` to generate reproducible outputs across all schemas in `schemas.py` with zero network I/O.
       - For `ImportanceBatchResponse`: parses `Item count: (\d+)` from `prompt` (falling back to counting `^\s*\d+\.\s+` lines, or `1` if none matched) so `len(ratings)` ALWAYS matches the exact batch item count even if a memory text contains digits or newlines, scoring urgent/social keywords (`fire`, `emergency`, `rumor`, `argument`, `secret`, `discovered`) higher (`7..9`) and routine items lower (`3..6`) deterministically.
       - Estimates realistic deterministic `tokens_in` / `tokens_out` (`max(1, len(prompt) // 4)`, `max(1, len(raw_text) // 4)`).

    AVOID: Using non-deterministic `random` global state or returning arbitrary extra keys that fail `extra="forbid"` schema validation.
    USE: `hashlib.sha256` per call and `model_validate` / `model_dump_json` inside `MockProvider` so every mock response is guaranteed schema-valid.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\ruff.exe check llm/__init__.py llm/schemas.py llm/prompts/__init__.py llm/providers/__init__.py llm/providers/base.py llm/providers/mock.py
    .venv\Scripts\mypy.exe llm/__init__.py llm/schemas.py llm/prompts/__init__.py llm/providers/__init__.py llm/providers/base.py llm/providers/mock.py
  </verify>
  <done>
    All schemas, `LLMProvider` protocol, and `MockProvider` pass `ruff check` and strict `mypy` with zero errors.
  </done>
</task>

<task type="auto">
  <name>Implement GeminiProvider and LLMGateway with cache, 1-retry repair, budget, and SQLite logging</name>
  <files>
    backend/llm/providers/gemini.py
    backend/llm/gateway.py
  </files>
  <action>
    Implement the `google-genai` async provider and the central `LLMGateway` enforcing validation, retries, caching, budget limits, and `llm_calls` logging.

    Steps:
    1. Implement `backend/llm/providers/gemini.py` (`GeminiProvider`):
       - `__init__(self, *, api_key: str, default_model: str = "gemini-2.5-flash", client: Any | None = None) -> None`.
       - `name = "gemini"`.
       - Lazy `_get_client(self) -> Any`: if `self._client is None`, validates `self._api_key.strip()` is non-empty (else raises `RuntimeError("GEMINI_API_KEY is required for GeminiProvider")`), imports `from google import genai` and creates `genai.Client(api_key=self._api_key)`.
       - `generate_raw(...)`: builds `types.GenerateContentConfig(system_instruction=system_instruction, response_mime_type="application/json", response_schema=response_model, temperature=temperature, seed=seed)` and awaits `client.aio.models.generate_content(model=target_model, contents=prompt, config=config)`.
       - Safely extracts `usage = getattr(response, "usage_metadata", None)` -> `tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)`, `tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0)`, `raw_text = str(getattr(response, "text", "") or "")`.
    2. Implement `backend/llm/gateway.py`:
       - Define `class LLMGatewayError(RuntimeError): ...` and `MODEL_PRICING_PER_MILLION: dict[str, tuple[float, float]]` (USD input/output per 1M tokens for `"gemini-2.5-flash"`, `"gemini-2.5-pro"`, `"gemini-2.0-flash"`, defaulting `"mock*"` to `(0.0, 0.0)` and unknown non-mock models to conservative flash fallback rates).
       - Implement `estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float`.
       - Implement `LLMGateway`:
         - `__init__(self, *, provider: LLMProvider, fallback_provider: LLMProvider | None = None, db: Database | None = None, daily_budget_usd: float = 0.50, daily_token_limit: int = 250_000, max_retries: int = 1, routine_model: str | None = None, planning_model: str | None = None, seed: int = 42) -> None`.
         - Maintains prompt cache (`dict[str, tuple[str, str]]` mapping SHA-256 key -> `(cached_json, model_name)`), plus per-day usage counters (`_daily_tokens: dict[int, int]`, `_daily_cost: dict[int, float]`) protected by `asyncio.Lock`.
         - `day_for_tick(tick: int) -> int`: `(max(0, tick) // 1440) + 1` (aligned with `SimClock.day` when starting at 06:00 or `tick // 1440 + 1`).
         - `async def generate(self, prompt: str, response_model: type[T], *, purpose: str, tick: int, agent_id: str | None = None, system_instruction: str | None = None, model_override: str | None = None, temperature: float = 0.2) -> T`:
           1. Compute deterministic cache key from `(target_model_hint, purpose, response_model.__qualname__, system_instruction or "", prompt)`.
           2. **Cache hit**: validate cached JSON via `response_model.model_validate_json(...)`, measure latency, log `LLMCallRecord(..., tokens_in=0, tokens_out=0, cost_est=0.0, cache_hit=True)` to DB (if `db is not None`), and return immediately.
           3. **Budget gate**: check current day's accumulated tokens and cost; if `tokens >= daily_token_limit` or `cost >= daily_budget_usd`, switch `active_provider = self.fallback_provider` (passing `model_override=None` to fallback so mock model is used cleanly).
           4. **Call + 1-retry repair**: loop up to `1 + self.max_retries` attempts:
              - Measure `time.perf_counter()` latency in ms.
              - Call `await active_provider.generate_raw(...)`.
              - Compute `cost = 0.0 if active_provider is self.fallback_provider and active_provider.name == "mock" else estimate_cost_usd(result.model, result.tokens_in, result.tokens_out)`.
              - Update per-day token & cost counters and log `LLMCallRecord` to DB.
              - Try `parsed = response_model.model_validate_json(result.raw_text)`.
              - On success: store `(parsed.model_dump_json(), result.model)` in prompt cache and return `parsed`.
              - On `ValidationError` (which also catches invalid JSON): if attempts remain, construct a concise repair prompt appending the Pydantic error string and invalid output snippet and retry once; if retries exhausted, raise `LLMGatewayError`.
         - `async def rate_importance_batch(self, texts: Sequence[str], *, tick: int, agent_id: str | None = None, purpose: str = "importance_batch") -> list[int]`:
           - Returns `[]` if `texts` is empty.
           - Builds prompt with `Item count: {len(texts)}` and numbered items (`1. ...`, `2. ...`) asking for exact count `len(texts)` ratings in `[1, 10]`.
           - Calls `self.generate(..., response_model=ImportanceBatchResponse, ...)`.
           - Validates `len(result.ratings) == len(texts)` (raising `LLMGatewayError` if mismatched).
         - `async def get_usage_summary(self, *, tick: int | None = None) -> dict[str, float | int]`: returns aggregated call counts, tokens, cost, and cache hits (querying `llm_calls` when `db` is attached or in-memory counters otherwise).

    AVOID: Instantiating `genai.Client()` at import time (breaks offline CI when `GEMINI_API_KEY` is blank) or skipping DB logging on failed validation attempts / cache hits.
    USE: Lazy `genai.Client` creation inside `GeminiProvider._get_client()` and guaranteed DB logging per provider invocation and cache hit.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\ruff.exe check llm/providers/gemini.py llm/gateway.py
    .venv\Scripts\mypy.exe llm/providers/gemini.py llm/gateway.py
  </verify>
  <done>
    `backend/llm/providers/gemini.py` and `backend/llm/gateway.py` pass `ruff check` and strict `mypy` with zero errors.
  </done>
</task>

<task type="auto">
  <name>Write offline unit tests for LLMGateway, MockProvider, and GeminiProvider</name>
  <files>
    backend/tests/test_llm_gateway.py
  </files>
  <action>
    Write comprehensive offline tests in `backend/tests/test_llm_gateway.py` covering every gateway guarantee with zero external network calls.

    Steps:
    1. Test `MockProvider` determinism and schema validity across all schemas in `backend/llm/schemas.py` (including two runs with identical seed producing byte-identical JSON).
    2. Test `LLMGateway` with `:memory:` `Database`:
       - Single call persists `LLMCallRecord` (`purpose`, `model`, `tokens_in > 0`, `tokens_out > 0`, `latency_ms >= 0`, `cache_hit=False`).
       - Repeat identical call hits prompt cache (underlying provider call count stays `1`, DB contains 2 rows, 2nd row has `cache_hit=True`, `tokens_in=0`, `tokens_out=0`, `cost_est=0.0`).
    3. Test 1-retry repair using a scripted fake `LLMProvider`:
       - Attempt 1 returns invalid JSON `"{bad_json"`, attempt 2 returns valid JSON -> gateway succeeds, repair prompt includes error details, DB logs both attempts.
       - Both attempts return invalid output -> raises `LLMGatewayError` after `max_retries=1` (2 provider calls total).
    4. Test daily token limit and daily USD budget fallback:
       - Configure tight `daily_token_limit=20` or `daily_budget_usd=0.0001` with a non-mock primary provider -> 1st call succeeds on primary, 2nd uncached call routes automatically to `MockProvider` fallback and succeeds without error.
    5. Test `rate_importance_batch(["Saw smoke at Market", "Walked past Park", "Drank coffee"], tick=12, agent_id="maya")` -> single LLM call (`1` row in `llm_calls`), returns `3` ints each in `1..10`, and empty input `[]` makes `0` calls.
    6. Test `GeminiProvider` offline using an injected fake async client verifying `GenerateContentConfig(response_mime_type="application/json", response_schema=ImportanceBatchResponse)` and `usage_metadata` parsing (including `usage_metadata=None` edge case), plus verifying empty `api_key` without injected client raises `RuntimeError`.

    AVOID: Making any real HTTP/Gemini API call or leaving `:memory:` `Database` undisposed.
    USE: Scripted fake `LLMProvider` and injected fake `genai` client so the entire test file runs in <1 second offline.
  </action>
  <verify>
    Run in backend/ (Cwd: backend):
    .venv\Scripts\pytest.exe -v tests/test_llm_gateway.py
    .venv\Scripts\ruff.exe check .
    .venv\Scripts\mypy.exe app sim api memory llm tests
  </verify>
  <done>
    All tests in `tests/test_llm_gateway.py` pass offline in <1s, and `ruff` + strict `mypy` exit 0.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] All Pydantic v2 schemas, `LLMProvider` protocol, `MockProvider`, and `GeminiProvider` exist and pass strict `mypy`
- [ ] `LLMGateway` enforces schema validation + 1-retry repair, prompt cache, daily budget fallback, batched importance scoring, and `llm_calls` logging
- [ ] `backend/tests/test_llm_gateway.py` passes completely offline in <1s

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in tests
