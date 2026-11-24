import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.db import Database
from memory.embeddings import EmbeddingService
from memory.models import AgentRecord, RelationshipRecord
from memory.store import MemoryStore


@pytest_asyncio.fixture
async def store() -> AsyncIterator[MemoryStore]:
    """Yield an in-memory MemoryStore seeded with sample agents."""
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.init_models()
    memory_store = MemoryStore(db, EmbeddingService.from_mode("mock"))
    try:
        seed_agents = [
            AgentRecord(
                id="maya",
                name="Maya Lin",
                persona_json='{"role": "Baker"}',
                home_location="Home_Maya",
                x=5,
                y=6,
            ),
            AgentRecord(
                id="liam",
                name="Liam Brooks",
                persona_json='{"role": "Barista"}',
                home_location="Home_Liam",
                x=34,
                y=6,
            ),
            AgentRecord(
                id="sam",
                name="Sam Rivera",
                persona_json='{"role": "Grocer"}',
                home_location="Market",
                x=14,
                y=12,
            ),
            AgentRecord(
                id="samuel",
                name="Samuel Cho",
                persona_json='{"role": "Archivist"}',
                home_location="Library",
                x=20,
                y=18,
            ),
        ]
        for agent in seed_agents:
            await memory_store.upsert_agent(agent)
        yield memory_store
    finally:
        await db.dispose()


async def test_add_and_list_conversations_ordering_limits_and_participant_filter(
    store: MemoryStore,
) -> None:
    """Verify conversation persistence, newest-first ordering, limits, and exact matching."""
    conv_old = await store.add_conversation(
        tick_start=10,
        participants=["maya", "liam"],
        turns=[
            {"speaker": "maya", "utterance": "Good morning, Liam!"},
            {"speaker": "liam", "utterance": "Morning Maya, fresh espresso is brewing."},
        ],
        summary="Maya and Liam exchanged morning greetings.",
    )
    conv_sam = await store.add_conversation(
        tick_start=25,
        participants=["sam", "maya"],
        turns=[{"speaker": "sam", "utterance": "Did the bakery open early today?"}],
        summary="Sam asked Maya about the bakery opening.",
    )
    conv_samuel = await store.add_conversation(
        tick_start=25,
        participants=["samuel", "liam"],
        turns=[{"speaker": "samuel", "utterance": "The library received new maps."}],
        summary="Samuel told Liam about new library maps.",
    )

    assert conv_old.id is not None
    assert conv_sam.id is not None
    assert conv_samuel.id is not None
    assert conv_samuel.id > conv_sam.id > conv_old.id

    all_convs = await store.list_conversations()
    assert [conv.id for conv in all_convs] == [conv_samuel.id, conv_sam.id, conv_old.id]

    limited = await store.list_conversations(limit=1)
    assert [conv.id for conv in limited] == [conv_samuel.id]
    assert await store.list_conversations(limit=0) == []
    assert await store.list_conversations(limit=-1) == []

    sam_convs = await store.list_conversations(participant_id="sam")
    assert [conv.id for conv in sam_convs] == [conv_sam.id]

    samuel_convs = await store.list_conversations(participant_id="samuel")
    assert [conv.id for conv in samuel_convs] == [conv_samuel.id]

    maya_latest = await store.list_conversations(participant_id="maya", limit=1)
    assert [conv.id for conv in maya_latest] == [conv_sam.id]
    assert await store.list_conversations(participant_id="sam", limit=0) == []

    assert json.loads(conv_sam.participants) == ["sam", "maya"]
    assert json.loads(conv_old.transcript_json) == [
        {"speaker": "maya", "utterance": "Good morning, Liam!"},
        {"speaker": "liam", "utterance": "Morning Maya, fresh espresso is brewing."},
    ]
    assert all_convs[2].summary == "Maya and Liam exchanged morning greetings."


async def test_log_and_list_events_ordering_since_tick_and_limits(store: MemoryStore) -> None:
    """Verify event queries return newest-first with optional since_tick and limit filters."""
    ev_5 = await store.log_event(
        tick=5,
        kind="weather",
        text="A cool breeze swept across Town Square.",
        location="Town Square",
        source="world",
    )
    ev_12 = await store.log_event(
        tick=12,
        kind="god_event",
        text="A spice merchant arrived at the Market.",
        location="Market",
        source="god",
    )
    ev_20 = await store.log_event(
        tick=20,
        kind="god_event",
        text="Evening lanterns flickered on across the village.",
        location=None,
        source="god",
    )

    all_events = await store.list_events()
    assert [ev.id for ev in all_events] == [ev_20.id, ev_12.id, ev_5.id]
    assert [ev.tick for ev in all_events] == [20, 12, 5]
    assert all_events[0].location is None
    assert all_events[1].location == "Market"

    since_12 = await store.list_events(since_tick=12)
    assert [ev.tick for ev in since_12] == [20, 12]

    limited = await store.list_events(limit=2)
    assert [ev.tick for ev in limited] == [20, 12]

    since_12_limited = await store.list_events(since_tick=12, limit=1)
    assert [ev.tick for ev in since_12_limited] == [20]

    assert await store.list_events(limit=0) == []
    assert await store.list_events(limit=-2) == []


async def test_list_events_tiebreaks_same_tick_by_id_desc(store: MemoryStore) -> None:
    """Verify events sharing the same tick are ordered newest id first."""
    first = await store.log_event(tick=30, kind="god_event", text="First event", source="god")
    second = await store.log_event(tick=30, kind="god_event", text="Second event", source="god")

    events = await store.list_events(since_tick=30)
    assert [ev.id for ev in events] == [second.id, first.id]


async def test_upsert_and_symmetric_get_relationship(store: MemoryStore) -> None:
    """Verify get_relationship resolves pairwise records symmetrically regardless of order."""
    await store.upsert_relationship(
        "liam",
        "maya",
        affinity=0.35,
        notes="Shared coffee recipes at the Cafe.",
        last_interaction_tick=42,
    )

    direct = await store.get_relationship("liam", "maya")
    assert direct is not None
    assert direct.agent_a == "liam"
    assert direct.agent_b == "maya"
    assert direct.affinity == pytest.approx(0.35)
    assert direct.notes == "Shared coffee recipes at the Cafe."
    assert direct.last_interaction_tick == 42

    symmetric = await store.get_relationship("maya", "liam")
    assert symmetric is not None
    assert symmetric.agent_a == "liam"
    assert symmetric.agent_b == "maya"
    assert symmetric.affinity == pytest.approx(0.35)
    assert symmetric.notes == "Shared coffee recipes at the Cafe."

    assert await store.get_relationship("maya", "noah") is None
    assert await store.get_relationship("maya", "maya") is None


async def test_upsert_relationship_canonicalizes_pair_and_rejects_self_loop(
    store: MemoryStore,
) -> None:
    """Verify canonical (min, max) keys, clamping, consolidation, and self-loop rejection."""
    created = await store.upsert_relationship(
        "maya",
        "liam",
        affinity=0.4,
        notes="First chat",
        last_interaction_tick=10,
    )
    assert created.agent_a == "liam"
    assert created.agent_b == "maya"

    updated = await store.upsert_relationship(
        "liam",
        "maya",
        affinity=1.5,
        notes="Close friends",
        last_interaction_tick=25,
    )
    assert updated.agent_a == "liam"
    assert updated.agent_b == "maya"
    all_rels = await store.list_relationships()
    assert len(all_rels) == 1
    assert all_rels[0].affinity == pytest.approx(1.0)
    assert all_rels[0].notes == "Close friends"
    assert all_rels[0].last_interaction_tick == 25

    # Seed a legacy non-canonical reversed row and verify upsert consolidates it cleanly.
    async with store.db.session() as session:
        session.add(
            RelationshipRecord(
                agent_a="samuel",
                agent_b="sam",
                affinity=0.2,
                notes="Legacy reversed row",
                last_interaction_tick=5,
            )
        )
        await session.commit()

    consolidated = await store.upsert_relationship(
        "sam",
        "samuel",
        affinity=-1.8,
        notes="Consolidated canonical row",
        last_interaction_tick=30,
    )
    assert consolidated.agent_a == "sam"
    assert consolidated.agent_b == "samuel"
    assert consolidated.affinity == pytest.approx(-1.0)
    sam_rels = await store.list_relationships("sam")
    assert len(sam_rels) == 1
    assert sam_rels[0].agent_a == "sam"
    assert sam_rels[0].agent_b == "samuel"
    assert sam_rels[0].notes == "Consolidated canonical row"

    with pytest.raises(ValueError, match="itself"):
        await store.upsert_relationship("maya", "maya", affinity=0.5)


async def test_update_agent_states_with_moods_and_get_memories_by_ids(
    store: MemoryStore,
) -> None:
    """Verify mood persistence and agent-scoped get_memories_by_ids lookups."""
    await store.update_agent_states(
        [
            ("maya", 7, 8, "Baking tarts", '["Bake pastries"]'),
            ("liam", 30, 6, "Brewing espresso", '["Serve coffee"]'),
        ],
        moods={"maya": "cheerful"},
    )
    maya = await store.get_agent("maya")
    liam = await store.get_agent("liam")
    assert maya is not None
    assert liam is not None
    assert maya.mood == "cheerful"
    assert liam.mood == "calm"

    await store.update_agent_states([], moods={"liam": "focused"})
    reloaded_liam = await store.get_agent("liam")
    assert reloaded_liam is not None
    assert reloaded_liam.mood == "focused"

    maya.mood = "reflective"
    await store.upsert_agent(maya)
    reloaded_maya = await store.get_agent("maya")
    assert reloaded_maya is not None
    assert reloaded_maya.mood == "reflective"

    m1 = await store.add_memory(
        agent_id="maya",
        memory_type="observation",
        text="Checked the morning oven temperature.",
        importance=4,
        created_tick=10,
    )
    m2 = await store.add_memory(
        agent_id="maya",
        memory_type="observation",
        text="Chat with Sam about flour delivery.",
        importance=6,
        created_tick=20,
    )
    liam_mem = await store.add_memory(
        agent_id="liam",
        memory_type="observation",
        text="Cleaned the espresso machine.",
        importance=5,
        created_tick=25,
    )
    assert m1.id is not None
    assert m2.id is not None
    assert liam_mem.id is not None

    fetched = await store.get_memories_by_ids(
        "maya",
        [m1.id, m2.id, m1.id, liam_mem.id, 99999, 0, -2],
    )
    assert [record.id for record in fetched] == [m2.id, m1.id]
    assert await store.get_memories_by_ids("maya", []) == []
    assert await store.get_memories_by_ids("maya", [0, -1, 99999]) == []
    assert await store.get_memories_by_ids("maya", [liam_mem.id]) == []
