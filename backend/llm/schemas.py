"""Strict Pydantic v2 structured output schemas for all LLM calls."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ImportanceBatchResponse(BaseModel):
    """Batched importance ratings (1..10) aligned 1:1 with input memory items."""

    model_config = ConfigDict(extra="forbid")

    ratings: list[Annotated[int, Field(ge=1, le=10)]]


class DailyPlanItem(BaseModel):
    """Single hourly/multi-hour scheduled block in an agent's daily plan."""

    model_config = ConfigDict(extra="forbid")

    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=0, le=24)
    location: str = Field(min_length=1)
    description: str = Field(min_length=1)


class DailyPlanResponse(BaseModel):
    """Broad daily schedule generated at wake-up or upon replanning."""

    model_config = ConfigDict(extra="forbid")

    items: list[DailyPlanItem] = Field(min_length=5, max_length=8)


class ConversationDecisionResponse(BaseModel):
    """Decision whether an agent initiates dialogue with a nearby peer."""

    model_config = ConfigDict(extra="forbid")

    initiate: bool
    reason: str
    opening_line: str = ""


class DialogueTurnResponse(BaseModel):
    """Single conversational utterance and continuation signal."""

    model_config = ConfigDict(extra="forbid")

    utterance: str = Field(min_length=1)
    continue_dialogue: bool = True


class ConversationSummaryResponse(BaseModel):
    """Post-dialogue memory summary and relationship affinity update."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    affinity_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    relationship_note: str = ""


class SalientQuestionsResponse(BaseModel):
    """Three high-level reflection questions derived from recent memories."""

    model_config = ConfigDict(extra="forbid")

    questions: list[str] = Field(min_length=3, max_length=3)


class ReflectionInsight(BaseModel):
    """Synthesized reflection statement grounded in cited memory IDs."""

    model_config = ConfigDict(extra="forbid")

    insight: str = Field(min_length=1)
    cited_memory_ids: list[int] = Field(default_factory=list)


class ReflectionResponse(BaseModel):
    """Collection of higher-level insights produced during agent reflection."""

    model_config = ConfigDict(extra="forbid")

    insights: list[ReflectionInsight] = Field(min_length=1)
