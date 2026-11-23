---
phase: 1
plan: 6
wave: 4
depends_on:
  - "2"
  - "3"
  - "5"
files_modified:
  - frontend/src/types/sim.ts
  - frontend/src/net/wsClient.ts
  - frontend/src/scenes/VillageScene.ts
  - frontend/src/main.ts
  - frontend/index.html
  - frontend/src/style.css
  - scripts/verify_phase1_ws.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "Phaser 3 loads map.json, tileset.png, and sprites.png and renders ground, structures, toggleable collision debug layer, and named location labels"
    - "WebSocket client connects to /ws, auto-reconnects on drop, and drives 4+ moving agent sprites smoothly from authoritative server tick coordinates"
    - "End-to-end verification confirms frontend build/typecheck, backend tests/lint/typecheck, and live /ws multi-tick synchronization work together"
  artifacts:
    - "frontend/src/types/sim.ts matches backend TickPayload and WorldInfo JSON schemas"
    - "frontend/src/net/wsClient.ts manages WebSocket /ws connection, parsing, and reconnect backoff"
    - "frontend/src/scenes/VillageScene.ts renders Tiled village map, named location badges, and tweened agent sprites"
    - "frontend/src/main.ts mounts VillageScene and connects VillageWsClient to the DOM HUD"
  key_links:
    - "frontend/src/net/wsClient.ts consumes /ws payloads emitted by backend/api/ws.py"
    - "frontend/src/scenes/VillageScene.ts matches tileset name 'village_tiles' and layers 'ground', 'structures', 'collision', 'locations' in frontend/public/assets/map.json"
---

# Plan 1.6: Phaser 3 Village Renderer, WebSocket Sync & Phase 1 Verification

## Objective
Wire the Phaser 3 `VillageScene` tilemap/sprite renderer and passive WebSocket `/ws` client to the running FastAPI simulation engine, display live simulated time and agent telemetry in the browser HUD, and verify full Phase 1 end-to-end synchronization.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- backend/api/ws.py
- backend/api/rest.py
- backend/sim/engine.py
- frontend/public/assets/map.json
- frontend/src/types/sim.ts

## Tasks

<task type="auto">
  <name>Implement typed WebSocket client and verify payload schema alignment</name>
  <files>
    frontend/src/types/sim.ts
    frontend/src/net/wsClient.ts
  </files>
  <action>
    Ensure `frontend/src/types/sim.ts` matches `backend/sim/engine.py` and `backend/api/rest.py` field-for-field, and implement `frontend/src/net/wsClient.ts` as a passive server-synchronized client.

    Steps:
    1. Review `backend/sim/engine.py` (`TickPayload`, `AgentSnapshot`) and `backend/api/rest.py` (`/world`), updating `frontend/src/types/sim.ts` to add `WsConnectionState = "connecting" | "connected" | "reconnecting" | "disconnected"` and strict type guards `isTickMessage(data: unknown): data is TickMessage`.
    2. Implement `VillageWsClient` in `frontend/src/net/wsClient.ts`:
       - Resolves WebSocket URL from `import.meta.env.VITE_WS_URL` if set, otherwise `${protocol}//${window.location.host}/ws` (`wss:` when `https:`, else `ws:`).
       - Constructor takes callbacks `{ onTick: (msg: TickMessage) => void; onStatusChange?: (status: WsConnectionState) => void }`.
       - `connect()`: opens `WebSocket`, transitions status (`"connecting"` -> `"connected"`), parses incoming JSON safely with `isTickMessage`, invokes `onTick`.
       - On `close` / `error` (unless explicitly `disconnect()`ed): transitions status to `"reconnecting"` and schedules reconnect with capped exponential backoff (`500ms` -> `1000ms` -> `2000ms` -> max `5000ms`).
       - `disconnect()`: stops reconnect timer and closes active socket cleanly.

    AVOID: Computing A* paths, local timers that guess movement, or modifying agent coordinates client-side (CON-01: server owns all state).
    USE: Strict runtime guard `isTickMessage` so malformed JSON never crashes the Phaser render loop.
  </action>
  <verify>
    npm --prefix frontend run typecheck
  </verify>
  <done>
    `frontend/src/types/sim.ts` and `frontend/src/net/wsClient.ts` compile under `tsc --noEmit` with zero errors.
  </done>
</task>

<task type="auto">
  <name>Build Phaser 3 VillageScene renderer and live HUD wiring</name>
  <files>
    frontend/src/scenes/VillageScene.ts
    frontend/src/main.ts
    frontend/index.html
    frontend/src/style.css
  </files>
  <action>
    Implement the Phaser 3 village scene rendering the Tiled map, named location labels, smooth sprite movement, camera controls, and live HUD overlay.

    Steps:
    1. Implement `VillageScene extends Phaser.Scene` in `frontend/src/scenes/VillageScene.ts`:
       - `preload()`: load `this.load.tilemapTiledJSON("village-map", "/assets/map.json")`, `this.load.image("tileset", "/assets/tileset.png")`, and `this.load.spritesheet("villagers", "/assets/sprites.png", { frameWidth: 32, frameHeight: 32 })`.
       - `create()`:
         - Build tilemap `const map = this.make.tilemap({ key: "village-map" })` and `const tileset = map.addTilesetImage("village_tiles", "tileset")` (must match `"village_tiles"` in `map.json`!).
         - Create layers `"ground"`, `"structures"`, and `"collision"` (`collisionLayer.setVisible(false).setAlpha(0.55)`).
         - Register `C` key toggle (`this.input.keyboard?.on("keydown-C", ...)`) to toggle `collisionLayer.visible` for visual debugging.
         - Parse `"locations"` object layer (`map.getObjectLayer("locations")?.objects ?? []`) and render styled Phaser text labels centered over each location (`Cafe`, `Park`, `Market`, `Town Square`, `Bakery`, `Library`, `Home_Maya`, etc.) at depth `20`.
         - Configure camera bounds `(0, 0, map.widthInPixels, map.heightInPixels)`, initial fit zoom (`Math.min(scale.width / map.widthInPixels, scale.height / map.heightInPixels, 1.2)`), middle/left-drag camera panning, and mouse wheel zoom clamped between `0.5` and `2.5`.
         - Replay any cached latest `TickMessage` if received before `create()` finished.
       - `applyTick(tickMsg: TickMessage): void`:
         - If scene is not ready yet, store `pendingTick = tickMsg` and return.
         - Compute tween duration from server speed (`Math.min(450, Math.max(45, (1000 / tickMsg.speed) * 0.8))`).
         - For each `AgentSnapshot` in `tickMsg.agents`:
           - Target pixel center: `px = agent.x * 32 + 16`, `py = agent.y * 32 + 16`.
           - If sprite container doesn't exist yet, create `Phaser.GameObjects.Container(this, px, py, [sprite, nameText])` with `sprite` using frame `agent.sprite_index * 4` (row start in 4x4 spritesheet) and `nameText` (`agent.name`) positioned cleanly above the sprite.
           - If position changed from stored `(lastX, lastY)`: kill existing tweens on container (`this.tweens.killTweensOf(container)`), update walk animation frame cycling (`frame = agent.sprite_index * 4 + (tickMsg.tick % 4)`), and tween `x: px, y: py` smoothly; set container depth `10 + agent.y` for clean overlap ordering.
    2. Update `frontend/src/main.ts`, `frontend/index.html`, and `frontend/src/style.css`:
       - Instantiate `const villageScene = new VillageScene()` and mount `new Phaser.Game({ type: Phaser.AUTO, parent: "game-container", pixelArt: true, scale: { mode: Phaser.Scale.RESIZE, autoCenter: Phaser.Scale.CENTER_BOTH }, scene: [villageScene] })`.
       - Connect `VillageWsClient` calling `villageScene.applyTick(tickMsg)` directly and updating HUD DOM elements (`#ws-status` badge class/text, `#sim-time`, `#sim-tick`, and `#agents-bar` pills showing each agent's `name`, `current_action`, and `(x, y)` coordinates).
       - Display brief controls hint (`Drag to pan · Scroll to zoom · Press C for collision grid`) in the HUD footer/header.

    AVOID: Hardcoding map dimensions or location names in TypeScript instead of reading from Tiled `map.json`, or leaving active tweens un-killed during fast updates.
    USE: `pixelArt: true` in Phaser config so 32x32 tiles and villager sprites stay sharp at any zoom level.
  </action>
  <verify>
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
  </verify>
  <done>
    `npm --prefix frontend run typecheck` and `npm --prefix frontend run build` succeed with 0 errors, producing `frontend/dist` containing bundled Phaser JS and copied `/assets/map.json`, `tileset.png`, and `sprites.png`.
  </done>
</task>

<task type="auto">
  <name>Add Phase 1 end-to-end verification script and run full backend + frontend + /ws suite</name>
  <files>
    scripts/verify_phase1_ws.py
  </files>
  <action>
    Write a clean, cross-platform verification script `scripts/verify_phase1_ws.py` and run full Phase 1 verification across backend tests, static analysis, frontend compilation/bundling, and live FastAPI + WebSocket multi-tick agent synchronization.

    Steps:
    1. Create `scripts/verify_phase1_ws.py` using Python stdlib (`subprocess`, `sys`, `os`, `time`, `json`, `asyncio`, `pathlib`) plus `httpx` and `websockets`:
       - Verify `frontend/dist/index.html`, `frontend/dist/assets/map.json`, `frontend/dist/assets/tileset.png`, and `frontend/dist/assets/sprites.png` exist.
       - Launch Uvicorn (`[sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8011"]`) with `cwd=backend` and `SIM_TICK_SECONDS=0.1` inside a `try/finally` block that terminates and waits on the process cleanly.
       - Poll `GET http://127.0.0.1:8011/health` (up to 10s) until HTTP 200.
       - Assert `GET http://127.0.0.1:8011/world` returns >= 10 named locations (`Cafe`, `Park`, `Market`, `Town Square`, `Home_*`) and `GET /agents` returns 4 agents.
       - Connect via `websockets.connect("ws://127.0.0.1:8011/ws")`, read 6 consecutive `"tick"` messages, assert `tick` increases monotonically, assert every tick has zero duplicate `(x, y)` agent coordinates, and assert at least 3 agents change `(x, y)` coordinates across the observed ticks.
       - Print `"e2e_ws_ok"` summary with tick numbers and moved agent count.
    2. Run each verification command individually (never chain with `&&` on Windows PowerShell).

    AVOID: Leaving a background Uvicorn server running after verification finishes or using `\n` inside inline `python -c` strings.
    USE: Standalone `scripts/verify_phase1_ws.py` with `try/finally` server teardown and sequential single-command invocations.
  </action>
  <verify>
    uv --directory backend run pytest -v
    uv --directory backend run ruff check .
    uv --directory backend run mypy app sim api tests
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
    uv --directory backend run python ../scripts/verify_phase1_ws.py
  </verify>
  <done>
    All pytest tests pass, `ruff` and `mypy` pass cleanly, `tsc --noEmit` and `vite build` pass cleanly, `frontend/dist` includes map/tileset/sprite assets, and `verify_phase1_ws.py` exits 0 printing `e2e_ws_ok` with 3+ agents moving over live `/ws` ticks.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] Phaser 3 renders the Tiled village map (`ground`, `structures`, toggleable `collision`, `locations` labels) from `/assets/map.json`
- [ ] WebSocket `/ws` synchronizes 4 moving agent sprites in real time without frontend pathfinding logic
- [ ] Full backend `pytest`, `ruff`, `mypy`, frontend `tsc --noEmit`, `vite build`, and live `/ws` verification all pass

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in tests
