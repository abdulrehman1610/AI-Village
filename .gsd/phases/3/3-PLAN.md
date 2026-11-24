---
phase: 3
plan: 3
wave: 1
depends_on: []
files_modified:
  - frontend/src/types/sim.ts
  - frontend/vite.config.ts
  - frontend/src/net/wsClient.ts
  - frontend/src/net/apiClient.ts
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`frontend/src/types/sim.ts` defines and runtime-validates `DialogueMessage`, `EventMessage`, `InjectEventRequest`, and `InjectEventResponse`"
    - "`frontend/src/net/wsClient.ts` dispatches `dialogue` and `event` WebSocket frames to typed callbacks without breaking `tick` handling"
    - "`frontend/src/net/apiClient.ts` provides typed `fetchWorld()` and `injectEvent()` REST helpers, and `frontend/vite.config.ts` proxies `/events` to the backend"
  artifacts:
    - "frontend/src/types/sim.ts exports `DialogueTurn`, `DialogueMessage`, `EventMessage`, `InjectEventRequest`, `InjectEventResponse`, `isDialogueMessage`, and `isEventMessage`"
    - "frontend/src/net/wsClient.ts extends `VillageWsClientCallbacks` with `onDialogue` and `onEvent`"
    - "frontend/src/net/apiClient.ts implements `fetchWorld` and `injectEvent`"
    - "frontend/vite.config.ts includes `'/events'` in `server.proxy`"
  key_links:
    - "frontend/src/net/wsClient.ts imports `isDialogueMessage` and `isEventMessage` from `../types/sim`"
    - "frontend/src/net/apiClient.ts imports `InjectEventRequest`, `InjectEventResponse`, and `WorldInfo` from `../types/sim`"
---

# Plan 3.3: Frontend Phase 3 Types, WebSocket/REST Clients & Vite Proxy

## Objective
Extend the frontend TypeScript contract layer (`frontend/src/types/sim.ts`), WebSocket client (`frontend/src/net/wsClient.ts`), REST client (`frontend/src/net/apiClient.ts`), and Vite dev proxy (`frontend/vite.config.ts`) so Phase 3 UI and Phaser scene modules can receive live `dialogue` and `event` messages and send `POST /events` requests cleanly.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/3/RESEARCH.md
- frontend/src/types/sim.ts
- frontend/src/net/wsClient.ts
- frontend/vite.config.ts
- frontend/package.json

## Tasks

<task type="auto">
  <name>Add DialogueMessage, EventMessage, and EventInject types plus Vite /events proxy</name>
  <files>
    frontend/src/types/sim.ts
    frontend/vite.config.ts
  </files>
  <action>
    Update `frontend/src/types/sim.ts` with Phase 3 wire types and strict runtime type guards, and add `/events` to Vite's backend proxy.

    Steps:
    1. In `frontend/src/types/sim.ts`, add interfaces:
       - `DialogueTurn`: `{ speaker_id: string; speaker_name: string; text: string }`
       - `DialogueMessage`: `{ type: "dialogue"; tick: number; sim_time: string; participants: string[]; participant_names: string[]; location: string | null; turns: DialogueTurn[]; summary: string }`
       - `EventMessage`: `{ type: "event"; id: number | null; tick: number; sim_time: string; text: string; location: string | null; affected_agents: string[] }`
       - `InjectEventRequest`: `{ text: string; location: string | null }`
       - `InjectEventResponse`: `{ id: number | null; tick: number; sim_time: string; text: string; location: string | null; affected_agents: string[] }`
    2. Add runtime type guards in `frontend/src/types/sim.ts`:
       - `isDialogueTurn(data: unknown): data is DialogueTurn`
       - `isDialogueMessage(data: unknown): data is DialogueMessage` (checking `data.type === "dialogue"`, integer `tick`, string `sim_time`, `Array.isArray(data.participants)` of strings, `Array.isArray(data.participant_names)` of strings, `location === null || typeof location === "string"`, `Array.isArray(data.turns) && data.turns.every(isDialogueTurn)`, `typeof data.summary === "string"`)
       - `isEventMessage(data: unknown): data is EventMessage` (checking `data.type === "event"`, `data.id === null || (typeof data.id === "number" && Number.isInteger(data.id))`, integer `tick`, string `sim_time`, string `text`, `location === null || typeof location === "string"`, `Array.isArray(data.affected_agents)` of strings)
    3. In `frontend/vite.config.ts`, add `"/events": { target: "http://127.0.0.1:8000", changeOrigin: true }` inside `server.proxy`.

    AVOID: Using unsafe `as` casts on WebSocket payloads or omitting `"/events"` from `vite.config.ts` (which would cause Vite dev mode `POST /events` to 404).
    USE: Runtime validation predicates (`isDialogueMessage`, `isEventMessage`) matching existing `isTickMessage` style.
  </action>
  <verify>
    Run from repo root (Cwd: repo root):
    npm --prefix frontend run typecheck
  </verify>
  <done>
    `frontend/src/types/sim.ts` exports all Phase 3 types and runtime guards, `frontend/vite.config.ts` proxies `/events`, and `tsc --noEmit` passes cleanly.
  </done>
</task>

<task type="auto">
  <name>Extend VillageWsClient for dialogue/event messages and create REST apiClient</name>
  <files>
    frontend/src/net/wsClient.ts
    frontend/src/net/apiClient.ts
  </files>
  <action>
    Extend `VillageWsClient` to route `dialogue` and `event` frames, and add a typed REST client module in `frontend/src/net/apiClient.ts`.

    Steps:
    1. In `frontend/src/net/wsClient.ts`:
       - Import `isDialogueMessage`, `isEventMessage`, `DialogueMessage`, and `EventMessage` from `../types/sim`.
       - Extend `VillageWsClientCallbacks` with optional callbacks:
         - `onDialogue?: (msg: DialogueMessage) => void;`
         - `onEvent?: (msg: EventMessage) => void;`
       - Inside the `message` listener after `const parsed: unknown = JSON.parse(event.data);`, route:
         - `if (isTickMessage(parsed)) { this.callbacks.onTick(parsed); }`
         - `else if (isDialogueMessage(parsed)) { this.callbacks.onDialogue?.(parsed); }`
         - `else if (isEventMessage(parsed)) { this.callbacks.onEvent?.(parsed); }`
    2. Create `frontend/src/net/apiClient.ts`:
       - Support optional `VITE_API_BASE_URL` env var (defaulting to `""` so same-origin relative paths `/world` and `/events` work via Vite proxy and production serving).
       - Implement `fetchWorld(): Promise<WorldInfo>` calling `GET /world` and throwing an `Error` if `!response.ok`.
       - Implement `injectEvent(payload: InjectEventRequest): Promise<InjectEventResponse>` calling `POST /events` with `headers: { "Content-Type": "application/json" }` and `body: JSON.stringify(payload)`. On `!response.ok`, parse `{ detail?: string }` safely from JSON if present and throw a descriptive `Error`.

    AVOID: Hardcoding `http://127.0.0.1:8000` in `apiClient.ts` (which breaks relative Vite proxy and reverse-proxied deployments) or throwing unhandled errors inside WebSocket `message` listeners.
    USE: Empty-string base URL default with `VITE_API_BASE_URL` override and clean optional callbacks.
  </action>
  <verify>
    Run from repo root (separate commands):
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
  </verify>
  <done>
    `wsClient.ts` dispatches `tick`, `dialogue`, and `event` messages cleanly, `apiClient.ts` exports `fetchWorld` and `injectEvent`, and both `tsc --noEmit` and `vite build` succeed with zero errors.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `frontend/src/types/sim.ts` validates `DialogueMessage` and `EventMessage` at runtime
- [ ] `VillageWsClient` supports optional `onDialogue` and `onEvent` callbacks alongside `onTick`
- [ ] `frontend/src/net/apiClient.ts` exposes `fetchWorld()` and `injectEvent()` and `vite.config.ts` proxies `/events`

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] `npm --prefix frontend run typecheck` and `npm --prefix frontend run build` succeed cleanly
