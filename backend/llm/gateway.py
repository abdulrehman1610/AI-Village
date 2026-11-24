"""Central schema-enforcing LLM gateway with caching, retry repair, budget gate, and logging."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlmodel import col, select

from app.db import Database
from llm.providers.base import LLMProvider
from llm.providers.mock import MockProvider
from llm.schemas import (
    ConversationDecisionResponse,
    ConversationSummaryResponse,
    DailyPlanResponse,
    DialogueTurnResponse,
    HourlyActionPlanResponse,
    ImportanceBatchResponse,
    ReplanResponse,
)
from memory.models import LLMCallRecord

T = TypeVar("T", bound=BaseModel)

_TICKS_PER_DAY = 1440
_FALLBACK_PRICING: tuple[float, float] = (0.15, 0.60)
_PLANNING_PURPOSES: frozenset[str] = frozenset(
    {
        "daily_plan",
        "replan",
        "hourly_plan",
        "reflection",
        "salient_questions",
    }
)

# Approximate USD pricing per 1M tokens: (input_usd, output_usd).
MODEL_PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
}


class LLMGatewayError(RuntimeError):
    """Raised when an LLM response fails schema validation after exhausting retries."""


def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate call cost in USD from model name and input/output token counts."""
    normalized = model.strip().lower()
    if normalized.startswith("mock"):
        return 0.0

    pricing = MODEL_PRICING_PER_MILLION.get(normalized)
    if pricing is None:
        for known_model in sorted(MODEL_PRICING_PER_MILLION, key=len, reverse=True):
            if normalized.startswith(known_model):
                pricing = MODEL_PRICING_PER_MILLION[known_model]
                break
    if pricing is None:
        pricing = _FALLBACK_PRICING

    in_rate, out_rate = pricing
    safe_in = max(0, tokens_in)
    safe_out = max(0, tokens_out)
    return ((safe_in * in_rate) + (safe_out * out_rate)) / 1_000_000.0


class LLMGateway:
    """Single entry point for all LLM requests across the village simulation."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        fallback_provider: LLMProvider | None = None,
        db: Database | None = None,
        daily_budget_usd: float = 0.50,
        daily_token_limit: int = 250_000,
        max_retries: int = 1,
        routine_model: str | None = None,
        planning_model: str | None = None,
        seed: int = 42,
    ) -> None:
        self.provider = provider
        self.fallback_provider: LLMProvider = (
            fallback_provider if fallback_provider is not None else MockProvider(seed=seed)
        )
        self.db = db
        self.daily_budget_usd = daily_budget_usd
        self.daily_token_limit = daily_token_limit
        self.max_retries = max(0, max_retries)
        self.routine_model = routine_model
        self.planning_model = planning_model
        self.seed = seed

        self._lock = asyncio.Lock()
        self._prompt_cache: dict[str, tuple[str, str]] = {}
        self._daily_tokens: dict[int, int] = {}
        self._daily_cost: dict[int, float] = {}
        self._daily_calls: dict[int, int] = {}
        self._daily_cache_hits: dict[int, int] = {}
        self._daily_tokens_in: dict[int, int] = {}
        self._daily_tokens_out: dict[int, int] = {}

    @staticmethod
    def day_for_tick(tick: int) -> int:
        """Map a non-negative simulation tick to a 1-indexed budget day."""
        return (max(0, tick) // _TICKS_PER_DAY) + 1

    async def generate(
        self,
        prompt: str,
        response_model: type[T],
        *,
        purpose: str,
        tick: int,
        agent_id: str | None = None,
        system_instruction: str | None = None,
        model_override: str | None = None,
        temperature: float = 0.2,
    ) -> T:
        """Generate a schema-validated response with prompt cache, budget gate, and repair."""
        requested_model = self._resolve_requested_model(
            purpose=purpose,
            model_override=model_override,
        )
        target_model_hint = (
            requested_model
            or getattr(self.provider, "default_model", None)
            or getattr(self.provider, "model_name", None)
            or self.provider.name
        )
        cache_key = _build_cache_key(
            model_hint=str(target_model_hint),
            purpose=purpose,
            schema_name=response_model.__qualname__,
            system_instruction=system_instruction or "",
            prompt=prompt,
        )
        day = self.day_for_tick(tick)

        async with self._lock:
            cached = self._prompt_cache.get(cache_key)

        if cached is not None:
            cached_json, cached_model = cached
            t0 = time.perf_counter()
            parsed = response_model.model_validate_json(cached_json)
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            await self._record_call(
                day=day,
                record=LLMCallRecord(
                    tick=tick,
                    agent_id=agent_id,
                    purpose=purpose,
                    model=cached_model,
                    tokens_in=0,
                    tokens_out=0,
                    latency_ms=latency_ms,
                    cost_est=0.0,
                    cache_hit=True,
                ),
            )
            return parsed

        async with self._lock:
            budget_exhausted = (
                self._daily_tokens.get(day, 0) >= self.daily_token_limit
                or self._daily_cost.get(day, 0.0) >= self.daily_budget_usd
            )

        if budget_exhausted:
            active_provider: LLMProvider = self.fallback_provider
            provider_model_override: str | None = None
        else:
            active_provider = self.provider
            provider_model_override = requested_model

        current_prompt = prompt
        last_error: ValidationError | None = None
        total_attempts = 1 + self.max_retries

        for attempt in range(total_attempts):
            t0 = time.perf_counter()
            result = await active_provider.generate_raw(
                prompt=current_prompt,
                response_model=response_model,
                system_instruction=system_instruction,
                model_override=provider_model_override,
                temperature=temperature,
                seed=self.seed,
            )
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

            is_mock_fallback = (
                active_provider is self.fallback_provider and active_provider.name == "mock"
            )
            cost_est = (
                0.0
                if is_mock_fallback
                else estimate_cost_usd(result.model, result.tokens_in, result.tokens_out)
            )
            await self._record_call(
                day=day,
                record=LLMCallRecord(
                    tick=tick,
                    agent_id=agent_id,
                    purpose=purpose,
                    model=result.model,
                    tokens_in=max(0, result.tokens_in),
                    tokens_out=max(0, result.tokens_out),
                    latency_ms=latency_ms,
                    cost_est=cost_est,
                    cache_hit=False,
                ),
            )

            try:
                parsed = response_model.model_validate_json(result.raw_text)
            except ValidationError as exc:
                last_error = exc
                if attempt + 1 < total_attempts:
                    current_prompt = _build_repair_prompt(
                        original_prompt=prompt,
                        response_model=response_model,
                        invalid_output=result.raw_text,
                        error=exc,
                    )
                    continue
                break

            if not budget_exhausted:
                async with self._lock:
                    self._prompt_cache[cache_key] = (parsed.model_dump_json(), result.model)
            return parsed

        raise LLMGatewayError(
            f"LLM response validation failed for {response_model.__qualname__} "
            f"(purpose={purpose!r}) after {total_attempts} attempt(s): {last_error}"
        ) from last_error

    async def rate_importance_batch(
        self,
        texts: Sequence[str],
        *,
        tick: int,
        agent_id: str | None = None,
        purpose: str = "importance_batch",
    ) -> list[int]:
        """Rate importance (1..10) for a batch of memory texts in a single LLM call."""
        if not texts:
            return []

        numbered = "\n".join(f"{idx}. {text}" for idx, text in enumerate(texts, start=1))
        prompt = (
            "Rate the importance of each memory on an integer scale from 1 "
            "(mundane routine) to 10 (urgent, dramatic, or highly memorable).\n"
            f"Item count: {len(texts)}\n"
            f"Return JSON with `ratings` containing exactly {len(texts)} integers.\n\n"
            f"{numbered}"
        )
        response = await self.generate(
            prompt,
            ImportanceBatchResponse,
            purpose=purpose,
            tick=tick,
            agent_id=agent_id,
        )
        if len(response.ratings) != len(texts):
            raise LLMGatewayError(
                f"Expected {len(texts)} importance ratings, received {len(response.ratings)}"
            )
        return list(response.ratings)

    async def generate_daily_plan(
        self,
        prompt: str,
        *,
        tick: int,
        agent_id: str,
        system_instruction: str | None = None,
    ) -> DailyPlanResponse:
        """Generate a 5..8 item daily plan routed to the planning model."""
        return await self.generate(
            prompt,
            DailyPlanResponse,
            purpose="daily_plan",
            tick=tick,
            agent_id=agent_id,
            system_instruction=system_instruction,
        )

    async def generate_replan(
        self,
        prompt: str,
        *,
        tick: int,
        agent_id: str,
        system_instruction: str | None = None,
    ) -> ReplanResponse:
        """Generate a partial-day replan routed to the planning model."""
        return await self.generate(
            prompt,
            ReplanResponse,
            purpose="replan",
            tick=tick,
            agent_id=agent_id,
            system_instruction=system_instruction,
        )

    async def generate_hourly_actions(
        self,
        prompt: str,
        *,
        tick: int,
        agent_id: str,
        system_instruction: str | None = None,
    ) -> HourlyActionPlanResponse:
        """Decompose an active block into hourly focus and minute actions on routine_model."""
        return await self.generate(
            prompt,
            HourlyActionPlanResponse,
            purpose="action_decomposition",
            tick=tick,
            agent_id=agent_id,
            system_instruction=system_instruction,
        )

    async def decide_conversation(
        self,
        prompt: str,
        *,
        tick: int,
        agent_id: str,
        system_instruction: str | None = None,
    ) -> ConversationDecisionResponse:
        """Decide whether an agent initiates dialogue with a nearby peer."""
        return await self.generate(
            prompt,
            ConversationDecisionResponse,
            purpose="conversation_decide",
            tick=tick,
            agent_id=agent_id,
            system_instruction=system_instruction,
        )

    async def generate_dialogue_turn(
        self,
        prompt: str,
        *,
        tick: int,
        agent_id: str,
        system_instruction: str | None = None,
    ) -> DialogueTurnResponse:
        """Generate one conversational turn and continuation signal."""
        return await self.generate(
            prompt,
            DialogueTurnResponse,
            purpose="dialogue_turn",
            tick=tick,
            agent_id=agent_id,
            system_instruction=system_instruction,
        )

    async def summarize_conversation(
        self,
        prompt: str,
        *,
        tick: int,
        agent_id: str,
        system_instruction: str | None = None,
    ) -> ConversationSummaryResponse:
        """Summarize a finished conversation and estimate relationship affinity change."""
        return await self.generate(
            prompt,
            ConversationSummaryResponse,
            purpose="conversation_summary",
            tick=tick,
            agent_id=agent_id,
            system_instruction=system_instruction,
        )

    async def get_usage_summary(self, *, tick: int | None = None) -> dict[str, float | int]:
        """Return aggregated call, token, cost, and cache-hit metrics."""
        if self.db is not None:
            stmt = select(LLMCallRecord)
            if tick is not None:
                day = self.day_for_tick(tick)
                start_tick = (day - 1) * _TICKS_PER_DAY
                end_tick = day * _TICKS_PER_DAY
                stmt = stmt.where(
                    col(LLMCallRecord.tick) >= start_tick,
                    col(LLMCallRecord.tick) < end_tick,
                )
            async with self.db.session() as session:
                rows = list((await session.exec(stmt)).all())

            tokens_in = sum(row.tokens_in for row in rows)
            tokens_out = sum(row.tokens_out for row in rows)
            return {
                "total_calls": len(rows),
                "cache_hits": sum(1 for row in rows if row.cache_hit),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "total_tokens": tokens_in + tokens_out,
                "cost_est": sum(row.cost_est for row in rows),
            }

        async with self._lock:
            if tick is not None:
                day = self.day_for_tick(tick)
                tokens_in = self._daily_tokens_in.get(day, 0)
                tokens_out = self._daily_tokens_out.get(day, 0)
                return {
                    "total_calls": self._daily_calls.get(day, 0),
                    "cache_hits": self._daily_cache_hits.get(day, 0),
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "total_tokens": tokens_in + tokens_out,
                    "cost_est": self._daily_cost.get(day, 0.0),
                }

            tokens_in = sum(self._daily_tokens_in.values())
            tokens_out = sum(self._daily_tokens_out.values())
            return {
                "total_calls": sum(self._daily_calls.values()),
                "cache_hits": sum(self._daily_cache_hits.values()),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "total_tokens": tokens_in + tokens_out,
                "cost_est": sum(self._daily_cost.values()),
            }

    def _resolve_requested_model(
        self,
        *,
        purpose: str,
        model_override: str | None,
    ) -> str | None:
        if model_override is not None:
            return model_override
        normalized_purpose = purpose.strip().lower()
        if normalized_purpose in _PLANNING_PURPOSES or "plan" in normalized_purpose:
            return self.planning_model
        return self.routine_model

    async def _record_call(self, *, day: int, record: LLMCallRecord) -> None:
        async with self._lock:
            self._daily_calls[day] = self._daily_calls.get(day, 0) + 1
            if record.cache_hit:
                self._daily_cache_hits[day] = self._daily_cache_hits.get(day, 0) + 1
            else:
                self._daily_tokens_in[day] = (
                    self._daily_tokens_in.get(day, 0) + record.tokens_in
                )
                self._daily_tokens_out[day] = (
                    self._daily_tokens_out.get(day, 0) + record.tokens_out
                )
                self._daily_tokens[day] = (
                    self._daily_tokens.get(day, 0) + record.tokens_in + record.tokens_out
                )
                self._daily_cost[day] = self._daily_cost.get(day, 0.0) + record.cost_est

        if self.db is not None:
            async with self.db.session() as session:
                session.add(record)
                await session.commit()


def _build_cache_key(
    *,
    model_hint: str,
    purpose: str,
    schema_name: str,
    system_instruction: str,
    prompt: str,
) -> str:
    serialized = json.dumps(
        [model_hint, purpose, schema_name, system_instruction, prompt],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _build_repair_prompt(
    *,
    original_prompt: str,
    response_model: type[BaseModel],
    invalid_output: str,
    error: ValidationError,
) -> str:
    snippet = invalid_output.strip()[:400]
    schema_json = json.dumps(response_model.model_json_schema(), separators=(",", ":"))
    return (
        f"{original_prompt}\n\n"
        f"[VALIDATION REPAIR]\n"
        f"Your previous output failed validation for {response_model.__qualname__}.\n"
        f"Validation error: {error}\n"
        f"Invalid output snippet: {snippet!r}\n"
        f"Return ONLY valid JSON conforming strictly to schema: {schema_json}"
    )
