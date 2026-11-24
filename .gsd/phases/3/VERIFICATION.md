---
phase: 3
verified: 2026-11-24T15:58:30+05:00
status: gaps_found
score: 5/7 must-haves verified
is_re_verification: false
gaps:
  - truth: "MockProvider deterministically generates ReplanResponse, HourlyActionPlanResponse, and rumor-propagating dialogue/summaries without false-positive urgent keyword collisions from seeded persona bios"
    status: failed
    reason: "SimulationEngine.initialize_persistence() persists agent.persona.summary_text() as an observation memory; Maya's bio contains 'fire the village ovens', which MemoryRetriever injects into Context memories: and MockProvider._extract_salient_topic() matches via _URGENT_KEYWORD_PATTERN, hijacking baseline dialogues with Maya's bio"
    artifacts:
      - path: "backend/agents/personas.py"
        issue: "Maya's bio ('fire the village ovens') contains the urgent keyword 'fire'"
      - path: "backend/llm/providers/mock.py"
        issue: "_extract_salient_topic() and _build_importance_batch() do not exclude seeded persona summary/goal memories inside Context memories:"
      - path: "backend/tests/test_llm_gateway.py"
        issue: "test_mock_provider_rumor_propagation_and_neutral_persona_guard passes routine strings instead of maya.summary_text() in memories=[]"
    missing:
      - "Neutralize 'fire' in Maya's seeded bio in backend/agents/personas.py"
      - "Skip seeded persona summary/goal lines inside _extract_salient_topic() and _build_importance_batch() in backend/llm/providers/mock.py"
      - "Add regression test in backend/tests/test_llm_gateway.py passing maya.summary_text() inside memories=[]"
  - truth: "SimulationEngine executes baseline cognitive planning, conversations, and event-driven replanning cleanly without spontaneous false-positive replans"
    status: failed
    reason: "In an empirical 80-tick baseline SimulationEngine run with MockProvider(seed=42) and zero injected events, 11/12 dialogues repeated Maya's truncated bio ('...discussed: Maya (age 28, Baker)...') and triggered 16 spontaneous replans across 6/8 agents (explicitly deferred in 6-SUMMARY.md), forcing test_phase3_integration.py to weaken plan length assertions from 5..8 to 1..8"
    artifacts:
      - path: "backend/tests/test_phase3_integration.py"
        issue: "Line 131 relaxes parsed_plan length to 1..8 and does not assert zero spontaneous replans when zero events are injected"
    missing:
      - "Restore strict 5..8 block and zero-spontaneous-replan assertions in test_engine_80_ticks_cognitive_loop_and_dialogue after fixing personas.py and mock.py"
---

# Phase 3 Verification

## Summary

- **Phase Goal:** Wire the complete agent cognitive loop (Perceive → Remember → Decide) with hierarchical planning (wake-up day plan → hourly blocks → minute actions + replanning on interruption), proximity-triggered turn-by-turn agent conversations (up to 6 turns + memory summarization + WS `dialogue` broadcast), and god-mode event injection (`POST /events` + frontend UI bar) that delivers observations to nearby agents and spreads rumors.
- **Result:** **5/7** consolidated Phase 3 must-haves verified; **2 failed** due to a confirmed false-positive rumor/replan cascade from Maya's seeded persona bio (`"fire the village ovens"`) that was deferred in `6-SUMMARY.md` and confirmed empirically in an 80-tick `SimulationEngine` run.
- **Requirements Covered:** `REQ-06` (Partial/Gap), `REQ-07` (Partial/Gap), `REQ-08` (Satisfied), `NFR-01` (Satisfied), `NFR-02` (Partial/Gap), `NFR-03` (Satisfied), `NFR-04` (Satisfied), `NFR-05` (Satisfied), plus constraints `CON-01`–`CON-05`.
- **Gap Closure Plan:** [.gsd/phases/3/8-PLAN.md](file:///d:/Experiments%20with%20AI/AI%20Village/.gsd/phases/3/8-PLAN.md) (`gap_closure: true`).

---

## Must-Haves

### Truths

| Truth | Status | Evidence |
|-------|--------|----------|
| 1. Strict LLM planning/dialogue schemas (`ReplanResponse`, `MinuteActionItem`, `HourlyActionPlanResponse`), typed `LLMGateway` helpers (`action_decomposition` → `routine_model`), neutral prompt templates, and deterministic `MockProvider` free of false-positive persona bio triggers | ✗ FAILED | `backend/llm/schemas.py`, `backend/llm/gateway.py`, and `backend/llm/prompts/` pass `ruff`, strict `mypy`, and `test_llm_gateway.py` (10/10). **However**, `MockProvider._extract_salient_topic()` scans bulleted `Context memories:` lines and matches `"fire"` in Maya's seeded `persona.summary_text()` memory (`"Maya wakes before dawn to fire the village ovens..."`), causing `MockProvider` to treat Maya's bio as an urgent event whenever `MemoryRetriever` returns it (`test_mock_provider_rumor_propagation_and_neutral_persona_guard` omitted `maya.summary_text()` from `memories=[]`). |
| 2. `MemoryStore` persists and queries `ConversationRecord` (with exact participant ID filtering), newest-first `EventRecord` entries (`since_tick`/`limit`), and symmetric `RelationshipRecord` lookups | ✓ VERIFIED | [backend/memory/store.py](file:///d:/Experiments%20with%20AI/AI%20Village/backend/memory/store.py#L315-L401) implements `get_relationship`, `list_events`, `add_conversation`, and `list_conversations` (parsing `json.loads(row.participants)` for exact membership). `tests/test_store_phase3.py` (4/4) verified ordering, limits, `"sam"` vs `"samuel"` non-collision, and symmetric lookup against `:memory:` SQLite. |
| 3. Frontend Phase 3 TypeScript contracts, runtime type guards (`isDialogueMessage`, `isEventMessage`), `VillageWsClient` dispatch, `apiClient` (`fetchWorld`, `injectEvent`), and Vite `/events` proxy operate safely | ✓ VERIFIED | [frontend/src/types/sim.ts](file:///d:/Experiments%20with%20AI%20Village/frontend/src/types/sim.ts#L49-L191) exports and validates `DialogueMessage`, `EventMessage`, `InjectEventRequest`, and `InjectEventResponse`; [frontend/src/net/wsClient.ts](file:///d:/Experiments%20with%20AI%20Village/frontend/src/net/wsClient.ts#L85-L92) routes `tick`/`dialogue`/`event`; [frontend/src/net/apiClient.ts](file:///d:/Experiments with AI/AI Village/frontend/src/net/apiClient.ts) implements `fetchWorld()` and `injectEvent()`; [frontend/vite.config.ts](file:///d:/Experiments%20with%20AI%20Village/frontend/vite.config.ts#L24-L27) proxies `/events`. `tsc --noEmit` and `vite build` exited 0. |
| 4. Hierarchical `DailyPlanner` (5–8 wake-up plan, lazy minute decomposition, late-hour safe replanning, `canonicalize_location`) and `AgentBrain` perception deduplication run with zero tight-loop LLM calls | ✓ VERIFIED | [backend/agents/planner.py](file:///d:/Experiments%20with%20AI%20Village/backend/agents/planner.py) and [backend/agents/agent.py](file:///d:/Experiments%20with%20AI/AI%20Village/backend/agents/agent.py) pass `ruff`, strict `mypy`, and `tests/test_planner_and_agent.py` (6/6), proving 5–8 block plans, single-call lazy block decomposition (`total_calls == 2` across 12+ walking/dwelling ticks), safe hour `22:30` replans, location canonicalization, and `peer_perception_cooldown` deduplication. |
| 5. Proximity `ConversationManager` enforces `<= 2` Manhattan tiles, free status, dual cooldowns (`60` / `30`), `<= 6` turns grounded in top-8 memories, SQLite/relationship persistence, and 2-hop rumor propagation | ✓ VERIFIED | [backend/agents/conversation.py](file:///d:/Experiments%20with%20AI%20Village/backend/agents/conversation.py) implements `DialogueParticipant`, `select_candidate_pairs`, `can_converse`, and `run_conversation`. `tests/test_conversation.py` (5/5) proved proximity gating, `DECLINE_COOLDOWN_TICKS=30`, `CONVERSATION_COOLDOWN_TICKS=60`, `MAX_DIALOGUE_TURNS=6`, relationship clamping, and 2-hop `Maya -> Liam -> Elena` rumor spread. |
| 6. `SimulationEngine` cognitive loop integration, `POST /events`, live `/ws` `dialogue`/`event`/`tick` broadcasts, and clean 80-tick baseline cognitive behavior | ✗ FAILED | `POST /events` (`422` blank, `400` unknown location, `200` global/radius), `ws` broadcasts, `EventRecord`/witness persistence, spatial invariants (0 overlaps, 0 wall collisions), and 2-hop storm propagation pass in `tests/test_phase3_integration.py` (3/3) and live `uvicorn` testing (`live_phase3_ok`). **However**, an 80-tick baseline `SimulationEngine` run with zero injected events produced **11/12 dialogues** repeating Maya's truncated bio (`"Maya and Noah discussed: Maya (age 28, Baker)..."`) and triggered **16 spontaneous replans across 6/8 agents** (`maya`: 3, `liam`: 2, `elena`: 3, `noah`: 4, `clara`: 1, `marcus`: 3), forcing `test_phase3_integration.py:131` to relax `5..8` plan length down to `1..8`. Explicitly deferred in `6-SUMMARY.md`. |
| 7. Frontend `VillageScene` `depth >= 60` speaker-tracking speech bubbles, event location pulses/banners, input-guarded `keydown-C`, safe-DOM `ActivityFeed`, and `#god-mode-bar` `EventInjector` | ✓ VERIFIED | [frontend/src/scenes/VillageScene.ts](file:///d:/Experiments%20with%20AI%20Village/frontend/src/scenes/VillageScene.ts#L37-L386) renders speech bubbles at `depth = 60` tracking speakers in `update()`, event pulse rings (`depth = 55`) and banners (`depth = 65`), and guards `keydown-C` + `setKeyboardEnabled`; [frontend/src/ui/activityFeed.ts](file:///d:/Experiments%20with%20AI%20Village/frontend/src/ui/activityFeed.ts) uses `textContent` (no `innerHTML`); [frontend/src/ui/eventInjector.ts](file:///d:/Experiments%20with%20AI%20Village/frontend/src/ui/eventInjector.ts) + [frontend/src/main.ts](file:///d:/Experiments%20with%20AI%20Village/frontend/src/main.ts) wire `fetchWorld`, `injectEvent`, and WS callbacks. `tsc --noEmit`, `vite build`, and built `frontend/dist/index.html` DOM IDs verified. (Visual canvas check remains flagged for human review.) |

---

### Artifacts

| Path | Exists | Substantive | Wired | Notes |
|------|--------|-------------|-------|-------|
| `backend/llm/schemas.py` | ✓ | ✓ | ✓ | Adds `ReplanResponse`, `MinuteActionItem`, `HourlyActionPlanResponse` (`extra="forbid"`) |
| `backend/llm/gateway.py` | ✓ | ✓ | ✓ | Exposes all 6 typed planning/dialogue helpers; `action_decomposition` routes to `routine_model` |
| `backend/llm/prompts/__init__.py` | ✓ | ✓ | ✓ | Exports all 6 planning & conversation prompt builders |
| `backend/llm/prompts/planning.py` | ✓ | ✓ | ✓ | Pure typed builders (`build_daily_plan_prompt`, `build_hourly_action_prompt`, `build_replan_prompt`) |
| `backend/llm/prompts/conversation.py` | ✓ | ✓ | ✓ | Pure typed builders (`build_conversation_decision_prompt`, `build_dialogue_turn_prompt`, `build_conversation_summary_prompt`) |
| `backend/llm/providers/mock.py` | ✓ | ⚠️ | ✓ | Implements `ReplanResponse`, `HourlyActionPlanResponse`, rumor preservation, **but** `_extract_salient_topic` triggers on Maya's seeded bio memory |
| `backend/agents/personas.py` | ✓ | ⚠️ | ✓ | Defines 8 valid personas; Maya's `bio` contains `"fire the village ovens"` which collides with `MockProvider` urgent-keyword scan |
| `backend/memory/store.py` | ✓ | ✓ | ✓ | Adds `get_relationship`, `list_events`, `add_conversation`, `list_conversations` |
| `backend/agents/planner.py` | ✓ | ✓ | ✓ | Implements `canonicalize_location`, `MinuteStep`, `AgentPlanState`, `DailyPlanner` |
| `backend/agents/agent.py` | ✓ | ✓ | ✓ | Implements `PendingObservation`, `AgentBrain` |
| `backend/agents/conversation.py` | ✓ | ✓ | ✓ | Implements `DialogueParticipant`, `DialogueOutcome`, `ConversationManager` |
| `backend/sim/engine.py` | ✓ | ✓ | ✓ | Integrates two-phase cognitive loop, conversations, `register_event_callback`, `inject_event` |
| `backend/api/rest.py` | ✓ | ✓ | ✓ | Adds `InjectEventRequest`, `InjectEventResponse`, `POST /events` |
| `backend/app/main.py` | ✓ | ✓ | ✓ | Wires `engine.register_event_callback` → `ws_manager.broadcast_json` |
| `backend/tests/test_*.py` | ✓ | ⚠️ | ✓ | 88 tests pass; `test_phase3_integration.py:131` relaxed `5..8` check to `1..8` due to Maya bio replans |
| `scripts/verify_phase1_ws.py` | ✓ | ✓ | ✓ | Accepts `dialogue`/`event` frames alongside `tick` and cleans up Windows process tree |
| `frontend/src/types/sim.ts` | ✓ | ✓ | ✓ | `DialogueTurn`, `DialogueMessage`, `EventMessage`, `InjectEventRequest/Response` + guards |
| `frontend/vite.config.ts` | ✓ | ✓ | ✓ | Proxies `/events` to `http://127.0.0.1:8000` |
| `frontend/src/net/wsClient.ts` | ✓ | ✓ | ✓ | Dispatches `onDialogue` and `onEvent` alongside `onTick` |
| `frontend/src/net/apiClient.ts` | ✓ | ✓ | ✓ | Implements `fetchWorld()` and `injectEvent()` |
| `frontend/src/scenes/VillageScene.ts` | ✓ | ✓ | ✓ | Depth-60 speaker bubbles, depth-55/65 event pulses/banners, input-guarded `keydown-C` |
| `frontend/src/ui/activityFeed.ts` | ✓ | ✓ | ✓ | Safe DOM card feed (`MAX_FEED_ITEMS = 25`) |
| `frontend/src/ui/eventInjector.ts` | ✓ | ✓ | ✓ | Location loader (`fetchWorld`) + `POST /events` form + focus tracking |
| `frontend/src/main.ts` | ✓ | ✓ | ✓ | Mounts `ActivityFeed`, `EventInjector`, `Phaser.Game` (`capture: []`), and WS handlers |
| `frontend/index.html` & `style.css` | ✓ | ✓ | ✓ | Adds `#activity-feed` overlay and `#god-mode-bar` toolbar |

---

### Key Links

| From | To | Via | Status |
|------|----|-----|--------|
| `backend/llm/gateway.py` | `backend/llm/schemas.py` | Imports `ReplanResponse`, `HourlyActionPlanResponse`, etc. | ✓ WIRED |
| `backend/llm/prompts/*.py` | `agents.personas`, `llm.schemas` | Consumes `AgentPersona` and `DailyPlanItem` | ✓ WIRED |
| `backend/sim/engine.py` | `backend/llm/providers/mock.py` | `initialize_persistence()` seeds `persona.summary_text()` retrieved into `MockProvider` | ⚠️ DEFECT (bio `"fire"` false-positive trigger) |
| `backend/agents/planner.py` | `llm.gateway` & `llm.prompts.planning` | Calls `generate_daily_plan`, `generate_replan`, `generate_hourly_actions` | ✓ WIRED |
| `backend/agents/agent.py` | `agents.planner`, `memory.*` | Coordinates `DailyPlanner`, `MemoryRetriever`, `MemoryStore` | ✓ WIRED |
| `backend/agents/conversation.py` | `llm.gateway`, `memory.*`, `sim.world` | Uses `MemoryRetriever`, `MemoryStore`, `LLMGateway`, `WorldMap` | ✓ WIRED |
| `backend/sim/engine.py` | `agents.*` | Runs `_perceive_and_remember` → `_run_conversations` → `_decide_actions` before `_step_agent` | ✓ WIRED |
| `backend/api/rest.py` | `backend/sim/engine.py` | `POST /events` delegates to `engine.inject_event` | ✓ WIRED |
| `backend/app/main.py` | `backend/api/ws.py` | Registers both `_broadcast` and `_broadcast_event` on `ws_manager.broadcast_json` | ✓ WIRED |
| `frontend/src/main.ts` | `VillageScene`, `ActivityFeed`, `EventInjector`, `wsClient` | Wires `onDialogue`/`onEvent` and `setKeyboardEnabled(!focused)` | ✓ WIRED |
| `frontend/src/ui/eventInjector.ts` | `frontend/src/net/apiClient.ts` | Calls `fetchWorld()` and `injectEvent()` | ✓ WIRED |

---

## Command Verification Evidence

1. **Backend Test Suite (`pytest`)** (cwd: `backend/`):
   - Command: `Set-Location backend; .venv\Scripts\pytest.exe -v`
   - Output: `88 passed in 11.24s` (exit code 0) across all unit & integration tests (including `test_llm_gateway.py` 10, `test_store_phase3.py` 4, `test_planner_and_agent.py` 6, `test_conversation.py` 5, `test_phase3_integration.py` 3).
2. **Backend Linter (`ruff check .`)** (cwd: `backend/`):
   - Command: `Set-Location backend; .venv\Scripts\ruff.exe check .`
   - Output: `All checks passed!` (exit code 0).
3. **Backend Static Type Check (`mypy .`)** (cwd: `backend/`):
   - Command: `Set-Location backend; .venv\Scripts\mypy.exe .`
   - Output: `Success: no issues found in 47 source files` (exit code 0).
4. **Scripts Lint & Type Check**:
   - Command: `backend\.venv\Scripts\ruff.exe check --config backend\pyproject.toml scripts` → `All checks passed!` (exit code 0).
   - Command: `backend\.venv\Scripts\mypy.exe --config-file backend\pyproject.toml scripts` → `Success: no issues found in 2 source files` (exit code 0).
5. **Frontend TypeScript Check & Production Build**:
   - Command: `npm --prefix frontend run typecheck` → `tsc --noEmit` exited 0 with zero errors.
   - Command: `npm --prefix frontend run build` → `✓ 13 modules transformed.`, `dist/index.html 1.89 kB`, `dist/assets/index-DP_WV08p.css 4.88 kB`, `dist/assets/index-B3jzgCnD.js 1,498.85 kB`, `✓ built in 12.47s` (exit code 0).
6. **Live WebSocket & REST Verification**:
   - Command: `backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py` → `e2e_ws_ok ticks=[0, 1, 2, 3, 4, 5] moved_agents=6` (exit code 0).
   - Live `uvicorn` + `POST /events` + `/ws` + `frontend/dist/index.html` DOM check → `live_phase3_ok {'event_id': 1, 'affected': ['aria', 'liam', 'marcus'], 'seen_types': ['event', 'tick', 'tick', 'tick'], 'locations': 10}`, plus `422` on blank text and `400` on unknown location `"Atlantis"` (exit code 0).
7. **80-Tick Baseline Diagnostic (No Injected Events)**:
   - Command: `SimulationEngine` + `MockProvider(seed=42)` + `:memory:` DB stepped 80 ticks without calling `inject_event`:
     - Observed `dialogues: 12`, `usage: {'total_calls': 163, 'cache_hits': 3, 'tokens_in': 76227, 'tokens_out': 9180, 'total_tokens': 85407, 'cost_est': 0.0}`.
     - 11 of 12 dialogues repeated Maya's truncated bio (`"{A} and {B} discussed: Maya (age 28, Baker) lives at Home_Maya. Traits: warm, industrious, observant, generous. Maya wakes before..."`).
     - 6 of 8 agents spontaneously replanned (`maya`: 3 replans -> 2 blocks, `liam`: 2 replans -> 4 blocks, `elena`: 3 replans -> 3 blocks, `noah`: 4 replans -> 2 blocks, `clara`: 1 replan -> 2 blocks, `marcus`: 3 replans -> 3 blocks; 16 unplanned replans total).
8. **Anti-Pattern, SDK Boundary, Secret & Artifact Scans**:
   - `TODO|FIXME|XXX|HACK|PLACEHOLDER|NotImplementedError` scan across `backend/` `.py` files: 0 matches.
   - `TODO|FIXME|XXX|HACK|PLACEHOLDER|innerHTML` scan across `frontend/src/`: only comment `without innerHTML` in `frontend/src/ui/activityFeed.ts:5`.
   - `google.genai` import scan across `backend/`: confined strictly to `backend/llm/providers/gemini.py` (`CON-02` satisfied).
   - `git ls-files .env*`: `.env.example` only.
   - Leftover `.db`/`.sqlite`/`.sqlite3` files outside `.venv`/caches: none.

---

## Anti-Patterns & Findings

- 🛑 **Blocker — Seeded Maya bio (`"fire the village ovens"`) triggers village-wide false-positive rumor & replan cascade:** Confirmed empirically across 80 baseline ticks (`11/12` dialogues and `16` spontaneous replans across `6/8` agents with zero injected events). Addressed by gap-closure plan [.gsd/phases/3/8-PLAN.md](file:///d:/Experiments%20with%20AI/AI%20Village/.gsd/phases/3/8-PLAN.md).
- ℹ️ **Info — Trailing newlines in 4 `__init__.py` files:** `git status --short` shows unstaged trailing-newline edits in `backend/api/__init__.py`, `backend/app/__init__.py`, `backend/sim/__init__.py`, and `backend/tests/__init__.py`.

---

## Human Verification Needed

### 1. Visual Browser Review of Phase 3 Canvas Bubbles, Event Pulses & UI Overlay
**Test:** Start backend (`backend/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000` in `backend/`) and frontend (`npm --prefix frontend run dev`), open `http://localhost:5173`, inject `"Festival parade at the Bakery"` at `"Bakery"` via `#god-mode-bar`, and type the letter `c` while focused inside `#event-text`.
**Expected:**
- Typing `c` inside `#event-text` does NOT toggle the collision grid overlay on the Phaser canvas.
- An amber pulse ring and floating banner appear over the Bakery, `#activity-feed` prepends the event and subsequent dialogues without shifting `#game-container`, and `depth = 60` speech bubbles appear above walking villagers without clipping under location labels.
**Why human:** No interactive browser/screenshot tool is available in this headless verification context.

---

## Verdict

**FAIL (`gaps_found`)** — While 5/7 Phase 3 must-haves, `ruff`, `mypy`, `pytest` (88/88), `tsc --noEmit`, `vite build`, and live `POST /events` + `/ws` wiring pass, the deferred Maya bio false-positive defect causes 11/12 baseline dialogues and 16 unplanned replans across 6/8 agents in 80 ticks without any injected event. Execute [.gsd/phases/3/8-PLAN.md](file:///d:/Experiments%20with%20AI%20Village/.gsd/phases/3/8-PLAN.md) (`gap_closure: true`) and re-verify Phase 3.
