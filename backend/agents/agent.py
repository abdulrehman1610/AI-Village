"""Per-agent cognitive loop coordinator (Perceive -> Remember -> Decide)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

from agents.personas import AgentPersona
from agents.planner import AgentPlanState, DailyPlanner
from llm.gateway import LLMGateway
from memory.retrieval import MemoryRetriever
from memory.store import MemoryStore
from sim.clock import SimClock
from sim.world import WorldMap

_MIN_DWELL_TICKS = 8


@dataclass(frozen=True)
class PendingObservation:
    """Queued perception or world-event observation awaiting importance scoring."""

    agent_id: str
    text: str
    min_importance: int | None = None
    trigger_replan: bool = False
    reason: str = ""


@dataclass
class AgentBrain:
    """Cognitive state and decision coordinator decoupled from spatial tile movement."""

    agent_id: str
    persona: AgentPersona
    plan_state: AgentPlanState | None = None
    pending_observations: list[PendingObservation] = field(default_factory=list)
    accumulated_importance: int = 0
    peer_seen_tick: dict[str, int] = field(default_factory=dict)
    last_arrived_location: str | None = None
    peer_perception_cooldown: int = 25
    replan_cooldown: int = 10

    def queue_observation(
        self,
        text: str,
        *,
        min_importance: int | None = None,
        trigger_replan: bool = False,
        reason: str = "",
    ) -> None:
        """Enqueue a new observation (e.g., god-mode event or arrival notice)."""
        cleaned = text.strip()
        if not cleaned:
            return
        self.pending_observations.append(
            PendingObservation(
                agent_id=self.agent_id,
                text=cleaned,
                min_importance=min_importance,
                trigger_replan=trigger_replan,
                reason=reason.strip(),
            )
        )

    def perceive(
        self,
        *,
        tick: int,
        current_location: str | None,
        nearby_peers: Sequence[tuple[str, str, str]],
    ) -> list[PendingObservation]:
        """Drain queued observations and emit cooldown-deduplicated nearby peer sightings."""
        del current_location
        collected = list(self.pending_observations)
        self.pending_observations.clear()

        for peer_id, peer_name, peer_action in nearby_peers:
            if peer_id == self.agent_id:
                continue
            last_seen = self.peer_seen_tick.get(peer_id)
            if last_seen is not None and (tick - last_seen) < self.peer_perception_cooldown:
                continue
            self.peer_seen_tick[peer_id] = tick
            action_text = peer_action.strip() or "idle"
            collected.append(
                PendingObservation(
                    agent_id=self.agent_id,
                    text=f"Saw {peer_name} nearby ({action_text})",
                )
            )

        return collected

    def record_importance(
        self,
        scores: Sequence[int],
        *,
        tick: int,
        observations: Sequence[PendingObservation],
    ) -> tuple[bool, str]:
        """Accumulate importance scores and determine whether an interruption replan is needed."""
        self.accumulated_importance += sum(scores)

        for obs in observations:
            if obs.trigger_replan:
                return (True, obs.reason.strip() or obs.text)

        last_replan_tick = self.plan_state.last_replan_tick if self.plan_state is not None else -100
        if max(scores, default=0) >= 7 and (tick - last_replan_tick) >= self.replan_cooldown:
            if observations and len(observations) == len(scores):
                best_idx = max(range(len(scores)), key=lambda idx: scores[idx])
                chosen = observations[best_idx]
                return (True, chosen.reason.strip() or chosen.text)
            for obs in observations:
                candidate = obs.reason.strip() or obs.text
                if candidate:
                    return (True, candidate)
            return (True, "High-importance village observation")

        return (False, "")

    def mark_arrived(self, *, location: str, tick: int, dwell_ticks: int) -> None:
        """Mark the active MinuteStep arrived once and queue first-visit arrival notice."""
        if self.plan_state is not None:
            step = self.plan_state.current_step()
            if step is not None and not step.arrived:
                step.arrived = True
                capped_dwell = max(
                    1,
                    min(step.duration_minutes, max(dwell_ticks, _MIN_DWELL_TICKS)),
                )
                step.end_tick = tick + capped_dwell

        if location != self.last_arrived_location:
            self.last_arrived_location = location
            self.queue_observation(f"Arrived at {location}", min_importance=2)

    async def decide(
        self,
        *,
        clock: SimClock,
        world: WorldMap,
        planner: DailyPlanner,
        llm_gateway: LLMGateway,
        retriever: MemoryRetriever | None,
        memory_store: MemoryStore | None,
        needs_replan: bool,
        replan_reason: str,
        is_conversing: bool,
        dwell_ticks: int,
    ) -> tuple[str | None, str, bool]:
        """Resolve the agent's next target location and action without tight-loop LLM calls."""
        if is_conversing:
            return (None, "", False)

        replanned = False
        if self.plan_state is None or self.plan_state.day != clock.day:
            self.plan_state = await planner.generate_daily_plan(
                self.persona,
                clock=clock,
                world=world,
                llm_gateway=llm_gateway,
                retriever=retriever,
                memory_store=memory_store,
            )
        elif needs_replan:
            reason_text = replan_reason.strip() or "Unexpected village event"
            self.plan_state = await planner.replan_remaining_day(
                self.persona,
                self.plan_state,
                reason=reason_text,
                clock=clock,
                world=world,
                llm_gateway=llm_gateway,
                retriever=retriever,
                memory_store=memory_store,
            )
            replanned = True

        step = await planner.resolve_minute_step(
            self.persona,
            self.plan_state,
            clock=clock,
            world=world,
            llm_gateway=llm_gateway,
            retriever=retriever,
            dwell_ticks=dwell_ticks,
        )
        return (step.location, step.action, replanned)

    def serialized_plan_json(self, fallback_routine: Sequence[str]) -> str:
        """Return JSON representation of the structured daily plan or fallback routine."""
        if self.plan_state is not None:
            return self.plan_state.to_json()
        return json.dumps(list(fallback_routine))
