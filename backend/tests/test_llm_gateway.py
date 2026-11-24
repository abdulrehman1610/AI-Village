"""Offline tests for LLM schemas, MockProvider, GeminiProvider, and LLMGateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from pydantic import BaseModel
from sqlmodel import col, select

from agents.personas import get_persona
from app.db import Database
from llm.gateway import LLMGateway, LLMGatewayError, estimate_cost_usd
from llm.prompts import (
    build_conversation_decision_prompt,
    build_conversation_summary_prompt,
    build_daily_plan_prompt,
    build_dialogue_turn_prompt,
    build_hourly_action_prompt,
    build_replan_prompt,
)
from llm.providers.base import LLMProvider, ProviderResult
from llm.providers.gemini import GeminiProvider
from llm.providers.mock import _LOCATIONS, MockProvider
from llm.schemas import (
    ConversationDecisionResponse,
    ConversationSummaryResponse,
    DailyPlanItem,
    DailyPlanResponse,
    DialogueTurnResponse,
    HourlyActionPlanResponse,
    ImportanceBatchResponse,
    MinuteActionItem,
    ReflectionResponse,
    ReplanResponse,
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
        (
            ReplanResponse,
            "Current hour: 15\nInterruption: Fire broke out at Market",
        ),
        (
            HourlyActionPlanResponse,
            "Block: 09:00-11:00 at Bakery\nCurrent time: 09:15\nBlock goal: Bake morning loaves",
        ),
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


async def test_mock_provider_late_evening_replan_and_hourly_actions() -> None:
    """Late-evening replanning and hourly decomposition produce valid constrained blocks."""
    provider = MockProvider(seed=42)
    maya = get_persona("maya")

    replan_prompt = build_replan_prompt(
        persona=maya,
        current_hour=22,
        sim_time="Day 1 22:10",
        interruption_reason="[EVENT] Late night lantern parade at Market",
        remaining_blocks=[],
        valid_locations=_LOCATIONS,
        memories=["[EVENT] Late night lantern parade at Market"],
    )
    replan_res = await provider.generate_raw(
        prompt=replan_prompt,
        response_model=ReplanResponse,
    )
    replan = ReplanResponse.model_validate_json(replan_res.raw_text)
    assert 1 <= len(replan.items) <= 2
    assert replan.items[0].start_hour == 22
    assert replan.items[-1].end_hour == 24
    assert replan.items[0].location == "Market"
    assert "lantern parade" in replan.items[0].description.lower()
    for idx, item in enumerate(replan.items):
        assert item.start_hour >= 22
        assert item.start_hour < item.end_hour <= 24
        if idx > 0:
            assert item.start_hour == replan.items[idx - 1].end_hour

    final_hour_prompt = build_replan_prompt(
        persona=maya,
        current_hour=23,
        sim_time="Day 1 23:05",
        interruption_reason="Quiet night check",
        remaining_blocks=[],
        valid_locations=_LOCATIONS,
        memories=[],
    )
    final_hour_res = await provider.generate_raw(
        prompt=final_hour_prompt,
        response_model=ReplanResponse,
    )
    final_replan = ReplanResponse.model_validate_json(final_hour_res.raw_text)
    assert len(final_replan.items) == 1
    assert final_replan.items[0].start_hour == 23
    assert final_replan.items[0].end_hour == 24

    block = DailyPlanItem(
        start_hour=9,
        end_hour=11,
        location="Bakery",
        description="Bake sourdough loaves and organize pastry counter",
    )
    hourly_prompt = build_hourly_action_prompt(
        persona=maya,
        block=block,
        current_hour=9,
        current_minute=15,
        valid_locations=_LOCATIONS,
        memories=["Need extra flour sacks for morning rush."],
    )
    hourly_res = await provider.generate_raw(
        prompt=hourly_prompt,
        response_model=HourlyActionPlanResponse,
    )
    hourly = HourlyActionPlanResponse.model_validate_json(hourly_res.raw_text)
    assert hourly.hourly_focus
    assert 1 <= len(hourly.actions) <= 3
    for step in hourly.actions:
        assert isinstance(step, MinuteActionItem)
        assert 5 <= step.duration_minutes <= 60
        assert step.location == "Bakery"
        assert step.location in _LOCATIONS


async def test_gateway_planning_and_dialogue_helper_model_routing(db: Database) -> None:
    """Typed gateway helpers delegate with correct purposes and routine/planning model routing."""
    mock = MockProvider(seed=42)
    maya = get_persona("maya")
    liam = get_persona("liam")
    block = DailyPlanItem(
        start_hour=8,
        end_hour=10,
        location="Bakery",
        description="Open morning ovens",
    )

    daily_prompt = build_daily_plan_prompt(
        persona=maya,
        sim_time="Day 1 06:00",
        valid_locations=_LOCATIONS,
        memories=[],
    )
    replan_prompt = build_replan_prompt(
        persona=maya,
        current_hour=14,
        sim_time="Day 1 14:15",
        interruption_reason="Neighbor asked for help at Cafe",
        remaining_blocks=[block],
        valid_locations=_LOCATIONS,
        memories=[],
    )
    hourly_prompt = build_hourly_action_prompt(
        persona=maya,
        block=block,
        current_hour=8,
        current_minute=10,
        valid_locations=_LOCATIONS,
        memories=[],
    )
    decision_prompt = build_conversation_decision_prompt(
        speaker=maya,
        listener=liam,
        location="Cafe",
        sim_time="Day 1 10:00",
        speaker_action="Taking espresso break",
        listener_action="Serving coffee",
        memories=[],
    )
    turn_prompt = build_dialogue_turn_prompt(
        speaker=maya,
        listener=liam,
        location="Cafe",
        sim_time="Day 1 10:01",
        turn_index=1,
        max_turns=6,
        memories=[],
        transcript=[("Maya", "Good morning, Liam!")],
    )
    summary_prompt = build_conversation_summary_prompt(
        speaker_a=maya,
        speaker_b=liam,
        location="Cafe",
        sim_time="Day 1 10:03",
        transcript=[("Maya", "Good morning, Liam!"), ("Liam", "Morning, Maya!")],
    )

    scripted_results = [
        await mock.generate_raw(prompt=daily_prompt, response_model=DailyPlanResponse),
        await mock.generate_raw(prompt=replan_prompt, response_model=ReplanResponse),
        await mock.generate_raw(prompt=hourly_prompt, response_model=HourlyActionPlanResponse),
        await mock.generate_raw(
            prompt=decision_prompt, response_model=ConversationDecisionResponse
        ),
        await mock.generate_raw(prompt=turn_prompt, response_model=DialogueTurnResponse),
        await mock.generate_raw(
            prompt=summary_prompt, response_model=ConversationSummaryResponse
        ),
    ]
    scripted = ScriptedProvider(scripted_results)
    gateway = LLMGateway(
        provider=scripted,
        db=db,
        routine_model="gemini-2.5-flash",
        planning_model="gemini-2.5-pro",
    )

    daily = await gateway.generate_daily_plan(daily_prompt, tick=0, agent_id="maya")
    replan = await gateway.generate_replan(replan_prompt, tick=855, agent_id="maya")
    hourly = await gateway.generate_hourly_actions(hourly_prompt, tick=490, agent_id="maya")
    decision = await gateway.decide_conversation(decision_prompt, tick=600, agent_id="maya")
    turn = await gateway.generate_dialogue_turn(turn_prompt, tick=601, agent_id="maya")
    summary = await gateway.summarize_conversation(summary_prompt, tick=603, agent_id="maya")

    assert isinstance(daily, DailyPlanResponse)
    assert isinstance(replan, ReplanResponse)
    assert isinstance(hourly, HourlyActionPlanResponse)
    assert isinstance(decision, ConversationDecisionResponse)
    assert isinstance(turn, DialogueTurnResponse)
    assert isinstance(summary, ConversationSummaryResponse)

    assert [req.model_override for req in scripted.requests] == [
        "gemini-2.5-pro",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash",
        "gemini-2.5-flash",
        "gemini-2.5-flash",
    ]
    async with db.session() as session:
        rows = list(
            (await session.exec(select(LLMCallRecord).order_by(col(LLMCallRecord.id)))).all()
        )
    assert [row.purpose for row in rows] == [
        "daily_plan",
        "replan",
        "action_decomposition",
        "conversation_decide",
        "dialogue_turn",
        "conversation_summary",
    ]


async def test_mock_provider_rumor_propagation_and_neutral_persona_guard() -> None:
    """Injected events propagate across 2-hop dialogues without persona bio false positives."""
    provider = MockProvider(seed=42)
    maya = get_persona("maya")
    liam = get_persona("liam")
    noah = get_persona("noah")

    # Seeded persona summaries and goals (even containing urgent words) must not trigger rumor mode.
    routine_decision_prompt = build_conversation_decision_prompt(
        speaker=maya,
        listener=liam,
        location="Bakery",
        sim_time="Day 1 08:00",
        speaker_action="Baking sourdough loaves",
        listener_action="Picking up pastries",
        memories=[
            maya.summary_text(),
            f"{maya.name}'s goal: {maya.starting_goals[0]}",
            "Walked past the Park pond.",
            (
                "Conversation with Clara: Exchanged updates about daily routines "
                "and village happenings."
            ),
        ],
    )
    routine_decision = ConversationDecisionResponse.model_validate_json(
        (
            await provider.generate_raw(
                prompt=routine_decision_prompt,
                response_model=ConversationDecisionResponse,
            )
        ).raw_text
    )
    assert not routine_decision.opening_line.startswith("Have you heard?")

    # Synthetic persona bio/goal containing "fire" must stay routine under MockProvider guard.
    synthetic_seeded_bio = (
        "lives at Home_Test. Traits: steady, kind, alert. "
        "Prepares to fire the ceramic kiln before dawn. "
        "Starting goals: Shape clay bowls; Sweep studio."
    )
    synthetic_seeded_goal = "TestAgent's goal: Check the fire exit before opening"
    synthetic_guard_prompt = build_conversation_decision_prompt(
        speaker=maya,
        listener=liam,
        location="Bakery",
        sim_time="Day 1 08:05",
        speaker_action="Kneading dough",
        listener_action="Brewing espresso",
        memories=[synthetic_seeded_bio, synthetic_seeded_goal],
    )
    synthetic_guard_decision = ConversationDecisionResponse.model_validate_json(
        (
            await provider.generate_raw(
                prompt=synthetic_guard_prompt,
                response_model=ConversationDecisionResponse,
            )
        ).raw_text
    )
    assert not synthetic_guard_decision.opening_line.startswith("Have you heard?")

    synthetic_importance = ImportanceBatchResponse.model_validate_json(
        (
            await provider.generate_raw(
                prompt=(
                    "Rate the importance of each memory.\n"
                    "Item count: 3\n\n"
                    f"1. {maya.summary_text()}\n"
                    f"2. {synthetic_seeded_bio}\n"
                    f"3. {synthetic_seeded_goal}"
                ),
                response_model=ImportanceBatchResponse,
            )
        ).raw_text
    )
    assert all(3 <= score <= 6 for score in synthetic_importance.ratings)

    # Hop 1: Non-keyword [EVENT] memory triggers initiate=True and survives turn & summary.
    event_phrase = "Market fountain overflowed with lavender soap"
    event_memory = f"[EVENT] {event_phrase}"

    hop1_decision = ConversationDecisionResponse.model_validate_json(
        (
            await provider.generate_raw(
                prompt=build_conversation_decision_prompt(
                    speaker=maya,
                    listener=liam,
                    location="Cafe",
                    sim_time="Day 1 11:00",
                    speaker_action="Delivering pastries",
                    listener_action="Brewing espresso",
                    memories=[event_memory],
                ),
                response_model=ConversationDecisionResponse,
            )
        ).raw_text
    )
    assert hop1_decision.initiate is True
    assert event_phrase in hop1_decision.opening_line

    hop1_turn = DialogueTurnResponse.model_validate_json(
        (
            await provider.generate_raw(
                prompt=build_dialogue_turn_prompt(
                    speaker=liam,
                    listener=maya,
                    location="Cafe",
                    sim_time="Day 1 11:01",
                    turn_index=1,
                    max_turns=6,
                    memories=[],
                    transcript=[("Maya", hop1_decision.opening_line)],
                ),
                response_model=DialogueTurnResponse,
            )
        ).raw_text
    )
    assert event_phrase in hop1_turn.utterance

    hop1_summary = ConversationSummaryResponse.model_validate_json(
        (
            await provider.generate_raw(
                prompt=build_conversation_summary_prompt(
                    speaker_a=maya,
                    speaker_b=liam,
                    location="Cafe",
                    sim_time="Day 1 11:02",
                    transcript=[
                        ("Maya", hop1_decision.opening_line),
                        ("Liam", hop1_turn.utterance),
                    ],
                ),
                response_model=ConversationSummaryResponse,
            )
        ).raw_text
    )
    assert hop1_summary.summary == f"Maya and Liam discussed: {event_phrase}"

    # Hop 2: Liam meets Noah later with only Hop 1's stored summary in memory.
    hop2_decision = ConversationDecisionResponse.model_validate_json(
        (
            await provider.generate_raw(
                prompt=build_conversation_decision_prompt(
                    speaker=liam,
                    listener=noah,
                    location="Town Square",
                    sim_time="Day 1 13:00",
                    speaker_action="Walking across square",
                    listener_action="Checking produce crates",
                    memories=[hop1_summary.summary],
                ),
                response_model=ConversationDecisionResponse,
            )
        ).raw_text
    )
    assert hop2_decision.initiate is True
    assert event_phrase in hop2_decision.opening_line

    hop2_summary = ConversationSummaryResponse.model_validate_json(
        (
            await provider.generate_raw(
                prompt=build_conversation_summary_prompt(
                    speaker_a=liam,
                    speaker_b=noah,
                    location="Town Square",
                    sim_time="Day 1 13:02",
                    transcript=[("Liam", hop2_decision.opening_line)],
                ),
                response_model=ConversationSummaryResponse,
            )
        ).raw_text
    )
    assert hop2_summary.summary == f"Liam and Noah discussed: {event_phrase}"

    gateway = LLMGateway(provider=provider)
    ratings = await gateway.rate_importance_batch(
        [
            event_memory,
            hop1_summary.summary,
            "Walked past Park",
            maya.summary_text(),
            synthetic_seeded_bio,
            synthetic_seeded_goal,
        ],
        tick=800,
        agent_id="liam",
    )
    assert 7 <= ratings[0] <= 9
    assert 7 <= ratings[1] <= 9
    assert 3 <= ratings[2] <= 6
    assert 3 <= ratings[3] <= 6
    assert 3 <= ratings[4] <= 6
    assert 3 <= ratings[5] <= 6
