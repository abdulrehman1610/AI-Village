---
phase: 4
plan: 5
wave: 2
depends_on:
  - "3"
files_modified:
  - frontend/src/scenes/VillageScene.ts
  - frontend/src/ui/activityFeed.ts
  - frontend/src/ui/timeControls.ts
  - frontend/src/ui/agentInspector.ts
  - frontend/index.html
  - frontend/src/style.css
  - frontend/src/main.ts
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "Clicking an agent sprite in `VillageScene.ts` selects that agent when pointer travel <= 5px, while dragging to pan the camera never opens the inspector"
    - "HUD `#time-controls` renders Play/Pause and 1x/4x/16x buttons synced to server `running`/`speed` state and sends `POST /sim/start`, `POST /sim/pause`, and `POST /sim/speed` without double-toggling on Spacebar"
    - "Left-docked `#agent-inspector` displays persona, mood, current location/action, reflection meter, current plan, recent/top memories, reflections with cited memory IDs, and relationships using XSS-safe `createElement` + `textContent` without overlapping `#activity-feed` or `#god-mode-bar`"
    - "`ActivityFeed` renders `REFLECTION` cards and `VillageScene.ts` renders a transient reflection halo cue on `reflection` WebSocket broadcasts"
  artifacts:
    - "frontend/src/scenes/VillageScene.ts adds drag-disambiguated sprite selection, selection highlight ring, `setSelectedAgent`, `setOnAgentSelect`, and `showReflection`"
    - "frontend/src/ui/activityFeed.ts adds `pushReflection(msg: ReflectionMessage)`"
    - "frontend/src/ui/timeControls.ts implements `TimeControls` synced with `TickMessage` and `SimControlResponse`"
    - "frontend/src/ui/agentInspector.ts implements `AgentInspector` with live tick patching and dialogue/reflection/periodic refresh"
    - "frontend/index.html, frontend/src/style.css, and frontend/src/main.ts integrate `#time-controls`, clickable HUD agent chips, `#agent-inspector`, `Escape` close guard, and `onReflection` handlers"
  key_links:
    - "frontend/src/ui/timeControls.ts calls `startSim`, `pauseSim`, and `setSimSpeed` from `../net/apiClient`"
    - "frontend/src/ui/agentInspector.ts calls `fetchAgentDetail` from `../net/apiClient`"
    - "frontend/src/main.ts wires `VillageScene.setOnAgentSelect`, clickable `.agent-chip` buttons, `TimeControls`, `AgentInspector`, `ActivityFeed.pushReflection`, and `VillageWsClient.onReflection`"
---

# Plan 4.5: Frontend Time Controls, Clickable Agent Inspector & Reflection Visuals

## Objective
Deliver the interactive Phase 4 frontend controls and inspection experience (`REQ-09` UI, `REQ-11`, `REQ-12`): HUD Play/Pause and 1x/4x/16x Time Controls, drag-safe Phaser sprite & HUD-chip agent selection, a left-docked Agent Inspector panel with live/event-driven refresh, and `reflection` cards/visual cues in `ActivityFeed` and `VillageScene`.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/4/RESEARCH.md
- frontend/index.html
- frontend/src/style.css
- frontend/src/types/sim.ts
- frontend/src/net/apiClient.ts
- frontend/src/net/wsClient.ts
- frontend/src/scenes/VillageScene.ts
- frontend/src/ui/activityFeed.ts
- frontend/src/main.ts

## Tasks

<task type="auto">
  <name>Add drag-safe agent selection, highlight ring, and reflection cues to VillageScene and ActivityFeed</name>
  <files>
    frontend/src/scenes/VillageScene.ts
    frontend/src/ui/activityFeed.ts
  </files>
  <action>
    Extend `VillageScene.ts` for interactive sprite selection and reflection visuals, and add `pushReflection` to `ActivityFeed`.

    Steps:
    1. In `frontend/src/scenes/VillageScene.ts`:
       - Import `ReflectionMessage` from `../types/sim`.
       - Define `DRAG_THRESHOLD_PX = 5` and `REFLECTION_DURATION_MS = 2400`.
       - Extend `AgentVisual` with `selectionRing: Phaser.GameObjects.Arc`.
       - Track `private hasPanned = false;`, `private selectedAgentId: string | null = null;`, and `private onAgentSelect: ((agentId: string) => void) | null = null;`.
       - Export `public setOnAgentSelect(callback: ((agentId: string) => void) | null): void` and `public setSelectedAgent(agentId: string | null): void` (updating `selectionRing.setVisible(id === agentId)` on all existing visuals).
       - In `configureCamera`:
         - On `pointerdown`: set `this.hasPanned = false;` alongside `this.isDragging = true`, `this.dragStartX`, `this.dragStartY`.
         - On `pointermove`: if `Math.hypot(pointer.x - this.dragStartX, pointer.y - this.dragStartY) > DRAG_THRESHOLD_PX`, set `this.hasPanned = true;`.
         - On `pointerup`: set `this.isDragging = false;` (do NOT clear `this.hasPanned` here, so sprite `pointerup` handler order cannot race).
       - In `syncAgentVisual` when creating a new agent visual:
         - Create `selectionRing = this.add.circle(0, 8, 16, 0x38bdf8, 0.14).setStrokeStyle(2, 0x38bdf8, 0.95).setVisible(agent.id === this.selectedAgentId)`.
         - Add `[selectionRing, sprite, nameText]` to `container` so the ring always renders under the sprite and follows tweens automatically.
         - Call `sprite.setInteractive({ useHandCursor: true })` and attach `sprite.on("pointerup", (pointer: Phaser.Input.Pointer) => { ... })`: fire `this.onAgentSelect?.(agent.id)` ONLY when `!this.hasPanned && Math.hypot(pointer.x - this.dragStartX, pointer.y - this.dragStartY) <= DRAG_THRESHOLD_PX && pointer.button === 0`.
       - Implement `public showReflection(msg: ReflectionMessage): void`:
         - Guard `!this.isReady`.
         - Locate `const visual = this.agentVisuals.get(msg.agent_id)` (falling back to camera midpoint).
         - Render a violet expanding halo (`0xa855f7`, `EVENT_RING_DEPTH`) and concise floating badge (`"${msg.agent_name} reflected"`, `EVENT_BANNER_DEPTH`), tracked in `this.transientEventObjects` and destroyed cleanly on tween completion.
    2. In `frontend/src/ui/activityFeed.ts`:
       - Import `ReflectionMessage` from `../types/sim`.
       - Add `public pushReflection(msg: ReflectionMessage): void`:
         - Build `<article class="feed-item reflection">` via `document.createElement` + `textContent`:
           - Meta row via `createMetaRow("REFLECTION", msg.sim_time, msg.agent_name)`
           - Body with `msg.insight`
           - Submeta showing cited memory IDs (e.g. `Cited: #${msg.cited_memory_ids.join(", #")}` when non-empty, or `"Synthesized insight"`).
         - Prepend via `this.prependItem(item)`.

    AVOID: Triggering `onAgentSelect` when releasing a camera drag (`hasPanned === true`) or using `innerHTML` in `ActivityFeed`.
    USE: `DRAG_THRESHOLD_PX = 5` travel guard on both `pointermove` and sprite `pointerup`, plus `createElement` + `textContent`.
  </action>
  <verify>
    Run from repo root (Cwd: repo root):
    npm --prefix frontend run typecheck
  </verify>
  <done>
    `VillageScene.ts` supports drag-disambiguated sprite clicks, selection highlight rings, and reflection halos, `ActivityFeed` renders `REFLECTION` cards, and `tsc --noEmit` passes.
  </done>
</task>

<task type="auto">
  <name>Build TimeControls and left-docked AgentInspector UI modules with HTML/CSS layout</name>
  <files>
    frontend/src/ui/timeControls.ts
    frontend/src/ui/agentInspector.ts
    frontend/index.html
    frontend/src/style.css
  </files>
  <action>
    Create `frontend/src/ui/timeControls.ts` and `frontend/src/ui/agentInspector.ts`, and update `frontend/index.html` and `frontend/src/style.css` so all HUD, canvas, inspector, feed, and god-mode panels coexist without overlapping.

    Steps:
    1. Update `frontend/index.html`:
       - Inside `<header id="hud">`, inside or immediately beside `.hud-clock`, add `<div id="time-controls" class="time-controls" aria-label="Simulation playback controls"></div>`.
       - Inside `<main id="stage">`, add `<aside id="agent-inspector" class="agent-inspector hidden" aria-label="Agent inspector"></aside>` alongside `<div id="game-container"></div>` and `<aside id="activity-feed">...</aside>`.
       - Update `#controls-hint` text to mention clicking an agent (`Click agent to inspect · Drag to pan · Scroll to zoom · Press C for collision grid`).
    2. Update `frontend/src/style.css`:
       - Style `#time-controls`, `.sim-btn`, `.sim-btn.active`, `.sim-speed-group` cleanly inside `#hud`.
       - Style `#agents-bar .agent-chip` as interactive `<button>` pills with hover and `.agent-chip.active` highlight styling.
       - Style `#agent-inspector` as a left-docked translucent dark-slate drawer (`position: absolute; top: 1rem; left: 1rem; bottom: 1rem; width: 340px; max-width: calc(100% - 2rem); overflow-y: auto; z-index: 25;`) with `.hidden { display: none; }` and styled sections for mood pill, location/status, reflection meter, traits chips, plan blocks (`.plan-block.active`), memory items (`.memory-item`, `.cite-badge`), and relationship rows (`.affinity-bar`, positive/negative tone).
       - Add `.feed-item.reflection` violet accent border (`#a855f7`) and badge styling in `#activity-feed`.
    3. Create `frontend/src/ui/timeControls.ts` (`TimeControls` class):
       - Renders Play/Pause button (`#sim-toggle-btn`) and speed buttons (`1x`, `4x`, `16x` with `data-speed`) using `document.createElement` + `textContent`.
       - Tracks `running`, `speed`, and `pending` request guard; calls `startSim()`, `pauseSim()`, or `setSimSpeed(speed)` from `../net/apiClient` and notifies `onStateChange?.(res)`.
       - Exposes `sync(state: { running: boolean; speed: number }): void` so incoming `tick` WS payloads keep button states and active speed pill authoritative.
       - Displays concise inline error text if a control request fails (without throwing).
    4. Create `frontend/src/ui/agentInspector.ts` (`AgentInspector` class):
       - Exposes `open(agentId: string): Promise<void>`, `close(): void`, `refresh(): Promise<void>`, `getSelectedAgentId(): string | null`, `applyTick(tickMsg: TickMessage): void`, `handleDialogue(msg: DialogueMessage): void`, and `handleReflection(msg: ReflectionMessage): void`.
       - Builds the entire inspector panel using `document.createElement` + `textContent` ONLY (NO `innerHTML`), showing:
         - Header: Name, Role, Mood pill, Refresh button, Close button (`×` calling `onClose`).
         - Status card: Current location, Target location, Coordinates `(x, y)`, Current action, Reflection progress (`accumulated_importance / reflection_threshold`).
         - Persona card: Age, Home location, Bio, Traits tags, Starting goals.
         - Current Plan card: Active hourly focus / current step + list of daily blocks highlighting `active_block_index`.
         - Reflections card: Reflection entries with `[#id]` cited memory pills (or empty-state message).
         - Memories card: Recent and Top memories with type, importance, and tick badges.
         - Relationships card: Peer name, signed affinity (`+0.35` / `-0.10`), and notes (or `"No recorded interactions yet."`).
       - Live refresh behavior while open:
         - `applyTick`: immediately updates live `(x, y)`, `current_action`, `target_location`, and `mood` in the open detail view without hammering the REST API on every tick; when `tickMsg.running` and `Date.now() - lastFetchAt >= 3000` (and no fetch in flight), triggers a throttled `void this.refresh()`.
         - `handleDialogue`: if `selectedAgentId` is in `msg.participants`, calls `void this.refresh()`.
         - `handleReflection`: if `selectedAgentId === msg.agent_id`, calls `void this.refresh()`.
       - Guard against stale out-of-order async responses with a monotonic `requestSeq` token!

    AVOID: Using `innerHTML` anywhere for LLM-generated plans, memories, insights, moods, or relationship notes; binding an unguarded global `Space` key handler; or letting slow `fetchAgentDetail` responses overwrite a newer selection.
    USE: Strict `createElement` + `textContent`, `requestSeq` race guard, and left-docked positioning opposite `#activity-feed`.
  </action>
  <verify>
    Run from repo root (Cwd: repo root):
    npm --prefix frontend run typecheck
  </verify>
  <done>
    `timeControls.ts`, `agentInspector.ts`, `index.html`, and `style.css` compile cleanly under `tsc --noEmit` with XSS-safe DOM rendering and non-overlapping layout.
  </done>
</task>

<task type="auto">
  <name>Wire TimeControls, AgentInspector, clickable HUD chips, and reflection handlers in main.ts</name>
  <files>
    frontend/src/main.ts
  </files>
  <action>
    Connect all Phase 4 UI components, Phaser selection callbacks, WebSocket handlers, and keyboard guards in `frontend/src/main.ts`, then verify `tsc --noEmit` and `vite build`.

    Steps:
    1. In `frontend/src/main.ts`:
       - Import `AgentInspector` from `./ui/agentInspector` and `TimeControls` from `./ui/timeControls`.
       - Instantiate `timeControls` on `#time-controls` with `onStateChange`: update `#sim-time` / `#sim-tick` immediately from `SimControlResponse` (`running`, `speed`, `day`, `sim_time`, `tick`).
       - Instantiate `agentInspector` on `#agent-inspector` with `onClose`: clear `villageScene.setSelectedAgent(null)` and `.agent-chip.active` class.
       - Define `selectAgent(agentId: string)` helper: calls `villageScene.setSelectedAgent(agentId)`, updates `.agent-chip` active state, and calls `void agentInspector.open(agentId)`.
       - Wire `villageScene.setOnAgentSelect((agentId) => selectAgent(agentId))`.
       - Upgrade `updateHud(tickMsg)` so `.agent-chip` items are cached `<button type="button" class="agent-chip">` elements keyed by `agent.id` in a `Map<string, { button: HTMLButtonElement; metaEl: HTMLSpanElement }>` — creating them once and updating only `metaEl.textContent` and `.active` class on each tick so clicks are NEVER dropped at `16x` speed!
       - Also call `timeControls.sync({ running: tickMsg.running, speed: tickMsg.speed })` and `agentInspector.applyTick(tickMsg)` inside `onTick`.
       - Wire `onDialogue` -> `agentInspector.handleDialogue(dialogueMsg)`.
       - Wire `onReflection` -> `villageScene.showReflection(reflectionMsg)`, `activityFeed.pushReflection(reflectionMsg)`, `agentInspector.handleReflection(reflectionMsg)`.
       - Add `window` `"keydown"` listener for `Escape` (guarded by `document.activeElement` text-input check) to close `agentInspector` cleanly, and remove it on `beforeunload` alongside `timeControls.destroy()` and `agentInspector.destroy()`.
    2. Run `npm --prefix frontend run typecheck` and `npm --prefix frontend run build` to confirm zero TS errors and fresh `frontend/dist` assets.

    AVOID: Rebuilding `.agent-chip` DOM nodes via `replaceChildren` on every `16x` tick (drops button clicks between `mousedown` and `mouseup`) or leaving global listeners attached on unload.
    USE: Keyed `<button type="button">` chip cache and clean `beforeunload` teardown.
  </action>
  <verify>
    Run from repo root (Cwd: repo root, separate commands):
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
  </verify>
  <done>
    `main.ts` wires TimeControls, AgentInspector, sprite/chip selection, and `reflection` handlers cleanly, and both `tsc --noEmit` and `vite build` pass with zero errors.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] Sprite selection in `VillageScene.ts` ignores camera drag-pan gestures (`> 5px`) and highlights the selected agent
- [ ] `#time-controls` reflects authoritative server `running`/`speed` state and drives `/sim/start`, `/sim/pause`, and `/sim/speed`
- [ ] Left-docked `#agent-inspector` displays persona, mood, plan, memories, reflections, and relationships safely via `textContent` and stays refreshed while open
- [ ] `ActivityFeed` and `VillageScene.ts` render live `reflection` updates and `frontend/dist` builds cleanly

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] `npm --prefix frontend run typecheck` and `npm --prefix frontend run build` succeed with zero errors
