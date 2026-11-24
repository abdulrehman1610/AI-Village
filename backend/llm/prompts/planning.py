"""Typed prompt builders for hierarchical daily planning and replanning."""

from __future__ import annotations

from collections.abc import Sequence

from agents.personas import AgentPersona
from llm.schemas import DailyPlanItem


def _format_memories(memories: Sequence[str]) -> str:
    cleaned = [item.strip() for item in memories if item.strip()]
    if not cleaned:
        return "- (none)"
    return "\n".join(f"- {item}" for item in cleaned)


def _format_locations(valid_locations: Sequence[str]) -> str:
    cleaned = [loc.strip() for loc in valid_locations if loc.strip()]
    return ", ".join(cleaned) if cleaned else "(none)"


def _format_plan_blocks(blocks: Sequence[DailyPlanItem]) -> str:
    if not blocks:
        return "- (none)"
    return "\n".join(
        f"- {item.start_hour:02d}:00-{item.end_hour:02d}:00 at {item.location}: {item.description}"
        for item in blocks
    )


def build_daily_plan_prompt(
    *,
    persona: AgentPersona,
    sim_time: str,
    valid_locations: Sequence[str],
    memories: Sequence[str],
) -> str:
    """Build the wake-up prompt requesting 5..8 contiguous DailyPlanItem blocks."""
    locations_text = _format_locations(valid_locations)
    memories_block = _format_memories(memories)
    return (
        "Create a daily schedule for this villager.\n"
        f"Persona: {persona.summary_text()}\n"
        f"Sim time: {sim_time}\n"
        f"Valid locations: {locations_text}\n"
        "Context memories:\n"
        f"{memories_block}\n\n"
        "Instructions:\n"
        "- Return 5 to 8 contiguous DailyPlanItem blocks covering waking hours "
        "(06:00 to 22:00 or 24:00).\n"
        "- Every location must come verbatim from Valid locations.\n"
        "- Keep descriptions concrete and grounded in the villager's role, goals, "
        "and context memories."
    )


def build_hourly_action_prompt(
    *,
    persona: AgentPersona,
    block: DailyPlanItem,
    current_hour: int,
    current_minute: int,
    valid_locations: Sequence[str],
    memories: Sequence[str],
) -> str:
    """Build the block decomposition prompt requesting hourly focus and minute-level steps."""
    locations_text = _format_locations(valid_locations)
    memories_block = _format_memories(memories)
    return (
        "Decompose the active schedule block into an hourly focus and minute-level steps.\n"
        f"Persona: {persona.summary_text()}\n"
        f"Block: {block.start_hour:02d}:00-{block.end_hour:02d}:00 at {block.location}\n"
        f"Current time: {current_hour:02d}:{current_minute:02d}\n"
        f"Block goal: {block.description}\n"
        f"Valid locations: {locations_text}\n"
        "Context memories:\n"
        f"{memories_block}\n\n"
        "Instructions:\n"
        "- Return 1 to 6 MinuteActionItem steps with duration_minutes between 5 and 60.\n"
        "- Every location must come verbatim from Valid locations.\n"
        "- Keep hourly_focus and action descriptions concrete and aligned with the block goal."
    )


def build_replan_prompt(
    *,
    persona: AgentPersona,
    current_hour: int,
    sim_time: str,
    interruption_reason: str,
    remaining_blocks: Sequence[DailyPlanItem],
    valid_locations: Sequence[str],
    memories: Sequence[str],
) -> str:
    """Build a partial-day replanning prompt starting from current_hour."""
    locations_text = _format_locations(valid_locations)
    memories_block = _format_memories(memories)
    remaining_text = _format_plan_blocks(remaining_blocks)
    return (
        "Update the remainder of this villager's daily schedule after a new situation.\n"
        f"Persona: {persona.summary_text()}\n"
        f"Current hour: {current_hour}\n"
        f"Sim time: {sim_time}\n"
        f"Interruption: {interruption_reason}\n"
        "Remaining schedule:\n"
        f"{remaining_text}\n"
        f"Valid locations: {locations_text}\n"
        "Context memories:\n"
        f"{memories_block}\n\n"
        "Instructions:\n"
        f"- Return 1 to 8 contiguous DailyPlanItem blocks starting from hour {current_hour} "
        "through the end of the day (up to 24:00).\n"
        "- Every location must come verbatim from Valid locations.\n"
        "- Address the new situation naturally while keeping realistic follow-up activities."
    )
