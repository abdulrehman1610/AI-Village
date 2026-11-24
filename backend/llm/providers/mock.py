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
    HourlyActionPlanResponse,
    ImportanceBatchResponse,
    ReflectionInsight,
    ReflectionResponse,
    ReplanResponse,
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

_URGENT_KEYWORD_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in _URGENT_KEYWORDS) + r")\b"
)

_EVENT_IMPORTANCE_MARKERS: tuple[str, ...] = (
    "[event]",
    "event at ",
    "observed event:",
    "heard ",
    "discussed:",
)

_METADATA_LINE_PREFIXES: tuple[str, ...] = (
    "persona:",
    "speaker profile:",
    "listener profile:",
    "valid locations:",
    "sim time:",
    "current hour:",
    "current time:",
    "participants:",
    "location:",
    "turn:",
    "block:",
    "block goal:",
    "speaker current activity:",
    "listener current activity:",
    "remaining schedule:",
    "instructions:",
    "context memories:",
    "transcript:",
    "create a daily schedule",
    "decompose the active schedule",
    "update the remainder of this villager",
    "decide whether ",
    "generate the next spoken reply",
    "summarize the exchange",
    "- return ",
    "- every ",
    "- keep ",
    "- set ",
    "- provide ",
    "- write ",
    "- estimate ",
    "- address ",
    "- (none)",
    "(none)",
)

_TIER1_EVENT_MARKERS: tuple[str, ...] = (
    "[event]",
    "observed event:",
    "interruption:",
)

_TIER2_RUMOR_MARKERS: tuple[str, ...] = (
    "heard news:",
    "discussed:",
    "have you heard?",
    "everyone should know about this:",
    "wait, regarding ",
)

_NEUTRAL_ROUTINE_SUMMARY = "Exchanged updates about daily routines and village happenings."

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
        if response_model is ReplanResponse:
            return self._build_replan(prompt=prompt, digest=digest)
        if response_model is HourlyActionPlanResponse:
            return self._build_hourly_action_plan(prompt=prompt, digest=digest)
        if response_model is DailyPlanItem:
            loc, desc = _PLAN_TEMPLATES[digest[0] % len(_PLAN_TEMPLATES)]
            return {
                "start_hour": 8,
                "end_hour": 10,
                "location": loc,
                "description": desc,
            }
        if response_model is ConversationDecisionResponse:
            topic = _extract_salient_topic(prompt)
            if topic is not None:
                return {
                    "initiate": True,
                    "reason": "Sharing important village news with nearby neighbor.",
                    "opening_line": f"Have you heard? {topic}",
                }
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
            topic = _extract_salient_topic(prompt)
            if topic is not None:
                utterance = (
                    f"Everyone should know about this: {topic}"
                    if (digest[0] % 2) == 0
                    else f"Wait, regarding {topic} — I'll adjust my plans."
                )
            else:
                utterance = _DIALOGUE_POOL[digest[0] % len(_DIALOGUE_POOL)]
            return {
                "utterance": utterance,
                "continue_dialogue": (digest[1] % 4) != 0,
            }
        if response_model is ConversationSummaryResponse:
            topic = _extract_salient_topic(prompt)
            delta = round(((digest[0] % 11) - 3) * 0.05, 2)
            if topic is not None:
                participants = _extract_participants(prompt)
                return {
                    "summary": f"{participants} discussed: {topic}",
                    "affinity_delta": delta,
                    "relationship_note": f"Shared urgent update about {topic[:60]}.",
                }
            return {
                "summary": _NEUTRAL_ROUTINE_SUMMARY,
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
            is_urgent = bool(_URGENT_KEYWORD_PATTERN.search(lowered)) or any(
                marker in lowered for marker in _EVENT_IMPORTANCE_MARKERS
            )
            if is_urgent:
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

    def _build_replan(self, *, prompt: str, digest: bytes) -> dict[str, Any]:
        hour_match = re.search(r"(?im)^Current hour:\s*(\d+)", prompt)
        start_hour = max(0, min(23, int(hour_match.group(1)))) if hour_match else 12
        total_span = max(1, 24 - start_hour)
        max_blocks = min(4, total_span)
        item_count = 1 + (digest[0] % max_blocks)
        base_dur, remainder = divmod(total_span, item_count)

        topic = _extract_salient_topic(prompt)
        target_loc = _extract_prompt_location(topic) if topic is not None else None
        if target_loc is None:
            for line in prompt.splitlines():
                stripped = line.strip()
                if not _is_metadata_line(stripped):
                    target_loc = _extract_prompt_location(stripped)
                    if target_loc is not None:
                        break

        items: list[dict[str, Any]] = []
        current_hour = start_hour
        for idx in range(item_count):
            duration = base_dur + (1 if idx < remainder else 0)
            end_hour = min(24, current_hour + max(1, duration))
            template_idx = (idx + (digest[idx % len(digest)] % 2)) % len(_PLAN_TEMPLATES)
            default_loc, default_desc = _PLAN_TEMPLATES[template_idx]
            location = _LOCATIONS[(idx + digest[1]) % len(_LOCATIONS)] if idx > 0 else default_loc
            description = default_desc

            if idx == 0 and (topic is not None or target_loc is not None):
                if target_loc is not None:
                    location = target_loc
                description = (
                    f"Respond to {topic}"
                    if topic is not None
                    else f"Adjust plans at {location}"
                )

            items.append(
                {
                    "start_hour": current_hour,
                    "end_hour": end_hour,
                    "location": location,
                    "description": description,
                }
            )
            current_hour = end_hour
        return {"items": items}

    def _build_hourly_action_plan(self, *, prompt: str, digest: bytes) -> dict[str, Any]:
        block_match = re.search(r"(?im)^Block:\s*(\d+):00-(\d+):00\s+at\s+([^\n]+)", prompt)
        time_match = re.search(r"(?im)^Current time:\s*(\d+):(\d+)", prompt)
        goal_match = re.search(r"(?im)^Block goal:\s*([^\n]+)", prompt)

        block_start = int(block_match.group(1)) if block_match else 9
        if block_match is not None:
            raw_loc = block_match.group(3).strip()
            location = _extract_prompt_location(raw_loc) or _LOCATIONS[digest[0] % len(_LOCATIONS)]
        else:
            location = _extract_prompt_location(prompt) or _LOCATIONS[digest[0] % len(_LOCATIONS)]

        current_hour = max(0, min(23, int(time_match.group(1)))) if time_match else block_start
        current_minute = max(0, min(59, int(time_match.group(2)))) if time_match else 0

        topic = _extract_salient_topic(prompt)
        if topic is not None:
            hourly_focus = (
                f"Respond to {topic} at {location} ({current_hour:02d}:{current_minute:02d})"
            )
        elif goal_match is not None and goal_match.group(1).strip():
            hourly_focus = f"{goal_match.group(1).strip()} at {location}"
        else:
            hourly_focus = (
                f"Follow scheduled activity at {location} from "
                f"{current_hour:02d}:{current_minute:02d}"
            )

        action_count = 1 + (digest[1] % 3)
        step_templates = (
            f"Arrive at {location} and begin {topic or 'scheduled work'}",
            f"Carry out main task at {location}",
            f"Wrap up notes and prepare next step at {location}",
        )
        actions: list[dict[str, Any]] = []
        for idx in range(action_count):
            dur = 10 + ((digest[(idx + 2) % len(digest)] % 8) * 5)  # 10..45 minutes
            actions.append(
                {
                    "duration_minutes": dur,
                    "location": location,
                    "action": step_templates[idx % len(step_templates)],
                }
            )
        return {"hourly_focus": hourly_focus, "actions": actions}


def _is_metadata_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return stripped.lower().startswith(_METADATA_LINE_PREFIXES)


def _clean_topic_payload(raw: str) -> str | None:
    cleaned = " ".join(raw.strip().split())
    cleaned = re.sub(r"^[\s:\-]+", "", cleaned)
    cleaned = re.sub(r"\s+—\s+I'll adjust my plans\.?$", "", cleaned)
    lowered = cleaned.lower()
    if lowered in {"", "(none)", "none"}:
        return None
    if "exchanged updates about daily routines" in lowered:
        return None
    if len(cleaned) > 110:
        return cleaned[:107].rstrip() + "..."
    return cleaned


def _extract_after_marker(line: str, markers: tuple[str, ...]) -> str | None:
    lowered = line.lower()
    for marker in markers:
        idx = lowered.find(marker)
        if idx == -1:
            continue
        remainder = line[idx + len(marker) :]
        if marker == "conversation with " and ":" in remainder:
            remainder = remainder.split(":", 1)[1]
        cleaned = _clean_topic_payload(remainder)
        if cleaned is not None:
            return cleaned
    return None


def _extract_salient_topic(prompt: str) -> str | None:
    """Extract an injected event, interruption, or rumor topic from a prompt."""
    candidate_lines = [
        line.strip() for line in prompt.splitlines() if not _is_metadata_line(line)
    ]
    for marker_group in (
        _TIER1_EVENT_MARKERS,
        _TIER2_RUMOR_MARKERS,
        ("conversation with ",),
    ):
        for line in candidate_lines:
            extracted = _extract_after_marker(line, marker_group)
            if extracted is not None:
                return extracted

    for line in candidate_lines:
        if _URGENT_KEYWORD_PATTERN.search(line.lower()):
            stripped = re.sub(r"^-\s*", "", line)
            stripped = re.sub(r"^[A-Z][A-Za-z]+:\s*", "", stripped)
            cleaned = _clean_topic_payload(stripped)
            if cleaned is not None:
                return cleaned
    return None


def _extract_prompt_location(text: str) -> str | None:
    """Match a known village location case-insensitively inside a text snippet."""
    lowered = text.lower()
    for location in sorted(_LOCATIONS, key=len, reverse=True):
        pattern = rf"(?<![a-z0-9_]){re.escape(location.lower())}(?![a-z0-9_])"
        if re.search(pattern, lowered):
            return location
    return None


def _extract_participants(prompt: str) -> str:
    header_match = re.search(r"(?im)^Participants:\s*([^\n]+)", prompt)
    if header_match is not None:
        raw = " ".join(header_match.group(1).strip().split())
        if "," in raw and " and " not in raw:
            parts = [part.strip() for part in raw.split(",") if part.strip()]
            if len(parts) == 2:
                return f"{parts[0]} and {parts[1]}"
            if parts:
                return ", ".join(parts)
        if raw:
            return raw

    speaker_names: list[str] = []
    for match in re.finditer(r"(?m)^-\s*([A-Z][A-Za-z]+):\s+", prompt):
        name = match.group(1).strip()
        if name not in speaker_names:
            speaker_names.append(name)
    if len(speaker_names) >= 2:
        return f"{speaker_names[0]} and {speaker_names[1]}"
    if len(speaker_names) == 1:
        return speaker_names[0]
    return "Neighbors"


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
