"""Offline tests for SimulationEngine spatial invariants and named-location A* routing."""

from __future__ import annotations

import pytest

from app.config import get_settings
from sim.astar import find_path, manhattan
from sim.clock import SimClock
from sim.engine import SimulationEngine, TickPayload
from sim.world import GridPos, WorldMap


def _load_real_world() -> WorldMap:
    return WorldMap.from_tiled_json(get_settings().resolved_map_path())


def test_astar_between_all_named_locations() -> None:
    world = _load_real_world()
    route_pairs = [
        ("Cafe", "Park"),
        ("Park", "Market"),
        ("Market", "Town Square"),
        ("Town Square", "Bakery"),
        ("Bakery", "Library"),
        ("Home_Maya", "Cafe"),
    ]

    for start_name, goal_name in route_pairs:
        start = world.get_location(start_name).anchor
        goal = world.get_location(goal_name).anchor
        path = find_path(start, goal, world.is_walkable)

        assert path is not None, f"Expected valid path from {start_name} to {goal_name}"
        assert len(path) >= manhattan(start, goal)
        assert path[-1] == goal

        prev = start
        for tile in path:
            assert world.is_walkable(*tile)
            assert manhattan(prev, tile) == 1
            prev = tile


@pytest.mark.asyncio
async def test_engine_150_ticks_spatial_invariants() -> None:
    world = _load_real_world()
    clock = SimClock(speed=1, base_tick_seconds=0.05)
    engine = SimulationEngine(world=world, clock=clock, seed=42, dwell_ticks=4)

    assert len(engine.agents) == 4
    initial_positions: dict[str, GridPos] = {
        agent_id: (agent.x, agent.y) for agent_id, agent in engine.agents.items()
    }
    assert len(set(initial_positions.values())) == 4
    for pos in initial_positions.values():
        assert world.is_walkable(*pos)

    moved_agents: set[str] = set()
    for step_idx in range(1, 151):
        payload = await engine.step_once()
        assert payload.tick == step_idx
        assert len(payload.agents) == 4

        positions = [(agent.x, agent.y) for agent in engine.agents.values()]
        assert len(set(positions)) == len(engine.agents), (
            f"Tile overlap detected at tick {step_idx}: {positions}"
        )

        for agent_id, agent in engine.agents.items():
            assert world.is_walkable(agent.x, agent.y), (
                f"Agent {agent_id} clipped into {(agent.x, agent.y)} at tick {step_idx}"
            )
            if (agent.x, agent.y) != initial_positions[agent_id]:
                moved_agents.add(agent_id)

    assert moved_agents == set(engine.agents.keys())
    for agent_id, agent in engine.agents.items():
        assert len(agent.visited_locations) >= 2, (
            f"Agent {agent_id} only visited {agent.visited_locations}"
        )


@pytest.mark.asyncio
async def test_engine_callback_failure_does_not_halt_tick() -> None:
    world = _load_real_world()
    engine = SimulationEngine(world=world, clock=SimClock(), seed=42)
    received_ticks: list[int] = []

    async def failing_callback(_payload: TickPayload) -> None:
        raise RuntimeError("Simulated closed socket")

    async def healthy_callback(payload: TickPayload) -> None:
        received_ticks.append(payload.tick)

    engine.register_tick_callback(failing_callback)
    engine.register_tick_callback(healthy_callback)

    payload = await engine.step_once()
    assert payload.tick == 1
    assert received_ticks == [1]


@pytest.mark.asyncio
async def test_engine_contested_destination_routes_adjacent_without_overlap() -> None:
    world = _load_real_world()
    engine = SimulationEngine(world=world, clock=SimClock(), seed=42, dwell_ticks=20)
    town_square = world.get_location("Town Square").anchor

    # Place Liam directly at Town Square dwelling while Maya approaches Town Square.
    liam = engine.agents["liam"]
    liam.x, liam.y = town_square
    liam.target_location = "Town Square"
    liam.path = []
    liam.dwell_ticks_remaining = 20

    maya = engine.agents["maya"]
    maya.x, maya.y = (town_square[0] - 3, town_square[1])
    maya.routine = ["Town Square", "Bakery"]
    maya.routine_index = len(maya.routine) - 1
    maya.target_location = None
    maya.path = []
    maya.dwell_ticks_remaining = 0

    for _ in range(10):
        await engine.step_once()
        positions = [(a.x, a.y) for a in engine.agents.values()]
        assert len(set(positions)) == len(engine.agents)
        assert all(world.is_walkable(a.x, a.y) for a in engine.agents.values())

    assert "Town Square" in maya.visited_locations
    assert (maya.x, maya.y) != (liam.x, liam.y)
    assert manhattan((maya.x, maya.y), town_square) == 1

