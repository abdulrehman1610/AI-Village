from __future__ import annotations

import sys
import threading
from collections.abc import AsyncIterator
from types import SimpleNamespace

import numpy as np
import pytest
import pytest_asyncio

from app.db import Database
from memory.embeddings import (
    EMBEDDING_DIM,
    DeterministicEmbeddingProvider,
    EmbeddingService,
    SentenceTransformerEmbeddingProvider,
    pack_embedding,
    unpack_embedding,
)
from memory.models import AgentRecord
from memory.retrieval import MemoryRetriever, cosine_similarity_batch, min_max_normalize
from memory.store import MemoryCreate, MemoryStore


@pytest_asyncio.fixture
async def db() -> AsyncIterator[Database]:
    """Provide a clean in-memory SQLite database and dispose it on teardown."""
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.init_models()
    try:
        yield database
    finally:
        await database.dispose()


@pytest_asyncio.fixture
async def store(db: Database) -> MemoryStore:
    """Provide a MemoryStore backed by the deterministic mock embedding service."""
    embedding_service = EmbeddingService.from_mode("mock")
    mem_store = MemoryStore(db=db, embedding_service=embedding_service)
    await mem_store.upsert_agent(
        AgentRecord(
            id="maya",
            name="Maya Lin",
            persona_json='{"role": "Baker"}',
            home_location="Home_Maya",
            x=5,
            y=6,
        )
    )
    await mem_store.upsert_agent(
        AgentRecord(
            id="liam",
            name="Liam Brooks",
            persona_json='{"role": "Barista"}',
            home_location="Home_Liam",
            x=34,
            y=6,
        )
    )
    return mem_store


async def test_deterministic_embedding_provider_zero_torch_and_semantics() -> None:
    """Mock embeddings run with zero torch imports, exact 384-d float32 roundtrip, and semantics."""
    service = EmbeddingService.from_mode("mock")
    assert isinstance(service.provider, DeterministicEmbeddingProvider)
    assert "torch" not in sys.modules
    assert "sentence_transformers" not in sys.modules

    vecs = await service.embed_batch(
        [
            "fire at the Market",
            "Market fire and smoke",
            "quiet poetry reading at Library",
            "",
        ]
    )
    assert "torch" not in sys.modules
    assert "sentence_transformers" not in sys.modules
    assert await service.embed_batch([]) == []

    assert len(vecs) == 4
    for vec in vecs:
        assert vec.shape == (EMBEDDING_DIM,)
        assert vec.dtype == np.float32
        assert np.all(np.isfinite(vec))
        assert float(np.linalg.norm(vec)) == pytest.approx(1.0, abs=1e-5)

        blob = pack_embedding(vec)
        assert len(blob) == EMBEDDING_DIM * 4
        restored = unpack_embedding(blob)
        assert restored.dtype == np.float32
        assert np.array_equal(restored, vec)

    sims = cosine_similarity_batch(np.vstack([vecs[1], vecs[2]]), vecs[0])
    assert sims.shape == (2,)
    assert sims[0] > sims[1]

    with pytest.raises(ValueError):
        pack_embedding(np.zeros(16, dtype=np.float32))
    with pytest.raises(ValueError):
        unpack_embedding(b"\x00" * 16)


async def test_sentence_transformer_provider_lazy_load_and_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SentenceTransformerEmbeddingProvider loads lazily and encodes inside asyncio.to_thread."""
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)

    provider = SentenceTransformerEmbeddingProvider(model_name="all-MiniLM-L6-v2", device="cpu")
    assert "sentence_transformers" not in sys.modules

    main_thread_id = threading.get_ident()
    observed_calls: list[dict[str, object]] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, device: str = "cpu") -> None:
            observed_calls.append({"init": (model_name, device)})

        def encode(
            self,
            sentences: list[str],
            *,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
            show_progress_bar: bool,
        ) -> np.ndarray:
            observed_calls.append(
                {
                    "sentences": sentences,
                    "convert_to_numpy": convert_to_numpy,
                    "normalize_embeddings": normalize_embeddings,
                    "show_progress_bar": show_progress_bar,
                    "thread_id": threading.get_ident(),
                }
            )
            out = np.zeros((len(sentences), EMBEDDING_DIM), dtype=np.float32)
            for idx in range(len(sentences)):
                out[idx, idx] = 1.0
            return out

    fake_module = SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    service = EmbeddingService(provider)
    assert await service.embed_batch([]) == []
    assert observed_calls == []

    vectors = await service.embed_batch(["hello", "world"])
    assert len(vectors) == 2
    assert all(v.shape == (EMBEDDING_DIM,) and v.dtype == np.float32 for v in vectors)
    assert vectors[0][0] == pytest.approx(1.0)
    assert vectors[1][1] == pytest.approx(1.0)

    assert observed_calls[0] == {"init": ("all-MiniLM-L6-v2", "cpu")}
    assert observed_calls[1]["sentences"] == ["hello", "world"]
    assert observed_calls[1]["convert_to_numpy"] is True
    assert observed_calls[1]["normalize_embeddings"] is True
    assert observed_calls[1]["show_progress_bar"] is False
    assert observed_calls[1]["thread_id"] != main_thread_id

    local_service = EmbeddingService.from_mode("local")
    assert isinstance(local_service.provider, SentenceTransformerEmbeddingProvider)


async def test_memory_store_crud_across_tables(store: MemoryStore) -> None:
    """MemoryStore handles memories, batches, agents, sim_state, events, and relationships."""
    single = await store.add_memory(
        agent_id="maya",
        memory_type="observation",
        text="Opened the bakery shutters at dawn.",
        importance=5,
        created_tick=10,
    )
    assert single.id is not None
    assert single.last_access_tick == 10
    assert len(single.embedding) == EMBEDDING_DIM * 4

    batched = await store.add_memories_batch(
        [
            MemoryCreate(
                agent_id="maya",
                memory_type="plan",
                text="Knead sourdough loaves before noon.",
                importance=7,
                created_tick=20,
            ),
            MemoryCreate(
                agent_id="maya",
                memory_type="reflection",
                text="Morning routines set a calm pace for the day.",
                importance=8,
                created_tick=30,
                metadata_json='{"cited_ids": [1]}',
            ),
        ]
    )
    assert len(batched) == 2
    assert await store.add_memories_batch([]) == []

    with pytest.raises(ValueError):
        await store.add_memory(
            agent_id="maya",
            memory_type="observation",
            text="Invalid importance.",
            importance=11,
            created_tick=35,
        )

    all_maya = await store.list_memories("maya")
    assert [m.created_tick for m in all_maya] == [30, 20, 10]
    plans = await store.list_memories("maya", memory_type="plan")
    assert len(plans) == 1
    assert plans[0].type == "plan"
    assert len(await store.list_memories("maya", limit=2)) == 2
    assert await store.list_memories("maya", limit=0) == []

    # Agent CRUD & batch state updates
    fetched_maya = await store.get_agent("maya")
    assert fetched_maya is not None
    assert fetched_maya.name == "Maya Lin"
    assert [a.id for a in await store.list_agents()] == ["liam", "maya"]

    await store.update_agent_states(
        [("maya", 24, 6, "Baking loaves", '["Bake bread"]')]
    )
    updated_maya = await store.get_agent("maya")
    assert updated_maya is not None
    assert (updated_maya.x, updated_maya.y) == (24, 6)
    assert updated_maya.current_action == "Baking loaves"

    # SimState singleton CRUD
    initial_state = await store.get_or_create_sim_state(tick=0, sim_time="Day 1 06:00")
    assert initial_state.id == 1
    saved_state = await store.save_sim_state(
        tick=120,
        sim_time="Day 1 08:00",
        speed=4,
        seed=99,
    )
    assert saved_state.tick == 120
    assert saved_state.speed == 4

    # Events & relationships
    event = await store.log_event(
        tick=45,
        kind="announcement",
        text="Fresh pastries ready at Bakery.",
        location="Bakery",
        source="agent",
    )
    assert event.id is not None
    assert event.location == "Bakery"

    await store.upsert_relationship(
        "maya",
        "liam",
        affinity=0.6,
        notes="Friendly chat",
        last_interaction_tick=50,
    )
    await store.upsert_relationship(
        "maya",
        "liam",
        affinity=0.8,
        notes="Close friends",
        last_interaction_tick=80,
    )
    rels = await store.list_relationships("liam")
    assert len(rels) == 1
    assert rels[0].affinity == pytest.approx(0.8)
    assert rels[0].notes == "Close friends"


async def test_retrieval_empty_single_and_min_max_edge_cases(store: MemoryStore) -> None:
    """Empty streams, single memories, and uniform arrays never emit NaN or Inf."""
    retriever = MemoryRetriever(store=store, embedding_service=store.embedding_service)
    assert (
        await retriever.retrieve(agent_id="maya", query="anything", current_tick=100)
        == []
    )

    assert min_max_normalize(np.empty(0, dtype=np.float64)).size == 0
    uniform = min_max_normalize(np.array([0.4, 0.4, 0.4], dtype=np.float64))
    assert np.allclose(uniform, [0.4, 0.4, 0.4])
    assert cosine_similarity_batch(
        np.empty((0, EMBEDDING_DIM), dtype=np.float32),
        np.zeros(EMBEDDING_DIM, dtype=np.float32),
    ).size == 0

    await store.add_memory(
        agent_id="maya",
        memory_type="observation",
        text="Swept the bakery floor.",
        importance=4,
        created_tick=50,
    )
    single_results = await retriever.retrieve(
        agent_id="maya",
        query="Market fire",
        current_tick=50,
    )
    assert len(single_results) == 1
    result = single_results[0]
    assert np.isfinite(result.score)
    assert 0.0 <= result.score <= 3.0
    assert 0.0 <= result.recency_score <= 1.0
    assert 0.0 <= result.importance_score <= 1.0
    assert 0.0 <= result.relevance_score <= 1.0


async def test_retrieval_recency_decay_importance_and_relevance_ranking(
    store: MemoryStore,
) -> None:
    """Verify exponential 0.995**hours recency, importance weighting, and semantic relevance."""
    retriever = MemoryRetriever(store=store, embedding_service=store.embedding_service)

    # 1. Recency decay: equal text & importance, recent tick=1200 outranks stale tick=0
    stale = await store.add_memory(
        agent_id="maya",
        memory_type="observation",
        text="Checked inventory notebook in the back room.",
        importance=5,
        created_tick=0,
    )
    recent = await store.add_memory(
        agent_id="maya",
        memory_type="observation",
        text="Checked inventory notebook in the back room.",
        importance=5,
        created_tick=1200,
    )
    recency_ranked = await retriever.retrieve(
        agent_id="maya",
        query="unrelated query weather clouds",
        current_tick=1200,
        touch=False,
    )
    assert [item.memory.id for item in recency_ranked] == [recent.id, stale.id]
    assert recency_ranked[0].recency_score == pytest.approx(1.0)
    assert recency_ranked[1].recency_score == pytest.approx(0.0)

    # 2. Importance weighting: on separate agent with equal tick & equal text
    low_imp = await store.add_memory(
        agent_id="liam",
        memory_type="observation",
        text="Quiet afternoon breeze outside.",
        importance=2,
        created_tick=500,
    )
    high_imp = await store.add_memory(
        agent_id="liam",
        memory_type="observation",
        text="Quiet afternoon breeze outside.",
        importance=9,
        created_tick=500,
    )
    imp_ranked = await retriever.retrieve(
        agent_id="liam",
        query="unrelated query stars",
        current_tick=500,
        touch=False,
    )
    assert [item.memory.id for item in imp_ranked] == [high_imp.id, low_imp.id]
    assert imp_ranked[0].importance_score == pytest.approx(1.0)
    assert imp_ranked[1].importance_score == pytest.approx(0.0)

    # 3. Semantic relevance: equal tick & equal importance
    await store.upsert_agent(
        AgentRecord(
            id="elena",
            name="Elena Rostova",
            persona_json='{"role": "Librarian"}',
            home_location="Home_Elena",
            x=5,
            y=24,
        )
    )
    baking = await store.add_memory(
        agent_id="elena",
        memory_type="observation",
        text="baking sourdough loaves",
        importance=5,
        created_tick=600,
    )
    market_smoke = await store.add_memory(
        agent_id="elena",
        memory_type="observation",
        text="smoke rising near Market stalls",
        importance=5,
        created_tick=600,
    )
    rel_ranked = await retriever.retrieve(
        agent_id="elena",
        query="Market smoke",
        current_tick=600,
        touch=False,
    )
    assert [item.memory.id for item in rel_ranked] == [market_smoke.id, baking.id]
    assert rel_ranked[0].relevance_score > rel_ranked[1].relevance_score


async def test_retrieval_top_k_truncation_and_selective_touch(store: MemoryStore) -> None:
    """Top-k=8 retrieval returns 8 items and updates last_access_tick ONLY on returned records."""
    items = [
        MemoryCreate(
            agent_id="maya",
            memory_type="observation",
            text=f"Routine village observation number {idx}",
            importance=(idx % 9) + 1,
            created_tick=idx * 20,
        )
        for idx in range(15)
    ]
    created = await store.add_memories_batch(items)
    assert len(created) == 15

    retriever = MemoryRetriever(
        store=store,
        embedding_service=store.embedding_service,
        default_top_k=8,
    )
    current_tick = 1000
    top_eight = await retriever.retrieve(
        agent_id="maya",
        query="Routine village observation number 14",
        current_tick=current_tick,
    )
    assert len(top_eight) == 8
    returned_ids = {item.memory.id for item in top_eight}
    assert len(returned_ids) == 8
    assert all(item.memory.last_access_tick == current_tick for item in top_eight)

    reloaded = await store.list_memories("maya")
    assert len(reloaded) == 15
    for record in reloaded:
        if record.id in returned_ids:
            assert record.last_access_tick == current_tick
        else:
            assert record.last_access_tick == record.created_tick
