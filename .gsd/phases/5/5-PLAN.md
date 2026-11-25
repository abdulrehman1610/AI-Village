---
phase: 5
plan: 5
wave: 2
depends_on:
  - "2"
files_modified:
  - frontend/src/scenes/VillageScene.ts
  - frontend/src/ui/activityFeed.ts
  - frontend/src/ui/replayControls.ts
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`VillageScene` exposes `resetTransientVisuals()` (clearing dialogue timers, speech bubbles, event rings/banners, and movement tweens) and `applyTick(tickMsg, { immediate?: boolean })` so timeline scrubbing snaps sprites immediately without tween artifacts"
    - "`ActivityFeed` exposes `clear(placeholder?)` and `setModeLabel(label)` so entering or exiting Replay Mode cleanly separates live and recorded activity entries"
    - "`ReplayController` (`frontend/src/ui/replayControls.ts`) loads available days from `GET /replay` and frames from `GET /replay/{day}`, provides Day selector, Play/Pause, `1x`/`4x`/`16x` client playback timer, range timeline scrubber, and `Exit to Live` without calling server `/sim/*` endpoints"
  artifacts:
    - "frontend/src/scenes/VillageScene.ts adds `resetTransientVisuals()` and `applyTick(..., { immediate?: boolean })`"
    - "frontend/src/ui/activityFeed.ts adds `clear()` and `setModeLabel()`"
    - "frontend/src/ui/replayControls.ts implements `ReplayController`"
  key_links:
    - "frontend/src/ui/replayControls.ts calls `fetchReplayDays` and `fetchReplayDay` from `../net/apiClient`"
    - "frontend/src/ui/replayControls.ts dispatches `onApplyTick(msg, immediate)`, `onApplyDialogue`, `onApplyEvent`, `onApplyReflection`, and `onResetTimeline` callbacks"
---

# Plan 5.5: Day Replay Controller, VillageScene Immediate Mode & ActivityFeed Reset

## Objective
Extend `VillageScene.ts` with transient visual cleanup and immediate sprite snapping, add timeline reset helpers to `ActivityFeed`, and implement the client-side `ReplayController` (`frontend/src/ui/replayControls.ts`) supporting Day selection, Play/Pause, 1x/4x/16x playback, scrubbing, and clean exit (`REQ-13`, `NFR-04`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/5/RESEARCH.md
- frontend/src/scenes/VillageScene.ts
- frontend/src/ui/activityFeed.ts
- frontend/src/types/sim.ts
- frontend/src/net/apiClient.ts

## Tasks

<task type="auto">
  <name>Add resetTransientVisuals() and immediate snap mode to VillageScene.ts and clear() to ActivityFeed</name>
  <files>
    frontend/src/scenes/VillageScene.ts
    frontend/src/ui/activityFeed.ts
  </files>
  <action>
    Prepare `VillageScene` and `ActivityFeed` to transition seamlessly between live simulation streaming, timeline scrubber jumps, and day replay playback.

    Steps:
    1. In `frontend/src/scenes/VillageScene.ts`:
       - Add `public resetTransientVisuals(): void`:
         - Call `this.cleanupTransientVisuals()` and `this.speakerDialogueSeq.clear()`.
         - If `this.isReady`, kill active movement tweens on every `visual.container` in `this.agentVisuals.values()` so scrubbing or exiting replay never leaves mid-flight tweens overwriting snapped coordinates.
       - Update `public applyTick(tickMsg: TickMessage, options?: { immediate?: boolean }): void`:
         - If `!this.isReady`, store `this.pendingTick = tickMsg` and return.
         - When `options?.immediate === true`, pass `tweenDuration = 0`; otherwise use `Math.min(450, Math.max(45, (1000 / safeSpeed) * 0.8))`.
         - Update `syncAgentVisual(agent, tickMsg.tick, tweenDuration)`: when `agent.x !== existing.lastX || agent.y !== existing.lastY`, always `this.tweens.killTweensOf(existing.container)`; if `tweenDuration <= 0`, immediately call `existing.container.setPosition(targetPx, targetPy)`, `existing.sprite.setFrame(baseFrame)`, `existing.container.setDepth(10 + agent.y)`, and update `existing.lastX`/`existing.lastY` without adding a tween!
    2. In `frontend/src/ui/activityFeed.ts`:
       - Store `private titleEl: HTMLSpanElement | null = null;` in constructor when creating the header span.
       - Add `public setModeLabel(label: string): void` updating `this.titleEl.textContent`.
       - Add `public clear(emptyText = "Waiting for live events and conversations..."): void` clearing `this.listEl` children and restoring a fresh `.feed-empty` placeholder element.

    AVOID: Creating zero-duration tweens when `immediate` is true (snap synchronously via `setPosition`) or leaving `dialogueTimers` active when resetting visuals.
    USE: `cleanupTransientVisuals()`, `killTweensOf`, and `replaceChildren`.
  </action>
  <verify>
    Run from repo root:
    npm --prefix frontend run typecheck
  </verify>
  <done>
    `VillageScene.resetTransientVisuals()`, `VillageScene.applyTick(..., { immediate })`, `ActivityFeed.clear()`, and `ActivityFeed.setModeLabel()` compile cleanly under strict `tsc --noEmit`.
  </done>
</task>

<task type="auto">
  <name>Build ReplayController scrubber and playback bar in frontend/src/ui/replayControls.ts</name>
  <files>
    frontend/src/ui/replayControls.ts
  </files>
  <action>
    Create `frontend/src/ui/replayControls.ts` implementing client-side day replay loading, timeline indexing, playback timer (1x/4x/16x), range scrubbing, and clean mode entry/exit without touching server `/sim/*` playback state.

    Steps:
    1. Export `ReplayControllerOptions`:
       - `onEnter?: () => void`
       - `onExit?: () => void`
       - `onResetTimeline?: () => void`
       - `onApplyTick: (msg: TickMessage, immediate: boolean) => void`
       - `onApplyDialogue: (msg: DialogueMessage) => void`
       - `onApplyEvent: (msg: EventMessage) => void`
       - `onApplyReflection: (msg: ReflectionMessage) => void`
    2. Export `ReplayController` accepting `(containerEl: HTMLElement | null, options: ReplayControllerOptions)`:
       - Public methods: `isActive(): boolean`, `open(): Promise<void>`, `exit(): void`, `destroy(): void`.
       - Construct replay bar UI purely with `document.createElement` + `textContent`:
         - Badge `REPLAY MODE`
         - Day `<select>` (`Day N (M ticks)`) + Refresh Days button
         - `Play` / `Pause` button
         - Client playback speed buttons `1x` (`1000ms`), `4x` (`250ms`), `16x` (`63ms`)
         - Range scrubber `<input type="range" min="0" max="0" value="0">` + timestamp readout (`Tick X / Y · Sim Time`)
         - Status/error indicator span + `Exit to Live` button
       - Implement timeline indexing when `fetchReplayDay(day)` resolves:
         - Extract all unique sorted ticks present in `log.frames`.
         - Carry forward the latest `TickMessage` for each tick index so every tick step in `tickOrder` has an authoritative `TickMessage` snapshot (using first available `TickMessage` fallback if an out-of-band event preceded tick 0).
         - Bucket `DialogueMessage`, `EventMessage`, and `ReflectionMessage` frames into `eventsByTick: Map<number, ReplayFrame[]>` so both sequential playback and scrubbing show events occurring at that tick.
       - Implement `open()`:
         - Mark `active = true`, remove `.hidden` from `containerEl`, invoke `options.onEnter?.()`, fetch `fetchReplayDays()`, populate Day `<select>`, and load the latest recorded day (or show a helpful `"No replay logs recorded yet"` message if `days.length === 0`).
         - When a day finishes loading in `loadDay(day)`, immediately apply index `0` (`scrubToIndex(0)`) so `VillageScene`, clock readout, and `ActivityFeed` jump cleanly to the start of the selected day right away.
       - Implement `stepForward()` (timer loop):
         - Advance `currentIndex += 1`, apply `TickMessage` with `immediate = false`, dispatch `dialogue`/`event`/`reflection` frames for that tick; stop playback cleanly when reaching the final index.
       - Implement `scrubToIndex(idx)` (on range `input`/`change`):
         - Stop client timer (`playing = false`), invoke `options.onResetTimeline?.()`, apply `TickMessage` with `immediate = true`, and dispatch frames at that tick cleanly.
       - Implement `exit()`:
         - Stop timer, set `active = false`, add `.hidden` to `containerEl`, and invoke `options.onExit?.()`.
       - Guard all async fetches with `requestSeq` and `disposed` flags, and remove all DOM listeners + clear timers in `destroy()`.

    AVOID: Calling `pauseSim()` or `setSimSpeed()` on the backend when entering, playing, or exiting Replay Mode, or allowing stale async `fetchReplayDay` responses to overwrite a newer day selection or an already-exited replay session.
    USE: Pure client-side `setTimeout` playback scheduling, monotonic `requestSeq` checks, and `immediate: true` snapping on scrubber jumps.
  </action>
  <verify>
    Run from repo root (separate commands):
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
  </verify>
  <done>
    `frontend/src/ui/replayControls.ts` implements `ReplayController` with zero `innerHTML`, zero server state mutation, and passes `tsc --noEmit` + `vite build`.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `VillageScene` supports `resetTransientVisuals()` and `applyTick(tickMsg, { immediate: true })` for glitch-free scrubbing and live restoration
- [ ] `ActivityFeed` supports `clear()` and `setModeLabel()` cleanly
- [ ] `ReplayController` renders Day selector, Play/Pause, 1x/4x/16x speed, range scrubber, and Exit to Live backed by `GET /replay` and `GET /replay/{day}` without mutating server simulation state
- [ ] `npm --prefix frontend run typecheck` and `npm --prefix frontend run build` pass

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero TypeScript strict-mode warnings or errors
