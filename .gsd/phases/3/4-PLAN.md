---
phase: 3
plan: 4
wave: 2
depends_on:
  - "1"
  - "2"
files_modified:
  - backend/agents/planner.py
  - backend/agents/agent.py
  - backend/tests/test_planner_and_agent.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`DailyPlanner` generates a wake-up day plan of 5–8 `DailyPlanItem` blocks at day start, lazily decomposes active blocks into `MinuteActionItem` steps, and replans remaining day blocks on interruption (`ReplanResponse`)"
    - "`canonicalize_location` maps LLM-returned location names cleanly onto `WorldMap.locations` with safe fallback to `persona.home_location` so `world.get_location(...)` never raises `KeyError`"
    - "`AgentBrain` coordinates `Perceive -> Remember -> Decide` with peer-sighting deduplication (no every-tick duplicate peer memories) and zero tight-loop planning LLM calls"
  artifacts:
    - "backend/agents/planner.py implements `canonicalize_location`, `MinuteStep`, `AgentPlanState`, and `DailyPlanner`"
    - "backend/agents/agent.py implements `PendingObservation` and `AgentBrain`"
    - "backend/tests/test_planner_and_agent.py verifies day-plan generation, lazy hourly/minute decomposition, location canonicalization, interruption replanning, and observation deduplication offline"
  key_links:
    - "backend/agents/planner.py calls `LLMGateway.generate_daily_plan`, `generate_replan`, and `generate_hourly_actions` with prompts from `llm.prompts.planning`"
    - "backend/agents/agent.py uses `DailyPlanner`, `MemoryRetriever`, and `MemoryStore` without calling LLMs on steady-state ticks"
---

# Plan 3.4: Hierarchical Daily Planner & AgentBrain Cognitive Loop

## Objective
Build the hierarchical planning module (`backend/agents/planner.py`) and per-agent cognitive coordinator (`backend/agents/agent.py`) implementing `Perceive -> Remember -> Decide` with wake-up 5–8 item daily planning, lazy hourly-to-minute decomposition, interruption replanning, location canonicalization, and perception deduplication.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/3/RESEARCH.md
- backend/agents/personas.py
- backend/llm/schemas.py
- backend/llm/gateway.py
- backend/llm/prompts/planning.py
- backend/memory/store.py
- backend/memory/retrieval.py
- backend/sim/clock.py
- backend/sim/world.py

## Tasks

<task type="auto">
  <name>Implement hierarchical DailyPlanner and location canonicalization in backend/agents/planner.py</name>
  <files>
    backend/agents/planner.py
  </files>
  <action>
    Create `backend/agents/planner.py` implementing the 3-level planning hierarchy (`DailyPlanResponse` -> `HourlyActionPlanResponse` -> `MinuteStep`) and interruption replanning.

    Steps:
    1. Implement `canonicalize_location(raw_location: str, world: WorldMap, fallback_location: str) -> str`:
       - Exact match against `world.locations`.
       - Normalized match (case-insensitive, spaces/hyphens/underscores collapsed).
       - Longest substring match against `world.locations` keys.
       - Fallback to `fallback_location` (asserted valid or first key in `world.locations`).
    2. Define `@dataclass` `MinuteStep` (`duration_minutes: int`, `location: str`, `action: str`, `start_tick: int`, `end_tick: int`, `arrived: bool = False`) and `@dataclass` `AgentPlanState`:
       - Fields: `day: int`, `daily_items: list[DailyPlanItem]`, `active_block_index: int = 0`, `minute_steps_by_block: dict[int, list[MinuteStep]] = field(default_factory=dict)`, `active_minute_index: int = 0`, `last_replan_tick: int = -100`.
       - Method `to_json(self) -> str`: serializes `daily_items` (plus decomposed `actions` per block if present) into a JSON list of dicts suitable for `AgentRecord.current_plan_json`.
       - Method `active_block(self) -> DailyPlanItem | None` and `current_step(self) -> MinuteStep | None`.
    3. Implement `DailyPlanner`:
       - `async def generate_daily_plan(self, persona: AgentPersona, *, clock: SimClock, world: WorldMap, llm_gateway: LLMGateway, retriever: MemoryRetriever | None = None, memory_store: MemoryStore | None = None) -> AgentPlanState`:
         - Retrieve top-k memories for planning goals if `retriever is not None`.
         - Build prompt via `build_daily_plan_prompt(...)`, call `await llm_gateway.generate_daily_plan(...)`.
         - Canonicalize all block locations against `world`, normalize `start_hour` / `end_hour` (`0 <= start_hour < end_hour <= 24`), sort chronologically.
         - If `memory_store is not None`, persist a `"plan"` memory (`importance=6`, `created_tick=clock.tick`) summarizing the daily plan.
         - Set `active_block_index` to the block matching `clock.hour` (or nearest upcoming block).
       - `async def replan_remaining_day(self, persona: AgentPersona, plan_state: AgentPlanState, *, reason: str, clock: SimClock, world: WorldMap, llm_gateway: LLMGateway, retriever: MemoryRetriever | None = None, memory_store: MemoryStore | None = None) -> AgentPlanState`:
         - Keep earlier blocks with `item.end_hour <= clock.hour`.
         - Retrieve context memories for `reason` if `retriever is not None`.
         - Build prompt via `build_replan_prompt(...)`, call `await llm_gateway.generate_replan(...)`.
         - Canonicalize locations, clamp `start_hour = max(clock.hour, item.start_hour)` and `end_hour = max(start_hour + 1, min(24, item.end_hour))`.
         - Merge prefix + replanned suffix, clear decomposed `minute_steps_by_block` for the replaced tail, update `active_block_index`, `active_minute_index = 0`, `last_replan_tick = clock.tick`.
         - Persist a `"plan"` memory (`importance=7`) if `memory_store is not None`.
       - `async def resolve_minute_step(self, persona: AgentPersona, plan_state: AgentPlanState, *, clock: SimClock, world: WorldMap, llm_gateway: LLMGateway, retriever: MemoryRetriever | None = None, dwell_ticks: int = 4) -> MinuteStep`:
         - Advance `active_block_index` when `clock.hour >= current_block.end_hour` and another block follows (or when current block's decomposed minute steps have finished and `clock.hour >= current_block.start_hour` allows advancing).
         - Lazily call `await llm_gateway.generate_hourly_actions(...)` ONLY when `active_block_index not in plan_state.minute_steps_by_block` (zero repeat LLM calls while executing steps within the same block!).
         - Keep the active `MinuteStep` pinned while `not step.arrived` (extending `end_tick = max(step.end_tick, clock.tick + 2)`) so agents finish walking before switching steps; upon arrival (`mark_arrived`), cap dwell duration to `min(step.duration_minutes, max(dwell_ticks, 8))` so simulated days progress briskly without getting stuck at one anchor.

    AVOID: Re-invoking `generate_daily_plan` or `generate_hourly_actions` on every tick, or calling `world.get_location` on raw LLM text without `canonicalize_location`.
    USE: Lazy per-block `minute_steps_by_block` caching and `canonicalize_location` everywhere a location string enters plan state.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check agents/planner.py
    .venv\Scripts\mypy.exe agents/planner.py
  </verify>
  <done>
    `backend/agents/planner.py` implements `DailyPlanner`, `AgentPlanState`, `MinuteStep`, and `canonicalize_location`, passing `ruff` and strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Implement AgentBrain cognitive loop coordinator in backend/agents/agent.py</name>
  <files>
    backend/agents/agent.py
  </files>
  <action>
    Create `backend/agents/agent.py` encapsulating per-agent `Perceive -> Remember -> Decide` coordination cleanly decoupled from `SimulationEngine` spatial mechanics.

    Steps:
    1. Define `@dataclass(frozen=True)` `PendingObservation`:
       - `agent_id: str`, `text: str`, `min_importance: int | None = None`, `trigger_replan: bool = False`, `reason: str = ""`.
    2. Implement `AgentBrain`:
       - Attributes: `agent_id: str`, `persona: AgentPersona`, `plan_state: AgentPlanState | None = None`, `pending_observations: list[PendingObservation] = []`, `accumulated_importance: int = 0`, `peer_seen_tick: dict[str, int] = {}`, `last_arrived_location: str | None = None`, `peer_perception_cooldown: int = 25`, `replan_cooldown: int = 10`.
       - `queue_observation(self, text: str, *, min_importance: int | None = None, trigger_replan: bool = False, reason: str = "") -> None`: appends a `PendingObservation` (used by god-mode events and arrival notifications).
       - `perceive(self, *, tick: int, current_location: str | None, nearby_peers: Sequence[tuple[str, str, str]]) -> list[PendingObservation]`:
         - Drains `self.pending_observations`.
         - For each `(peer_id, peer_name, peer_action)` in `nearby_peers`: if `tick - self.peer_seen_tick.get(peer_id, -999) >= self.peer_perception_cooldown`, records `self.peer_seen_tick[peer_id] = tick` and emits `"Saw {peer_name} nearby ({peer_action})"`.
         - Returns the collected observations for cross-agent batched importance rating and memory storage.
       - `record_importance(self, scores: Sequence[int], *, tick: int, observations: Sequence[PendingObservation]) -> tuple[bool, str]`:
         - Adds `sum(scores)` to `self.accumulated_importance`.
         - Returns `(should_replan, reason)` = `(True, reason)` if any observation had `trigger_replan=True` OR (`max(scores, default=0) >= 7` and `tick - last_replan_tick >= self.replan_cooldown`), else `(False, "")`.
       - `mark_arrived(self, *, location: str, tick: int, dwell_ticks: int) -> None`:
         - Updates `plan_state` active `MinuteStep.arrived = True` and sets `end_tick = tick + min(step.duration_minutes, max(dwell_ticks, 8))` if not already arrived; queues a lightweight arrival observation only if `location != self.last_arrived_location`.
       - `async def decide(self, *, clock: SimClock, world: WorldMap, planner: DailyPlanner, llm_gateway: LLMGateway, retriever: MemoryRetriever | None, memory_store: MemoryStore | None, needs_replan: bool, replan_reason: str, is_conversing: bool, dwell_ticks: int) -> tuple[str | None, str, bool]`:
         - If `is_conversing`: returns `(None, "", False)` (caller keeps conversation hold action).
         - If `self.plan_state is None or self.plan_state.day != clock.day`: generates `self.plan_state = await planner.generate_daily_plan(...)`.
         - Else if `needs_replan`: calls `self.plan_state = await planner.replan_remaining_day(...)` and returns `replanned=True`.
         - Resolves active `MinuteStep` via `await planner.resolve_minute_step(...)` and returns `(step.location, step.action, replanned)`.
       - `serialized_plan_json(self, fallback_routine: Sequence[str]) -> str`: returns `self.plan_state.to_json()` when `self.plan_state is not None`, else `json.dumps(list(fallback_routine))`.

    AVOID: Calling `LLMGateway` inside `perceive()` or firing LLM replans when `is_conversing` is True or within `replan_cooldown`.
    USE: Typed `PendingObservation` queues and deduplicated `peer_seen_tick` windows.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check agents/agent.py
    .venv\Scripts\mypy.exe agents/agent.py
  </verify>
  <done>
    `backend/agents/agent.py` cleanly coordinates `perceive`, `record_importance`, `mark_arrived`, `decide`, and `serialized_plan_json`, passing `ruff` and strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Add offline unit tests for DailyPlanner and AgentBrain</name>
  <files>
    backend/tests/test_planner_and_agent.py
  </files>
  <action>
    Create `backend/tests/test_planner_and_agent.py` testing every branch of `planner.py` and `agent.py` offline with `MockProvider` and an in-memory `Database`.

    Steps:
    1. Test `canonicalize_location`: exact match (`"Cafe"`), case/whitespace normalization (`"town square"`, `"home maya"`), substring match (`"near the Bakery"`), and unknown fallback (`"Space Station"` -> `"Home_Maya"`).
    2. Test `DailyPlanner.generate_daily_plan` at Day 1 `06:00`:
       - Verify 5–8 valid `DailyPlanItem` blocks, all locations valid in `WorldMap.locations`, and 1 `"plan"` memory saved to `MemoryStore`.
       - Verify `resolve_minute_step` calls `generate_hourly_actions` ONLY once when stepping through multiple ticks inside the same block (assert `gateway.get_usage_summary()["total_calls"]` does NOT grow on steady-state ticks!).
    3. Test `DailyPlanner.replan_remaining_day`:
       - Test mid-day interruption at `14:00` and late-evening interruption at `22:30` (`clock` advanced to 22:30), confirming valid `ReplanResponse` with `1 <= len(remaining) <= 8`, cleared minute cache on replaced blocks, and updated `"plan"` memory.
    4. Test `AgentBrain`:
       - Verify `perceive()` emits peer sighting on first encounter, deduplicates repeated sightings within `peer_perception_cooldown`, and emits again after cooldown elapses.
       - Verify `decide()` generates Day 1 plan on first call, executes `resolve_minute_step` on tick 2 with minimal calls, regenerates fresh plan when `clock` rolls over to Day 2 (`tick=1080`+ from `06:00`), and honors `serialized_plan_json()`.

    AVOID: Depending on wall-clock sleeps or external network calls.
    USE: `MockProvider(seed=42)`, `EmbeddingService.from_mode("mock")`, and `Database("sqlite+aiosqlite:///:memory:")`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_planner_and_agent.py
    .venv\Scripts\ruff.exe check agents tests/test_planner_and_agent.py
    .venv\Scripts\mypy.exe agents tests/test_planner_and_agent.py
  </verify>
  <done>
    All tests in `tests/test_planner_and_agent.py` pass offline, confirming 5–8 day items, lazy minute decomposition, zero tight-loop LLM calls, late-day replanning, and peer perception deduplication.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `DailyPlanner` generates 5–8 item day plans, lazily decomposes hourly blocks into minute steps, and replans remaining day safely even at late hours
- [ ] `canonicalize_location` prevents any unknown location string from crashing `WorldMap.get_location`
- [ ] `AgentBrain` deduplicates nearby peer observations and avoids tight-loop LLM calls

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] `ruff` and strict `mypy` pass across `backend/agents` and `tests/test_planner_and_agent.py`
