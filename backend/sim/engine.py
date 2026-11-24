"""Async simulation engine coordinating agent navigation, spatial invariants, and ticks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from agents.agent import AgentBrain, PendingObservation
from agents.conversation import ConversationManager
from agents.personas import SEEDED_PERSONAS, AgentPersona
from agents.planner import DailyPlanner
from agents.reflection import ReflectionManager
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
    mood: str = "calm"


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
    conversation_hold_ticks: int = 0
    needs_replan: bool = False
    replan_reason: str = ""
    active_plan_action: str = ""
    last_salient_tick: int = -1
    mood: str = "calm"

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
            mood=self.mood,
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
EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


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
        reflection_threshold: int = 150,
    ) -> None:
        if isinstance(dwell_ticks, bool) or dwell_ticks < 0:
            raise ValueError(f"dwell_ticks must be >= 0, got {dwell_ticks!r}")
        if isinstance(reflection_threshold, bool) or reflection_threshold < 1:
            raise ValueError(
                f"reflection_threshold must be >= 1, got {reflection_threshold!r}"
            )
        self.world = world
        self.clock = clock if clock is not None else SimClock()
        self.seed = seed
        self.dwell_ticks = dwell_ticks
        self.reflection_threshold = reflection_threshold
        resolved_personas = SEEDED_PERSONAS if personas is None else personas
        self.agents: dict[str, AgentEntity] = _create_initial_agents(world, resolved_personas)
        self.memory_store = memory_store
        self.retriever = retriever
        self.llm_gateway = llm_gateway
        self.planner = DailyPlanner()
        self.brains: dict[str, AgentBrain] = {
            agent_id: AgentBrain(
                agent_id=agent_id,
                persona=agent.persona,
                reflection_threshold=reflection_threshold,
            )
            for agent_id, agent in self.agents.items()
        }
        self.conversation_manager: ConversationManager | None = (
            ConversationManager(
                llm_gateway=llm_gateway,
                memory_store=memory_store,
                retriever=retriever,
            )
            if llm_gateway is not None and memory_store is not None
            else None
        )
        self.reflection_manager: ReflectionManager | None = (
            ReflectionManager(
                llm_gateway=llm_gateway,
                memory_store=memory_store,
                retriever=retriever,
                reflection_threshold=reflection_threshold,
            )
            if llm_gateway is not None and memory_store is not None
            else None
        )
        self._step_lock = asyncio.Lock()
        self._stepping = False
        self._pre_step_payload: TickPayload | None = None
        self._tick_callbacks: list[TickCallback] = []
        self._event_callbacks: list[EventCallback] = []
        self._loop_task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._wake_event = asyncio.Event()

    def get_serialized_plan_json(self, agent_id: str) -> str:
        """Return JSON representation of an agent's structured plan or fallback routine."""
        agent = self.agents[agent_id]
        return self.brains[agent_id].serialized_plan_json(agent.routine)

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
                    current_plan_json=self.get_serialized_plan_json(agent.id),
                    mood=agent.mood,
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

    async def _persist_clock_state(self) -> None:
        """Persist current simulation clock metadata when a MemoryStore is attached."""
        if self.memory_store is None:
            return
        await self.memory_store.save_sim_state(
            tick=self.clock.tick,
            sim_time=self.clock.sim_time_str,
            speed=self.clock.speed,
            seed=self.seed,
        )

    async def persist_tick_state(self) -> None:
        """Persist current agent positions, actions, plans, moods, and simulation clock."""
        if self.memory_store is None:
            return

        states = [
            (
                agent.id,
                agent.x,
                agent.y,
                agent.current_action,
                self.get_serialized_plan_json(agent.id),
            )
            for agent in self.agents.values()
        ]
        moods = {agent.id: agent.mood for agent in self.agents.values()}
        await self.memory_store.update_agent_states(states, moods=moods)
        await self._persist_clock_state()

    def register_tick_callback(self, callback: TickCallback) -> None:
        """Register an async callback invoked with each emitted TickPayload."""
        self._tick_callbacks.append(callback)

    def register_event_callback(self, callback: EventCallback) -> None:
        """Register an async callback invoked for dialogue and god-mode event payloads."""
        self._event_callbacks.append(callback)

    def _build_live_tick_payload(self) -> TickPayload:
        return TickPayload(
            tick=self.clock.tick,
            sim_time=self.clock.sim_time_str,
            day=self.clock.day,
            speed=self.clock.speed,
            running=self.clock.running,
            agents=[agent.to_snapshot() for agent in self.agents.values()],
        )

    def build_tick_payload(self) -> TickPayload:
        """Build a consistent TickPayload snapshot of current clock and agent states."""
        if self._stepping and self._pre_step_payload is not None:
            return self._pre_step_payload
        return self._build_live_tick_payload()

    def _current_control_tick_payload(self) -> TickPayload:
        """Build a tick payload overlaying live clock playback state even mid-step."""
        payload = self.build_tick_payload()
        if self._stepping:
            return payload.model_copy(
                update={
                    "speed": self.clock.speed,
                    "running": self.clock.running,
                }
            )
        return payload

    async def _broadcast_tick_payload(self, payload: TickPayload) -> None:
        """Dispatch a TickPayload to all registered tick callbacks safely."""
        for callback in list(self._tick_callbacks):
            try:
                await callback(payload)
            except Exception:
                logger.exception("Tick callback failed at tick %s", payload.tick)

    async def broadcast_current_tick(self) -> TickPayload:
        """Build and broadcast the current control-aware TickPayload."""
        payload = self._current_control_tick_payload()
        await self._broadcast_tick_payload(payload)
        return payload

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
        location_label = agent.target_location or agent.home_location
        if agent.target_location is not None:
            agent.visited_locations.add(agent.target_location)
        if self.llm_gateway is not None:
            self.brains[agent.id].mark_arrived(
                location=location_label,
                tick=self.clock.tick,
                dwell_ticks=self.dwell_ticks,
            )
        agent.current_action = agent.active_plan_action or f"At {location_label}"
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
            agent.current_action = agent.active_plan_action or f"At {location_label}"
            return

        if agent.target_location is None or not agent.path:
            if self.llm_gateway is None:
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
            if self.llm_gateway is None:
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

    async def _perceive_and_remember(self, gateway: LLMGateway) -> None:
        """Gather nearby peer/queued observations across agents and score/store in one batch."""
        ordered_ids = sorted(self.agents)
        per_agent_obs: dict[str, list[PendingObservation]] = {}
        flat_obs: list[PendingObservation] = []

        for agent_id in ordered_ids:
            agent = self.agents[agent_id]
            nearby_peers: list[tuple[str, str, str]] = []
            for peer_id in ordered_ids:
                if peer_id == agent_id:
                    continue
                peer = self.agents[peer_id]
                if abs(agent.x - peer.x) + abs(agent.y - peer.y) <= 4:
                    nearby_peers.append((peer.id, peer.name, peer.current_action))
            obs_list = self.brains[agent_id].perceive(
                tick=self.clock.tick,
                current_location=agent.target_location or agent.home_location,
                nearby_peers=nearby_peers,
            )
            if obs_list:
                per_agent_obs[agent_id] = obs_list
                flat_obs.extend(obs_list)

        if not flat_obs:
            return

        raw_scores = await gateway.rate_importance_batch(
            [obs.text for obs in flat_obs],
            tick=self.clock.tick,
            agent_id=None,
        )
        final_scores: list[int] = []
        for obs, raw_score in zip(flat_obs, raw_scores, strict=True):
            effective = (
                max(obs.min_importance, raw_score)
                if obs.min_importance is not None
                else raw_score
            )
            final_scores.append(max(1, min(10, effective)))

        if self.memory_store is not None:
            await self.memory_store.add_memories_batch(
                [
                    MemoryCreate(
                        agent_id=obs.agent_id,
                        memory_type="observation",
                        text=obs.text,
                        importance=score,
                        created_tick=self.clock.tick,
                    )
                    for obs, score in zip(flat_obs, final_scores, strict=True)
                ]
            )

        offset = 0
        for agent_id in ordered_ids:
            agent_obs = per_agent_obs.get(agent_id)
            if not agent_obs:
                continue
            count = len(agent_obs)
            agent_scores = final_scores[offset : offset + count]
            offset += count

            agent = self.agents[agent_id]
            if max(agent_scores, default=0) >= 7:
                agent.last_salient_tick = self.clock.tick

            should_replan, reason = self.brains[agent_id].record_importance(
                agent_scores,
                tick=self.clock.tick,
                observations=agent_obs,
            )
            if should_replan:
                if not agent.needs_replan or not agent.replan_reason:
                    agent.replan_reason = reason
                agent.needs_replan = True

    async def _run_conversations(self) -> list[dict[str, Any]]:
        """Run proximity conversations concurrently for disjoint free agent pairs."""
        if self.conversation_manager is None:
            return []

        ordered_agents = [self.agents[agent_id] for agent_id in sorted(self.agents)]
        pairs = self.conversation_manager.select_candidate_pairs(
            ordered_agents,
            tick=self.clock.tick,
        )
        if not pairs:
            return []

        ordered_pairs: list[tuple[AgentEntity, AgentEntity]] = []
        for first, second in pairs:
            first_entity = self.agents[first.id]
            second_entity = self.agents[second.id]
            if (second_entity.needs_replan, second_entity.last_salient_tick) > (
                first_entity.needs_replan,
                first_entity.last_salient_tick,
            ):
                ordered_pairs.append((second_entity, first_entity))
            else:
                ordered_pairs.append((first_entity, second_entity))

        outcomes = await asyncio.gather(
            *(
                self.conversation_manager.run_conversation(
                    speaker,
                    listener,
                    tick=self.clock.tick,
                    sim_time=self.clock.sim_time_str,
                    world=self.world,
                )
                for speaker, listener in ordered_pairs
            )
        )

        payloads: list[dict[str, Any]] = []
        for outcome in outcomes:
            if outcome is not None:
                for participant_id, mood in zip(
                    outcome.participants,
                    outcome.moods,
                    strict=True,
                ):
                    if participant_id in self.agents:
                        self.agents[participant_id].mood = mood
                    if participant_id in self.brains:
                        self.brains[participant_id].mood = mood
                        self.brains[participant_id].add_importance(outcome.importance)
                if outcome.importance >= 7:
                    for participant_id in outcome.participants:
                        if participant_id in self.agents:
                            self.agents[participant_id].last_salient_tick = self.clock.tick
                payloads.append(outcome.ws_payload)
        return payloads

    async def _decide_actions(self, gateway: LLMGateway) -> None:
        """Resolve hierarchical plans and next target locations for non-conversing agents."""
        deciding_agents = [
            self.agents[agent_id]
            for agent_id in sorted(self.agents)
            if self.agents[agent_id].conversation_hold_ticks == 0
        ]
        if not deciding_agents:
            return

        seen_replan_reasons = {
            agent.id: agent.replan_reason for agent in deciding_agents
        }
        decisions = await asyncio.gather(
            *(
                self.brains[agent.id].decide(
                    clock=self.clock,
                    world=self.world,
                    planner=self.planner,
                    llm_gateway=gateway,
                    retriever=self.retriever,
                    memory_store=self.memory_store,
                    needs_replan=agent.needs_replan,
                    replan_reason=agent.replan_reason,
                    is_conversing=False,
                    dwell_ticks=self.dwell_ticks,
                )
                for agent in deciding_agents
            )
        )

        for agent, (target_location, action_text, _replanned) in zip(
            deciding_agents,
            decisions,
            strict=True,
        ):
            # Preserve any concurrent inject_event replan triggered while decide() was awaiting.
            if agent.replan_reason == seen_replan_reasons[agent.id]:
                agent.needs_replan = False
                agent.replan_reason = ""

            if target_location is not None:
                if target_location != agent.target_location:
                    agent.target_location = target_location
                    agent.path = []
                    agent.dwell_ticks_remaining = 0
                if action_text:
                    agent.active_plan_action = action_text

            plan_state = self.brains[agent.id].plan_state
            if plan_state is not None and plan_state.daily_items:
                unique_locations = list(
                    dict.fromkeys(block.location for block in plan_state.daily_items)
                )
                if unique_locations:
                    agent.routine = unique_locations

    async def _run_reflections(self) -> list[dict[str, Any]]:
        """Run threshold-triggered reflections concurrently for qualifying agents."""
        if self.reflection_manager is None:
            return []

        qualifying_ids = [
            agent_id
            for agent_id in sorted(self.agents)
            if self.brains[agent_id].should_reflect()
        ]
        if not qualifying_ids:
            return []

        outcomes = await asyncio.gather(
            *(
                self.reflection_manager.run_reflection(
                    agent_id=agent_id,
                    persona=self.agents[agent_id].persona,
                    tick=self.clock.tick,
                    sim_time=self.clock.sim_time_str,
                )
                for agent_id in qualifying_ids
            )
        )

        payloads: list[dict[str, Any]] = []
        for agent_id, outcome in zip(qualifying_ids, outcomes, strict=True):
            if outcome is not None:
                self.brains[agent_id].reset_reflection_counter(tick=self.clock.tick)
                self.brains[agent_id].mood = outcome.mood
                self.agents[agent_id].mood = outcome.mood
                payloads.extend(outcome.ws_payloads)
        return payloads

    async def _run_cognitive_phase(self, gateway: LLMGateway) -> list[dict[str, Any]]:
        """Execute Perceive -> Remember -> Converse -> Decide -> Reflect before movement."""
        for agent in self.agents.values():
            agent.conversation_hold_ticks = max(0, agent.conversation_hold_ticks - 1)

        await self._perceive_and_remember(gateway)
        dialogue_payloads = await self._run_conversations()
        await self._decide_actions(gateway)
        reflection_payloads = await self._run_reflections()
        return dialogue_payloads + reflection_payloads

    async def _emit_event_payload(self, event_payload: dict[str, Any]) -> None:
        """Dispatch a dialogue or god-mode event payload to registered callbacks."""
        for callback in list(self._event_callbacks):
            try:
                await callback(event_payload)
            except Exception:
                logger.exception(
                    "Event callback failed for type %r at tick %s",
                    event_payload.get("type"),
                    event_payload.get("tick"),
                )

    def _resolve_location_case_insensitive(self, raw_location: str) -> str:
        lowered = raw_location.lower()
        for loc_name in self.world.locations:
            if loc_name.lower() == lowered:
                return loc_name
        raise KeyError(f"Unknown location: {raw_location!r}")

    async def inject_event(
        self,
        text: str,
        location: str | None = None,
        *,
        radius: int = 10,
    ) -> dict[str, Any]:
        """Inject a god-mode event globally or near a location without blocking on _step_lock."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Event text must not be empty.")
        if radius < 0:
            raise ValueError(f"radius must be >= 0, got {radius!r}")

        clean_loc = location.strip() if location is not None else ""
        resolved_location = (
            self._resolve_location_case_insensitive(clean_loc) if clean_loc else None
        )

        current_tick = self.clock.tick
        current_sim_time = self.clock.sim_time_str

        if resolved_location is None:
            affected_agents = sorted(self.agents)
        else:
            loc = self.world.get_location(resolved_location)
            tile_size = self.world.tile_size
            min_tx = loc.x // tile_size
            max_tx = (loc.x + loc.width) // tile_size
            min_ty = loc.y // tile_size
            max_ty = (loc.y + loc.height) // tile_size
            affected_agents = []
            for agent_id in sorted(self.agents):
                agent = self.agents[agent_id]
                near_anchor = (
                    abs(agent.x - loc.anchor_x) + abs(agent.y - loc.anchor_y) <= radius
                )
                in_bounds = min_tx <= agent.x <= max_tx and min_ty <= agent.y <= max_ty
                if near_anchor or in_bounds or agent.target_location == resolved_location:
                    affected_agents.append(agent_id)

        obs_text = (
            f"[EVENT]{' at ' + resolved_location if resolved_location else ''}: {clean_text}"
        )

        event_id: int | None = None
        if self.memory_store is not None:
            event_record = await self.memory_store.log_event(
                tick=current_tick,
                kind="god_event",
                text=clean_text,
                location=resolved_location,
                source="god",
            )
            event_id = event_record.id
            if affected_agents:
                await self.memory_store.add_memories_batch(
                    [
                        MemoryCreate(
                            agent_id=agent_id,
                            memory_type="observation",
                            text=obs_text,
                            importance=8,
                            created_tick=current_tick,
                        )
                        for agent_id in affected_agents
                    ]
                )

        for agent_id in affected_agents:
            agent = self.agents[agent_id]
            agent.needs_replan = True
            agent.replan_reason = obs_text
            agent.last_salient_tick = current_tick
            self.brains[agent_id].add_importance(8)

        event_payload: dict[str, Any] = {
            "type": "event",
            "id": event_id,
            "tick": current_tick,
            "sim_time": current_sim_time,
            "text": clean_text,
            "location": resolved_location,
            "affected_agents": affected_agents,
        }
        await self._emit_event_payload(event_payload)
        return event_payload

    async def step_once(self) -> TickPayload:
        """Advance simulation state by one tick and notify registered async callbacks."""
        pending_event_payloads: list[dict[str, Any]] = []
        async with self._step_lock:
            self._pre_step_payload = self._build_live_tick_payload()
            self._stepping = True
            try:
                if self.llm_gateway is not None:
                    pending_event_payloads = await self._run_cognitive_phase(
                        self.llm_gateway
                    )

                reserved_tiles: set[GridPos] = {(a.x, a.y) for a in self.agents.values()}
                for agent_id in sorted(self.agents):
                    agent = self.agents[agent_id]
                    if agent.conversation_hold_ticks > 0:
                        continue
                    self._step_agent(agent, reserved_tiles)

                self.clock.advance()
                payload = self._build_live_tick_payload()
                if self.memory_store is not None:
                    await self.persist_tick_state()
            finally:
                self._stepping = False
                self._pre_step_payload = None

        await self._broadcast_tick_payload(payload)

        for event_payload in pending_event_payloads:
            await self._emit_event_payload(event_payload)

        return payload

    async def _finalize_control_change(self) -> TickPayload:
        """Wake the background loop, persist clock state, and broadcast live snapshot."""
        self._wake_event.set()
        await self._persist_clock_state()
        return await self.broadcast_current_tick()

    async def start_simulation(self) -> TickPayload:
        """Start or resume the simulation loop, wake it immediately, and broadcast state."""
        self.clock.start()
        await self.start_loop()
        return await self._finalize_control_change()

    async def pause_simulation(self) -> TickPayload:
        """Pause the simulation loop immediately and broadcast live playback state."""
        self.clock.pause()
        return await self._finalize_control_change()

    async def set_simulation_speed(self, speed: int) -> TickPayload:
        """Update playback speed (1, 4, or 16), wake the loop, and broadcast state."""
        self.clock.set_speed(speed)
        return await self._finalize_control_change()

    async def start_loop(self) -> None:
        """Start the background async simulation loop if not already running."""
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stop_requested = False
        self._loop_task = asyncio.create_task(self._run_loop(), name="sim-engine-loop")

    async def stop_loop(self) -> None:
        """Stop the background simulation loop and await task cancellation."""
        self._stop_requested = True
        self._wake_event.set()
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
            self._wake_event.clear()
            if self.clock.running:
                try:
                    await self.step_once()
                except Exception:
                    logger.exception("Unexpected error during simulation tick")
                timeout = self.clock.tick_interval_seconds
            else:
                timeout = 0.25

            if not self._wake_event.is_set() and not self._stop_requested:
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=timeout)
                except TimeoutError:
                    pass
