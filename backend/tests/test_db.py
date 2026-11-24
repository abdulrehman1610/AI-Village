import asyncio
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.config import Settings
from app.db import Database
from memory.models import (
    AgentRecord,
    ConversationRecord,
    EventRecord,
    LLMCallRecord,
    MemoryRecord,
    RelationshipRecord,
    SimStateRecord,
)


@pytest_asyncio.fixture
async def db() -> AsyncIterator[Database]:
    """Provide an initialized in-memory async Database and dispose it on teardown."""
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.init_models()
    try:
        yield database
    finally:
        await database.dispose()


async def test_init_models_creates_all_seven_tables(db: Database) -> None:
    """Verify sqlite_master contains all 7 PRD tables."""
    expected_tables = {
        "agents",
        "memories",
        "relationships",
        "events",
        "conversations",
        "llm_calls",
        "sim_state",
    }
    async with db.session() as session:
        conn = await session.connection()
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = set(result.scalars().all())

    assert expected_tables.issubset(table_names)


async def test_agent_crud_roundtrip(db: Database) -> None:
    """Verify inserting, fetching, updating, and persisting an AgentRecord."""
    async with db.session() as session:
        session.add(
            AgentRecord(
                id="maya",
                name="Maya Lin",
                persona_json='{"role": "Baker"}',
                home_location="Home_Maya",
                x=5,
                y=6,
                current_action="Baking bread",
                current_plan_json='["Open bakery"]',
            )
        )
        await session.commit()

    async with db.session() as session:
        agent = await session.get(AgentRecord, "maya")
        assert agent is not None
        assert agent.name == "Maya Lin"
        assert (agent.x, agent.y) == (5, 6)

        agent.x = 24
        agent.y = 6
        agent.current_action = "Walking to Bakery"
        session.add(agent)
        await session.commit()

    async with db.session() as session:
        reloaded = await session.get(AgentRecord, "maya")
        assert reloaded is not None
        assert (reloaded.x, reloaded.y) == (24, 6)
        assert reloaded.current_action == "Walking to Bakery"


async def test_memory_binary_float32_embedding_roundtrip(db: Database) -> None:
    """Verify 384-d float32 embedding blobs roundtrip with exact byte fidelity."""
    embedding_vec = np.arange(384, dtype=np.float32)
    embedding_blob = embedding_vec.tobytes()
    assert len(embedding_blob) == 1536

    async with db.session() as session:
        session.add(
            AgentRecord(
                id="maya",
                name="Maya Lin",
                persona_json="{}",
                home_location="Home_Maya",
                x=5,
                y=6,
            )
        )
        await session.commit()

    async with db.session() as session:
        record = MemoryRecord(
            agent_id="maya",
            type="observation",
            text="Fresh croissants cooled on the bakery rack.",
            importance=6,
            created_tick=12,
            last_access_tick=12,
            embedding=embedding_blob,
            metadata_json='{"location": "Bakery"}',
        )
        session.add(record)
        await session.commit()
        assert record.id is not None
        memory_id = record.id

    async with db.session() as session:
        loaded = await session.get(MemoryRecord, memory_id)
        assert loaded is not None
        assert loaded.embedding == embedding_blob
        unpacked = np.frombuffer(loaded.embedding, dtype=np.float32)
        assert unpacked.shape == (384,)
        assert np.array_equal(unpacked, embedding_vec)


async def test_relationship_composite_pk_and_foreign_keys(db: Database) -> None:
    """Verify RelationshipRecord composite keys, duplicate errors, and FK enforcement."""
    async with db.session() as session:
        session.add(
            AgentRecord(
                id="maya",
                name="Maya Lin",
                persona_json="{}",
                home_location="Home_Maya",
                x=5,
                y=6,
            )
        )
        session.add(
            AgentRecord(
                id="liam",
                name="Liam Brooks",
                persona_json="{}",
                home_location="Home_Liam",
                x=34,
                y=6,
            )
        )
        await session.commit()

    async with db.session() as session:
        session.add(
            RelationshipRecord(
                agent_a="maya",
                agent_b="liam",
                affinity=0.45,
                notes="Shared morning coffee.",
                last_interaction_tick=25,
            )
        )
        await session.commit()

    async with db.session() as session:
        rel = await session.get(RelationshipRecord, ("maya", "liam"))
        assert rel is not None
        assert rel.affinity == pytest.approx(0.45)
        assert rel.notes == "Shared morning coffee."
        assert rel.last_interaction_tick == 25

    async with db.session() as session:
        session.add(
            RelationshipRecord(
                agent_a="maya",
                agent_b="liam",
                affinity=0.8,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async with db.session() as session:
        session.add(
            RelationshipRecord(
                agent_a="maya",
                agent_b="nonexistent_agent",
                affinity=0.1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_events_conversations_and_llm_calls_queries(db: Database) -> None:
    """Verify EventRecord, ConversationRecord, and LLMCallRecord inserts and ordering."""
    async with db.session() as session:
        session.add(
            EventRecord(
                tick=5,
                kind="weather",
                text="Morning bell rings at the plaza.",
                location="Town Square",
                source="god",
            )
        )
        session.add(
            EventRecord(
                tick=15,
                kind="rumor",
                text="A spice merchant arrived at the Market.",
                location="Market",
                source="agent",
            )
        )
        session.add(
            ConversationRecord(
                tick_start=18,
                participants='["maya", "liam"]',
                transcript_json='[{"speaker": "maya", "text": "Morning!"}]',
                summary="Maya and Liam greeted each other.",
            )
        )
        session.add(
            LLMCallRecord(
                tick=10,
                agent_id="maya",
                purpose="importance_batch",
                model="mock",
                tokens_in=40,
                tokens_out=12,
                latency_ms=1.2,
                cost_est=0.0,
                cache_hit=False,
            )
        )
        session.add(
            LLMCallRecord(
                tick=20,
                agent_id=None,
                purpose="event_parse",
                model="gemini-2.5-flash",
                tokens_in=0,
                tokens_out=0,
                latency_ms=0.2,
                cost_est=0.0,
                cache_hit=True,
            )
        )
        await session.commit()

    async with db.session() as session:
        events = list(
            (await session.exec(select(EventRecord).order_by(col(EventRecord.tick).desc()))).all()
        )
        assert [event.tick for event in events] == [15, 5]
        assert events[0].location == "Market"
        assert events[1].source == "god"

        conversations = list(
            (
                await session.exec(
                    select(ConversationRecord).order_by(col(ConversationRecord.tick_start).asc())
                )
            ).all()
        )
        assert len(conversations) == 1
        assert conversations[0].participants == '["maya", "liam"]'

        llm_calls = list(
            (
                await session.exec(
                    select(LLMCallRecord).order_by(col(LLMCallRecord.tick).asc())
                )
            ).all()
        )
        assert len(llm_calls) == 2
        assert llm_calls[0].cache_hit is False
        assert llm_calls[1].cache_hit is True
        assert llm_calls[1].agent_id is None


async def test_sim_state_singleton_update(db: Database) -> None:
    """Verify SimStateRecord updates in-place as a single row with id=1."""
    async with db.session() as session:
        session.add(SimStateRecord(id=1, tick=0, sim_time="Day 1 06:00", speed=1, seed=42))
        await session.commit()

    async with db.session() as session:
        state = await session.get(SimStateRecord, 1)
        assert state is not None
        state.tick = 42
        state.sim_time = "Day 1 06:42"
        state.speed = 4
        session.add(state)
        await session.commit()

    async with db.session() as session:
        rows = list((await session.exec(select(SimStateRecord))).all())
        assert len(rows) == 1
        assert rows[0].tick == 42
        assert rows[0].sim_time == "Day 1 06:42"
        assert rows[0].speed == 4


async def test_memory_database_concurrent_sessions_serialized(db: Database) -> None:
    """Verify concurrent :memory: session access is safely serialized without lock errors."""
    async def read_tables() -> int:
        async with db.session() as session:
            conn = await session.connection()
            result = await conn.exec_driver_sql(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            )
            return int(result.scalar_one())

    counts = await asyncio.gather(*(read_tables() for _ in range(5)))
    assert all(count >= 7 for count in counts)


async def test_file_backed_wal_mode_and_persistence(tmp_path: Path) -> None:
    """Verify WAL mode on file SQLite DB and data persistence across dispose/reopen."""
    db_file = tmp_path / "nested" / "village_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

    first_db = Database(db_url)
    try:
        await first_db.init_models()
        async with first_db.session() as session:
            conn = await session.connection()
            pragma_result = await conn.exec_driver_sql("PRAGMA journal_mode;")
            journal_mode = str(pragma_result.scalar_one()).lower()
            assert journal_mode == "wal"

            session.add(
                AgentRecord(
                    id="elena",
                    name="Elena Rostova",
                    persona_json='{"role": "Librarian"}',
                    home_location="Home_Elena",
                    x=5,
                    y=24,
                )
            )
            session.add(SimStateRecord(id=1, tick=7, sim_time="Day 1 06:07", speed=1, seed=99))
            await session.commit()
    finally:
        await first_db.dispose()

    reopened_db = Database(db_url)
    try:
        async with reopened_db.session() as session:
            agent = await session.get(AgentRecord, "elena")
            state = await session.get(SimStateRecord, 1)
            assert agent is not None
            assert agent.name == "Elena Rostova"
            assert state is not None
            assert state.tick == 7
            assert state.seed == 99
    finally:
        await reopened_db.dispose()


async def test_agent_mood_default_and_roundtrip(db: Database) -> None:
    """Verify AgentRecord.mood defaults to 'calm' and persists updated mood values."""
    async with db.session() as session:
        session.add(
            AgentRecord(
                id="maya",
                name="Maya Lin",
                persona_json='{"role": "Baker"}',
                home_location="Home_Maya",
                x=5,
                y=6,
                current_plan_json='["Open bakery"]',
            )
        )
        await session.commit()

    async with db.session() as session:
        agent = await session.get(AgentRecord, "maya")
        assert agent is not None
        assert agent.mood == "calm"
        assert agent.current_plan_json == '["Open bakery"]'
        agent.mood = "reflective"
        session.add(agent)
        await session.commit()

    async with db.session() as session:
        reloaded = await session.get(AgentRecord, "maya")
        assert reloaded is not None
        assert reloaded.mood == "reflective"
        assert reloaded.current_plan_json == '["Open bakery"]'


async def test_init_models_migrates_legacy_agents_table_missing_mood(tmp_path: Path) -> None:
    """Verify init_models idempotently adds agents.mood to legacy SQLite DBs."""
    db_file = tmp_path / "legacy_village.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            """
            CREATE TABLE agents (
                id VARCHAR NOT NULL PRIMARY KEY,
                name VARCHAR NOT NULL,
                persona_json VARCHAR NOT NULL,
                home_location VARCHAR NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                current_action VARCHAR NOT NULL,
                current_plan_json VARCHAR NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO agents (
                id, name, persona_json, home_location, x, y, current_action, current_plan_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "maya",
                "Maya Lin",
                '{"role": "Baker"}',
                "Home_Maya",
                5,
                6,
                "Idle",
                '["Open bakery"]',
            ),
        )
        conn.commit()
    finally:
        conn.close()

    database = Database(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    try:
        await database.init_models()
        await database.init_models()

        async with database.session() as session:
            sa_conn = await session.connection()
            pragma = await sa_conn.exec_driver_sql("PRAGMA table_info('agents')")
            column_names = {str(list(row)[1]) for row in pragma.fetchall()}
            assert "mood" in column_names

            maya = await session.get(AgentRecord, "maya")
            assert maya is not None
            assert maya.name == "Maya Lin"
            assert maya.mood == "calm"
            assert maya.current_plan_json == '["Open bakery"]'
    finally:
        await database.dispose()


def test_settings_reflection_threshold_default_and_validation() -> None:
    """Verify Settings.reflection_threshold defaults to 150 and enforces >= 1."""
    assert Settings().reflection_threshold == 150
    assert Settings(reflection_threshold=50).reflection_threshold == 50
    with pytest.raises(ValidationError):
        Settings(reflection_threshold=0)
