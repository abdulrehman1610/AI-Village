---
phase: 4
plan: 6
wave: 3
depends_on:
  - "4"
files_modified:
  - backend/sim/engine.py
  - backend/app/main.py
  - backend/tests/test_engine.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`SimulationEngine` accumulates importance across observations, plans/replans, god-mode events, and conversations; triggers `ReflectionManager` at end of `_run_cognitive_phase()` when `accumulated_importance >= reflection_threshold`; resets the accumulator; updates `AgentEntity.mood` and `AgentBrain.mood`; and emits `reflection` WS frames after `_step_lock` releases"
    - "`SimulationEngine` exposes `start_simulation()`, `pause_simulation()`, and `set_simulation_speed(speed)` backed by an interruptible `asyncio.Event` in `_run_loop()` and immediate live `TickPayload` broadcasts (overlaying live `speed`/`running` even mid-step)"
    - "`AgentSnapshot.mood` is included on every `TickPayload` and `AgentRecord.mood` is persisted on initialization and every tick without altering `current_plan_json` list format"
    - "`backend/app/main.py` passes `reflection_threshold=resolved_settings.reflection_threshold` to `SimulationEngine` and `running=resolved_settings.sim_auto_start` to `SimClock`"
  artifacts:
    - "backend/sim/engine.py integrates `ReflectionManager`, `mood`, `reflection_threshold`, `_wake_event`, `start_simulation`, `pause_simulation`, `set_simulation_speed`, and `broadcast_current_tick`"
    - "backend/app/main.py configures `SimClock(running=resolved_settings.sim_auto_start, ...)` and `SimulationEngine(..., reflection_threshold=resolved_settings.reflection_threshold)`"
    - "backend/tests/test_engine.py tests reflection triggering, accumulator reset, mood persistence, and interruptible time controls offline"
  key_links:
    - "backend/sim/engine.py connects `ReflectionManager` (`agents.reflection`) and `AgentBrain` (`agents.agent`) inside `_run_cognitive_phase()`"
    - "backend/sim/engine.py broadcasts `reflection` frames through `_emit_event_payload` and updated `TickPayload` frames through `_tick_callbacks`"
---

# Plan 4.6: SimulationEngine Reflection Integration & Interruptible Time Controls

## Objective
Integrate `ReflectionManager`, agent `mood` synchronization, and interruptible simulation time controls (`start_simulation`, `pause_simulation`, `set_simulation_speed` with `asyncio.Event` wakeup and immediate `TickPayload` broadcasts) into `SimulationEngine` (`backend/sim/engine.py`) and `backend/app/main.py` (`REQ-09`, `REQ-11`, `REQ-12`, `NFR-01`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/4/RESEARCH.md
- backend/app/config.py
- backend/app/main.py
- backend/sim/clock.py
- backend/sim/engine.py
- backend/agents/agent.py
- backend/agents/conversation.py
- backend/agents/reflection.py
- backend/memory/store.py
- backend/tests/test_engine.py

## Tasks

<task type="auto">
  <name>Wire reflection pipeline, mood sync, and interruptible time controls in SimulationEngine</name>
  <files>
    backend/sim/engine.py
  </files>
  <action>
    Update `backend/sim/engine.py` to execute threshold-triggered reflections, persist/broadcast agent `mood`, and support instantaneous start/pause/speed transitions via an interruptible `asyncio.Event`.

    Steps:
    1. Import `ReflectionManager` from `agents.reflection`.
    2. Extend `AgentSnapshot` and `AgentEntity` with `mood: str = "calm"` (and pass `mood=self.mood` in `AgentEntity.to_snapshot()`).
    3. Update `SimulationEngine.__init__`:
       - Accept keyword-only `reflection_threshold: int = 150` (reject `bool` or `< 1` with `ValueError`).
       - Store `self.reflection_threshold = reflection_threshold`.
       - Pass `reflection_threshold=reflection_threshold` when constructing each `AgentBrain(...)`.
       - Construct `self.reflection_manager: ReflectionManager | None` when `llm_gateway is not None and memory_store is not None` with `reflection_threshold=reflection_threshold`.
       - Add `self._wake_event = asyncio.Event()` for instant loop wakeups.
    4. Update persistence methods:
       - In `initialize_persistence()`: include `mood=agent.mood` in `AgentRecord(...)`.
       - In `persist_tick_state()`: build `moods = {agent.id: agent.mood for agent in self.agents.values()}` and call `await self.memory_store.update_agent_states(states, moods=moods)`.
    5. Wire importance + mood + reflection in cognitive loop:
       - In `inject_event`: when `affected_agents` receive a witness observation (`importance=8`), also call `self.brains[agent_id].add_importance(8)` (keeping `current_plan_json` and `needs_replan` untouched).
       - In `_run_conversations`: for each non-None `outcome`, add `outcome.importance` to `self.brains[pid].add_importance(outcome.importance)` for both participants, and update `self.agents[pid].mood = mood` and `self.brains[pid].mood = mood` from `outcome.moods`.
       - Add `async def _run_reflections(self) -> list[dict[str, Any]]`:
         - If `self.reflection_manager is None`, return `[]`.
         - Identify `qualifying_ids = [aid for aid in sorted(self.agents) if self.brains[aid].should_reflect()]`.
         - If empty, return `[]`.
         - Run `outcomes = await asyncio.gather(*(self.reflection_manager.run_reflection(agent_id=aid, persona=self.agents[aid].persona, tick=self.clock.tick, sim_time=self.clock.sim_time_str) for aid in qualifying_ids))`.
         - For each `aid, outcome` in `zip(qualifying_ids, outcomes, strict=True)`: if `outcome is not None`:
           - `self.brains[aid].reset_reflection_counter(tick=self.clock.tick)`
           - `self.brains[aid].mood = outcome.mood`
           - `self.agents[aid].mood = outcome.mood`
           - extend `payloads` with `outcome.ws_payloads`.
         - Return `payloads`.
       - In `_run_cognitive_phase`: run `dialogue_payloads = await self._run_conversations()`, `await self._decide_actions(gateway)`, and `reflection_payloads = await self._run_reflections()`, returning `dialogue_payloads + reflection_payloads`.
    6. Wire interruptible time controls and broadcasts:
       - Add `def _current_control_tick_payload(self) -> TickPayload`: uses `self.build_tick_payload()` and if `self._stepping` overlays live `speed=self.clock.speed, running=self.clock.running` via `model_copy(update=...)`.
       - Add `async def _broadcast_tick_payload(self, payload: TickPayload) -> None` shared by `step_once()` and control helpers (removing duplicate callback try/except loops!).
       - Add `async def _persist_clock_state(self) -> None` and control methods:
         - `async def start_simulation(self) -> TickPayload`: `self.clock.start()`, `await self.start_loop()`, `self._wake_event.set()`, `await self._persist_clock_state()`, build & broadcast `payload = self._current_control_tick_payload()`, return `payload`.
         - `async def pause_simulation(self) -> TickPayload`: `self.clock.pause()`, `self._wake_event.set()`, `await self._persist_clock_state()`, build & broadcast `payload = self._current_control_tick_payload()`, return `payload`.
         - `async def set_simulation_speed(self, speed: int) -> TickPayload`: `self.clock.set_speed(speed)`, `self._wake_event.set()`, `await self._persist_clock_state()`, build & broadcast `payload = self._current_control_tick_payload()`, return `payload`.
       - Update `stop_loop()` to set `self._stop_requested = True` and `self._wake_event.set()` before cancelling `_loop_task`.
       - Update `_run_loop()` to clear `self._wake_event.clear()` at the top of each iteration before checking `self.clock.running` and await `asyncio.wait_for(self._wake_event.wait(), timeout=timeout)` only when `not self._wake_event.is_set()` (using `self.clock.tick_interval_seconds` when running and `0.25` when paused).

    AVOID: Clearing `_wake_event` AFTER `step_once()` (which could drop a wake signal fired mid-step), running reflections outside `_step_lock`, or calling `_emit_event_payload` inside `_step_lock`.
    USE: Top-of-loop `_wake_event.clear()`, `asyncio.gather` in `_run_reflections`, and shared `_broadcast_tick_payload` outside `_step_lock`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check sim/engine.py
    .venv\Scripts\mypy.exe sim/engine.py
  </verify>
  <done>
    `SimulationEngine` executes threshold-triggered reflections, tracks/persists agent `mood`, and handles instant start/pause/speed control with live broadcasts, passing `ruff` and strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Update FastAPI lifespan in main.py and expand engine tests for reflections and time controls</name>
  <files>
    backend/app/main.py
    backend/tests/test_engine.py
  </files>
  <action>
    Wire `reflection_threshold` and `sim_auto_start` clock alignment in `backend/app/main.py`, and add offline unit tests to `backend/tests/test_engine.py`.

    Steps:
    1. In `backend/app/main.py`:
       - Pass `running=resolved_settings.sim_auto_start` when creating `SimClock(...)`.
       - Pass `reflection_threshold=resolved_settings.reflection_threshold` when creating `SimulationEngine(...)`.
    2. In `backend/tests/test_engine.py`:
       - Add `test_engine_triggers_reflection_at_threshold_and_resets_counter`:
         - Construct `SimulationEngine` with `:memory:` DB, `MockProvider(seed=42)`, and `reflection_threshold=30` (plus a quick boundary check at default `150`!).
         - Capture emitted event payloads via `register_event_callback`.
         - Pre-load or inject observations/steps until Maya's `accumulated_importance` reaches `>= reflection_threshold`, step tick(s), and verify:
           - At least one `"reflection"` payload was emitted (`type == "reflection"`, `agent_id == "maya"`, non-empty `insight` and `cited_memory_ids`).
           - `"reflection"` memory exists in `memory_store.list_memories("maya", memory_type="reflection")` with `importance == 8` and valid `cited_memory_ids` in `metadata_json`.
           - `engine.brains["maya"].accumulated_importance < 30` (reset cleanly!) and `engine.agents["maya"].mood` / persisted `AgentRecord.mood` updated cleanly.
       - Add `test_engine_time_controls_wake_loop_and_broadcast_immediately`:
         - Construct `SimulationEngine` with `clock=SimClock(speed=1, running=False, base_tick_seconds=2.0)`.
         - Capture tick callbacks, call `await engine.start_loop()`, call `pause_simulation()` / `set_simulation_speed(16)` / `start_simulation()`, and assert within `< 0.5s` (not waiting `2.0s`!) that `clock.running` / `clock.speed` updated, live `TickPayload` callbacks fired immediately, and ticks advance smoothly at `16x`, then `await engine.stop_loop()`.

    AVOID: Modifying existing Phase 1/2/3 assertions in `test_engine.py` (`test_engine_150_ticks_spatial_invariants` and `test_engine_persists_agents_memories_and_sim_state`).
    USE: Short timeouts (`base_tick_seconds=2.0` vs `< 0.5s` wakeup check) to prove `_wake_event` interrupts slow `1x` sleeps instantaneously.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_engine.py tests/test_phase3_integration.py
    .venv\Scripts\ruff.exe check sim/engine.py app/main.py tests/test_engine.py
    .venv\Scripts\mypy.exe sim/engine.py app/main.py tests/test_engine.py
  </verify>
  <done>
    All tests in `test_engine.py` and `test_phase3_integration.py` pass offline with zero regressions, confirming threshold reflection and instant interruptible time controls under `ruff` + `mypy`.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `SimulationEngine` executes `ReflectionManager` at threshold, resets accumulator, syncs `mood`, and emits `reflection` WS payloads
- [ ] `start_simulation`, `pause_simulation`, and `set_simulation_speed` wake `_run_loop()` immediately and broadcast updated `TickPayload`
- [ ] `backend/app/main.py` initializes `SimClock.running` from `sim_auto_start` and wires `reflection_threshold`
- [ ] Zero regressions in `test_engine.py` and `test_phase3_integration.py`

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] `pytest`, `ruff`, and strict `mypy` pass cleanly
