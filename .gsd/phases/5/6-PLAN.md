---
phase: 5
plan: 6
wave: 3
depends_on:
  - "4"
  - "5"
files_modified:
  - frontend/index.html
  - frontend/src/style.css
  - frontend/src/main.ts
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`#hud` provides tool buttons (`Relationships`, `Metrics`, `Replay`) opening mutually exclusive `z-index: 35` drawer panels (`#relationship-panel`, `#metrics-panel`) and `#replay-bar` without overlapping `#agent-inspector`, `#activity-feed`, or Phaser canvas interactions"
    - "Live WebSocket `onTick`, `onDialogue`, `onEvent`, and `onReflection` callbacks are gated behind `!replayController.isActive()` while still caching `lastLiveTick` and forwarding `onMetrics` to `MetricsDashboardPanel`"
    - "Entering Replay Mode hides live `#time-controls` + `#god-mode-bar`, closes `#agent-inspector`, resets transient visuals, and shows `#replay-bar`; exiting Replay Mode resets transient visuals, clears replay feed entries, restores `#time-controls` + `#god-mode-bar`, and immediately snaps `VillageScene` + HUD clock/chips back to `lastLiveTick`"
    - "Clicking an agent node inside the Cytoscape.js Relationship Graph invokes `selectAgent(agentId)` to inspect that villager directly"
  artifacts:
    - "frontend/index.html adds `.hud-tools`, `#relationship-panel`, `#metrics-panel`, and `#replay-bar`"
    - "frontend/src/style.css styles the Relationship Graph modal, Chart.js KPI/chart grid, and Replay scrubber bar cleanly"
    - "frontend/src/main.ts coordinates `RelationshipGraphModal`, `MetricsDashboardPanel`, `ReplayController`, `VillageWsClient`, `lastLiveTick`, and `Escape` key handling"
  key_links:
    - "frontend/src/main.ts connects `wsClient` `onMetrics` -> `metricsDashboard.applyMetrics` and `onDialogue` -> `relationshipGraph.handleDialogue`"
    - "frontend/src/main.ts coordinates `ReplayController` `onExit` -> `villageScene.resetTransientVisuals()` + `villageScene.applyTick(lastLiveTick, { immediate: true })`"
---

# Plan 5.6: Frontend HUD Integration, Drawer Coordination & Live/Replay Mode Switching

## Objective
Integrate the Cytoscape.js Relationship Graph drawer, Chart.js Cost & Token Dashboard drawer, and Day Replay scrubber bar into `frontend/index.html`, `frontend/src/style.css`, and `frontend/src/main.ts` with clean live/replay WebSocket gating (`lastLiveTick`) and strict TypeScript verification (`REQ-10`, `REQ-13`, `REQ-14`, `NFR-04`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/5/RESEARCH.md
- frontend/index.html
- frontend/src/style.css
- frontend/src/main.ts
- frontend/src/ui/relationshipGraph.ts
- frontend/src/ui/metricsDashboard.ts
- frontend/src/ui/replayControls.ts
- frontend/src/scenes/VillageScene.ts
- frontend/src/ui/activityFeed.ts

## Tasks

<task type="auto">
  <name>Add HUD tool buttons, drawer containers, and replay bar markup + styles in index.html and style.css</name>
  <files>
    frontend/index.html
    frontend/src/style.css
  </files>
  <action>
    Update `frontend/index.html` and `frontend/src/style.css` to host the Relationship Graph drawer, Cost/Metrics Dashboard drawer, HUD navigation toggles, and Day Replay bar cleanly.

    Steps:
    1. In `frontend/index.html`:
       - Inside `#hud` (between `.hud-clock` and `#agents-bar` or inside `.hud-brand`/`.hud-tools`), add `<nav class="hud-tools" aria-label="Village views">` containing three buttons:
         - `<button id="btn-relationships" type="button" class="sim-btn hud-tool-btn" aria-pressed="false">Relationships</button>`
         - `<button id="btn-metrics" type="button" class="sim-btn hud-tool-btn" aria-pressed="false">Metrics</button>`
         - `<button id="btn-replay" type="button" class="sim-btn hud-tool-btn" aria-pressed="false">Replay</button>`
       - Inside `#stage`, add:
         - `<section id="relationship-panel" class="drawer-panel hidden" aria-label="Relationship network"></section>`
         - `<section id="metrics-panel" class="drawer-panel hidden" aria-label="Cost and token dashboard"></section>`
       - Right after `#god-mode-bar`, add:
         - `<section id="replay-bar" class="replay-bar hidden" aria-label="Day replay controls"></section>`
    2. In `frontend/src/style.css`:
       - Elevate `#agent-inspector` to `z-index: 36` so clicking a node in the Relationship Graph opens `#agent-inspector` visibly alongside the right-anchored drawer on desktop.
       - Style `.hud-tools` and `.hud-tool-btn.active` matching existing `.sim-btn` theme (`#38bdf8` active highlight, focus ring).
       - Style `.drawer-panel` (`position: absolute; top: 1rem; right: 1rem; bottom: 1rem; width: min(860px, calc(100% - 2rem)); z-index: 35; display: flex; flex-direction: column; gap: 0.75rem; padding: 1rem; border-radius: 0.75rem; background: rgba(15, 23, 42, 0.96); border: 1px solid #334155; box-shadow: 0 20px 50px rgba(2, 6, 23, 0.82); backdrop-filter: blur(12px); overflow-y: auto;`), plus `#stage.inspector-open .drawer-panel { max-width: calc(100% - 376px); }` and responsive `@media (max-width: 960px)` rule so panels adapt on smaller viewports.
       - Style Cytoscape graph elements: `.graph-header`, `.graph-legend`, `.graph-canvas` (`min-height: 360px; flex: 1; border-radius: 0.5rem; background: #0b1220; border: 1px solid #334155;`), and `.graph-detail`.
       - Style Chart.js metrics elements: `.kpi-grid` (`grid-template-columns: repeat(auto-fit, minmax(145px, 1fr))`), `.kpi-card`, `.budget-bar-wrap`, `.metrics-charts-grid`, `.metrics-chart-card`, `.metrics-chart-box` (`position: relative; height: 210px; width: 100%;`), and `.metrics-model-table`.
       - Style `.replay-bar` (matching `#god-mode-bar` dark slate bar, flex wrap, `.replay-badge` violet/amber pill, `.replay-select`, `.replay-scrubber` flex-1 range input, and `#replay-exit-btn`).

    AVOID: Leaving `.metrics-chart-box` or `.graph-canvas` without explicit height/min-height (Chart.js and Cytoscape need concrete container bounds) or overlapping `#activity-feed` / `#god-mode-bar`.
    USE: Existing slate/cyan/amber/violet color palette and `z-index` layering (`20` feed, `35` drawers, `36` inspector).
  </action>
  <verify>
    Run from repo root:
    npm --prefix frontend run build
  </verify>
  <done>
    `frontend/index.html` and `frontend/src/style.css` define all drawer, tool button, and replay bar slots with clean responsive styling and pass `vite build`.
  </done>
</task>

<task type="auto">
  <name>Wire RelationshipGraphModal, MetricsDashboardPanel, and ReplayController in frontend/src/main.ts</name>
  <files>
    frontend/src/main.ts
  </files>
  <action>
    Connect all Phase 5 UI panels and live/replay WebSocket coordination inside `frontend/src/main.ts`.

    Steps:
    1. Query the new DOM elements (`btn-relationships`, `btn-metrics`, `btn-replay`, `relationship-panel`, `metrics-panel`, `replay-bar`, `god-mode-bar`, `stage`).
    2. Instantiate:
       - `relationshipGraph = new RelationshipGraphModal(relationshipPanelEl, { onSelectAgent: (agentId) => selectAgent(agentId), onClose: () => syncToolButtons() })`
       - `metricsDashboard = new MetricsDashboardPanel(metricsPanelEl, { onClose: () => syncToolButtons() })`
       - `replayController = new ReplayController(replayBarEl, { ... })`
    3. Track `let lastLiveTick: TickMessage | null = null;` and helper `applyTickToUi(tickMsg: TickMessage, immediate: boolean, isReplay: boolean)`:
       - Calls `villageScene.applyTick(tickMsg, { immediate })`, updates clock display (`Day D · HH:MM · Replay` when `isReplay`, else normal speed/paused), updates agent chips (`selectedAgentId` = `null` in replay, `agentInspector.getSelectedAgentId()` in live), and updates `timeControls.sync` + `agentInspector.applyTick` only when `!isReplay`.
    4. Implement `ReplayController` callbacks:
       - `onEnter`: `agentInspector.close()`, `villageScene.resetTransientVisuals()`, hide `#time-controls` and `#god-mode-bar` via `.classList.add("hidden")`, set `activityFeed.setModeLabel("Replay Activity")`, `activityFeed.clear("Replay active — press Play or scrub timeline...")`, sync `#btn-replay` active state.
       - `onResetTimeline`: `villageScene.resetTransientVisuals()`, `activityFeed.clear("Replay position jumped...")`.
       - `onApplyTick(msg, immediate)`: `applyTickToUi(msg, immediate, true)`.
       - `onApplyDialogue(msg)`: `villageScene.showDialogue(msg)`, `activityFeed.pushDialogue(msg)`.
       - `onApplyEvent(msg)`: `villageScene.showEvent(msg)`, `activityFeed.pushEvent(msg)`.
       - `onApplyReflection(msg)`: `villageScene.showReflection(msg)`, `activityFeed.pushReflection(msg)`.
       - `onExit`: `villageScene.resetTransientVisuals()`, `activityFeed.setModeLabel("Live Activity")`, `activityFeed.clear()`, un-hide `#time-controls` and `#god-mode-bar`, sync `#btn-replay`, and if `lastLiveTick !== null`, restore immediately via `applyTickToUi(lastLiveTick, true, false)`.
    5. Wire HUD tool buttons (`btn-relationships`, `btn-metrics`, `btn-replay`) with mutual exclusion between drawers (`relationshipGraph` closes `metricsDashboard` and vice versa), `syncToolButtons()` updating `aria-pressed` and `.active`, and `Escape` key handler closing open drawers before `agentInspector` (when no text input is focused).
    6. Update `selectAgent(agentId)` to update `#stage.classList.toggle("inspector-open", ...)` (and clear on `agentInspector` `onClose`), and skip opening live REST `AgentInspector` while `replayController.isActive()` (highlighting selection ring only).
    7. Update `VillageWsClient` callbacks:
       - `onTick`: ALWAYS save `lastLiveTick = tickMsg` and call `timeControls.sync({ running: tickMsg.running, speed: tickMsg.speed })`; only call `applyTickToUi(tickMsg, false, false)` when `!replayController.isActive()`.
       - `onDialogue`: ALWAYS call `relationshipGraph.handleDialogue()`; gate `villageScene.showDialogue`, `activityFeed.pushDialogue`, and `agentInspector.handleDialogue` behind `!replayController.isActive()`.
       - `onEvent`: gate `villageScene.showEvent` and `activityFeed.pushEvent` behind `!replayController.isActive()`.
       - `onReflection`: gate `villageScene.showReflection`, `activityFeed.pushReflection`, and `agentInspector.handleReflection` behind `!replayController.isActive()`.
       - `onMetrics`: ALWAYS call `metricsDashboard.applyMetrics(metricsMsg)`.
    8. Clean up `relationshipGraph.destroy()`, `metricsDashboard.destroy()`, and `replayController.destroy()` inside `window.addEventListener("beforeunload", ...)`.

    AVOID: Letting live WebSocket ticks overwrite Phaser sprites or HUD time while `replayController.isActive()`, dropping `onMetrics` updates during replay, or forgetting to restore `lastLiveTick` on replay exit.
    USE: `replayController.isActive()` gating, `lastLiveTick` caching, and `applyTick(lastLiveTick, { immediate: true })` on exit.
  </action>
  <verify>
    Run from repo root (separate commands):
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
  </verify>
  <done>
    `frontend/src/main.ts` coordinates all Phase 5 interactive panels and live/replay state cleanly, and `npm --prefix frontend run typecheck` + `npm --prefix frontend run build` succeed with zero errors.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] HUD buttons toggle Relationship Graph (`Cytoscape.js`), Cost & Telemetry Dashboard (`Chart.js`), and Day Replay mode cleanly
- [ ] Clicking a node in the Relationship Graph opens `AgentInspector` for that villager without overlap glitches
- [ ] Entering Replay Mode disables live time/event controls, replays or scrubs JSONL frames smoothly, keeps receiving live `lastLiveTick` and `metrics` updates in the background, and cleanly snaps back to `lastLiveTick` on exit
- [ ] `npm --prefix frontend run typecheck` and `npm --prefix frontend run build` pass cleanly

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero TypeScript strict-mode errors or broken existing Phase 1–4 UI flows
