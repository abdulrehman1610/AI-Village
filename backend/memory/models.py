from typing import ClassVar

from sqlalchemy import Column, LargeBinary
from sqlmodel import Field, SQLModel


class AgentRecord(SQLModel, table=True):
    """Persistent state and serialized persona for a village agent."""

    __tablename__: ClassVar[str] = "agents"

    id: str = Field(primary_key=True)
    name: str
    persona_json: str
    home_location: str
    x: int
    y: int
    current_action: str = "Idle"
    current_plan_json: str = "[]"


class MemoryRecord(SQLModel, table=True):
    """Episodic memory entry with raw float32 embedding vector blob."""

    __tablename__: ClassVar[str] = "memories"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True, foreign_key="agents.id")
    type: str = Field(index=True)
    text: str
    importance: int = Field(ge=1, le=10)
    created_tick: int = Field(index=True)
    last_access_tick: int
    embedding: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    metadata_json: str = "{}"


class RelationshipRecord(SQLModel, table=True):
    """Directional or pairwise agent relationship affinity and interaction notes."""

    __tablename__: ClassVar[str] = "relationships"

    agent_a: str = Field(primary_key=True, foreign_key="agents.id")
    agent_b: str = Field(primary_key=True, foreign_key="agents.id")
    affinity: float = 0.0
    notes: str = ""
    last_interaction_tick: int = 0


class EventRecord(SQLModel, table=True):
    """Simulated world or god-mode event log entry."""

    __tablename__: ClassVar[str] = "events"

    id: int | None = Field(default=None, primary_key=True)
    tick: int = Field(index=True)
    kind: str
    text: str
    location: str | None = Field(default=None)
    source: str


class ConversationRecord(SQLModel, table=True):
    """Completed multi-turn agent dialogue transcript and summary."""

    __tablename__: ClassVar[str] = "conversations"

    id: int | None = Field(default=None, primary_key=True)
    tick_start: int = Field(index=True)
    participants: str
    transcript_json: str
    summary: str


class LLMCallRecord(SQLModel, table=True):
    """Audit and cost/token telemetry record for an LLM gateway invocation."""

    __tablename__: ClassVar[str] = "llm_calls"

    id: int | None = Field(default=None, primary_key=True)
    tick: int = Field(index=True)
    agent_id: str | None = Field(default=None, index=True)
    purpose: str = Field(index=True)
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    cost_est: float = 0.0
    cache_hit: bool = False


class SimStateRecord(SQLModel, table=True):
    """Singleton simulation clock and seed checkpoint row."""

    __tablename__: ClassVar[str] = "sim_state"

    id: int = Field(default=1, primary_key=True)
    tick: int = 0
    sim_time: str = "Day 1 06:00"
    speed: int = 1
    seed: int = 42
