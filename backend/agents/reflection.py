"""Threshold-triggered agent reflection pipeline producing cited insight memories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agents.personas import AgentPersona
from llm.gateway import LLMGateway
from llm.prompts.reflection import (
    build_reflection_insights_prompt,
    build_salient_questions_prompt,
)
from memory.models import MemoryRecord
from memory.retrieval import MemoryRetriever
from memory.store import MemoryCreate, MemoryStore


@dataclass(frozen=True)
class ReflectionOutcome:
    """Persisted insights, citations, mood, and WS payloads from one reflection cycle."""

    agent_id: str
    agent_name: str
    questions: list[str]
    insights: list[str]
    cited_memory_ids_per_insight: list[list[int]]
    mood: str
    ws_payloads: list[dict[str, Any]]


class ReflectionManager:
    """Coordinates salient question generation, evidence retrieval, and cited reflections."""

    def __init__(
        self,
        *,
        llm_gateway: LLMGateway,
        memory_store: MemoryStore,
        retriever: MemoryRetriever | None = None,
        reflection_threshold: int = 150,
        recent_memory_limit: int = 20,
        evidence_top_k: int = 8,
        reflection_importance: int = 8,
    ) -> None:
        if reflection_threshold < 1:
            raise ValueError(
                f"reflection_threshold must be >= 1, got {reflection_threshold}"
            )
        if recent_memory_limit < 1:
            raise ValueError(
                f"recent_memory_limit must be >= 1, got {recent_memory_limit}"
            )
        if evidence_top_k < 1:
            raise ValueError(f"evidence_top_k must be >= 1, got {evidence_top_k}")
        if not 1 <= reflection_importance <= 10:
            raise ValueError(
                f"reflection_importance must be in [1, 10], got {reflection_importance}"
            )

        self.llm_gateway = llm_gateway
        self.memory_store = memory_store
        self.retriever = retriever
        self.reflection_threshold = reflection_threshold
        self.recent_memory_limit = recent_memory_limit
        self.evidence_top_k = evidence_top_k
        self.reflection_importance = reflection_importance

    def should_reflect(self, accumulated_importance: int) -> bool:
        """Return True when accumulated importance reaches the reflection threshold."""
        return accumulated_importance >= self.reflection_threshold

    async def run_reflection(
        self,
        *,
        agent_id: str,
        persona: AgentPersona,
        tick: int,
        sim_time: str,
    ) -> ReflectionOutcome | None:
        """Run the two-step reflection pipeline and persist cited reflection memories."""
        recent_memories = await self.memory_store.list_memories(
            agent_id,
            limit=self.recent_memory_limit,
        )
        if not recent_memories:
            return None

        questions_prompt = build_salient_questions_prompt(
            persona=persona,
            sim_time=sim_time,
            recent_memories=[memory.text for memory in recent_memories],
        )
        questions_resp = await self.llm_gateway.generate_salient_questions(
            questions_prompt,
            tick=tick,
            agent_id=agent_id,
        )
        questions = list(questions_resp.questions)

        evidence_pairs = await self._collect_evidence_pairs(
            agent_id=agent_id,
            tick=tick,
            questions=questions,
            recent_memories=recent_memories,
        )
        if not evidence_pairs:
            return None

        valid_id_set = {memory_id for memory_id, _ in evidence_pairs}
        fallback_cited_ids = [memory_id for memory_id, _ in evidence_pairs[:2]]

        insights_prompt = build_reflection_insights_prompt(
            persona=persona,
            sim_time=sim_time,
            questions=questions,
            evidence_memories=evidence_pairs,
        )
        reflection_resp = await self.llm_gateway.generate_reflections(
            insights_prompt,
            tick=tick,
            agent_id=agent_id,
        )

        memory_items: list[MemoryCreate] = []
        cited_per_insight: list[list[int]] = []
        for item in reflection_resp.insights[:3]:
            insight_text = item.insight.strip()
            if not insight_text:
                continue

            valid_cited_ids = list(
                dict.fromkeys(
                    int(memory_id)
                    for memory_id in item.cited_memory_ids
                    if int(memory_id) in valid_id_set
                )
            )
            if not valid_cited_ids:
                valid_cited_ids = list(fallback_cited_ids)

            cited_per_insight.append(valid_cited_ids)
            memory_items.append(
                MemoryCreate(
                    agent_id=agent_id,
                    memory_type="reflection",
                    text=insight_text,
                    importance=self.reflection_importance,
                    created_tick=tick,
                    metadata_json=json.dumps(
                        {
                            "cited_memory_ids": valid_cited_ids,
                            "questions": questions,
                        }
                    ),
                )
            )

        if not memory_items:
            return None

        persisted_records = await self.memory_store.add_memories_batch(memory_items)
        resolved_mood = reflection_resp.mood.strip() or "reflective"

        ws_payloads = [
            {
                "type": "reflection",
                "tick": tick,
                "sim_time": sim_time,
                "agent_id": agent_id,
                "agent_name": persona.name,
                "insight": record.text,
                "cited_memory_ids": valid_cited_ids,
                "mood": resolved_mood,
            }
            for record, valid_cited_ids in zip(persisted_records, cited_per_insight, strict=True)
        ]

        return ReflectionOutcome(
            agent_id=agent_id,
            agent_name=persona.name,
            questions=questions,
            insights=[record.text for record in persisted_records],
            cited_memory_ids_per_insight=cited_per_insight,
            mood=resolved_mood,
            ws_payloads=ws_payloads,
        )

    async def _collect_evidence_pairs(
        self,
        *,
        agent_id: str,
        tick: int,
        questions: list[str],
        recent_memories: list[MemoryRecord],
    ) -> list[tuple[int, str]]:
        """Retrieve unique evidence memories for salient questions with recent fallback."""
        candidates_by_id: dict[int, tuple[float, MemoryRecord]] = {}

        if self.retriever is not None:
            for question in questions:
                scored_items = await self.retriever.retrieve(
                    agent_id,
                    question,
                    tick,
                    top_k=self.evidence_top_k,
                )
                for scored in scored_items:
                    memory_id = scored.memory.id
                    if memory_id is None:
                        continue
                    prev = candidates_by_id.get(memory_id)
                    if prev is None or scored.score > prev[0]:
                        candidates_by_id[memory_id] = (scored.score, scored.memory)

        if not candidates_by_id:
            for memory in recent_memories:
                if memory.id is not None and memory.id not in candidates_by_id:
                    candidates_by_id[memory.id] = (0.0, memory)

        max_evidence = max(12, self.evidence_top_k * 2)
        sorted_entries = sorted(
            candidates_by_id.items(),
            key=lambda entry: (
                entry[1][0],
                entry[1][1].created_tick,
                entry[0],
            ),
            reverse=True,
        )[:max_evidence]

        evidence_pairs: list[tuple[int, str]] = []
        for memory_id, (_, memory) in sorted_entries:
            text = memory.text.strip()
            if text:
                evidence_pairs.append((memory_id, text))
        return evidence_pairs
