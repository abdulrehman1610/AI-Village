"""Offline unit tests for hierarchical DailyPlanner and AgentBrain."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest_asyncio

from agents.agent import AgentBrain, PendingObservation
from agents.personas import AgentPersona, get_persona
from agents.planner import AgentPlanState, DailyPlanner, canonicalize_location
from app.config import get_settings
from app.db import Database
from llm.gateway import LLMGateway
from llm.providers.mock import MockProvider
from llm.schemas import DailyPlanItem
from memory.embeddings import EmbeddingService
from memory.models import AgentRecord
from memory.retrieval import MemoryRetriever
from memory.store import MemoryStore
from sim.clock import SimClock
from sim.world import WorldMap


@dataclass
class _RuntimeDeps:
    db: Database
    world: WorldMap
    store: MemoryStore
    retriever: MemoryRetriever
    gateway: LLMGateway
    planner: DailyPlanner
    persona: AgentPersona


@pytest_asyncio.fixture
async def deps() -> AsyncIterator[_RuntimeDeps]:
    """Build an isolated in-memory DB, MockProvider gateway, WorldMap, and MemoryRetriever."""
    world = WorldMap.from_tiled_json(get_settings().resolved_map_path())
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.init_models()
    embeddings = EmbeddingService.from_mode("mock")
    store = MemoryStore(db, embeddings)
    retriever = MemoryRetriever(store, embeddings)
    gateway = LLMGateway(provider=MockProvider(seed=42), db=db, seed=42)
    planner = DailyPlanner()
    persona = get_persona("maya")

    home_anchor = world.get_location(persona.home_location).anchor
    await store.upsert_agent(
        AgentRecord(
            id=persona.id,
            name=persona.name,
            persona_json=persona.to_persona_json(),
            home_location=persona.home_location,
            x=home_anchor[0],
            y=home_anchor[1],
        )
    )
    try:
        yield _RuntimeDeps(
            db=db,
            world=world,
            store=store,
            retriever=retriever,
            gateway=gateway,
            planner=planner,
            persona=persona,
        )
    finally:
        await db.dispose()


def test_canonicalize_location_handles_exact_normalized_substring_and_fallback(
    deps: _RuntimeDeps,
) -> None:
    world = deps.world
    fallback = "Home_Maya"

    assert canonicalize_location("Cafe", world, fallback) == "Cafe"
    assert canonicalize_location("town square", world, fallback) == "Town Square"
    assert canonicalize_location("home maya", world, fallback) == "Home_Maya"
    assert canonicalize_location("Home-Liam", world, fallback) == "Home_Liam"
    assert canonicalize_location("near the Bakery", world, fallback) == "Bakery"
    assert canonicalize_location("Square", world, fallback) == "Town Square"
    assert canonicalize_location("Space Station", world, fallback) == "Home_Maya"
    assert canonicalize_location("Home", world, fallback) == "Home_Maya"
    assert canonicalize_location("   ", world, fallback) == "Home_Maya"

    for sample in (
        "Cafe",
        "town square",
        "home maya",
        "near the Bakery",
        "Space Station",
    ):
        resolved = canonicalize_location(sample, world, fallback)
        assert world.get_location(resolved).name == resolved


async def test_generate_daily_plan_and_lazy_minute_decomposition_zero_tight_loop_calls(
    deps: _RuntimeDeps,
) -> None:
    clock = SimClock(tick=0)  # Day 1 06:00
    plan_state = await deps.planner.generate_daily_plan(
        deps.persona,
        clock=clock,
        world=deps.world,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        memory_store=deps.store,
    )

    assert plan_state.day == 1
    assert 5 <= len(plan_state.daily_items) <= 8
    for item in plan_state.daily_items:
        assert 0 <= item.start_hour < item.end_hour <= 24
        assert item.location in deps.world.locations
        assert deps.world.get_location(item.location).name == item.location

    plan_memories = await deps.store.list_memories(deps.persona.id, memory_type="plan")
    assert len(plan_memories) == 1
    assert plan_memories[0].importance == 6
    assert plan_memories[0].created_tick == 0

    calls_after_wakeup = int((await deps.gateway.get_usage_summary())["total_calls"])
    assert calls_after_wakeup == 1

    # Entering block 0 lazily decomposes into MinuteSteps once.
    first_step = await deps.planner.resolve_minute_step(
        deps.persona,
        plan_state,
        clock=clock,
        world=deps.world,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        dwell_ticks=4,
    )
    assert first_step.location in deps.world.locations
    calls_after_first_decomp = int((await deps.gateway.get_usage_summary())["total_calls"])
    assert calls_after_first_decomp == 2

    # Stepping multiple ticks while walking (not arrived) pins the step with zero LLM calls.
    for _ in range(12):
        clock.advance(1)
        pinned = await deps.planner.resolve_minute_step(
            deps.persona,
            plan_state,
            clock=clock,
            world=deps.world,
            llm_gateway=deps.gateway,
            retriever=deps.retriever,
            dwell_ticks=4,
        )
        assert pinned is first_step
        assert pinned.end_tick >= clock.tick + 2

    assert int((await deps.gateway.get_usage_summary())["total_calls"]) == calls_after_first_decomp

    # Mark arrived and step through the capped dwell inside the same block with zero new calls.
    first_step.arrived = True
    first_step.end_tick = clock.tick + min(first_step.duration_minutes, 8)
    while clock.tick + 1 < first_step.end_tick:
        clock.advance(1)
        step = await deps.planner.resolve_minute_step(
            deps.persona,
            plan_state,
            clock=clock,
            world=deps.world,
            llm_gateway=deps.gateway,
            retriever=deps.retriever,
            dwell_ticks=4,
        )
        assert step is first_step

    assert int((await deps.gateway.get_usage_summary())["total_calls"]) == calls_after_first_decomp


async def test_resolve_minute_step_advances_across_steps_and_blocks(deps: _RuntimeDeps) -> None:
    clock = SimClock(tick=0)  # Day 1 06:00
    plan_state = AgentPlanState(
        day=1,
        daily_items=[
            DailyPlanItem(start_hour=6, end_hour=9, location="Bakery", description="Bake bread"),
            DailyPlanItem(start_hour=9, end_hour=12, location="Cafe", description="Drink coffee"),
        ],
    )
    step0 = await deps.planner.resolve_minute_step(
        deps.persona,
        plan_state,
        clock=clock,
        world=deps.world,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        dwell_ticks=4,
    )
    assert plan_state.active_block_index == 0
    assert step0.location in deps.world.locations
    calls_block0 = int((await deps.gateway.get_usage_summary())["total_calls"])
    assert calls_block0 == 1

    # Advance clock past block 0's end_hour (09:00 -> tick = 180) and verify block transition.
    clock = SimClock(tick=180)
    assert clock.hour == 9
    step_block1 = await deps.planner.resolve_minute_step(
        deps.persona,
        plan_state,
        clock=clock,
        world=deps.world,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        dwell_ticks=4,
    )
    assert plan_state.active_block_index == 1
    assert step_block1.location in deps.world.locations
    assert int((await deps.gateway.get_usage_summary())["total_calls"]) == 2


async def test_replan_remaining_day_midday_and_late_evening(deps: _RuntimeDeps) -> None:
    # Add an event memory so retrieval has context for replanning.
    await deps.store.add_memory(
        agent_id=deps.persona.id,
        memory_type="observation",
        text="Observed event at Market: urgent spice delivery arrived early",
        importance=9,
        created_tick=470,
    )

    clock = SimClock(tick=0)  # Day 1 06:00
    plan_state = await deps.planner.generate_daily_plan(
        deps.persona,
        clock=clock,
        world=deps.world,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        memory_store=deps.store,
    )
    # Decompose block 0 and block 3 so we can verify prefix preserved & tail cache cleared.
    await deps.planner.resolve_minute_step(
        deps.persona,
        plan_state,
        clock=clock,
        world=deps.world,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
    )
    # Inject a synthetic cached step on the final block index to ensure tail cache clears.
    tail_idx = len(plan_state.daily_items) - 1
    plan_state.minute_steps_by_block[tail_idx] = [
        plan_state.minute_steps_by_block[0][0],
    ]

    # Mid-day interruption at 14:00 (tick = 480 from 06:00).
    clock = SimClock(tick=480)
    assert clock.hour == 14
    earlier_blocks = [item for item in plan_state.daily_items if item.end_hour <= 14]
    replanned = await deps.planner.replan_remaining_day(
        deps.persona,
        plan_state,
        reason="Observed event at Market: urgent spice delivery arrived early",
        clock=clock,
        world=deps.world,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        memory_store=deps.store,
    )

    assert replanned.last_replan_tick == 480
    assert replanned.daily_items[: len(earlier_blocks)] == earlier_blocks
    suffix = replanned.daily_items[len(earlier_blocks) :]
    assert 1 <= len(suffix) <= 8
    for block in suffix:
        assert block.start_hour >= 14
        assert block.end_hour > block.start_hour
        assert block.location in deps.world.locations
    if earlier_blocks:
        assert 0 in replanned.minute_steps_by_block
    assert len(replanned.daily_items) - 1 not in replanned.minute_steps_by_block

    # Late-evening interruption at 22:30 (tick = 990 from 06:00).
    late_clock = SimClock(tick=990)
    assert (late_clock.hour, late_clock.minute) == (22, 30)
    late_replanned = await deps.planner.replan_remaining_day(
        deps.persona,
        replanned,
        reason="Festival lanterns lit in Town Square",
        clock=late_clock,
        world=deps.world,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        memory_store=deps.store,
    )
    late_suffix = [item for item in late_replanned.daily_items if item.end_hour > 22]
    assert 1 <= len(late_suffix) <= 8
    for block in late_suffix:
        assert 22 <= block.start_hour < block.end_hour <= 24
        assert deps.world.get_location(block.location).name == block.location

    plan_memories = await deps.store.list_memories(deps.persona.id, memory_type="plan")
    assert len(plan_memories) == 3  # initial + 2 replans
    assert plan_memories[0].importance == 7


def test_agent_brain_perceive_dedup_importance_and_arrival(deps: _RuntimeDeps) -> None:
    brain = AgentBrain(
        agent_id=deps.persona.id,
        persona=deps.persona,
        peer_perception_cooldown=25,
        replan_cooldown=10,
    )
    assert json.loads(brain.serialized_plan_json(deps.persona.default_routine)) == list(
        deps.persona.default_routine
    )

    brain.queue_observation("Fresh bread cooling on racks", min_importance=3)
    first = brain.perceive(
        tick=10,
        current_location="Bakery",
        nearby_peers=[("liam", "Liam", "Walking to Cafe"), ("maya", "Maya", "Self")],
    )
    assert [obs.text for obs in first] == [
        "Fresh bread cooling on racks",
        "Saw Liam nearby (Walking to Cafe)",
    ]

    # Within peer_perception_cooldown (tick 20 - 10 = 10 < 25), Liam is deduplicated.
    second = brain.perceive(
        tick=20,
        current_location="Bakery",
        nearby_peers=[("liam", "Liam", "Brewing espresso")],
    )
    assert second == []

    # After cooldown elapses (tick 35 - 10 = 25 >= 25), Liam sighting emits again.
    third = brain.perceive(
        tick=35,
        current_location="Cafe",
        nearby_peers=[("liam", "Liam", "Brewing espresso")],
    )
    assert [obs.text for obs in third] == ["Saw Liam nearby (Brewing espresso)"]

    # Arrival queues observation only when location changes.
    brain.mark_arrived(location="Cafe", tick=36, dwell_ticks=4)
    brain.mark_arrived(location="Cafe", tick=37, dwell_ticks=4)
    arrival_obs = brain.perceive(tick=38, current_location="Cafe", nearby_peers=[])
    assert [obs.text for obs in arrival_obs] == ["Arrived at Cafe"]

    # Importance accumulation and replan gating.
    should_replan, reason = brain.record_importance([3, 4], tick=38, observations=first)
    assert brain.accumulated_importance == 7
    assert (should_replan, reason) == (False, "")

    urgent_obs = [
        PendingObservation(
            agent_id=deps.persona.id,
            text="Fire at Market!",
            min_importance=9,
            trigger_replan=True,
            reason="Fire at Market!",
        )
    ]
    should_replan, reason = brain.record_importance([9], tick=39, observations=urgent_obs)
    assert brain.accumulated_importance == 16
    assert (should_replan, reason) == (True, "Fire at Market!")

    # High-score observation without trigger_replan respects replan_cooldown when plan_state exists.
    brain.plan_state = AgentPlanState(
        day=1,
        daily_items=[
            DailyPlanItem(start_hour=6, end_hour=9, location="Cafe", description="Coffee"),
        ],
        last_replan_tick=35,
    )
    high_obs = [PendingObservation(agent_id=deps.persona.id, text="Loud bell in Town Square")]
    blocked, _ = brain.record_importance([8], tick=40, observations=high_obs)
    assert blocked is False
    allowed, allowed_reason = brain.record_importance([8], tick=45, observations=high_obs)
    assert (allowed, allowed_reason) == (True, "Loud bell in Town Square")


async def test_agent_brain_decide_lifecycle_and_day2_rollover(deps: _RuntimeDeps) -> None:
    brain = AgentBrain(agent_id=deps.persona.id, persona=deps.persona)
    clock = SimClock(tick=0)  # Day 1 06:00

    # Conversing short-circuits without any LLM calls.
    target, action, replanned = await brain.decide(
        clock=clock,
        world=deps.world,
        planner=deps.planner,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        memory_store=deps.store,
        needs_replan=True,
        replan_reason="Ignored while conversing",
        is_conversing=True,
        dwell_ticks=4,
    )
    assert (target, action, replanned) == (None, "", False)
    assert int((await deps.gateway.get_usage_summary())["total_calls"]) == 0

    # Tick 0: generates Day 1 plan + lazily decomposes block 0.
    target1, action1, replanned1 = await brain.decide(
        clock=clock,
        world=deps.world,
        planner=deps.planner,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        memory_store=deps.store,
        needs_replan=False,
        replan_reason="",
        is_conversing=False,
        dwell_ticks=4,
    )
    assert target1 is not None and target1 in deps.world.locations
    assert action1 != ""
    assert replanned1 is False
    assert brain.plan_state is not None and brain.plan_state.day == 1
    calls_day1_start = int((await deps.gateway.get_usage_summary())["total_calls"])
    assert calls_day1_start == 2

    # Tick 1 / Tick 2: uses cached step with zero additional LLM calls.
    clock.advance(1)
    target2, action2, replanned2 = await brain.decide(
        clock=clock,
        world=deps.world,
        planner=deps.planner,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        memory_store=deps.store,
        needs_replan=False,
        replan_reason="",
        is_conversing=False,
        dwell_ticks=4,
    )
    assert (target2, action2, replanned2) == (target1, action1, False)
    assert int((await deps.gateway.get_usage_summary())["total_calls"]) == calls_day1_start

    # Mark arrived and verify serialized_plan_json includes structured blocks and actions.
    brain.mark_arrived(location=target1, tick=clock.tick, dwell_ticks=4)
    arrived_step = brain.plan_state.current_step()
    assert arrived_step is not None
    assert arrived_step.arrived is True
    serialized = json.loads(brain.serialized_plan_json(deps.persona.default_routine))
    assert isinstance(serialized, list)
    assert len(serialized) == len(brain.plan_state.daily_items)
    assert "actions" in serialized[brain.plan_state.active_block_index]

    # Interruption replanning sets replanned=True.
    clock.advance(60)  # 07:01
    target3, _, replanned3 = await brain.decide(
        clock=clock,
        world=deps.world,
        planner=deps.planner,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        memory_store=deps.store,
        needs_replan=True,
        replan_reason="Surprise gathering at Park",
        is_conversing=False,
        dwell_ticks=4,
    )
    assert target3 in deps.world.locations
    assert replanned3 is True

    # Day 2 rollover (tick >= 1080 from 06:00 start_minute_of_day=360) generates a fresh plan.
    day2_clock = SimClock(tick=1440)  # Day 2 06:00
    assert day2_clock.day == 2
    target4, _, replanned4 = await brain.decide(
        clock=day2_clock,
        world=deps.world,
        planner=deps.planner,
        llm_gateway=deps.gateway,
        retriever=deps.retriever,
        memory_store=deps.store,
        needs_replan=False,
        replan_reason="",
        is_conversing=False,
        dwell_ticks=4,
    )
    assert target4 in deps.world.locations
    assert replanned4 is False
    assert brain.plan_state.day == 2
