"""Deterministic zero-network mock LLM provider for offline tests and fallback."""

from __future__ import annotations

import hashlib
import re
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from llm.providers.base import ProviderResult
from llm.schemas import (
    ConversationDecisionResponse,
    ConversationSummaryResponse,
    DailyPlanItem,
    DailyPlanResponse,
    DialogueTurnResponse,
    ImportanceBatchResponse,
    ReflectionInsight,
    ReflectionResponse,
    SalientQuestionsResponse,
)

_URGENT_KEYWORDS: tuple[str, ...] = (
    "fire",
    "emergency",
    "rumor",
    "rumour",
    "argument",
    "secret",
    "discovered",
)

_LOCATIONS: tuple[str, ...] = (
    "Home_Maya",
    "Bakery",
    "Cafe",
    "Market",
    "Town Square",
    "Park",
    "Library",
    "Home_Liam",
)

_PLAN_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("Home_Maya", "Wake up, stretch, and prepare breakfast"),
    ("Bakery", "Open the ovens and prepare fresh morning loaves"),
    ("Market", "Browse stalls and pick up fresh village ingredients"),
    ("Cafe", "Take a mid-day espresso break and greet neighbors"),
    ("Town Square", "Stroll through the plaza and catch up on village news"),
    ("Library", "Read community records and afternoon periodicals"),
    ("Park", "Take an evening walk along the central pond"),
    ("Home_Maya", "Wind down at home and review notes for tomorrow"),
)

_DIALOGUE_POOL: tuple[str, ...] = (
    "Good morning! The village feels lively today.",
    "Have you noticed anything unusual near the Market?",
    "I just stopped by the Cafe before heading across the square.",
    "Let's catch up properly once today's errands are finished.",
    "I heard people talking about new plans in Town Square earlier.",
)

_QUESTION_POOL: tuple[str, ...] = (
    "Which recent interactions in the village mattered most to my goals?",
    "How are my relationships with neighbors evolving today?",
    "What unexpected events or rumors might affect tomorrow's plans?",
    "Which village locations have shaped my daily routine lately?",
    "Who should I check in with next based on recent observations?",
)

_INSIGHT_POOL: tuple[str, ...] = (
    "Shared conversations near central gathering spots strengthen community ties.",
    "Unusual town events quickly reshape neighbors' attention and priorities.",
    "Balancing daily work routines with social check-ins keeps village life steady.",
    "Repeated encounters at the Cafe and Market deepen familiarity across households.",
)


class MockProvider:
    """Deterministic hash-driven LLM provider requiring zero network I/O."""

    def __init__(self, *, seed: int = 42, model_name: str = "mock-flash") -> None:
        self._seed = seed
        self._model_name = model_name

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

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
        del system_instruction, temperature
        effective_seed = self._seed if seed is None else seed
        digest = hashlib.sha256(
            f"{effective_seed}:{response_model.__qualname__}:{prompt}".encode()
        ).digest()

        payload = self._build_payload(response_model=response_model, prompt=prompt, digest=digest)
        validated = response_model.model_validate(payload)
        raw_text = validated.model_dump_json()

        chosen_model = (
            model_override
            if (model_override is not None and model_override.startswith("mock"))
            else self._model_name
        )
        tokens_in = max(1, len(prompt) // 4)
        tokens_out = max(1, len(raw_text) // 4)
        return ProviderResult(
            raw_text=raw_text,
            model=chosen_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    def _build_payload(
        self,
        *,
        response_model: type[BaseModel],
        prompt: str,
        digest: bytes,
    ) -> dict[str, Any]:
        if response_model is ImportanceBatchResponse:
            return self._build_importance_batch(prompt=prompt, digest=digest)
        if response_model is DailyPlanResponse:
            return self._build_daily_plan(digest=digest)
        if response_model is DailyPlanItem:
            loc, desc = _PLAN_TEMPLATES[digest[0] % len(_PLAN_TEMPLATES)]
            return {
                "start_hour": 8,
                "end_hour": 10,
                "location": loc,
                "description": desc,
            }
        if response_model is ConversationDecisionResponse:
            initiate = (digest[0] % 2) == 0
            return {
                "initiate": initiate,
                "reason": (
                    "Neighbor is nearby and available for a brief chat."
                    if initiate
                    else "Staying focused on current scheduled activity."
                ),
                "opening_line": (
                    "Hello there! How is your day going around the village?"
                    if initiate
                    else ""
                ),
            }
        if response_model is DialogueTurnResponse:
            lower_prompt = prompt.lower()
            if any(word in lower_prompt for word in _URGENT_KEYWORDS):
                utterance = "Did you hear the latest news? Everyone is talking about it."
            else:
                utterance = _DIALOGUE_POOL[digest[0] % len(_DIALOGUE_POOL)]
            return {
                "utterance": utterance,
                "continue_dialogue": (digest[1] % 4) != 0,
            }
        if response_model is ConversationSummaryResponse:
            delta = round(((digest[0] % 11) - 3) * 0.05, 2)
            return {
                "summary": "Exchanged updates about daily routines and village happenings.",
                "affinity_delta": delta,
                "relationship_note": "Cordial conversation in the village.",
            }
        if response_model is SalientQuestionsResponse:
            start = digest[0] % len(_QUESTION_POOL)
            questions = [
                _QUESTION_POOL[(start + offset) % len(_QUESTION_POOL)]
                for offset in range(3)
            ]
            return {"questions": questions}
        if response_model is ReflectionInsight:
            cited = _extract_cited_ids(prompt)
            return {
                "insight": _INSIGHT_POOL[digest[0] % len(_INSIGHT_POOL)],
                "cited_memory_ids": cited,
            }
        if response_model is ReflectionResponse:
            cited = _extract_cited_ids(prompt)
            count = 1 + (digest[0] % 2)
            start = digest[1] % len(_INSIGHT_POOL)
            insights = [
                {
                    "insight": _INSIGHT_POOL[(start + idx) % len(_INSIGHT_POOL)],
                    "cited_memory_ids": cited,
                }
                for idx in range(count)
            ]
            return {"insights": insights}
        return _synthesize_generic_payload(response_model, digest)

    def _build_importance_batch(self, *, prompt: str, digest: bytes) -> dict[str, Any]:
        count, segments = _extract_batch_items(prompt)
        ratings: list[int] = []
        for idx in range(count):
            item_digest = hashlib.sha256(digest + idx.to_bytes(4, "big")).digest()
            text = segments[idx] if idx < len(segments) else prompt
            lowered = text.lower()
            if any(keyword in lowered for keyword in _URGENT_KEYWORDS):
                ratings.append(7 + (item_digest[0] % 3))
            else:
                ratings.append(3 + (item_digest[0] % 4))
        return {"ratings": ratings}

    def _build_daily_plan(self, *, digest: bytes) -> dict[str, Any]:
        item_count = 5 + (digest[0] % 4)  # 5..8 items
        start_hour = 6
        total_span = 16  # 06:00 -> 22:00
        base_dur, remainder = divmod(total_span, item_count)

        items: list[dict[str, Any]] = []
        current_hour = start_hour
        for idx in range(item_count):
            duration = base_dur + (1 if idx < remainder else 0)
            end_hour = min(24, current_hour + max(1, duration))
            template_idx = (idx + (digest[idx % len(digest)] % 2)) % len(_PLAN_TEMPLATES)
            default_loc, desc = _PLAN_TEMPLATES[template_idx]
            location = _LOCATIONS[idx % len(_LOCATIONS)] if idx > 0 else default_loc
            items.append(
                {
                    "start_hour": current_hour,
                    "end_hour": end_hour,
                    "location": location,
                    "description": desc,
                }
            )
            current_hour = end_hour
        return {"items": items}


def _extract_batch_items(prompt: str) -> tuple[int, list[str]]:
    count_match = re.search(r"Item count:\s*(\d+)", prompt)
    if count_match is not None:
        count = max(0, int(count_match.group(1)))
    else:
        numbered_headers = re.findall(r"(?m)^\s*\d+\.\s+", prompt)
        count = len(numbered_headers) if numbered_headers else 1

    if count == 0:
        return 0, []

    segments: list[str] = []
    # Match sequential item headers 1..count so digits/newlines inside items don't misalign slots.
    positions: list[tuple[int, int]] = []
    search_start = 0
    for item_num in range(1, count + 1):
        pattern = re.compile(rf"(?m)^\s*{item_num}\.\s+")
        match = pattern.search(prompt, search_start)
        if match is None:
            break
        positions.append((match.start(), match.end()))
        search_start = match.end()

    for idx, (_, content_start) in enumerate(positions):
        content_end = positions[idx + 1][0] if idx + 1 < len(positions) else len(prompt)
        segments.append(prompt[content_start:content_end].strip())

    return count, segments


def _extract_cited_ids(prompt: str) -> list[int]:
    matches = re.findall(r"(?:\[|#|\bID[: ]+)(\d+)\b", prompt)
    seen: list[int] = []
    for raw in matches:
        value = int(raw)
        if value not in seen:
            seen.append(value)
    return seen[:5]


def _synthesize_generic_payload(response_model: type[BaseModel], digest: bytes) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field_name, field_info in response_model.model_fields.items():
        if not field_info.is_required():
            continue
        annotation = field_info.annotation
        origin = get_origin(annotation)
        if annotation is str:
            payload[field_name] = f"mock-{digest.hex()[:8]}"
        elif annotation is int:
            payload[field_name] = 1 + (digest[0] % 5)
        elif annotation is float:
            payload[field_name] = 0.5
        elif annotation is bool:
            payload[field_name] = (digest[0] % 2) == 0
        elif origin is list:
            args = get_args(annotation)
            elem = args[0] if args else str
            if elem is int:
                payload[field_name] = [1]
            else:
                payload[field_name] = ["mock-item"]
        else:
            payload[field_name] = "mock"
    return payload
