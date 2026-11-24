"""Offline tests for LLM schemas, MockProvider, GeminiProvider, and LLMGateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from pydantic import BaseModel
from sqlmodel import col, select

from app.db import Database
from llm.gateway import LLMGateway, LLMGatewayError, estimate_cost_usd
from llm.providers.base import LLMProvider, ProviderResult
from llm.providers.gemini import GeminiProvider
from llm.providers.mock import MockProvider
from llm.schemas import (
    ConversationDecisionResponse,
    ConversationSummaryResponse,
    DailyPlanResponse,
    DialogueTurnResponse,
    ImportanceBatchResponse,
    ReflectionResponse,
    SalientQuestionsResponse,
)
from memory.models import LLMCallRecord


@dataclass
class RecordedRequest:
    prompt: str
    response_model: type[BaseModel]
    system_instruction: str | None
    model_override: str | None
    temperature: float
    seed: int | None


class ScriptedProvider:
    """Offline fake LLMProvider returning pre-scripted responses and recording prompts."""

    def __init__(
        self,
        responses: list[ProviderResult],
        *,
        provider_name: str = "scripted-gemini",
    ) -> None:
        self._responses = list(responses)
        self._provider_name = provider_name
        self.requests: list[RecordedRequest] = []

    @property
    def name(self) -> str:
        return self._provider_name

    async def generate_raw(
        self,
        *,
        prompt: str,
        response_model: type[BaseModel],
        system_instruction: str | None = None,
        model_override: str | None = None,
        temperature: float = 0.2,
        seed: int | None = None,
    ) -> ProviderResult:
        self.requests.append(
            RecordedRequest(
                prompt=prompt,
                response_model=response_model,
                system_instruction=system_instruction,
                model_override=model_override,
                temperature=temperature,
                seed=seed,
            )
        )
        if not self._responses:
            raise AssertionError("ScriptedProvider ran out of responses")
        return self._responses.pop(0)


class _FakeUsage:
    def __init__(self, prompt_token_count: int, candidates_token_count: int) -> None:
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


class _FakeGenAIResponse:
    def __init__(self, text: str, usage_metadata: _FakeUsage | None) -> None:
        self.text = text
        self.usage_metadata = usage_metadata


class _FakeAsyncModels:
    def __init__(self, responses: list[_FakeGenAIResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: Any,
    ) -> _FakeGenAIResponse:
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self._responses.pop(0)


class _FakeAsyncIO:
    def __init__(self, models: _FakeAsyncModels) -> None:
        self.models = models


class _FakeGenAIClient:
    def __init__(self, responses: list[_FakeGenAIResponse]) -> None:
        self.models = _FakeAsyncModels(responses)
        self.aio = _FakeAsyncIO(self.models)


@pytest_asyncio.fixture
async def db() -> AsyncIterator[Database]:
    """Provide an initialized in-memory async Database and dispose it on teardown."""
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.init_models()
    try:
        yield database
    finally:
        await database.dispose()


async def test_mock_provider_deterministic_and_schema_valid_across_all_schemas() -> None:
    """MockProvider produces deterministic byte-identical valid JSON across all schemas."""
    provider_a = MockProvider(seed=42)
    provider_b = MockProvider(seed=42)
    assert isinstance(provider_a, LLMProvider)

    schemas_and_prompts: list[tuple[type[BaseModel], str]] = [
        (
            ImportanceBatchResponse,
            "Item count: 3\n"
            "1. Fire at Market\n"
            "2. Walked with 2 bags\n   2. decoy line\n"
            "3. Drank tea",
        ),
        (DailyPlanResponse, "Generate a daily plan for Maya at Home_Maya."),
        (ConversationDecisionResponse, "Should Maya talk to Liam at the Cafe?"),
        (DialogueTurnResponse, "Respond to Liam about the Market fire."),
        (ConversationSummaryResponse, "Summarize Maya and Liam's morning dialogue."),
        (SalientQuestionsResponse, "Ask 3 salient reflection questions for Maya."),
        (ReflectionResponse, "Synthesize insights from [1] and [4] about village events."),
    ]

    for schema_cls, prompt in schemas_and_prompts:
        res_a = await provider_a.generate_raw(prompt=prompt, response_model=schema_cls)
        res_b = await provider_b.generate_raw(prompt=prompt, response_model=schema_cls)
        assert res_a.raw_text == res_b.raw_text
        assert res_a.model == "mock-flash"
        assert res_a.tokens_in > 0
        assert res_a.tokens_out > 0
        parsed = schema_cls.model_validate_json(res_a.raw_text)
        assert isinstance(parsed, schema_cls)

    batch = ImportanceBatchResponse.model_validate_json(
        (
            await provider_a.generate_raw(
                prompt=schemas_and_prompts[0][1],
                response_model=ImportanceBatchResponse,
            )
        ).raw_text
    )
    assert len(batch.ratings) == 3
    assert 7 <= batch.ratings[0] <= 9
    assert 3 <= batch.ratings[2] <= 6


async def test_gateway_persists_llm_call_and_hits_prompt_cache(db: Database) -> None:
    """First call persists telemetry; repeat identical prompt hits SHA-256 cache with zero cost."""
    scripted = ScriptedProvider(
        [
            ProviderResult(
                raw_text='{"initiate": true, "reason": "Friendly", "opening_line": "Morning!"}',
                model="gemini-2.5-flash",
                tokens_in=80,
                tokens_out=24,
            )
        ]
    )
    gateway = LLMGateway(provider=scripted, db=db, seed=42)

    first = await gateway.generate(
        "Decide whether Maya greets Liam.",
        ConversationDecisionResponse,
        purpose="conversation_decide",
        tick=10,
        agent_id="maya",
    )
    second = await gateway.generate(
        "Decide whether Maya greets Liam.",
        ConversationDecisionResponse,
        purpose="conversation_decide",
        tick=11,
        agent_id="maya",
    )

    assert first == second
    assert first.initiate is True
    assert len(scripted.requests) == 1

    async with db.session() as session:
        rows = list(
            (await session.exec(select(LLMCallRecord).order_by(col(LLMCallRecord.id)))).all()
        )

    assert len(rows) == 2
    assert rows[0].purpose == "conversation_decide"
    assert rows[0].agent_id == "maya"
    assert rows[0].model == "gemini-2.5-flash"
    assert rows[0].tokens_in == 80
    assert rows[0].tokens_out == 24
    assert rows[0].latency_ms >= 0.0
    assert rows[0].cost_est > 0.0
    assert rows[0].cache_hit is False

    assert rows[1].cache_hit is True
    assert rows[1].tokens_in == 0
    assert rows[1].tokens_out == 0
    assert rows[1].cost_est == 0.0

    summary = await gateway.get_usage_summary(tick=10)
    assert summary["total_calls"] == 2
    assert summary["cache_hits"] == 1
    assert summary["tokens_in"] == 80
    assert summary["tokens_out"] == 24


async def test_gateway_one_retry_repair_succeeds_and_logs_both_attempts(db: Database) -> None:
    """Invalid JSON on attempt 1 triggers a validation-repair prompt and succeeds on attempt 2."""
    scripted = ScriptedProvider(
        [
            ProviderResult(
                raw_text="{bad_json",
                model="gemini-2.5-flash",
                tokens_in=50,
                tokens_out=5,
            ),
            ProviderResult(
                raw_text='{"utterance": "Good morning, Liam!", "continue_dialogue": false}',
                model="gemini-2.5-flash",
                tokens_in=90,
                tokens_out=15,
            ),
        ]
    )
    gateway = LLMGateway(provider=scripted, db=db, max_retries=1)

    parsed = await gateway.generate(
        "Generate next dialogue turn for Maya.",
        DialogueTurnResponse,
        purpose="dialogue_turn",
        tick=25,
        agent_id="maya",
    )
    assert parsed.utterance == "Good morning, Liam!"
    assert parsed.continue_dialogue is False
    assert len(scripted.requests) == 2
    assert "[VALIDATION REPAIR]" in scripted.requests[1].prompt
    assert "{bad_json" in scripted.requests[1].prompt

    async with db.session() as session:
        rows = list(
            (await session.exec(select(LLMCallRecord).order_by(col(LLMCallRecord.id)))).all()
        )
    assert len(rows) == 2
    assert all(row.cache_hit is False for row in rows)


async def test_gateway_raises_after_exhausting_retry_repair(db: Database) -> None:
    """Two consecutive invalid outputs exhaust max_retries=1 and raise LLMGatewayError."""
    scripted = ScriptedProvider(
        [
            ProviderResult(
                raw_text="{not_valid",
                model="gemini-2.5-flash",
                tokens_in=30,
                tokens_out=4,
            ),
            ProviderResult(
                raw_text='{"utterance": "", "extra_field": 1}',
                model="gemini-2.5-flash",
                tokens_in=60,
                tokens_out=8,
            ),
        ]
    )
    gateway = LLMGateway(provider=scripted, db=db, max_retries=1)

    with pytest.raises(LLMGatewayError):
        await gateway.generate(
            "Generate dialogue turn.",
            DialogueTurnResponse,
            purpose="dialogue_turn",
            tick=30,
            agent_id="maya",
        )

    assert len(scripted.requests) == 2
    async with db.session() as session:
        rows = list((await session.exec(select(LLMCallRecord))).all())
    assert len(rows) == 2


async def test_gateway_budget_exhaustion_routes_to_mock_fallback(db: Database) -> None:
    """Exhausting daily token or USD budget switches uncached calls cleanly to MockProvider."""
    primary = ScriptedProvider(
        [
            ProviderResult(
                raw_text='{"ratings": [6]}',
                model="gemini-2.5-flash",
                tokens_in=25,
                tokens_out=10,
            ),
            ProviderResult(
                raw_text='{"ratings": [8]}',
                model="gemini-2.5-flash",
                tokens_in=15,
                tokens_out=5,
            ),
        ]
    )
    gateway = LLMGateway(
        provider=primary,
        fallback_provider=MockProvider(seed=7),
        db=db,
        daily_token_limit=20,
        daily_budget_usd=0.50,
    )

    first = await gateway.generate(
        "Item count: 1\n1. Bought sourdough bread.",
        ImportanceBatchResponse,
        purpose="importance_batch",
        tick=5,
        agent_id="maya",
    )
    assert first.ratings == [6]
    assert len(primary.requests) == 1

    # Second uncached call on same day hits token budget (35 >= 20) -> MockProvider fallback.
    second = await gateway.generate(
        "Item count: 1\n1. Fire broke out near the Market!",
        ImportanceBatchResponse,
        purpose="importance_batch",
        tick=6,
        agent_id="maya",
    )
    assert len(second.ratings) == 1
    assert 7 <= second.ratings[0] <= 9
    assert len(primary.requests) == 1

    # Day 2 (tick >= 1440) starts a fresh daily budget and uses primary again.
    day_two = await gateway.generate(
        "Item count: 1\n1. Morning delivery arrived.",
        ImportanceBatchResponse,
        purpose="importance_batch",
        tick=1440,
        agent_id="maya",
    )
    assert day_two.ratings == [8]
    assert len(primary.requests) == 2

    # USD budget limit check with tight daily_budget_usd=0.0001.
    usd_primary = ScriptedProvider(
        [
            ProviderResult(
                raw_text='{"ratings": [5]}',
                model="gemini-2.5-pro",
                tokens_in=1000,
                tokens_out=1000,
            )
        ]
    )
    usd_gateway = LLMGateway(
        provider=usd_primary,
        db=db,
        daily_token_limit=1_000_000,
        daily_budget_usd=0.0001,
    )
    assert (await usd_gateway.rate_importance_batch(["Walked to Cafe"], tick=10)) == [5]
    fallback_res = await usd_gateway.rate_importance_batch(["Visited Park"], tick=11)
    assert len(fallback_res) == 1
    assert 1 <= fallback_res[0] <= 10
    assert len(usd_primary.requests) == 1


async def test_rate_importance_batch_single_call_and_empty_noop(db: Database) -> None:
    """Batch importance scoring issues 1 LLM call for 3 items and 0 calls for empty input."""
    gateway = LLMGateway(provider=MockProvider(seed=42), db=db)

    empty_ratings = await gateway.rate_importance_batch([], tick=10, agent_id="maya")
    assert empty_ratings == []

    ratings = await gateway.rate_importance_batch(
        ["Saw smoke at Market", "Walked past Park", "Drank coffee"],
        tick=12,
        agent_id="maya",
    )
    assert len(ratings) == 3
    assert all(isinstance(score, int) and 1 <= score <= 10 for score in ratings)

    async with db.session() as session:
        rows = list((await session.exec(select(LLMCallRecord))).all())
    assert len(rows) == 1
    assert rows[0].purpose == "importance_batch"
    assert rows[0].agent_id == "maya"

    no_db_gateway = LLMGateway(provider=MockProvider(seed=42))
    assert len(await no_db_gateway.rate_importance_batch(["Walked home"], tick=1)) == 1
    in_mem_summary = await no_db_gateway.get_usage_summary()
    assert in_mem_summary["total_calls"] == 1

    mismatched_gateway = LLMGateway(
        provider=ScriptedProvider(
            [
                ProviderResult(
                    raw_text='{"ratings": [5, 7]}',
                    model="gemini-2.5-flash",
                    tokens_in=20,
                    tokens_out=6,
                )
            ]
        )
    )
    with pytest.raises(LLMGatewayError, match="Expected 3 importance ratings"):
        await mismatched_gateway.rate_importance_batch(["a", "b", "c"], tick=15)


async def test_gemini_provider_offline_with_injected_fake_client() -> None:
    """GeminiProvider builds GenerateContentConfig, parses usage_metadata, and validates api_key."""
    fake_client = _FakeGenAIClient(
        [
            _FakeGenAIResponse(
                text='{"ratings": [8, 4]}',
                usage_metadata=_FakeUsage(prompt_token_count=45, candidates_token_count=18),
            ),
            _FakeGenAIResponse(
                text='{"ratings": [5]}',
                usage_metadata=None,
            ),
        ]
    )
    provider = GeminiProvider(api_key="", default_model="gemini-2.5-flash", client=fake_client)
    assert isinstance(provider, LLMProvider)

    first = await provider.generate_raw(
        prompt="Rate 2 memories.",
        response_model=ImportanceBatchResponse,
        system_instruction="Return strict JSON.",
        temperature=0.1,
        seed=42,
    )
    assert first.raw_text == '{"ratings": [8, 4]}'
    assert first.model == "gemini-2.5-flash"
    assert first.tokens_in == 45
    assert first.tokens_out == 18

    recorded = fake_client.models.calls[0]
    assert recorded["model"] == "gemini-2.5-flash"
    assert recorded["contents"] == "Rate 2 memories."
    assert recorded["config"].response_mime_type == "application/json"
    assert recorded["config"].response_schema is ImportanceBatchResponse
    assert recorded["config"].system_instruction == "Return strict JSON."

    second = await provider.generate_raw(
        prompt="Rate 1 memory.",
        response_model=ImportanceBatchResponse,
        model_override="gemini-2.5-pro",
    )
    assert second.model == "gemini-2.5-pro"
    assert second.tokens_in == 0
    assert second.tokens_out == 0

    unconfigured = GeminiProvider(api_key="   ")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await unconfigured.generate_raw(
            prompt="hello",
            response_model=ImportanceBatchResponse,
        )

    assert estimate_cost_usd("mock-flash", 1000, 1000) == 0.0
    assert estimate_cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000) == pytest.approx(0.75)
