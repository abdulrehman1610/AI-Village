---
phase: 1
plan: 2
wave: 1
depends_on: []
files_modified:
  - frontend/package.json
  - frontend/tsconfig.json
  - frontend/vite.config.ts
  - frontend/index.html
  - frontend/src/style.css
  - frontend/src/types/sim.ts
  - frontend/src/main.ts
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "Frontend TypeScript + Phaser 3 + Vite workspace installs and compiles cleanly"
    - "Vite dev server proxies /ws and REST endpoints (/health, /world, /agents) to the FastAPI backend"
    - "Shared TypeScript interfaces represent the server-authoritative tick and world state contracts"
  artifacts:
    - "frontend/package.json declares phaser, typescript, and vite with typecheck and build scripts"
    - "frontend/tsconfig.json enables strict TypeScript checking"
    - "frontend/vite.config.ts configures dev server and /ws WebSocket proxy to localhost:8000"
    - "frontend/src/types/sim.ts defines AgentSnapshot, TickMessage, NamedLocationInfo, and WorldInfo"
    - "frontend/src/main.ts boots a clean TypeScript entry point ready for VillageScene"
  key_links:
    - "frontend/vite.config.ts proxies /ws, /health, /world, and /agents to http://127.0.0.1:8000"
---

# Plan 1.2: Frontend Phaser 3 + TypeScript + Vite Scaffold

## Objective
Scaffold the `frontend/` Phaser 3 + TypeScript + Vite application with strict TypeScript config, Vite WebSocket/API proxy rules, base HTML/CSS shell, and shared TypeScript simulation payload types so the village map and WebSocket renderer can build cleanly without touching backend files.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/REQUIREMENTS.md

## Tasks

<task type="auto">
  <name>Configure Phaser 3, TypeScript, and Vite workspace</name>
  <files>
    frontend/package.json
    frontend/tsconfig.json
    frontend/vite.config.ts
  </files>
  <action>
    Create the Node/Vite/TypeScript configuration files in `frontend/` and install npm dependencies.

    Steps:
    1. Create `frontend/package.json` with `"name": "ai-village-frontend"`, `"private": true`, `"version": "0.1.0"`, `"type": "module"`, scripts (`"dev": "vite"`, `"build": "vite build"`, `"preview": "vite preview"`, `"typecheck": "tsc --noEmit"`), dependency `"phaser": "^3.85.2"`, and devDependencies (`"typescript": "^5.6.3"`, `"vite": "^5.4.11"`).
    2. Create `frontend/tsconfig.json` with `"target": "ES2022"`, `"module": "ESNext"`, `"moduleResolution": "bundler"`, `"strict": true`, `"noUnusedLocals": true`, `"noUnusedParameters": true`, `"isolatedModules": true`, `"skipLibCheck": true`, `"noEmit": true`, `"include": ["src"]`.
    3. Create `frontend/vite.config.ts` using `defineConfig` from `vite`, setting `server.port = 5173` and `server.proxy` entries:
       - `"/ws": { target: "ws://127.0.0.1:8000", ws: true, changeOrigin: true }`
       - `"/health": { target: "http://127.0.0.1:8000", changeOrigin: true }`
       - `"/world": { target: "http://127.0.0.1:8000", changeOrigin: true }`
       - `"/agents": { target: "http://127.0.0.1:8000", changeOrigin: true }`
    4. Install dependencies using `npm --prefix frontend install`.

    AVOID: Putting simulation logic or pathfinding packages in `frontend/package.json` because the server is the single source of truth (CON-01).
    USE: `npm --prefix frontend` so commands execute cleanly from repo root without chaining `cd` and `&&`.
  </action>
  <verify>
    npm --prefix frontend ls --depth=0
    npm --prefix frontend exec -- tsc --version
    npm --prefix frontend exec -- vite --version
  </verify>
  <done>
    `frontend/node_modules` is installed with `phaser`, `typescript`, and `vite`, and both `tsc --version` and `vite --version` resolve cleanly.
  </done>
</task>

<task type="auto">
  <name>Create frontend shell, shared simulation types, and minimal Phaser bootstrap</name>
  <files>
    frontend/index.html
    frontend/src/style.css
    frontend/src/types/sim.ts
    frontend/src/main.ts
  </files>
  <action>
    Create the HTML host shell, dark canvas styling, TypeScript interfaces for server WebSocket/REST payloads, and initial Phaser entry point.

    Steps:
    1. Create `frontend/index.html` with title `AI Village`, `<div id="app">`, a clean top HUD container (`#hud`) showing connection pill (`#ws-status`), simulated clock (`#sim-time`), tick readout (`#sim-tick`), and an `#agents-bar` container plus `<div id="game-container">` for Phaser, loading `/src/main.ts`.
    2. Create `frontend/src/style.css` styling full-viewport layout (`#0f172a` background, crisp sans-serif HUD bar at top, centered responsive canvas area, clean status badges).
    3. Create `frontend/src/types/sim.ts` exporting strict TypeScript interfaces:
       - `AgentSnapshot`: `{ id: string; name: string; role: string; sprite_index: number; x: number; y: number; target_location: string | null; current_action: string }`
       - `TickMessage`: `{ type: "tick"; tick: number; sim_time: string; day: number; speed: number; running: boolean; agents: AgentSnapshot[] }`
       - `NamedLocationInfo`: `{ name: string; category: string; anchor_x: number; anchor_y: number; x: number; y: number; width: number; height: number }`
       - `WorldInfo`: `{ width: number; height: number; tile_size: number; locations: NamedLocationInfo[] }`
    4. Create `frontend/src/main.ts` importing `Phaser` and rendering a minimal placeholder `Phaser.Scene` inside `#game-container` (displaying `"AI Village initializing..."`) so `tsc --noEmit` and `vite build` pass end-to-end before Plan 1.6 wires `VillageScene` and `VillageWsClient`.

    AVOID: Using `any` types in `sim.ts` or `main.ts` because strict TypeScript (`strict: true`) is required by NFR-04.
    USE: Explicit interfaces matching the backend WebSocket/REST contract defined in `.gsd/ARCHITECTURE.md`.
  </action>
  <verify>
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
  </verify>
  <done>
    Both `npm --prefix frontend run typecheck` (`tsc --noEmit`) and `npm --prefix frontend run build` (`vite build`) exit 0 and emit `frontend/dist/index.html`.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `frontend/package.json`, `frontend/tsconfig.json`, and `frontend/vite.config.ts` exist and dependencies are installed
- [ ] `frontend/src/types/sim.ts` strictly types server tick and world payloads
- [ ] `tsc --noEmit` and `vite build` pass with zero errors

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in build or typecheck
