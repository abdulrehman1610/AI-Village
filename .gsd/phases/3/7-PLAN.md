---
phase: 3
plan: 7
wave: 4
depends_on:
  - "3"
  - "6"
files_modified:
  - frontend/src/scenes/VillageScene.ts
  - frontend/src/ui/eventInjector.ts
  - frontend/src/ui/activityFeed.ts
  - frontend/src/main.ts
  - frontend/index.html
  - frontend/src/style.css
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`VillageScene.ts` renders live `dialogue` speech bubbles at `depth >= 60` tracking speaker sprites and `event` location pulses/banners without clipping behind labels (`depth 20`) or agents (`depth 10..39`)"
    - "`VillageScene.ts` guards `keydown-C` (and Phaser keyboard capture) when focus is inside `<input>`, `<textarea>`, `<select>`, or `contentEditable` elements"
    - "The God-Mode Event Injection bar (`#god-mode-bar`, `eventInjector.ts`) lets viewers enter free-text events with an optional location dropdown (`All Village` + `GET /world` locations) and calls `POST /events` with inline feedback"
    - "The live Activity Feed overlay (`activityFeed.ts`) renders recent `event` and `dialogue` updates inside `#stage` cleanly without shifting the Phaser canvas"
  artifacts:
    - "frontend/src/scenes/VillageScene.ts adds `showDialogue`, `showEvent`, `update` bubble tracking, location center lookup, and input-focus guard on `keydown-C`"
    - "frontend/src/ui/eventInjector.ts implements the God-Mode injection controller"
    - "frontend/src/ui/activityFeed.ts implements the live event/dialogue feed panel"
    - "frontend/index.html, frontend/src/style.css, and frontend/src/main.ts integrate `#god-mode-bar`, `#activity-feed`, and WS/REST handlers"
  key_links:
    - "frontend/src/main.ts wires `wsClient` `onDialogue`/`onEvent` to `VillageScene.showDialogue`/`showEvent` and `ActivityFeed`, and mounts `EventInjector` with `fetchWorld`/`injectEvent`"
    - "frontend/src/ui/eventInjector.ts calls `fetchWorld` and `injectEvent` from `../net/apiClient`"
---

# Plan 3.7: Frontend Speech Bubbles, Location Event Pulses, Activity Feed & God-Mode Injection UI

## Objective
Complete the Phase 3 viewer experience in the Phaser 3 + TypeScript frontend: render `depth >= 60` agent speech bubbles for `dialogue` broadcasts, render location pulse rings and banners for `event` broadcasts, mount a live Activity Feed overlay and God-Mode Event Injection bar, guard `keydown-C` when typing in form inputs, and run full-stack verification.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/3/RESEARCH.md
- frontend/src/types/sim.ts
- frontend/src/net/wsClient.ts
- frontend/src/net/apiClient.ts
- frontend/src/scenes/VillageScene.ts
- frontend/src/main.ts
- frontend/index.html
- frontend/src/style.css

## Tasks

<task type="auto">
  <name>Add depth>=60 speech bubbles, event location pulses, and input-guarded keydown-C to VillageScene</name>
  <files>
    frontend/src/scenes/VillageScene.ts
  </files>
  <action>
    Extend `frontend/src/scenes/VillageScene.ts` to visualize live `dialogue` turns and `event` broadcasts in world space while fixing keyboard input focus collisions.

    Steps:
    1. Import `DialogueMessage` and `EventMessage` from `../types/sim`.
    2. Guard `keydown-C` inside `create()`:
       - Check `const active = document.activeElement;` — if `active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement || active instanceof HTMLSelectElement || (active instanceof HTMLElement && active.isContentEditable)`, return early without toggling `this.collisionLayer`.
       - Also expose `public setKeyboardEnabled(enabled: boolean): void` (`if (this.input.keyboard !== null) { this.input.keyboard.enabled = enabled; }`) so DOM inputs can disable Phaser key capture while focused.
    3. Record `locationCenters: Map<string, { x: number; y: number }>` inside `renderLocationLabels(map)` so `showEvent` can pinpoint named locations.
    4. Implement `public showDialogue(msg: DialogueMessage): void`:
       - Ignore gracefully if `!this.isReady` or `msg.turns.length === 0`.
       - Sequence turns over time using `this.time.delayedCall(...)` (e.g., showing each turn for `2400ms` staggered by `1800ms`, capped cleanly), rendering each speaker's bubble in a dedicated world-space `Phaser.GameObjects.Container` at `depth = 60` (well above location labels at `depth 20` and agents at `depth 10..39`).
       - Each bubble combines a rounded dark-slate background (`Phaser.GameObjects.Graphics` or styled `Text` with wordWrap `width: 190` and bright border), tracked per `speaker_id` in `activeBubbles: Map<string, ...>` (destroying any previous bubble/timer for that speaker cleanly so GameObjects never leak).
       - In `public override update(): void`: reposition every active bubble container to follow its `AgentVisual.container` `(x, y - 40)` so bubbles smoothly track moving speakers!
    5. Implement `public showEvent(msg: EventMessage): void`:
       - Ignore if `!this.isReady`.
       - Determine target `(px, py)` from `locationCenters.get(msg.location)` when `msg.location` is provided, else camera center (`this.cameras.main.midPoint.x`, `this.cameras.main.midPoint.y`).
       - Spawn a transient expanding ring (`Phaser.GameObjects.Arc`, `depth = 55`) and floating banner (`Phaser.GameObjects.Text`, `depth = 65`) tweened and destroyed on completion (`~2600ms`).

    AVOID: Parenting speech bubbles inside `AgentVisual.container` (whose depth `10 + agent.y` causes northern agents at `y < 10` to render behind `depth 20` location labels) or leaking un-destroyed Phaser timers/GameObjects.
    USE: Top-level scene containers at `depth >= 60`, `activeBubbles` cleanup on replacement/expiry, and `document.activeElement` focus guards.
  </action>
  <verify>
    Run from repo root (Cwd: repo root):
    npm --prefix frontend run typecheck
  </verify>
  <done>
    `VillageScene.ts` renders non-occluded `depth >= 60` speech bubbles and `event` location pulses, guards `keydown-C` during text input, and passes `tsc --noEmit`.
  </done>
</task>

<task type="auto">
  <name>Build EventInjector, ActivityFeed UI components, and update HTML/CSS layout</name>
  <files>
    frontend/src/ui/eventInjector.ts
    frontend/src/ui/activityFeed.ts
    frontend/index.html
    frontend/src/style.css
  </files>
  <action>
    Create modular DOM overlay/control components in `frontend/src/ui/` and add the corresponding containers to `frontend/index.html` and `frontend/src/style.css`.

    Steps:
    1. Update `frontend/index.html`:
       - Inside `<main id="stage">`, add `<aside id="activity-feed" aria-label="Live village activity"></aside>` alongside `<div id="game-container"></div>`.
       - Between `</main>` and `<footer id="controls-hint">`, add `<section id="god-mode-bar" aria-label="God-mode event injection">` containing `<form id="event-form">` with `<label>`, `<select id="event-location">` (default option `<option value="">All Village</option>`), `<input id="event-text" type="text" maxlength="500" placeholder="Inject a village event (e.g. A fire starts at the Bakery)..." required />`, `<button id="event-submit" type="submit">Inject Event</button>`, and `<span id="event-feedback" role="status" aria-live="polite"></span>`.
    2. Update `frontend/src/style.css`:
       - Set `position: relative` on `#stage`.
       - Style `#activity-feed` as a compact translucent dark-slate overlay (`position: absolute; top: 1rem; right: 1rem; width: 320px; max-height: 240px; overflow-y: auto; z-index: 20`) with crisp `.feed-item.event` (amber accent) and `.feed-item.dialogue` (sky/emerald accent) cards.
       - Style `#god-mode-bar` as a sleek horizontal dark toolbar matching `#hud`, including `.feedback.ok` and `.feedback.error` pill states.
    3. Create `frontend/src/ui/activityFeed.ts` (`ActivityFeed` class):
       - Methods `pushEvent(msg: EventMessage): void` and `pushDialogue(msg: DialogueMessage): void` (using safe `textContent` DOM construction — NEVER `innerHTML` with untrusted event text!).
       - Keep at most 25 newest entries at the top of the list and show an empty-state placeholder until the first event/dialogue arrives.
    4. Create `frontend/src/ui/eventInjector.ts` (`mountEventInjector(...)`):
       - Populates `#event-location` options via `fetchWorld()` (retaining `"All Village"` when offline or loading).
       - Handles form `submit`: trims text, disables button while awaiting `injectEvent({ text, location: selected || null })`, resets text input on success, displays affected villager count (`"Alerted N villager(s)"`), or displays descriptive error on failure.
       - Invokes optional `onInputFocusChange(focused: boolean)` callback on `focusin` / `focusout` so `VillageScene` suspends keyboard capture while typing!

    AVOID: Using `innerHTML` for user-supplied event text (XSS risk) or shrinking `#game-container` canvas layout unnecessarily.
    USE: Safe `document.createElement` + `textContent` DOM updates and `position: relative` overlay inside `#stage`.
  </action>
  <verify>
    Run from repo root (Cwd: repo root):
    npm --prefix frontend run typecheck
  </verify>
  <done>
    `eventInjector.ts`, `activityFeed.ts`, `index.html`, and `style.css` compile cleanly under `tsc --noEmit` with safe DOM construction and responsive layout.
  </done>
</task>

<task type="auto">
  <name>Wire Phase 3 UI + WebSocket callbacks in main.ts and run full-stack verification</name>
  <files>
    frontend/src/main.ts
  </files>
  <action>
    Connect `VillageWsClient` (`onDialogue`, `onEvent`), `VillageScene` (`showDialogue`, `showEvent`, `setKeyboardEnabled`), `ActivityFeed`, and `mountEventInjector` inside `frontend/src/main.ts`, then verify the complete built frontend and backend end-to-end.

    Steps:
    1. In `frontend/src/main.ts`:
       - Import `ActivityFeed` from `./ui/activityFeed` and `mountEventInjector` from `./ui/eventInjector`.
       - Instantiate `const activityFeed = new ActivityFeed(document.getElementById("activity-feed"));`.
       - Call `mountEventInjector({ formEl, locationSelectEl, textInputEl, submitBtnEl, feedbackEl, onFocusChange: (focused) => villageScene.setKeyboardEnabled(!focused) })` cleanly (passing queried elements from DOM).
       - Extend `VillageWsClient` callbacks:
         - `onDialogue: (dialogueMsg) => { villageScene.showDialogue(dialogueMsg); activityFeed.pushDialogue(dialogueMsg); }`
         - `onEvent: (eventMsg) => { villageScene.showEvent(eventMsg); activityFeed.pushEvent(eventMsg); }`
    2. Build the frontend (`npm --prefix frontend run typecheck` and `npm --prefix frontend run build`) so `frontend/dist` contains all Phase 3 bundles and assets.
    3. Run full backend tests, linters, type checks, and live WebSocket + `POST /events` verification against the running backend (`scripts/verify_phase1_ws.py`).

    AVOID: Letting unguarded focus events leave Phaser keyboard disabled permanently (verify blur/`focusout` checks `formEl.contains(relatedTarget)` or `document.activeElement`).
    USE: Clean lifecycle wiring and full post-build end-to-end verification.
  </action>
  <verify>
    Run from repo root (separate commands):
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
    backend\.venv\Scripts\python.exe scripts/verify_phase1_ws.py
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v
    .venv\Scripts\ruff.exe check .
    .venv\Scripts\mypy.exe app sim api agents memory llm tests
  </verify>
  <done>
    Frontend `tsc --noEmit` and `vite build` succeed with zero errors, `scripts/verify_phase1_ws.py` prints `e2e_ws_ok`, and full backend `pytest`, `ruff`, and `mypy` suites pass cleanly.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] Speech bubbles render at `depth >= 60` tracking speakers and event pulses highlight target locations in `VillageScene.ts`
- [ ] Typing in `#god-mode-bar` inputs never triggers `keydown-C` collision overlay toggling
- [ ] God-Mode Event Injection bar (`POST /events`) and live Activity Feed work with `MockProvider` backend and built `frontend/dist`

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Full backend + frontend verification commands pass cleanly with zero regressions
