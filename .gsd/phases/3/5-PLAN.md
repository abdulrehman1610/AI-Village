---
phase: 3
plan: 5
wave: 2
depends_on:
  - "1"
  - "2"
files_modified:
  - backend/agents/conversation.py
  - backend/tests/test_conversation.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`ConversationManager` selects disjoint pairs of free agents within Manhattan distance `<= 2` whose cooldown has elapsed"
    - "Dual cooldowns (`CONVERSATION_COOLDOWN_TICKS = 60` after dialogue, `DECLINE_COOLDOWN_TICKS = 30` after `initiate=False`) prevent tight-loop LLM spam between adjacent stationary agents"
    - "Completed dialogues run `<= 6` turns grounded in retrieved top-k (`k=8`) memories, persist a `ConversationRecord`, write `"conversation"` memories for both participants, update pairwise `RelationshipRecord` affinity, set `conversation_hold_ticks`, and build a WS `dialogue` payload"
    - "Multi-hop rumor propagation works deterministically offline (`Event -> Agent A -> Agent B -> Agent C`)"
  artifacts:
    - "backend/agents/conversation.py implements `DialogueParticipant` protocol, `DialogueOutcome`, and `ConversationManager`"
    - "backend/tests/test_conversation.py tests proximity eligibility, cooldown gating, <=6 turn cap, DB/memory/relationship persistence, and 2-hop rumor propagation"
  key_links:
    - "backend/agents/conversation.py uses `MemoryRetriever.retrieve`, `MemoryStore.add_conversation` / `add_memories_batch` / `get_relationship` / `upsert_relationship`, and `LLMGateway` dialogue helpers"
---

# Plan 3.5: Proximity Conversation Manager & Multi-Hop Rumor Propagation

## Objective
Implement `backend/agents/conversation.py` (`ConversationManager`) so pairs of free agents within 2 Manhattan tiles whose pair cooldown has elapsed evaluate memory-grounded initiation, hold a `<= 6`-turn conversation, persist `ConversationRecord` + dual `conversation` memories + pairwise relationship affinity updates, and emit structured WebSocket `dialogue` payloads.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/3/RESEARCH.md
- backend/agents/personas.py
- backend/llm/gateway.py
- backend/llm/prompts/conversation.py
- backend/memory/store.py
- backend/memory/retrieval.py
- backend/sim/world.py

## Tasks

<task type="auto">
  <name>Implement ConversationManager in backend/agents/conversation.py</name>
  <files>
    backend/agents/conversation.py
  </files>
  <action>
    Create `backend/agents/conversation.py` with clean structural typing (`DialogueParticipant` `Protocol`) so it integrates seamlessly with `AgentEntity` without circular imports.

    Steps:
    1. Define constants (`PROXIMITY_TILES = 2`, `MAX_DIALOGUE_TURNS = 6`, `CONVERSATION_COOLDOWN_TICKS = 60`, `DECLINE_COOLDOWN_TICKS = 30`) and `DialogueParticipant(Protocol)` requiring attributes: `id: str`, `name: str`, `persona: AgentPersona`, `x: int`, `y: int`, `target_location: str | None`, `current_action: str`, `conversation_hold_ticks: int`, `needs_replan: bool`, `replan_reason: str`.
    2. Define `@dataclass(frozen=True)` `DialogueOutcome`:
       - `participants: tuple[str, str]`, `participant_names: tuple[str, str]`, `location: str | None`, `turns: list[dict[str, str]]`, `summary: str`, `importance: int`, `affinity_delta: float`, `ws_payload: dict[str, Any]`.
    3. Implement `ConversationManager`:
       - `__init__(self, *, llm_gateway: LLMGateway, memory_store: MemoryStore, retriever: MemoryRetriever | None = None, proximity_tiles: int = 2, max_turns: int = 6, conversation_cooldown_ticks: int = 60, decline_cooldown_ticks: int = 30)`: tracks `self.pair_cooldown_until: dict[tuple[str, str], int] = {}`.
       - `can_converse(self, agent_a: DialogueParticipant, agent_b: DialogueParticipant, *, tick: int) -> bool`: verifies `agent_a.id != agent_b.id`, `agent_a.conversation_hold_ticks == 0`, `agent_b.conversation_hold_ticks == 0`, `abs(agent_a.x - agent_b.x) + abs(agent_a.y - agent_b.y) <= self.proximity_tiles`, and `tick >= self.pair_cooldown_until.get(tuple(sorted((agent_a.id, agent_b.id))), 0)`.
       - `select_candidate_pairs(self, agents: Sequence[DialogueParticipant], *, tick: int) -> list[tuple[DialogueParticipant, DialogueParticipant]]`: sorts by `agent.id`, greedily matches each unmatched free agent to its closest eligible neighbor so every agent participates in at most one dialogue per tick.
       - `async def run_conversation(self, agent_a: DialogueParticipant, agent_b: DialogueParticipant, *, tick: int, sim_time: str, world: WorldMap) -> DialogueOutcome | None`:
         1. Resolve nearest location label within `<= 4` tiles of `loc.anchor` (else `agent_a.target_location` or `"Village"`).
         2. Retrieve top-k memories (`k=8`) for `agent_a` and `agent_b` via `self.retriever.retrieve(...)` when `retriever` is attached.
         3. Call `await self.llm_gateway.decide_conversation(...)` with `build_conversation_decision_prompt(...)`.
         4. If `not decision.initiate`: set `self.pair_cooldown_until[pair] = tick + self.decline_cooldown_ticks` and return `None`.
         5. Generate up to `self.max_turns` (`<= 6`) turns:
            - Turn 0 uses `decision.opening_line.strip()` if non-empty, else `generate_dialogue_turn(...)` for `agent_a`.
            - Alternate `agent_b`, `agent_a`, ... calling `generate_dialogue_turn(...)` with speaker's memories and running `(speaker_name, text)` transcript; stop early if `not turn_resp.continue_dialogue and len(turns) >= 2`.
         6. Summarize via `await self.llm_gateway.summarize_conversation(...)` and rate importance via `await self.llm_gateway.rate_importance_batch([summary_resp.summary], tick=tick, agent_id=agent_a.id)`.
         7. Persist:
            - `await self.memory_store.add_conversation(tick_start=tick, participants=[agent_a.id, agent_b.id], turns=turns, summary=summary_resp.summary)`
            - `await self.memory_store.add_memories_batch(...)` saving `MemoryCreate(agent_id=agent_a.id, memory_type="conversation", text=f"Conversation with {agent_b.name}: {summary_resp.summary}", importance=importance, created_tick=tick)` and symmetric record for `agent_b`.
            - Update canonical pairwise relationship `(id_1, id_2) = tuple(sorted((agent_a.id, agent_b.id)))`: read existing via `get_relationship`, clamp `affinity` to `[-1.0, 1.0]`, and `upsert_relationship(...)`.
         8. Set `self.pair_cooldown_until[pair] = tick + self.conversation_cooldown_ticks`, set `conversation_hold_ticks = min(max(2, len(turns)), 4)` and `current_action = f"Talking with {peer.name}"` on both participants, and if `importance >= 7` mark `needs_replan = True` and `replan_reason = summary_resp.summary` on both participants.
         9. Return `DialogueOutcome` with `ws_payload = {"type": "dialogue", "tick": tick, "sim_time": sim_time, "participants": [agent_a.id, agent_b.id], "participant_names": [agent_a.name, agent_b.name], "location": location_label, "turns": turns, "summary": summary_resp.summary}`.

    AVOID: Importing `AgentEntity` from `sim.engine` (would create circular imports) or allowing unbounded loops (`len(turns)` must never exceed `max_turns`).
    USE: `DialogueParticipant` `Protocol` and dual initiate/decline cooldown maps.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check agents/conversation.py
    .venv\Scripts\mypy.exe agents/conversation.py
  </verify>
  <done>
    `backend/agents/conversation.py` passes `ruff` and strict `mypy` with zero circular imports and full cooldown/memory/relationship support.
  </done>
</task>

<task type="auto">
  <name>Add offline unit tests for ConversationManager and 2-hop rumor propagation</name>
  <files>
    backend/tests/test_conversation.py
  </files>
  <action>
    Create `backend/tests/test_conversation.py` testing proximity selection, cooldown gating, decline cooldown, `<= 6` turn limit, DB/memory/relationship updates, and 2-hop rumor transfer offline.

    Steps:
    1. Define a lightweight `@dataclass` `_FakeParticipant` matching `DialogueParticipant` and initialize `WorldMap`, `:memory:` `Database`, `MemoryStore`, `MemoryRetriever`, and `LLMGateway(provider=MockProvider(seed=42), db=db)`. Seed `AgentRecord` rows for `maya`, `liam`, and `elena`.
    2. Test proximity & hold eligibility:
       - Distance 3 returns `[]` from `select_candidate_pairs`; distance 2 returns `[(maya, liam)]`.
       - Agents with `conversation_hold_ticks > 0` are excluded.
       - When 3 agents stand adjacent, `select_candidate_pairs` returns disjoint pairs (at most 1 pair for 3 agents).
    3. Test decline cooldown (`initiate=False`):
       - Use a `ScriptedProvider` or custom fake returning `ConversationDecisionResponse(initiate=False, ...)` at tick 10; confirm `run_conversation` returns `None`, `select_candidate_pairs` excludes that pair at tick 11 and tick 39, and allows re-check at tick 40 (`10 + 30`).
    4. Test completed conversation + 2-hop rumor propagation (`MockProvider`):
       - Seed `maya` with observation `"[EVENT] at Bakery: A fire broke out near the ovens"` (`importance=9`, `created_tick=5`).
       - Run `run_conversation(maya, liam, tick=10, sim_time="Day 1 06:10", world=world)`.
       - Assert `outcome is not None`, `2 <= len(outcome.turns) <= 6`, `outcome.ws_payload["type"] == "dialogue"`, `"fire"` appears in turns and summary, `MemoryStore.list_conversations()` has 1 row, both `maya` and `liam` have a `"conversation"` memory containing `"fire"`, `get_relationship("maya", "liam")` exists, and `select_candidate_pairs` respects `CONVERSATION_COOLDOWN_TICKS = 60` (blocked at tick 69, allowed at tick 70).
       - Move `liam` next to `elena` at tick 15 and call `run_conversation(liam, elena, tick=15, ...)`; assert `elena`'s persisted `"conversation"` memory now contains `"fire"` (2-hop rumor spread!).

    AVOID: Network requests or external DB files.
    USE: In-memory SQLite + `MockProvider` / `ScriptedProvider`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_conversation.py
    .venv\Scripts\ruff.exe check agents/conversation.py tests/test_conversation.py
    .venv\Scripts\mypy.exe agents/conversation.py tests/test_conversation.py
  </verify>
  <done>
    All tests in `tests/test_conversation.py` pass offline, proving proximity gating, dual cooldowns, `<= 6` turn dialogue, SQLite persistence, and deterministic 2-hop rumor propagation.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `ConversationManager` enforces proximity `<= 2` tiles, free state, and both `CONVERSATION_COOLDOWN_TICKS` and `DECLINE_COOLDOWN_TICKS`
- [ ] Dialogues cap at `<= 6` turns, ground turns in retrieved top-8 memories, save `ConversationRecord` + symmetric `"conversation"` memories + relationship affinity, and return a WS `dialogue` payload
- [ ] Injected event rumors propagate across 2 hops (`A -> B -> C`) offline with `MockProvider`

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] `ruff` and strict `mypy` pass with zero errors
