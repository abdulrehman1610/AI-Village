from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import update
from sqlmodel import col, or_, select

from app.db import Database
from memory.embeddings import EmbeddingService, pack_embedding
from memory.models import (
    AgentRecord,
    ConversationRecord,
    EventRecord,
    MemoryRecord,
    RelationshipRecord,
    SimStateRecord,
)

MemoryType = Literal["observation", "plan", "reflection", "conversation"]


@dataclass(frozen=True)
class MemoryCreate:
    """Input payload for batched memory insertion."""

    agent_id: str
    memory_type: MemoryType
    text: str
    importance: int
    created_tick: int
    metadata_json: str = "{}"


def _validate_importance(importance: int) -> None:
    if not 1 <= importance <= 10:
        raise ValueError(f"Memory importance must be in range [1, 10], got {importance}.")


class MemoryStore:
    """Async SQLite persistence service for memories, agents, relationships, events, and clock."""

    def __init__(self, db: Database, embedding_service: EmbeddingService) -> None:
        self.db = db
        self.embedding_service = embedding_service

    async def add_memory(
        self,
        *,
        agent_id: str,
        memory_type: MemoryType,
        text: str,
        importance: int,
        created_tick: int,
        metadata_json: str = "{}",
    ) -> MemoryRecord:
        """Embed and persist a single episodic memory record."""
        records = await self.add_memories_batch(
            [
                MemoryCreate(
                    agent_id=agent_id,
                    memory_type=memory_type,
                    text=text,
                    importance=importance,
                    created_tick=created_tick,
                    metadata_json=metadata_json,
                )
            ]
        )
        return records[0]

    async def add_memories_batch(self, items: Sequence[MemoryCreate]) -> list[MemoryRecord]:
        """Batch-embed and persist multiple memories in a single SQLite transaction."""
        if not items:
            return []

        for item in items:
            _validate_importance(item.importance)

        vectors = await self.embedding_service.embed_batch([item.text for item in items])
        records = [
            MemoryRecord(
                agent_id=item.agent_id,
                type=item.memory_type,
                text=item.text,
                importance=item.importance,
                created_tick=item.created_tick,
                last_access_tick=item.created_tick,
                embedding=pack_embedding(vector),
                metadata_json=item.metadata_json,
            )
            for item, vector in zip(items, vectors, strict=True)
        ]

        async with self.db.session() as session:
            session.add_all(records)
            await session.commit()

        return records

    async def list_memories(
        self,
        agent_id: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        """List memories for an agent ordered newest-first by created_tick and id."""
        if limit is not None and limit <= 0:
            return []

        stmt = select(MemoryRecord).where(col(MemoryRecord.agent_id) == agent_id)
        if memory_type is not None:
            stmt = stmt.where(col(MemoryRecord.type) == memory_type)
        stmt = stmt.order_by(col(MemoryRecord.created_tick).desc(), col(MemoryRecord.id).desc())
        if limit is not None:
            stmt = stmt.limit(limit)

        async with self.db.session() as session:
            result = await session.exec(stmt)
            return list(result.all())

    async def touch_memories(self, memory_ids: Sequence[int], tick: int) -> None:
        """Refresh last_access_tick on retrieved memories in a single transaction."""
        unique_ids = list(dict.fromkeys(int(memory_id) for memory_id in memory_ids))
        if not unique_ids:
            return

        stmt = (
            update(MemoryRecord)
            .where(col(MemoryRecord.id).in_(unique_ids))
            .values(last_access_tick=tick)
        )
        async with self.db.session() as session:
            conn = await session.connection()
            await conn.execute(stmt)
            await session.commit()

    async def upsert_agent(self, record: AgentRecord) -> AgentRecord:
        """Insert or update an agent record by primary key."""
        async with self.db.session() as session:
            existing = await session.get(AgentRecord, record.id)
            if existing is None:
                session.add(record)
                await session.commit()
                return record

            existing.name = record.name
            existing.persona_json = record.persona_json
            existing.home_location = record.home_location
            existing.x = record.x
            existing.y = record.y
            existing.current_action = record.current_action
            existing.current_plan_json = record.current_plan_json
            session.add(existing)
            await session.commit()
            return existing

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        """Fetch a persisted agent record by ID, or None if missing."""
        async with self.db.session() as session:
            return await session.get(AgentRecord, agent_id)

    async def list_agents(self) -> list[AgentRecord]:
        """List all persisted agent records ordered by ID."""
        stmt = select(AgentRecord).order_by(col(AgentRecord.id).asc())
        async with self.db.session() as session:
            result = await session.exec(stmt)
            return list(result.all())

    async def update_agent_states(
        self,
        states: Sequence[tuple[str, int, int, str, str]],
    ) -> None:
        """Batch-update (agent_id, x, y, current_action, current_plan_json) rows."""
        if not states:
            return

        agent_ids = [agent_id for agent_id, *_ in states]
        stmt = select(AgentRecord).where(col(AgentRecord.id).in_(agent_ids))
        async with self.db.session() as session:
            rows = list((await session.exec(stmt)).all())
            by_id = {row.id: row for row in rows}
            for agent_id, x, y, current_action, current_plan_json in states:
                agent = by_id.get(agent_id)
                if agent is None:
                    continue
                agent.x = x
                agent.y = y
                agent.current_action = current_action
                agent.current_plan_json = current_plan_json
                session.add(agent)
            await session.commit()

    async def get_or_create_sim_state(
        self,
        *,
        tick: int = 0,
        sim_time: str = "Day 1 06:00",
        speed: int = 1,
        seed: int = 42,
    ) -> SimStateRecord:
        """Return the singleton simulation state row, initializing it if absent."""
        async with self.db.session() as session:
            state = await session.get(SimStateRecord, 1)
            if state is None:
                state = SimStateRecord(
                    id=1,
                    tick=tick,
                    sim_time=sim_time,
                    speed=speed,
                    seed=seed,
                )
                session.add(state)
                await session.commit()
            return state

    async def save_sim_state(
        self,
        *,
        tick: int,
        sim_time: str,
        speed: int,
        seed: int,
    ) -> SimStateRecord:
        """Persist updated singleton simulation state values."""
        async with self.db.session() as session:
            state = await session.get(SimStateRecord, 1)
            if state is None:
                state = SimStateRecord(
                    id=1,
                    tick=tick,
                    sim_time=sim_time,
                    speed=speed,
                    seed=seed,
                )
            else:
                state.tick = tick
                state.sim_time = sim_time
                state.speed = speed
                state.seed = seed
            session.add(state)
            await session.commit()
            return state

    async def log_event(
        self,
        *,
        tick: int,
        kind: str,
        text: str,
        location: str | None = None,
        source: str,
    ) -> EventRecord:
        """Persist a simulated world or god-mode event entry."""
        event = EventRecord(
            tick=tick,
            kind=kind,
            text=text,
            location=location,
            source=source,
        )
        async with self.db.session() as session:
            session.add(event)
            await session.commit()
        return event

    async def upsert_relationship(
        self,
        agent_a: str,
        agent_b: str,
        affinity: float = 0.0,
        notes: str = "",
        last_interaction_tick: int = 0,
    ) -> RelationshipRecord:
        """Insert or update a pairwise agent relationship record."""
        async with self.db.session() as session:
            rel = await session.get(RelationshipRecord, (agent_a, agent_b))
            if rel is None:
                rel = RelationshipRecord(
                    agent_a=agent_a,
                    agent_b=agent_b,
                    affinity=affinity,
                    notes=notes,
                    last_interaction_tick=last_interaction_tick,
                )
            else:
                rel.affinity = affinity
                rel.notes = notes
                rel.last_interaction_tick = last_interaction_tick
            session.add(rel)
            await session.commit()
            return rel

    async def list_relationships(self, agent_id: str | None = None) -> list[RelationshipRecord]:
        """List relationship records, optionally filtered to those involving agent_id."""
        stmt = select(RelationshipRecord)
        if agent_id is not None:
            stmt = stmt.where(
                or_(
                    col(RelationshipRecord.agent_a) == agent_id,
                    col(RelationshipRecord.agent_b) == agent_id,
                )
            )
        stmt = stmt.order_by(
            col(RelationshipRecord.agent_a).asc(),
            col(RelationshipRecord.agent_b).asc(),
        )
        async with self.db.session() as session:
            result = await session.exec(stmt)
            return list(result.all())

    async def get_relationship(
        self,
        agent_a: str,
        agent_b: str,
    ) -> RelationshipRecord | None:
        """Fetch a pairwise relationship record symmetrically regardless of ID order."""
        async with self.db.session() as session:
            rel = await session.get(RelationshipRecord, (agent_a, agent_b))
            if rel is None and agent_a != agent_b:
                rel = await session.get(RelationshipRecord, (agent_b, agent_a))
            return rel

    async def list_events(
        self,
        *,
        since_tick: int | None = None,
        limit: int | None = None,
    ) -> list[EventRecord]:
        """List world or god-mode events ordered newest-first by tick and id."""
        if limit is not None and limit <= 0:
            return []

        stmt = select(EventRecord)
        if since_tick is not None:
            stmt = stmt.where(col(EventRecord.tick) >= since_tick)
        stmt = stmt.order_by(col(EventRecord.tick).desc(), col(EventRecord.id).desc())
        if limit is not None:
            stmt = stmt.limit(limit)

        async with self.db.session() as session:
            result = await session.exec(stmt)
            return list(result.all())

    async def add_conversation(
        self,
        *,
        tick_start: int,
        participants: Sequence[str],
        turns: Sequence[Mapping[str, Any]],
        summary: str,
    ) -> ConversationRecord:
        """Persist a completed multi-turn agent conversation transcript and summary."""
        record = ConversationRecord(
            tick_start=tick_start,
            participants=json.dumps(list(participants)),
            transcript_json=json.dumps([dict(turn) for turn in turns]),
            summary=summary,
        )
        async with self.db.session() as session:
            session.add(record)
            await session.commit()
        return record

    async def list_conversations(
        self,
        *,
        participant_id: str | None = None,
        limit: int | None = None,
    ) -> list[ConversationRecord]:
        """List conversations newest-first, optionally filtered to an exact participant."""
        if limit is not None and limit <= 0:
            return []

        stmt = select(ConversationRecord).order_by(
            col(ConversationRecord.tick_start).desc(),
            col(ConversationRecord.id).desc(),
        )
        if participant_id is None and limit is not None:
            stmt = stmt.limit(limit)

        async with self.db.session() as session:
            rows = list((await session.exec(stmt)).all())

        if participant_id is None:
            return rows

        filtered: list[ConversationRecord] = []
        for row in rows:
            try:
                participants = json.loads(row.participants)
            except json.JSONDecodeError:
                continue
            if isinstance(participants, list) and participant_id in participants:
                filtered.append(row)
                if limit is not None and len(filtered) >= limit:
                    break
        return filtered
