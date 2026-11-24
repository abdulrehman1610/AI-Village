"""Async simulation engine coordinating agent navigation, spatial invariants, and ticks."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from agents.personas import SEEDED_PERSONAS, AgentPersona
from llm.gateway import LLMGateway
from memory.models import AgentRecord
from memory.retrieval import MemoryRetriever
from memory.store import MemoryCreate, MemoryStore
from sim.astar import find_path
from sim.clock import SimClock
from sim.world import GridPos, WorldMap

logger = logging.getLogger(__name__)

MAX_STALL_TICKS = 15


class AgentSnapshot(BaseModel):
    """Serializable per-agent state included in WebSocket ticks and REST responses."""

    id: str
    name: str
    role: str
    sprite_index: int
    x: int
    y: int
    target_location: str | None
    current_action: str


class TickPayload(BaseModel):
    """Authoritative simulation snapshot emitted after each simulation tick."""

    type: Literal["tick"] = "tick"
    tick: int
    sim_time: str
    day: int
    speed: int
    running: bool
    agents: list[AgentSnapshot]


@dataclass
class AgentEntity:
    """Mutable runtime state for an autonomous villager agent."""

    id: str
    name: str
    role: str
    sprite_index: int
    home_location: str
    x: int
    y: int
    persona: AgentPersona
    target_location: str | None = None
    path: list[GridPos] = field(default_factory=list)
    current_action: str = "Idle"
    dwell_ticks_remaining: int = 0
    stall_ticks: int = 0
    routine: list[str] = field(default_factory=list)
    routine_index: int = -1
    visited_locations: set[str] = field(default_factory=set)

    def to_snapshot(self) -> AgentSnapshot:
        """Convert runtime agent state into a serializable AgentSnapshot."""
        return AgentSnapshot(
            id=self.id,
            name=self.name,
            role=self.role,
            sprite_index=self.sprite_index,
            x=self.x,
            y=self.y,
            target_location=self.target_location,
            current_action=self.current_action,
        )


def _create_initial_agents(
    world: WorldMap,
    personas: Sequence[AgentPersona] = SEEDED_PERSONAS,
) -> dict[str, AgentEntity]:
    """Seed the initial villager agents at their distinct home or shop anchors."""
    agents: dict[str, AgentEntity] = {}
    occupied: set[GridPos] = set()

    for persona in personas:
        if persona.id in agents:
            raise ValueError(f"Duplicate persona id: {persona.id!r}")
        anchor = world.get_location(persona.home_location).anchor
        spawn = anchor
        if spawn in occupied:
            fallback = world.find_free_adjacent(anchor[0], anchor[1], occupied, max_radius=5)
            if fallback is None:
                raise ValueError(
                    f"No free spawn tile near {persona.home_location!r} "
                    f"for agent {persona.id!r}"
                )
            spawn = fallback
        occupied.add(spawn)

        routine = list(persona.default_routine)
        agents[persona.id] = AgentEntity(
            id=persona.id,
            name=persona.name,
            role=persona.role,
            sprite_index=persona.sprite_index,
            home_location=persona.home_location,
            x=spawn[0],
            y=spawn[1],
            persona=persona,
            target_location=None,
            path=[],
            current_action=f"At {persona.home_location}",
            dwell_ticks_remaining=0,
            stall_ticks=0,
            routine=routine,
            routine_index=len(routine) - 1 if routine else -1,
            visited_locations=set(),
        )

    return agents


TickCallback = Callable[[TickPayload], Awaitable[None]]


class SimulationEngine:
    """Server-authoritative simulation orchestrating ticks, A* routing, and invariants."""

    def __init__(
        self,
        world: WorldMap,
        clock: SimClock | None = None,
        seed: int = 42,
        dwell_ticks: int = 4,
        *,
        personas: Sequence[AgentPersona] | None = None,
        memory_store: MemoryStore | None = None,
        retriever: MemoryRetriever | None = None,
        llm_gateway: LLMGateway | None = None,
    ) -> None:
        if isinstance(dwell_ticks, bool) or dwell_ticks < 0:
            raise ValueError(f"dwell_ticks must be >= 0, got {dwell_ticks!r}")
        self.world = world
        self.clock = clock if clock is not None else SimClock()
        self.seed = seed
        self.dwell_ticks = dwell_ticks
        resolved_personas = SEEDED_PERSONAS if personas is None else personas
        self.agents: dict[str, AgentEntity] = _create_initial_agents(world, resolved_personas)
        self.memory_store = memory_store
        self.retriever = retriever
        self.llm_gateway = llm_gateway
        self._step_lock = asyncio.Lock()
        self._tick_callbacks: list[TickCallback] = []
        self._loop_task: asyncio.Task[None] | None = None
        self._stop_requested = False

    async def initialize_persistence(self) -> None:
        """Upsert agents, seed initial persona memories idempotently, and ensure sim_state."""
        if self.memory_store is None:
            return

        seed_items: list[MemoryCreate] = []
        for agent in self.agents.values():
            await self.memory_store.upsert_agent(
                AgentRecord(
                    id=agent.id,
                    name=agent.name,
                    persona_json=agent.persona.to_persona_json(),
                    home_location=agent.home_location,
                    x=agent.x,
                    y=agent.y,
                    current_action=agent.current_action,
                    current_plan_json=json.dumps(agent.routine),
                )
            )
            existing = await self.memory_store.list_memories(agent.id, limit=1)
            if not existing:
                seed_items.append(
                    MemoryCreate(
                        agent_id=agent.id,
                        memory_type="observation",
                        text=agent.persona.summary_text(),
                        importance=6,
                        created_tick=self.clock.tick,
                    )
                )
                for goal in agent.persona.starting_goals:
                    seed_items.append(
                        MemoryCreate(
                            agent_id=agent.id,
                            memory_type="observation",
                            text=f"{agent.name}'s goal: {goal}",
                            importance=6,
                            created_tick=self.clock.tick,
                        )
                    )

        if seed_items:
            await self.memory_store.add_memories_batch(seed_items)

        await self.memory_store.get_or_create_sim_state(
            tick=self.clock.tick,
            sim_time=self.clock.sim_time_str,
            speed=self.clock.speed,
            seed=self.seed,
        )

    async def persist_tick_state(self) -> None:
        """Persist current agent positions, actions, plans, and simulation clock to SQLite."""
        if self.memory_store is None:
            return

        states = [
            (
                agent.id,
                agent.x,
                agent.y,
                agent.current_action,
                json.dumps(agent.routine),
            )
            for agent in self.agents.values()
        ]
        await self.memory_store.update_agent_states(states)
        await self.memory_store.save_sim_state(
            tick=self.clock.tick,
            sim_time=self.clock.sim_time_str,
            speed=self.clock.speed,
            seed=self.seed,
        )

    def register_tick_callback(self, callback: TickCallback) -> None:
        """Register an async callback invoked with each emitted TickPayload."""
        self._tick_callbacks.append(callback)

    def build_tick_payload(self) -> TickPayload:
        """Build a consistent TickPayload snapshot of current clock and agent states."""
        return TickPayload(
            tick=self.clock.tick,
            sim_time=self.clock.sim_time_str,
            day=self.clock.day,
            speed=self.clock.speed,
            running=self.clock.running,
            agents=[agent.to_snapshot() for agent in self.agents.values()],
        )

    def _advance_routine_target(self, agent: AgentEntity) -> None:
        """Select the next routine destination, skipping the agent's current anchor tile."""
        if not agent.routine:
            return
        for _ in range(len(agent.routine)):
            agent.routine_index = (agent.routine_index + 1) % len(agent.routine)
            candidate = agent.routine[agent.routine_index]
            if self.world.get_location(candidate).anchor != (agent.x, agent.y):
                agent.target_location = candidate
                return
        agent.target_location = agent.routine[agent.routine_index]

    def _compute_path_to_target(
        self,
        agent: AgentEntity,
        reserved_tiles: set[GridPos],
    ) -> list[GridPos] | None:
        """Compute an A* path to the agent's target anchor or nearest free adjacent tile."""
        if agent.target_location is None:
            return None
        goal = self.world.get_location(agent.target_location).anchor
        blocked = reserved_tiles - {(agent.x, agent.y)}
        effective_goal: GridPos | None = goal
        if goal in blocked:
            effective_goal = self.world.find_free_adjacent(
                goal[0],
                goal[1],
                reserved_tiles,
                max_radius=3,
            )
        if effective_goal is None:
            return None
        return find_path(
            (agent.x, agent.y),
            effective_goal,
            self.world.is_walkable,
            blocked_tiles=blocked,
        )

    def _mark_arrived(self, agent: AgentEntity) -> None:
        """Transition an agent into dwell state upon reaching its destination."""
        agent.dwell_ticks_remaining = self.dwell_ticks
        if agent.target_location is not None:
            agent.visited_locations.add(agent.target_location)
            agent.current_action = f"At {agent.target_location}"
        else:
            agent.current_action = f"At {agent.home_location}"
        agent.stall_ticks = 0

    def _move_agent_step(
        self,
        agent: AgentEntity,
        next_pos: GridPos,
        reserved_tiles: set[GridPos],
        *,
        reset_stall: bool,
    ) -> None:
        """Atomically move agent onto an unreserved walkable tile."""
        reserved_tiles.discard((agent.x, agent.y))
        agent.x, agent.y = next_pos
        reserved_tiles.add(next_pos)
        agent.path.pop(0)
        if reset_stall:
            agent.stall_ticks = 0
        if not agent.path:
            self._mark_arrived(agent)
        else:
            agent.current_action = f"Walking to {agent.target_location}"

    def _step_agent(self, agent: AgentEntity, reserved_tiles: set[GridPos]) -> None:
        """Advance a single agent by one tick while preserving spatial invariants."""
        if agent.dwell_ticks_remaining > 0:
            agent.dwell_ticks_remaining -= 1
            location_label = agent.target_location or agent.home_location
            agent.current_action = f"At {location_label}"
            return

        if agent.target_location is None or not agent.path:
            self._advance_routine_target(agent)
            computed = self._compute_path_to_target(agent, reserved_tiles)
            if computed is None:
                agent.path = []
                agent.stall_ticks += 1
                label = agent.target_location or agent.home_location
                agent.current_action = f"Waiting for {label}"
                return
            if not computed:
                agent.path = []
                self._mark_arrived(agent)
                return
            agent.path = computed

        next_pos = agent.path[0]
        if self.world.is_walkable(*next_pos) and next_pos not in reserved_tiles:
            self._move_agent_step(agent, next_pos, reserved_tiles, reset_stall=True)
            return

        # Next tile is occupied by another agent: attempt reroute or yield without overlap.
        agent.stall_ticks += 1
        if agent.stall_ticks > MAX_STALL_TICKS:
            agent.path = []
            agent.target_location = None
            agent.stall_ticks = 0
            agent.current_action = "Rerouting"
            return

        rerouted = self._compute_path_to_target(agent, reserved_tiles)
        if rerouted is None:
            label = agent.target_location or agent.home_location
            agent.current_action = f"Waiting for {label}"
            return
        if not rerouted:
            agent.path = []
            self._mark_arrived(agent)
            return

        agent.path = rerouted
        detour_next = agent.path[0]
        if self.world.is_walkable(*detour_next) and detour_next not in reserved_tiles:
            self._move_agent_step(agent, detour_next, reserved_tiles, reset_stall=False)
        else:
            label = agent.target_location or agent.home_location
            agent.current_action = f"Waiting for {label}"

    async def step_once(self) -> TickPayload:
        """Advance simulation state by one tick and notify registered async callbacks."""
        async with self._step_lock:
            reserved_tiles: set[GridPos] = {(a.x, a.y) for a in self.agents.values()}
            for agent_id in sorted(self.agents):
                self._step_agent(self.agents[agent_id], reserved_tiles)
            self.clock.advance()
            payload = self.build_tick_payload()
            if self.memory_store is not None:
                await self.persist_tick_state()

        for callback in list(self._tick_callbacks):
            try:
                await callback(payload)
            except Exception:
                logger.exception("Tick callback failed at tick %s", payload.tick)

        return payload

    async def start_loop(self) -> None:
        """Start the background async simulation loop if not already running."""
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stop_requested = False
        self._loop_task = asyncio.create_task(self._run_loop(), name="sim-engine-loop")

    async def stop_loop(self) -> None:
        """Stop the background simulation loop and await task cancellation."""
        self._stop_requested = True
        task = self._loop_task
        self._loop_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        """Run continuous non-blocking ticks according to clock running and speed state."""
        while not self._stop_requested:
            if self.clock.running:
                try:
                    await self.step_once()
                except Exception:
                    logger.exception("Unexpected error during simulation tick")
                await asyncio.sleep(self.clock.tick_interval_seconds)
            else:
                await asyncio.sleep(0.1)
