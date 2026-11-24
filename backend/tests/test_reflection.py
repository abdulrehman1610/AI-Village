"""Offline unit tests for threshold-triggered ReflectionManager and citation grounding."""

from __future__ import annotations

import json

from pydantic import BaseModel

from agents.personas import get_persona
from agents.reflection import ReflectionManager
from app.db import Database
from llm.gateway import LLMGateway
from llm.providers.base import ProviderResult
from llm.providers.mock import MockProvider
from llm.schemas import ReflectionInsight, ReflectionResponse, SalientQuestionsResponse
from memory.embeddings import EmbeddingService
from memory.models import AgentRecord
from memory.retrieval import MemoryRetriever
from memory.store import MemoryCreate, MemoryStore


class _ScriptedReflectionProvider:
    """Offline fake LLMProvider returning scripted salient questions and reflection insights."""

    def __init__(self, responses: list[BaseModel]) -> None:
        self._responses = list(responses)

    @property
    def name(self) -> str:
        return "scripted-reflection-mock"

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
        del prompt, system_instruction, model_override, temperature, seed
        if not self._responses:
            raise AssertionError("ScriptedReflectionProvider ran out of responses")
        item = self._responses.pop(0)
        assert isinstance(item, response_model)
        return ProviderResult(
            raw_text=item.model_dump_json(),
            model="mock-scripted",
            tokens_in=15,
            tokens_out=20,
        )


async def _seed_maya_memories(
    store: MemoryStore,
) -> list[int]:
    persona = get_persona("maya")
    await store.upsert_agent(
        AgentRecord(
            id=persona.id,
            name=persona.name,
            persona_json=persona.to_persona_json(),
            home_location=persona.home_location,
            x=4,
            y=4,
        )
    )
    seeded = await store.add_memories_batch(
        [
            MemoryCreate(
                agent_id="maya",
                memory_type="observation",
                text="Baked fresh sourdough loaves before sunrise at the Bakery",
                importance=5,
                created_tick=10,
            ),
            MemoryCreate(
                agent_id="maya",
                memory_type="observation",
                text="[EVENT] at Market: Urgent spice delivery drew a crowd at dawn",
                importance=9,
                created_tick=25,
            ),
            MemoryCreate(
                agent_id="maya",
                memory_type="conversation",
                text="Conversation with Liam: Discussed sharing pastries and espresso orders",
                importance=6,
                created_tick=40,
            ),
            MemoryCreate(
                agent_id="maya",
                memory_type="plan",
                text="Day 1 plan: 06:00-09:00 Bakery; 09:00-12:00 Cafe; 12:00-15:00 Market",
                importance=6,
                created_tick=1,
            ),
        ]
    )
    return [record.id for record in seeded if record.id is not None]


async def test_reflection_manager_threshold_retrieval_and_cited_memories() -> None:
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.init_models()
    try:
        embeddings = EmbeddingService.from_mode("mock")
        store = MemoryStore(db, embeddings)
        retriever = MemoryRetriever(store, embeddings)
        gateway = LLMGateway(provider=MockProvider(seed=42), db=db, seed=42)
        persona = get_persona("maya")
        seeded_ids = set(await _seed_maya_memories(store))

        manager = ReflectionManager(
            llm_gateway=gateway,
            memory_store=store,
            retriever=retriever,
            reflection_threshold=150,
        )
        assert manager.should_reflect(149) is False
        assert manager.should_reflect(150) is True

        outcome = await manager.run_reflection(
            agent_id="maya",
            persona=persona,
            tick=60,
            sim_time="Day 1 07:00",
        )
        assert outcome is not None
        assert outcome.agent_id == "maya"
        assert outcome.agent_name == "Maya"
        assert len(outcome.questions) == 3
        assert all(question.strip() for question in outcome.questions)
        assert len(outcome.insights) >= 1
        assert outcome.mood != ""
        assert len(outcome.ws_payloads) == len(outcome.insights)

        reflection_memories = await store.list_memories("maya", memory_type="reflection")
        assert len(reflection_memories) == len(outcome.insights)
        for mem in reflection_memories:
            assert mem.importance == 8
            assert mem.created_tick == 60
            metadata = json.loads(mem.metadata_json)
            cited = metadata["cited_memory_ids"]
            assert isinstance(cited, list)
            assert len(cited) >= 1
            assert set(cited).issubset(seeded_ids)
            assert metadata["questions"] == outcome.questions

        for payload in outcome.ws_payloads:
            assert set(payload.keys()) == {
                "type",
                "tick",
                "sim_time",
                "agent_id",
                "agent_name",
                "insight",
                "cited_memory_ids",
                "mood",
            }
            assert payload["type"] == "reflection"
            assert payload["tick"] == 60
            assert payload["sim_time"] == "Day 1 07:00"
            assert payload["agent_id"] == "maya"
            assert payload["agent_name"] == "Maya"
            assert payload["mood"] == outcome.mood
            assert set(payload["cited_memory_ids"]).issubset(seeded_ids)

        usage = await gateway.get_usage_summary()
        assert int(usage["total_calls"]) == 2
    finally:
        await db.dispose()


async def test_reflection_manager_filters_hallucinated_citations_with_fallback() -> None:
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.init_models()
    try:
        embeddings = EmbeddingService.from_mode("mock")
        store = MemoryStore(db, embeddings)
        retriever = MemoryRetriever(store, embeddings)
        persona = get_persona("maya")
        seeded_ids = await _seed_maya_memories(store)
        valid_id = seeded_ids[0]

        scripted = _ScriptedReflectionProvider(
            [
                SalientQuestionsResponse(
                    questions=[
                        "How did the dawn market spice rush affect my morning?",
                        "What should I coordinate next with Liam at the Cafe?",
                        "Which baking prep priorities matter most today?",
                    ]
                ),
                ReflectionResponse(
                    insights=[
                        ReflectionInsight(
                            insight="Community demand shifts rapidly when surprise deliveries hit.",
                            cited_memory_ids=[999999, -1],
                        ),
                        ReflectionInsight(
                            insight="Coordinating early with neighbors smooths morning rushes.",
                            cited_memory_ids=[999999, valid_id, valid_id, -1],
                        ),
                    ],
                    mood="thoughtful",
                ),
            ]
        )
        gateway = LLMGateway(provider=scripted, db=db)
        manager = ReflectionManager(
            llm_gateway=gateway,
            memory_store=store,
            retriever=retriever,
        )

        outcome = await manager.run_reflection(
            agent_id="maya",
            persona=persona,
            tick=75,
            sim_time="Day 1 07:15",
        )
        assert outcome is not None
        assert outcome.mood == "thoughtful"
        assert len(outcome.cited_memory_ids_per_insight) == 2

        first_cited, second_cited = outcome.cited_memory_ids_per_insight
        assert first_cited
        assert 999999 not in first_cited
        assert -1 not in first_cited
        assert set(first_cited).issubset(set(seeded_ids))
        assert len(first_cited) <= 2

        assert second_cited == [valid_id]

        persisted = await store.list_memories("maya", memory_type="reflection")
        assert len(persisted) == 2
        persisted_citations = [
            json.loads(record.metadata_json)["cited_memory_ids"]
            for record in persisted
        ]
        assert sorted(persisted_citations) == sorted([first_cited, second_cited])
    finally:
        await db.dispose()


async def test_reflection_manager_returns_none_without_memories() -> None:
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.init_models()
    try:
        embeddings = EmbeddingService.from_mode("mock")
        store = MemoryStore(db, embeddings)
        gateway = LLMGateway(provider=MockProvider(seed=42), db=db, seed=42)
        persona = get_persona("maya")

        manager = ReflectionManager(llm_gateway=gateway, memory_store=store, retriever=None)
        outcome = await manager.run_reflection(
            agent_id="maya",
            persona=persona,
            tick=5,
            sim_time="Day 1 06:05",
        )
        assert outcome is None
        assert int((await gateway.get_usage_summary())["total_calls"]) == 0
    finally:
        await db.dispose()
