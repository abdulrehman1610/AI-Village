"""Typed prompt builders for salient reflection questions and cited insights."""

from __future__ import annotations

from collections.abc import Sequence

from agents.personas import AgentPersona


def _format_recent_memories(memories: Sequence[str]) -> str:
    cleaned = [" ".join(item.strip().split()) for item in memories if item.strip()]
    if not cleaned:
        return "- (none)"
    return "\n".join(f"- {item}" for item in cleaned)


def _format_salient_questions(questions: Sequence[str]) -> str:
    cleaned = [" ".join(item.strip().split()) for item in questions if item.strip()]
    if not cleaned:
        return "- (none)"
    return "\n".join(f"Q{idx}. {question}" for idx, question in enumerate(cleaned, start=1))


def _format_evidence_memories(evidence_memories: Sequence[tuple[int, str]]) -> str:
    lines: list[str] = []
    for memory_id, text in evidence_memories:
        cleaned = " ".join(text.strip().split())
        if cleaned:
            lines.append(f"- [{memory_id}] {cleaned}")
    if not lines:
        return "- (none)"
    return "\n".join(lines)


def build_salient_questions_prompt(
    *,
    persona: AgentPersona,
    sim_time: str,
    recent_memories: Sequence[str],
) -> str:
    """Build the reflection Step 1 prompt asking for 3 salient high-level questions."""
    memories_block = _format_recent_memories(recent_memories)
    return (
        "Generate 3 salient high-level questions grounded in this villager's recent memories.\n"
        f"Persona: {persona.summary_text()}\n"
        f"Sim time: {sim_time}\n"
        "Recent memories:\n"
        f"{memories_block}\n\n"
        "Instructions:\n"
        "- Return exactly 3 concise high-level questions inspired by recent observations, "
        "events, and relationships.\n"
        "- Keep each question grounded in the memories above rather than generic small talk."
    )


def build_reflection_insights_prompt(
    *,
    persona: AgentPersona,
    sim_time: str,
    questions: Sequence[str],
    evidence_memories: Sequence[tuple[int, str]],
) -> str:
    """Build the reflection Step 2 prompt synthesizing cited insights and agent mood."""
    questions_block = _format_salient_questions(questions)
    evidence_block = _format_evidence_memories(evidence_memories)
    return (
        "Synthesize higher-level reflection insights from this villager's salient questions "
        "and evidence memories.\n"
        f"Persona: {persona.summary_text()}\n"
        f"Sim time: {sim_time}\n"
        "Salient questions:\n"
        f"{questions_block}\n"
        "Evidence memories:\n"
        f"{evidence_block}\n\n"
        "Instructions:\n"
        "- Write 1 to 3 concise insights answering the salient questions from evidence.\n"
        "- Return supporting integer IDs from [id] evidence labels in cited_memory_ids "
        "and a short single-word mood label in mood.\n"
        "- Keep insights grounded strictly in the provided evidence memories."
    )
