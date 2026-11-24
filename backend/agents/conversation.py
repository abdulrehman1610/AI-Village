"""Proximity-gated multi-turn conversation manager with memory and relationship persistence."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from agents.personas import AgentPersona
from llm.gateway import LLMGateway
from llm.prompts.conversation import (
    build_conversation_decision_prompt,
    build_conversation_summary_prompt,
    build_dialogue_turn_prompt,
)
from memory.retrieval import MemoryRetriever
from memory.store import MemoryCreate, MemoryStore
from sim.world import WorldMap

PROXIMITY_TILES = 2
MAX_DIALOGUE_TURNS = 6
CONVERSATION_COOLDOWN_TICKS = 60
DECLINE_COOLDOWN_TICKS = 30

_LOCATION_RADIUS_TILES = 4
_RETRIEVAL_TOP_K = 8
_REPLAN_IMPORTANCE_THRESHOLD = 7
_MIN_HOLD_TICKS = 2
_MAX_HOLD_TICKS = 4


@runtime_checkable
class DialogueParticipant(Protocol):
    """Structural participant contract decoupled from SimulationEngine's AgentEntity."""

    id: str
    name: str
    persona: AgentPersona
    x: int
    y: int
    target_location: str | None
    current_action: str
    conversation_hold_ticks: int
    needs_replan: bool
    replan_reason: str


@dataclass(frozen=True)
class DialogueOutcome:
    """Persisted outcome and WebSocket payload for a completed conversation."""

    participants: tuple[str, str]
    participant_names: tuple[str, str]
    location: str | None
    turns: list[dict[str, str]]
    summary: str
    importance: int
    affinity_delta: float
    ws_payload: dict[str, Any]


def _pair_key(id_a: str, id_b: str) -> tuple[str, str]:
    return (id_a, id_b) if id_a <= id_b else (id_b, id_a)


def _manhattan_distance(agent_a: DialogueParticipant, agent_b: DialogueParticipant) -> int:
    return abs(agent_a.x - agent_b.x) + abs(agent_a.y - agent_b.y)


def _resolve_location_label(agent_a: DialogueParticipant, world: WorldMap) -> str:
    best_name: str | None = None
    best_dist: int | None = None
    for loc in sorted(world.list_locations(), key=lambda item: item.name):
        dist = abs(agent_a.x - loc.anchor_x) + abs(agent_a.y - loc.anchor_y)
        if dist <= _LOCATION_RADIUS_TILES and (best_dist is None or dist < best_dist):
            best_dist = dist
            best_name = loc.name
    if best_name is not None:
        return best_name
    return agent_a.target_location or "Village"


class ConversationManager:
    """Coordinates proximity eligibility, dual cooldowns, dialogue turns, and persistence."""

    def __init__(
        self,
        *,
        llm_gateway: LLMGateway,
        memory_store: MemoryStore,
        retriever: MemoryRetriever | None = None,
        proximity_tiles: int = PROXIMITY_TILES,
        max_turns: int = MAX_DIALOGUE_TURNS,
        conversation_cooldown_ticks: int = CONVERSATION_COOLDOWN_TICKS,
        decline_cooldown_ticks: int = DECLINE_COOLDOWN_TICKS,
    ) -> None:
        if proximity_tiles < 0:
            raise ValueError(f"proximity_tiles must be >= 0, got {proximity_tiles}")
        if max_turns < 1:
            raise ValueError(f"max_turns must be >= 1, got {max_turns}")
        if conversation_cooldown_ticks < 0 or decline_cooldown_ticks < 0:
            raise ValueError("Cooldown durations must be non-negative.")

        self.llm_gateway = llm_gateway
        self.memory_store = memory_store
        self.retriever = retriever
        self.proximity_tiles = proximity_tiles
        self.max_turns = min(max_turns, MAX_DIALOGUE_TURNS)
        self.conversation_cooldown_ticks = conversation_cooldown_ticks
        self.decline_cooldown_ticks = decline_cooldown_ticks
        self.pair_cooldown_until: dict[tuple[str, str], int] = {}

    def can_converse(
        self,
        agent_a: DialogueParticipant,
        agent_b: DialogueParticipant,
        *,
        tick: int,
    ) -> bool:
        """Return True when two distinct free agents are nearby and off pair cooldown."""
        if agent_a.id == agent_b.id:
            return False
        if agent_a.conversation_hold_ticks != 0 or agent_b.conversation_hold_ticks != 0:
            return False
        if _manhattan_distance(agent_a, agent_b) > self.proximity_tiles:
            return False
        cooldown_until = self.pair_cooldown_until.get(_pair_key(agent_a.id, agent_b.id), 0)
        return tick >= cooldown_until

    def select_candidate_pairs(
        self,
        agents: Sequence[DialogueParticipant],
        *,
        tick: int,
    ) -> list[tuple[DialogueParticipant, DialogueParticipant]]:
        """Greedily match disjoint free agents to their closest eligible neighbors."""
        ordered = sorted(agents, key=lambda agent: agent.id)
        matched_ids: set[str] = set()
        pairs: list[tuple[DialogueParticipant, DialogueParticipant]] = []

        for idx, agent_a in enumerate(ordered):
            if agent_a.id in matched_ids or agent_a.conversation_hold_ticks != 0:
                continue

            best_dist: int | None = None
            best_peer: DialogueParticipant | None = None
            for agent_b in ordered[idx + 1 :]:
                if agent_b.id in matched_ids:
                    continue
                if not self.can_converse(agent_a, agent_b, tick=tick):
                    continue
                dist = _manhattan_distance(agent_a, agent_b)
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_peer = agent_b

            if best_peer is not None:
                matched_ids.add(agent_a.id)
                matched_ids.add(best_peer.id)
                pairs.append((agent_a, best_peer))

        return pairs

    async def _retrieve_memories(
        self,
        agent: DialogueParticipant,
        peer: DialogueParticipant,
        *,
        location_label: str,
        tick: int,
    ) -> list[str]:
        if self.retriever is None:
            return []
        query = f"{peer.name} {peer.persona.role} at {location_label}: {agent.current_action}"
        scored = await self.retriever.retrieve(
            agent.id,
            query,
            tick,
            top_k=_RETRIEVAL_TOP_K,
        )
        return [item.memory.text for item in scored]

    async def run_conversation(
        self,
        agent_a: DialogueParticipant,
        agent_b: DialogueParticipant,
        *,
        tick: int,
        sim_time: str,
        world: WorldMap,
    ) -> DialogueOutcome | None:
        """Evaluate initiation, execute <=6 dialogue turns, persist state, and build WS payload."""
        if agent_a.id == agent_b.id:
            raise ValueError("Conversation participants must have distinct agent IDs.")

        pair = _pair_key(agent_a.id, agent_b.id)
        location_label = _resolve_location_label(agent_a, world)

        memories_a = await self._retrieve_memories(
            agent_a,
            agent_b,
            location_label=location_label,
            tick=tick,
        )
        memories_b = await self._retrieve_memories(
            agent_b,
            agent_a,
            location_label=location_label,
            tick=tick,
        )

        decision_prompt = build_conversation_decision_prompt(
            speaker=agent_a.persona,
            listener=agent_b.persona,
            location=location_label,
            sim_time=sim_time,
            speaker_action=agent_a.current_action,
            listener_action=agent_b.current_action,
            memories=memories_a,
        )
        decision = await self.llm_gateway.decide_conversation(
            decision_prompt,
            tick=tick,
            agent_id=agent_a.id,
        )
        if not decision.initiate:
            self.pair_cooldown_until[pair] = tick + self.decline_cooldown_ticks
            return None

        turns: list[dict[str, str]] = []
        transcript: list[tuple[str, str]] = []

        for turn_index in range(self.max_turns):
            if turn_index % 2 == 0:
                speaker, listener, speaker_memories = agent_a, agent_b, memories_a
            else:
                speaker, listener, speaker_memories = agent_b, agent_a, memories_b

            opening = decision.opening_line.strip() if turn_index == 0 else ""
            if opening:
                utterance = opening
                continue_dialogue = True
            else:
                turn_prompt = build_dialogue_turn_prompt(
                    speaker=speaker.persona,
                    listener=listener.persona,
                    location=location_label,
                    sim_time=sim_time,
                    turn_index=turn_index + 1,
                    max_turns=self.max_turns,
                    memories=speaker_memories,
                    transcript=transcript,
                )
                turn_resp = await self.llm_gateway.generate_dialogue_turn(
                    turn_prompt,
                    tick=tick,
                    agent_id=speaker.id,
                )
                utterance = turn_resp.utterance.strip()
                continue_dialogue = turn_resp.continue_dialogue

            turns.append(
                {
                    "speaker_id": speaker.id,
                    "speaker_name": speaker.name,
                    "text": utterance,
                }
            )
            transcript.append((speaker.name, utterance))

            if not continue_dialogue and len(turns) >= 2:
                break

        summary_prompt = build_conversation_summary_prompt(
            speaker_a=agent_a.persona,
            speaker_b=agent_b.persona,
            location=location_label,
            sim_time=sim_time,
            transcript=transcript,
        )
        summary_resp = await self.llm_gateway.summarize_conversation(
            summary_prompt,
            tick=tick,
            agent_id=agent_a.id,
        )
        ratings = await self.llm_gateway.rate_importance_batch(
            [summary_resp.summary],
            tick=tick,
            agent_id=agent_a.id,
        )
        importance = ratings[0]

        await self.memory_store.add_conversation(
            tick_start=tick,
            participants=[agent_a.id, agent_b.id],
            turns=turns,
            summary=summary_resp.summary,
        )
        await self.memory_store.add_memories_batch(
            [
                MemoryCreate(
                    agent_id=agent_a.id,
                    memory_type="conversation",
                    text=f"Conversation with {agent_b.name}: {summary_resp.summary}",
                    importance=importance,
                    created_tick=tick,
                    metadata_json=json.dumps(
                        {"peer_id": agent_b.id, "location": location_label}
                    ),
                ),
                MemoryCreate(
                    agent_id=agent_b.id,
                    memory_type="conversation",
                    text=f"Conversation with {agent_a.name}: {summary_resp.summary}",
                    importance=importance,
                    created_tick=tick,
                    metadata_json=json.dumps(
                        {"peer_id": agent_a.id, "location": location_label}
                    ),
                ),
            ]
        )

        id_1, id_2 = pair
        existing_rel = await self.memory_store.get_relationship(id_1, id_2)
        target_a, target_b = (
            (existing_rel.agent_a, existing_rel.agent_b)
            if existing_rel is not None
            else (id_1, id_2)
        )
        base_affinity = existing_rel.affinity if existing_rel is not None else 0.0
        clamped_affinity = max(
            -1.0,
            min(1.0, round(base_affinity + summary_resp.affinity_delta, 6)),
        )
        relationship_notes = (
            summary_resp.relationship_note.strip()
            or (existing_rel.notes if existing_rel is not None else "")
            or summary_resp.summary
        )
        await self.memory_store.upsert_relationship(
            target_a,
            target_b,
            affinity=clamped_affinity,
            notes=relationship_notes,
            last_interaction_tick=tick,
        )

        self.pair_cooldown_until[pair] = tick + self.conversation_cooldown_ticks
        hold_ticks = min(max(_MIN_HOLD_TICKS, len(turns)), _MAX_HOLD_TICKS)
        agent_a.conversation_hold_ticks = hold_ticks
        agent_b.conversation_hold_ticks = hold_ticks
        agent_a.current_action = f"Talking with {agent_b.name}"
        agent_b.current_action = f"Talking with {agent_a.name}"

        if importance >= _REPLAN_IMPORTANCE_THRESHOLD:
            agent_a.needs_replan = True
            agent_a.replan_reason = summary_resp.summary
            agent_b.needs_replan = True
            agent_b.replan_reason = summary_resp.summary

        ws_payload: dict[str, Any] = {
            "type": "dialogue",
            "tick": tick,
            "sim_time": sim_time,
            "participants": [agent_a.id, agent_b.id],
            "participant_names": [agent_a.name, agent_b.name],
            "location": location_label,
            "turns": turns,
            "summary": summary_resp.summary,
        }
        return DialogueOutcome(
            participants=(agent_a.id, agent_b.id),
            participant_names=(agent_a.name, agent_b.name),
            location=location_label,
            turns=turns,
            summary=summary_resp.summary,
            importance=importance,
            affinity_delta=summary_resp.affinity_delta,
            ws_payload=ws_payload,
        )
