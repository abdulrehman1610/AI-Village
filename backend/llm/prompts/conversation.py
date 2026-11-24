"""Typed prompt builders for agent-to-agent conversation decisions, turns, and summaries."""

from __future__ import annotations

from collections.abc import Sequence

from agents.personas import AgentPersona


def _format_memories(memories: Sequence[str]) -> str:
    cleaned = [item.strip() for item in memories if item.strip()]
    if not cleaned:
        return "- (none)"
    return "\n".join(f"- {item}" for item in cleaned)


def _format_transcript(transcript: Sequence[tuple[str, str]]) -> str:
    if not transcript:
        return "- (none)"
    return "\n".join(f"- {speaker}: {utterance}" for speaker, utterance in transcript)


def build_conversation_decision_prompt(
    *,
    speaker: AgentPersona,
    listener: AgentPersona,
    location: str,
    sim_time: str,
    speaker_action: str,
    listener_action: str,
    memories: Sequence[str],
) -> str:
    """Build the initiation-check prompt for two nearby villagers."""
    memories_block = _format_memories(memories)
    return (
        f"Decide whether {speaker.name} greets {listener.name} to chat.\n"
        f"Participants: {speaker.name} and {listener.name}\n"
        f"Location: {location}\n"
        f"Sim time: {sim_time}\n"
        f"Speaker profile: {speaker.summary_text()}\n"
        f"Listener profile: {listener.summary_text()}\n"
        f"Speaker current activity: {speaker_action}\n"
        f"Listener current activity: {listener_action}\n"
        "Context memories:\n"
        f"{memories_block}\n\n"
        "Instructions:\n"
        "- Set initiate=true when there is a timely topic or friendly social opening to share.\n"
        "- Provide a concise reason and, when initiating, a natural opening_line."
    )


def build_dialogue_turn_prompt(
    *,
    speaker: AgentPersona,
    listener: AgentPersona,
    location: str,
    sim_time: str,
    turn_index: int,
    max_turns: int,
    memories: Sequence[str],
    transcript: Sequence[tuple[str, str]],
) -> str:
    """Build a turn-by-turn dialogue prompt grounded in retrieved memories and transcript."""
    memories_block = _format_memories(memories)
    transcript_block = _format_transcript(transcript)
    return (
        f"Generate the next spoken reply from {speaker.name} to {listener.name}.\n"
        f"Participants: {speaker.name} and {listener.name}\n"
        f"Location: {location}\n"
        f"Sim time: {sim_time}\n"
        f"Turn: {turn_index} of {max_turns}\n"
        f"Speaker profile: {speaker.summary_text()}\n"
        f"Listener profile: {listener.summary_text()}\n"
        "Context memories:\n"
        f"{memories_block}\n"
        "Transcript:\n"
        f"{transcript_block}\n\n"
        "Instructions:\n"
        "- Write one natural, in-character utterance grounded in context memories "
        "and transcript.\n"
        "- Set continue_dialogue=false when the exchange reaches a natural wrap-up."
    )


def build_conversation_summary_prompt(
    *,
    speaker_a: AgentPersona,
    speaker_b: AgentPersona,
    location: str,
    sim_time: str,
    transcript: Sequence[tuple[str, str]],
) -> str:
    """Build a post-dialogue summarization and relationship affinity update prompt."""
    transcript_block = _format_transcript(transcript)
    return (
        f"Summarize the exchange between {speaker_a.name} and {speaker_b.name}.\n"
        f"Participants: {speaker_a.name} and {speaker_b.name}\n"
        f"Location: {location}\n"
        f"Sim time: {sim_time}\n"
        "Transcript:\n"
        f"{transcript_block}\n\n"
        "Instructions:\n"
        "- Write a concise factual summary preserving key topics, names, and locations mentioned.\n"
        "- Estimate affinity_delta between -1.0 and 1.0 and provide a brief relationship_note."
    )
