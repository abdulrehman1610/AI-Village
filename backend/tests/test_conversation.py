"""Offline unit tests for ConversationManager and 2-hop rumor propagation."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from agents.conversation import (
    CONVERSATION_COOLDOWN_TICKS,
    DECLINE_COOLDOWN_TICKS,
    MAX_DIALOGUE_TURNS,
    ConversationManager,
    DialogueParticipant,
)
from agents.personas import AgentPersona, get_persona
from app.db import Database
from llm.gateway import LLMGateway
from llm.providers.base import ProviderResult
from llm.providers.mock import MockProvider
from llm.schemas import (
    ConversationDecisionResponse,
    ConversationSummaryResponse,
    DialogueTurnResponse,
    ImportanceBatchResponse,
)
from memory.embeddings import EmbeddingService
from memory.models import AgentRecord
from memory.retrieval import MemoryRetriever
from memory.store import MemoryStore
from sim.world import NamedLocation, WorldMap


@dataclass
class _FakeParticipant:
    """Lightweight test double satisfying the DialogueParticipant protocol."""

    id: str
    name: str
    persona: AgentPersona
    x: int
    y: int
    target_location: str | None = None
    current_action: str = "Idle"
    conversation_hold_ticks: int = 0
    needs_replan: bool = False
    replan_reason: str = ""
    mood: str = "calm"


class _ScriptedProvider:
    """Offline fake LLMProvider returning scripted structured payloads."""

    def __init__(self, responses: list[BaseModel]) -> None:
        self._responses = list(responses)
        self.prompts_seen: list[tuple[type[BaseModel], str]] = []

    @property
    def name(self) -> str:
        return "scripted-mock"

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
        del system_instruction, model_override, temperature, seed
        self.prompts_seen.append((response_model, prompt))
        if not self._responses:
            raise AssertionError("ScriptedProvider ran out of responses")
        item = self._responses.pop(0)
        assert isinstance(item, response_model)
        return ProviderResult(
            raw_text=item.model_dump_json(),
            model="mock-scripted",
            tokens_in=10,
            tokens_out=10,
        )


def _make_world() -> WorldMap:
    width, height = 24, 24
    collision_grid = [[False for _ in range(width)] for _ in range(height)]
    locations = {
        "Bakery": NamedLocation(
            name="Bakery",
            category="shop",
            anchor_x=4,
            anchor_y=4,
            x=3 * 32,
            y=3 * 32,
            width=3 * 32,
            height=3 * 32,
        ),
        "Cafe": NamedLocation(
            name="Cafe",
            category="social",
            anchor_x=12,
            anchor_y=12,
            x=11 * 32,
            y=11 * 32,
            width=3 * 32,
            height=3 * 32,
        ),
        "Market": NamedLocation(
            name="Market",
            category="shop",
            anchor_x=4,
            anchor_y=18,
            x=3 * 32,
            y=17 * 32,
            width=3 * 32,
            height=3 * 32,
        ),
    }
    return WorldMap(
        width=width,
        height=height,
        tile_size=32,
        collision_grid=collision_grid,
        locations=locations,
    )


async def _setup_context(
    *,
    provider: object | None = None,
) -> tuple[
    Database,
    MemoryStore,
    MemoryRetriever,
    LLMGateway,
    WorldMap,
    dict[str, _FakeParticipant],
]:
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.init_models()
    embeddings = EmbeddingService.from_mode("mock")
    store = MemoryStore(db, embeddings)
    retriever = MemoryRetriever(store, embeddings)
    active_provider = MockProvider(seed=42) if provider is None else provider
    gateway = LLMGateway(provider=active_provider, db=db)  # type: ignore[arg-type]
    world = _make_world()

    participants: dict[str, _FakeParticipant] = {}
    coords = {
        "maya": (4, 4, "Baking loaves"),
        "liam": (5, 4, "Delivering coffee"),
        "elena": (12, 12, "Sketching herbs"),
    }
    for agent_id, (x, y, action) in coords.items():
        persona = get_persona(agent_id)
        await store.upsert_agent(
            AgentRecord(
                id=persona.id,
                name=persona.name,
                persona_json=persona.to_persona_json(),
                home_location=persona.home_location,
                x=x,
                y=y,
                current_action=action,
            )
        )
        participants[agent_id] = _FakeParticipant(
            id=persona.id,
            name=persona.name,
            persona=persona,
            x=x,
            y=y,
            target_location="Bakery",
            current_action=action,
        )

    return db, store, retriever, gateway, world, participants


async def test_proximity_hold_and_disjoint_pair_selection() -> None:
    db, store, retriever, gateway, _world, agents = await _setup_context()
    try:
        manager = ConversationManager(
            llm_gateway=gateway,
            memory_store=store,
            retriever=retriever,
        )
        maya = agents["maya"]
        liam = agents["liam"]
        elena = agents["elena"]
        assert isinstance(maya, DialogueParticipant)

        # Distance 3 -> ineligible.
        maya.x, maya.y = 4, 4
        liam.x, liam.y = 7, 4
        assert manager.can_converse(maya, liam, tick=10) is False
        assert manager.select_candidate_pairs([maya, liam], tick=10) == []

        # Distance 2 -> eligible (ordered lexicographically by id: liam, maya).
        liam.x, liam.y = 5, 5
        assert manager.can_converse(maya, liam, tick=10) is True
        assert manager.select_candidate_pairs([maya, liam], tick=10) == [(liam, maya)]

        # Busy agent (conversation_hold_ticks > 0) -> excluded.
        maya.conversation_hold_ticks = 2
        assert manager.can_converse(maya, liam, tick=10) is False
        assert manager.select_candidate_pairs([maya, liam], tick=10) == []
        maya.conversation_hold_ticks = 0

        # 3 adjacent agents -> disjoint pairs (at most 1 pair) choosing closest neighbor.
        elena.x, elena.y = 4, 4
        maya.x, maya.y = 5, 4  # dist 1 from elena
        liam.x, liam.y = 6, 4  # dist 2 from elena
        pairs = manager.select_candidate_pairs([maya, liam, elena], tick=10)
        assert len(pairs) == 1
        assert pairs[0] == (elena, maya)
    finally:
        await db.dispose()


async def test_decline_cooldown_gates_retries() -> None:
    scripted = _ScriptedProvider(
        [
            ConversationDecisionResponse(
                initiate=False,
                reason="Focused on morning baking.",
                opening_line="",
            )
        ]
    )
    db, store, retriever, gateway, world, agents = await _setup_context(provider=scripted)
    try:
        manager = ConversationManager(
            llm_gateway=gateway,
            memory_store=store,
            retriever=retriever,
        )
        maya = agents["maya"]
        liam = agents["liam"]

        outcome = await manager.run_conversation(
            maya,
            liam,
            tick=10,
            sim_time="Day 1 06:10",
            world=world,
        )
        assert outcome is None
        assert await store.list_conversations() == []
        assert maya.conversation_hold_ticks == 0
        assert liam.conversation_hold_ticks == 0

        assert manager.select_candidate_pairs([maya, liam], tick=11) == []
        blocked_tick = 10 + DECLINE_COOLDOWN_TICKS - 1
        assert manager.select_candidate_pairs([maya, liam], tick=blocked_tick) == []
        allowed_tick = 10 + DECLINE_COOLDOWN_TICKS
        assert manager.select_candidate_pairs([maya, liam], tick=allowed_tick) == [
            (liam, maya)
        ]
    finally:
        await db.dispose()


async def test_turn_cap_empty_opening_fallback_and_affinity_clamping() -> None:
    scripted = _ScriptedProvider(
        [
            ConversationDecisionResponse(
                initiate=True,
                reason="Catching up",
                opening_line="   ",
            ),
            DialogueTurnResponse(utterance="Turn 1 from Maya", continue_dialogue=False),
            DialogueTurnResponse(utterance="Turn 2 from Liam", continue_dialogue=True),
            DialogueTurnResponse(utterance="Turn 3 from Maya", continue_dialogue=True),
            DialogueTurnResponse(utterance="Turn 4 from Liam", continue_dialogue=True),
            DialogueTurnResponse(utterance="Turn 5 from Maya", continue_dialogue=True),
            DialogueTurnResponse(utterance="Turn 6 from Liam", continue_dialogue=True),
            ConversationSummaryResponse(
                summary="Maya and Liam chatted enthusiastically at the Bakery.",
                affinity_delta=0.75,
                relationship_note="Very warm rapport",
            ),
            ImportanceBatchResponse(ratings=[4]),
        ]
    )
    db, store, retriever, gateway, world, agents = await _setup_context(provider=scripted)
    try:
        await store.upsert_relationship(
            "liam",
            "maya",
            affinity=0.6,
            notes="Initial acquaintance",
            last_interaction_tick=2,
        )
        manager = ConversationManager(
            llm_gateway=gateway,
            memory_store=store,
            retriever=retriever,
        )
        maya = agents["maya"]
        liam = agents["liam"]

        outcome = await manager.run_conversation(
            maya,
            liam,
            tick=20,
            sim_time="Day 1 06:20",
            world=world,
        )
        assert outcome is not None
        assert len(outcome.turns) == MAX_DIALOGUE_TURNS == 6
        assert [turn["speaker_id"] for turn in outcome.turns] == [
            "maya",
            "liam",
            "maya",
            "liam",
            "maya",
            "liam",
        ]
        assert outcome.turns[0]["text"] == "Turn 1 from Maya"
        assert maya.conversation_hold_ticks == 4
        assert liam.conversation_hold_ticks == 4
        assert maya.needs_replan is False
        assert liam.needs_replan is False
        assert outcome.moods == ("warm", "warm")
        assert maya.mood == "warm"
        assert liam.mood == "warm"

        rel = await store.get_relationship("maya", "liam")
        assert rel is not None
        assert rel.affinity == pytest.approx(1.0)
        assert rel.notes == "Very warm rapport"
    finally:
        await db.dispose()


async def test_location_label_resolution_and_fallbacks() -> None:
    scripted = _ScriptedProvider(
        [
            ConversationDecisionResponse(
                initiate=True,
                reason="Quick greeting",
                opening_line="Hello out here!",
            ),
            DialogueTurnResponse(utterance="Hi there!", continue_dialogue=False),
            ConversationSummaryResponse(
                summary="Brief greeting near the edge of town.",
                affinity_delta=0.1,
                relationship_note="Polite wave",
            ),
            ImportanceBatchResponse(ratings=[3]),
            ConversationDecisionResponse(
                initiate=True,
                reason="Quick greeting",
                opening_line="Hello again!",
            ),
            DialogueTurnResponse(utterance="Good to see you!", continue_dialogue=False),
            ConversationSummaryResponse(
                summary="Another brief greeting.",
                affinity_delta=0.1,
                relationship_note="Friendly",
            ),
            ImportanceBatchResponse(ratings=[3]),
        ]
    )
    db, store, retriever, gateway, world, agents = await _setup_context(provider=scripted)
    try:
        manager = ConversationManager(
            llm_gateway=gateway,
            memory_store=store,
            retriever=retriever,
            conversation_cooldown_ticks=0,
        )
        maya = agents["maya"]
        liam = agents["liam"]

        maya.x, maya.y = 22, 22
        liam.x, liam.y = 22, 23
        maya.target_location = "Market"
        outcome_target = await manager.run_conversation(
            maya,
            liam,
            tick=10,
            sim_time="Day 1 06:10",
            world=world,
        )
        assert outcome_target is not None
        assert outcome_target.location == "Market"
        assert outcome_target.ws_payload["location"] == "Market"
        assert len(outcome_target.turns) == 2

        maya.target_location = None
        outcome_village = await manager.run_conversation(
            maya,
            liam,
            tick=15,
            sim_time="Day 1 06:15",
            world=world,
        )
        assert outcome_village is not None
        assert outcome_village.location == "Village"
        assert outcome_village.ws_payload["location"] == "Village"
    finally:
        await db.dispose()


async def test_completed_conversation_and_two_hop_rumor_propagation() -> None:
    db, store, retriever, gateway, world, agents = await _setup_context()
    try:
        manager = ConversationManager(
            llm_gateway=gateway,
            memory_store=store,
            retriever=retriever,
        )
        maya = agents["maya"]
        liam = agents["liam"]
        elena = agents["elena"]

        # Seed Maya with a high-importance fire observation at Bakery.
        await store.add_memory(
            agent_id="maya",
            memory_type="observation",
            text="[EVENT] at Bakery: A fire broke out near the ovens",
            importance=9,
            created_tick=5,
        )

        # Hop 1: Maya meets Liam near Bakery at tick 10.
        maya.x, maya.y = 4, 4
        liam.x, liam.y = 5, 4
        outcome1 = await manager.run_conversation(
            maya,
            liam,
            tick=10,
            sim_time="Day 1 06:10",
            world=world,
        )
        assert outcome1 is not None
        assert 2 <= len(outcome1.turns) <= 6
        assert outcome1.location == "Bakery"
        assert outcome1.ws_payload["type"] == "dialogue"
        assert outcome1.ws_payload["participants"] == ["maya", "liam"]
        assert outcome1.ws_payload["participant_names"] == ["Maya", "Liam"]
        assert outcome1.ws_payload["summary"] == outcome1.summary
        assert "fire" in outcome1.summary.lower()
        assert any("fire" in turn["text"].lower() for turn in outcome1.turns)
        assert all(
            set(turn.keys()) == {"speaker_id", "speaker_name", "text"}
            for turn in outcome1.turns
        )

        conversations = await store.list_conversations()
        assert len(conversations) == 1
        assert json.loads(conversations[0].participants) == ["maya", "liam"]
        assert json.loads(conversations[0].transcript_json) == outcome1.turns

        maya_conv_memories = await store.list_memories("maya", memory_type="conversation")
        liam_conv_memories = await store.list_memories("liam", memory_type="conversation")
        assert len(maya_conv_memories) == 1
        assert len(liam_conv_memories) == 1
        assert "fire" in maya_conv_memories[0].text.lower()
        assert "fire" in liam_conv_memories[0].text.lower()

        rel_ml = await store.get_relationship("maya", "liam")
        assert rel_ml is not None
        assert rel_ml.last_interaction_tick == 10
        assert -1.0 <= rel_ml.affinity <= 1.0

        expected_hold = min(max(2, len(outcome1.turns)), 4)
        assert maya.conversation_hold_ticks == expected_hold
        assert liam.conversation_hold_ticks == expected_hold
        assert maya.current_action == "Talking with Liam"
        assert liam.current_action == "Talking with Maya"
        assert outcome1.importance >= 7
        assert maya.needs_replan is True
        assert liam.needs_replan is True
        assert maya.replan_reason == outcome1.summary
        assert liam.replan_reason == outcome1.summary

        # Clear holds; CONVERSATION_COOLDOWN_TICKS=60 still blocks Maya+Liam until tick 70.
        maya.conversation_hold_ticks = 0
        liam.conversation_hold_ticks = 0
        cooldown_blocked = 10 + CONVERSATION_COOLDOWN_TICKS - 1
        cooldown_ready = 10 + CONVERSATION_COOLDOWN_TICKS
        assert manager.select_candidate_pairs([maya, liam], tick=cooldown_blocked) == []
        assert manager.select_candidate_pairs([maya, liam], tick=cooldown_ready) == [
            (liam, maya)
        ]

        # Hop 2: Liam walks over to Elena at Cafe at tick 15 and passes on the fire rumor.
        liam.x, liam.y = 12, 13
        elena.x, elena.y = 12, 12
        assert manager.select_candidate_pairs([liam, elena], tick=15) == [(elena, liam)]

        outcome2 = await manager.run_conversation(
            liam,
            elena,
            tick=15,
            sim_time="Day 1 06:15",
            world=world,
        )
        assert outcome2 is not None
        assert 2 <= len(outcome2.turns) <= 6
        assert outcome2.location == "Cafe"
        assert "fire" in outcome2.summary.lower()
        assert any("fire" in turn["text"].lower() for turn in outcome2.turns)

        elena_conv_memories = await store.list_memories("elena", memory_type="conversation")
        assert len(elena_conv_memories) == 1
        assert "fire" in elena_conv_memories[0].text.lower()
        assert elena.needs_replan is True
        assert len(await store.list_conversations()) == 2
        assert await store.get_relationship("liam", "elena") is not None
    finally:
        await db.dispose()


async def test_prior_relationship_context_canonical_key_and_mood_updates() -> None:
    scripted = _ScriptedProvider(
        [
            ConversationDecisionResponse(
                initiate=True,
                reason="Check on baking collaboration",
                opening_line="Did that sourdough starter rise well today?",
            ),
            DialogueTurnResponse(
                utterance="Yes, the crust turned out crisp and golden!",
                continue_dialogue=False,
            ),
            ConversationSummaryResponse(
                summary="Maya and Liam celebrated the successful sourdough batch.",
                affinity_delta=0.2,
                relationship_note="Trusted baking and cafe collaborators",
                speaker_a_mood="delighted",
                speaker_b_mood="inspired",
            ),
            ImportanceBatchResponse(ratings=[4]),
            ConversationDecisionResponse(
                initiate=True,
                reason="Report sudden storm warning",
                opening_line="A storm warning just reached the Market.",
            ),
            DialogueTurnResponse(
                utterance="Let's secure the Bakery shutters right away.",
                continue_dialogue=False,
            ),
            ConversationSummaryResponse(
                summary="Maya and Liam prepared for an incoming storm.",
                affinity_delta=0.05,
                relationship_note="Steady partners during urgent weather",
                speaker_a_mood="",
                speaker_b_mood="",
            ),
            ImportanceBatchResponse(ratings=[8]),
        ]
    )
    db, store, retriever, gateway, world, agents = await _setup_context(provider=scripted)
    try:
        await store.upsert_relationship(
            "maya",
            "liam",
            affinity=0.45,
            notes="Shared sourdough starter tips",
            last_interaction_tick=5,
        )
        manager = ConversationManager(
            llm_gateway=gateway,
            memory_store=store,
            retriever=retriever,
            conversation_cooldown_ticks=0,
        )
        maya = agents["maya"]
        liam = agents["liam"]

        outcome1 = await manager.run_conversation(
            maya,
            liam,
            tick=30,
            sim_time="Day 1 06:30",
            world=world,
        )
        assert outcome1 is not None
        assert outcome1.moods == ("delighted", "inspired")
        assert maya.mood == "delighted"
        assert liam.mood == "inspired"

        summary_prompts = [
            prompt
            for model, prompt in scripted.prompts_seen
            if model is ConversationSummaryResponse
        ]
        assert len(summary_prompts) == 1
        assert (
            "Prior relationship: affinity=0.45, notes=Shared sourdough starter tips"
            in summary_prompts[0]
        )

        rel = await store.get_relationship("maya", "liam")
        assert rel is not None
        assert (rel.agent_a, rel.agent_b) == ("liam", "maya")
        assert rel.affinity == pytest.approx(0.65)
        assert rel.notes == "Trusted baking and cafe collaborators"

        # High-importance exchange with blank LLM moods falls back to "concerned".
        outcome2 = await manager.run_conversation(
            maya,
            liam,
            tick=45,
            sim_time="Day 1 06:45",
            world=world,
        )
        assert outcome2 is not None
        assert outcome2.importance == 8
        assert outcome2.moods == ("concerned", "concerned")
        assert maya.mood == "concerned"
        assert liam.mood == "concerned"
    finally:
        await db.dispose()
