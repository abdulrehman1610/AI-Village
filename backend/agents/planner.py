"""Hierarchical daily planner (day -> hour -> minute) and location canonicalization."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from agents.personas import AgentPersona
from llm.gateway import LLMGateway
from llm.prompts.planning import (
    build_daily_plan_prompt,
    build_hourly_action_prompt,
    build_replan_prompt,
)
from llm.schemas import DailyPlanItem
from memory.retrieval import MemoryRetriever
from memory.store import MemoryStore
from sim.clock import SimClock
from sim.world import WorldMap

_MIN_DWELL_TICKS = 8
PLAN_MEMORY_IMPORTANCE = 6
REPLAN_MEMORY_IMPORTANCE = 7
_COLLAPSE_PATTERN = re.compile(r"[^a-z0-9]+")


def _normalize_key(value: str) -> str:
    return _COLLAPSE_PATTERN.sub("", value.strip().lower())


def _resolve_fallback_location(locations: dict[str, Any], fallback_location: str) -> str:
    if not locations:
        raise ValueError("WorldMap defines no locations.")

    stripped_fallback = fallback_location.strip()
    if stripped_fallback in locations:
        return stripped_fallback

    norm_fallback = _normalize_key(stripped_fallback)
    if norm_fallback:
        for key in locations:
            if _normalize_key(key) == norm_fallback:
                return key

    return next(iter(locations))


def canonicalize_location(raw_location: str, world: WorldMap, fallback_location: str) -> str:
    """Map an arbitrary LLM-returned location string onto a valid WorldMap location key."""
    locations = world.locations
    fallback = _resolve_fallback_location(locations, fallback_location)

    stripped = raw_location.strip()
    if not stripped:
        return fallback

    # 1. Exact match against WorldMap keys.
    if stripped in locations:
        return stripped

    # 2. Case-insensitive / punctuation-and-separator-collapsed match.
    norm_raw = _normalize_key(stripped)
    if norm_raw:
        for key in locations:
            if _normalize_key(key) == norm_raw:
                return key

    # 3. Longest substring match against WorldMap location keys.
    raw_lower = stripped.lower()
    substring_matches: list[str] = []
    for key in locations:
        key_lower = key.lower()
        norm_key = _normalize_key(key)
        if key_lower in raw_lower or (norm_key and norm_key in norm_raw):
            substring_matches.append(key)

    if substring_matches:
        return min(substring_matches, key=lambda key: (-len(key), key))

    # 4. Unique reverse substring match for longer phrases (e.g. "Square" -> "Town Square").
    if len(norm_raw) >= 4:
        reverse_matches = [key for key in locations if norm_raw in _normalize_key(key)]
        if len(reverse_matches) == 1:
            return reverse_matches[0]

    # 5. Safe fallback so world.get_location(...) never raises KeyError.
    return fallback


@dataclass
class MinuteStep:
    """Single concrete minute-level action target executed by an agent."""

    duration_minutes: int
    location: str
    action: str
    start_tick: int
    end_tick: int
    arrived: bool = False


@dataclass
class AgentPlanState:
    """Per-agent hierarchical schedule state across day, block, and minute levels."""

    day: int
    daily_items: list[DailyPlanItem]
    active_block_index: int = 0
    minute_steps_by_block: dict[int, list[MinuteStep]] = field(default_factory=dict)
    active_minute_index: int = 0
    last_replan_tick: int = -100
    hourly_focus_by_block: dict[int, str] = field(default_factory=dict)

    def active_block(self) -> DailyPlanItem | None:
        """Return the currently active DailyPlanItem block, or None if out of bounds."""
        if 0 <= self.active_block_index < len(self.daily_items):
            return self.daily_items[self.active_block_index]
        return None

    def current_step(self) -> MinuteStep | None:
        """Return the active MinuteStep within the active block, or None if not decomposed."""
        steps = self.minute_steps_by_block.get(self.active_block_index)
        if steps and 0 <= self.active_minute_index < len(steps):
            return steps[self.active_minute_index]
        return None

    def to_json(self) -> str:
        """Serialize daily blocks and any lazily decomposed minute steps to JSON."""
        payload: list[dict[str, Any]] = []
        for idx, block in enumerate(self.daily_items):
            entry: dict[str, Any] = {
                "start_hour": block.start_hour,
                "end_hour": block.end_hour,
                "location": block.location,
                "description": block.description,
            }
            if idx in self.hourly_focus_by_block:
                entry["hourly_focus"] = self.hourly_focus_by_block[idx]
            steps = self.minute_steps_by_block.get(idx)
            if steps:
                entry["actions"] = [
                    {
                        "duration_minutes": step.duration_minutes,
                        "location": step.location,
                        "action": step.action,
                        "start_tick": step.start_tick,
                        "end_tick": step.end_tick,
                        "arrived": step.arrived,
                    }
                    for step in steps
                ]
            payload.append(entry)
        return json.dumps(payload)


def _capped_step_duration(duration_minutes: int, dwell_ticks: int) -> int:
    return max(1, min(duration_minutes, max(dwell_ticks, _MIN_DWELL_TICKS)))


def _normalize_plan_items(
    items: Sequence[DailyPlanItem],
    *,
    world: WorldMap,
    fallback_location: str,
    min_start_hour: int = 0,
) -> list[DailyPlanItem]:
    normalized: list[DailyPlanItem] = []
    clamped_floor = max(0, min(23, min_start_hour))
    for item in items:
        start_hour = max(clamped_floor, min(23, item.start_hour))
        end_hour = max(start_hour + 1, min(24, item.end_hour))
        canonical_loc = canonicalize_location(item.location, world, fallback_location)
        normalized.append(
            DailyPlanItem(
                start_hour=start_hour,
                end_hour=end_hour,
                location=canonical_loc,
                description=item.description.strip() or f"Spend time at {canonical_loc}",
            )
        )
    normalized.sort(key=lambda block: (block.start_hour, block.end_hour))
    return normalized


def _find_block_index_for_hour(items: Sequence[DailyPlanItem], hour: int) -> int:
    if not items:
        return 0
    for idx, block in enumerate(items):
        if block.start_hour <= hour < block.end_hour:
            return idx
    for idx, block in enumerate(items):
        if block.start_hour >= hour:
            return idx
    return len(items) - 1


def _summarize_plan_blocks(blocks: Sequence[DailyPlanItem]) -> str:
    return "; ".join(
        f"{block.start_hour:02d}:00-{block.end_hour:02d}:00 {block.location} ({block.description})"
        for block in blocks
    )


class DailyPlanner:
    """Three-tier hierarchical planner backed by LLMGateway and MemoryRetriever."""

    def __init__(self, *, retrieval_top_k: int = 8) -> None:
        self.retrieval_top_k = max(1, retrieval_top_k)

    async def generate_daily_plan(
        self,
        persona: AgentPersona,
        *,
        clock: SimClock,
        world: WorldMap,
        llm_gateway: LLMGateway,
        retriever: MemoryRetriever | None = None,
        memory_store: MemoryStore | None = None,
    ) -> AgentPlanState:
        """Generate a 5..8 block wake-up day plan and persist a plan memory."""
        memories: list[str] = []
        if retriever is not None:
            goals = "; ".join(persona.starting_goals)
            query = f"{persona.name} {persona.role} daily goals: {goals}"
            scored = await retriever.retrieve(
                persona.id,
                query,
                clock.tick,
                top_k=self.retrieval_top_k,
            )
            memories = [item.memory.text for item in scored]

        valid_locations = [loc.name for loc in world.list_locations()]
        prompt = build_daily_plan_prompt(
            persona=persona,
            sim_time=clock.sim_time_str,
            valid_locations=valid_locations,
            memories=memories,
        )
        response = await llm_gateway.generate_daily_plan(
            prompt,
            tick=clock.tick,
            agent_id=persona.id,
        )

        normalized_items = _normalize_plan_items(
            response.items,
            world=world,
            fallback_location=persona.home_location,
        )
        active_block_index = _find_block_index_for_hour(normalized_items, clock.hour)

        if memory_store is not None:
            summary = _summarize_plan_blocks(normalized_items)
            await memory_store.add_memory(
                agent_id=persona.id,
                memory_type="plan",
                text=f"Day {clock.day} plan: {summary}",
                importance=PLAN_MEMORY_IMPORTANCE,
                created_tick=clock.tick,
            )

        return AgentPlanState(
            day=clock.day,
            daily_items=normalized_items,
            active_block_index=active_block_index,
        )

    async def replan_remaining_day(
        self,
        persona: AgentPersona,
        plan_state: AgentPlanState,
        *,
        reason: str,
        clock: SimClock,
        world: WorldMap,
        llm_gateway: LLMGateway,
        retriever: MemoryRetriever | None = None,
        memory_store: MemoryStore | None = None,
    ) -> AgentPlanState:
        """Preserve completed earlier blocks and replan remaining hours after an interruption."""
        completed_prefix: list[DailyPlanItem] = []
        preserved_steps: dict[int, list[MinuteStep]] = {}
        preserved_focus: dict[int, str] = {}
        remaining_blocks: list[DailyPlanItem] = []

        for orig_idx, block in enumerate(plan_state.daily_items):
            if block.end_hour <= clock.hour:
                new_idx = len(completed_prefix)
                completed_prefix.append(block)
                if orig_idx in plan_state.minute_steps_by_block:
                    preserved_steps[new_idx] = plan_state.minute_steps_by_block[orig_idx]
                if orig_idx in plan_state.hourly_focus_by_block:
                    preserved_focus[new_idx] = plan_state.hourly_focus_by_block[orig_idx]
            else:
                remaining_blocks.append(block)

        memories: list[str] = []
        if retriever is not None:
            query = reason.strip() or f"{persona.name} {persona.role} schedule adjustment"
            scored = await retriever.retrieve(
                persona.id,
                query,
                clock.tick,
                top_k=self.retrieval_top_k,
            )
            memories = [item.memory.text for item in scored]

        valid_locations = [loc.name for loc in world.list_locations()]
        prompt = build_replan_prompt(
            persona=persona,
            current_hour=clock.hour,
            sim_time=clock.sim_time_str,
            interruption_reason=reason,
            remaining_blocks=remaining_blocks,
            valid_locations=valid_locations,
            memories=memories,
        )
        response = await llm_gateway.generate_replan(
            prompt,
            tick=clock.tick,
            agent_id=persona.id,
        )

        replanned_suffix = _normalize_plan_items(
            response.items,
            world=world,
            fallback_location=persona.home_location,
            min_start_hour=clock.hour,
        )
        merged_items = completed_prefix + replanned_suffix

        if memory_store is not None:
            summary = _summarize_plan_blocks(replanned_suffix)
            await memory_store.add_memory(
                agent_id=persona.id,
                memory_type="plan",
                text=f"Replanned Day {clock.day} from {clock.hour:02d}:00 ({reason}): {summary}",
                importance=REPLAN_MEMORY_IMPORTANCE,
                created_tick=clock.tick,
            )

        plan_state.day = clock.day
        plan_state.daily_items = merged_items
        plan_state.minute_steps_by_block = preserved_steps
        plan_state.hourly_focus_by_block = preserved_focus
        plan_state.active_block_index = _find_block_index_for_hour(merged_items, clock.hour)
        plan_state.active_minute_index = 0
        plan_state.last_replan_tick = clock.tick
        return plan_state

    async def resolve_minute_step(
        self,
        persona: AgentPersona,
        plan_state: AgentPlanState,
        *,
        clock: SimClock,
        world: WorldMap,
        llm_gateway: LLMGateway,
        retriever: MemoryRetriever | None = None,
        dwell_ticks: int = 4,
    ) -> MinuteStep:
        """Resolve the current MinuteStep, lazily decomposing blocks on first entry only."""
        if not plan_state.daily_items:
            fallback = canonicalize_location(persona.home_location, world, persona.home_location)
            duration = max(dwell_ticks, _MIN_DWELL_TICKS)
            return MinuteStep(
                duration_minutes=duration,
                location=fallback,
                action=f"Follow routine at {fallback}",
                start_tick=clock.tick,
                end_tick=clock.tick + duration,
            )

        # Advance past blocks whose end_hour has elapsed when a subsequent block follows.
        while plan_state.active_block_index + 1 < len(plan_state.daily_items):
            current_block = plan_state.daily_items[plan_state.active_block_index]
            if clock.hour >= current_block.end_hour:
                plan_state.active_block_index += 1
                plan_state.active_minute_index = 0
            else:
                break

        # Serve cached minute steps for the active block without additional LLM calls.
        if plan_state.active_block_index in plan_state.minute_steps_by_block:
            steps = plan_state.minute_steps_by_block[plan_state.active_block_index]
            if steps and plan_state.active_minute_index < len(steps):
                step = steps[plan_state.active_minute_index]
                if not step.arrived:
                    # Keep the active step pinned while still walking to its location.
                    step.end_tick = max(step.end_tick, clock.tick + 2)
                    return step
                if clock.tick < step.end_tick:
                    return step

                plan_state.active_minute_index += 1
                if plan_state.active_minute_index < len(steps):
                    next_step = steps[plan_state.active_minute_index]
                    next_step.start_tick = clock.tick
                    next_step.end_tick = clock.tick + _capped_step_duration(
                        next_step.duration_minutes, dwell_ticks
                    )
                    return next_step

            # All minute steps in the active block have completed.
            current_block = plan_state.daily_items[plan_state.active_block_index]
            if (
                plan_state.active_block_index + 1 < len(plan_state.daily_items)
                and clock.hour >= current_block.start_hour
            ):
                plan_state.active_block_index += 1
                plan_state.active_minute_index = 0
            elif steps:
                last_step = steps[-1]
                plan_state.active_minute_index = len(steps) - 1
                last_step.end_tick = max(
                    last_step.end_tick,
                    clock.tick + _capped_step_duration(last_step.duration_minutes, dwell_ticks),
                )
                return last_step

        # Lazy hourly -> minute decomposition only when entering an unexpanded block.
        active_block = plan_state.daily_items[plan_state.active_block_index]
        memories: list[str] = []
        if retriever is not None:
            query = f"{active_block.location} {active_block.description}"
            scored = await retriever.retrieve(
                persona.id,
                query,
                clock.tick,
                top_k=self.retrieval_top_k,
            )
            memories = [item.memory.text for item in scored]

        valid_locations = [loc.name for loc in world.list_locations()]
        prompt = build_hourly_action_prompt(
            persona=persona,
            block=active_block,
            current_hour=clock.hour,
            current_minute=clock.minute,
            valid_locations=valid_locations,
            memories=memories,
        )
        hourly = await llm_gateway.generate_hourly_actions(
            prompt,
            tick=clock.tick,
            agent_id=persona.id,
        )

        decomposed: list[MinuteStep] = []
        cursor_tick = clock.tick
        for action_item in hourly.actions:
            step_loc = canonicalize_location(
                action_item.location,
                world,
                active_block.location,
            )
            capped = _capped_step_duration(action_item.duration_minutes, dwell_ticks)
            decomposed.append(
                MinuteStep(
                    duration_minutes=action_item.duration_minutes,
                    location=step_loc,
                    action=action_item.action.strip() or f"Activity at {step_loc}",
                    start_tick=cursor_tick,
                    end_tick=cursor_tick + capped,
                    arrived=False,
                )
            )
            cursor_tick += capped

        plan_state.hourly_focus_by_block[plan_state.active_block_index] = hourly.hourly_focus
        plan_state.minute_steps_by_block[plan_state.active_block_index] = decomposed
        plan_state.active_minute_index = 0
        return decomposed[0]
