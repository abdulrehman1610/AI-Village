---
phase: 4
plan: 3
wave: 1
depends_on: []
files_modified:
  - frontend/vite.config.ts
  - frontend/src/types/sim.ts
  - frontend/src/net/apiClient.ts
  - frontend/src/net/wsClient.ts
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`frontend/vite.config.ts` proxies `/sim` and `/relationships` (alongside `/ws`, `/health`, `/world`, `/agents`, `/events`) to `127.0.0.1:8000`"
    - "`frontend/src/types/sim.ts` defines and runtime-validates `ReflectionMessage`, `SimControlResponse`, `AgentDetail`, and `RelationshipsResponse` without unsafe casts"
    - "`frontend/src/net/apiClient.ts` exposes `startSim`, `pauseSim`, `setSimSpeed`, `fetchAgentDetail`, and `fetchRelationships`, and `VillageWsClient` dispatches `reflection` frames to `onReflection`"
  artifacts:
    - "frontend/vite.config.ts adds `'/sim'` and `'/relationships'` to `server.proxy`"
    - "frontend/src/types/sim.ts exports `ReflectionMessage`, `SimSpeed`, `SimControlResponse`, `AgentPlanStep`, `AgentPlanBlock`, `AgentPlanView`, `AgentMemoryItem`, `AgentRelationshipItem`, `AgentPersonaProfile`, `AgentDetail`, `RelationshipNode`, `RelationshipEdge`, `RelationshipsResponse`, and their runtime type guards"
    - "frontend/src/net/apiClient.ts implements `startSim`, `pauseSim`, `setSimSpeed`, `fetchAgentDetail`, and `fetchRelationships`"
    - "frontend/src/net/wsClient.ts extends `VillageWsClientCallbacks` with `onReflection` and routes `isReflectionMessage` payloads"
  key_links:
    - "frontend/src/net/wsClient.ts imports `isReflectionMessage` and `ReflectionMessage` from `../types/sim`"
    - "frontend/src/net/apiClient.ts validates all Phase 4 REST payloads via type predicates imported from `../types/sim`"
---

# Plan 4.3: Frontend Phase 4 Types, REST/WS Clients & Vite Proxy

## Objective
Extend the frontend TypeScript contract layer (`frontend/src/types/sim.ts`), REST API client (`frontend/src/net/apiClient.ts`), WebSocket client (`frontend/src/net/wsClient.ts`), and Vite dev proxy (`frontend/vite.config.ts`) so Phase 4 UI modules can send time controls, fetch Agent Inspector details and relationships, and react to live `reflection` WebSocket broadcasts cleanly.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/4/RESEARCH.md
- frontend/vite.config.ts
- frontend/src/types/sim.ts
- frontend/src/net/apiClient.ts
- frontend/src/net/wsClient.ts
- frontend/tsconfig.json

## Tasks

<task type="auto">
  <name>Add Vite proxies and Phase 4 TypeScript interfaces with runtime type guards</name>
  <files>
    frontend/vite.config.ts
    frontend/src/types/sim.ts
  </files>
  <action>
    Update `frontend/vite.config.ts` to proxy Phase 4 backend prefixes and add strict TypeScript types + runtime validators in `frontend/src/types/sim.ts`.

    Steps:
    1. In `frontend/vite.config.ts`:
       - Add `"/sim": { target: "http://127.0.0.1:8000", changeOrigin: true }` and `"/relationships": { target: "http://127.0.0.1:8000", changeOrigin: true }` to `server.proxy`. (Keep `"/agents"` which already prefix-matches `/agents/{id}`.)
    2. In `frontend/src/types/sim.ts`:
       - Extend `AgentSnapshot` with `mood?: string;` and update `isAgentSnapshot` so `data.mood === undefined || typeof data.mood === "string"`.
       - Add `SimSpeed = 1 | 4 | 16` and `SimControlResponse`: `{ running: boolean; speed: number; tick: number; sim_time: string; day: number }`.
       - Add `ReflectionMessage`: `{ type: "reflection"; tick: number; sim_time: string; agent_id: string; agent_name: string; insight: string; cited_memory_ids: number[]; mood?: string }`.
       - Add Agent Inspector types matching backend `GET /agents/{id}`:
         - `AgentPersonaProfile`: `{ id: string; name: string; age: number; role: string; traits: string[]; bio: string; home_location: string; starting_goals: string[] }`
         - `AgentPlanStep`: `{ duration_minutes: number; location: string; action: string; start_tick: number; end_tick: number; arrived: boolean }`
         - `AgentPlanBlock`: `{ start_hour: number; end_hour: number; location: string; description: string; hourly_focus: string | null; actions: AgentPlanStep[] }`
         - `AgentPlanView`: `{ day: number | null; active_block_index: number; active_minute_index: number; hourly_focus: string | null; current_step: AgentPlanStep | null; daily_plan: AgentPlanBlock[] }`
         - `AgentMemoryItem`: `{ id: number | null; type: string; text: string; importance: number; created_tick: number; last_access_tick: number; cited_memory_ids: number[] }`
         - `AgentRelationshipItem`: `{ peer_id: string; peer_name: string; affinity: number; notes: string; last_interaction_tick: number }`
         - `AgentDetail`: `{ id: string; name: string; role: string; sprite_index: number; x: number; y: number; home_location: string; current_location: string; target_location: string | null; current_action: string; mood: string; accumulated_importance: number; reflection_threshold: number; persona: AgentPersonaProfile; plan: AgentPlanView; recent_memories: AgentMemoryItem[]; top_memories: AgentMemoryItem[]; reflections: AgentMemoryItem[]; relationships: AgentRelationshipItem[] }`
       - Add Relationships graph types matching backend `GET /relationships`:
         - `RelationshipNode`: `{ id: string; name: string; role: string; mood: string }`
         - `RelationshipEdge`: `{ agent_a: string; agent_b: string; agent_a_name: string; agent_b_name: string; affinity: number; notes: string; last_interaction_tick: number }`
         - `RelationshipsResponse`: `{ nodes: RelationshipNode[]; edges: RelationshipEdge[] }`
       - Export runtime type predicates: `isReflectionMessage`, `isSimControlResponse`, `isAgentDetail`, and `isRelationshipsResponse` (using small composable sub-guards with zero `any` or unsafe `as` casts).

    AVOID: Making `AgentSnapshot.mood` strictly required in `isAgentSnapshot` if an early/test tick omits it, or forgetting `cited_memory_ids` / `last_interaction_tick` integer/number checks.
    USE: Strict type predicates matching existing `isTickMessage` / `isEventMessage` style and `number.isInteger` / `Number.isFinite` checks.
  </action>
  <verify>
    Run from repo root (Cwd: repo root):
    npm --prefix frontend run typecheck
  </verify>
  <done>
    `frontend/vite.config.ts` proxies `/sim` and `/relationships`, `frontend/src/types/sim.ts` exports all Phase 4 types and runtime guards, and `tsc --noEmit` passes with zero errors.
  </done>
</task>

<task type="auto">
  <name>Add Phase 4 REST methods to apiClient and reflection dispatch to wsClient</name>
  <files>
    frontend/src/net/apiClient.ts
    frontend/src/net/wsClient.ts
  </files>
  <action>
    Wire the new REST endpoints into `frontend/src/net/apiClient.ts` and `reflection` frame dispatching into `frontend/src/net/wsClient.ts`.

    Steps:
    1. In `frontend/src/net/apiClient.ts`:
       - Import `AgentDetail`, `RelationshipsResponse`, `SimControlResponse`, `SimSpeed`, `isAgentDetail`, `isRelationshipsResponse`, and `isSimControlResponse` from `../types/sim`.
       - Export `async function startSim(): Promise<SimControlResponse>` calling `POST /sim/start`.
       - Export `async function pauseSim(): Promise<SimControlResponse>` calling `POST /sim/pause`.
       - Export `async function setSimSpeed(speed: SimSpeed): Promise<SimControlResponse>` calling `POST /sim/speed` with JSON body `{ speed }`.
       - Export `async function fetchAgentDetail(agentId: string): Promise<AgentDetail>` calling `GET /agents/${encodeURIComponent(agentId)}`.
       - Export `async function fetchRelationships(): Promise<RelationshipsResponse>` calling `GET /relationships`.
       - Reuse the existing `requestJson<T>` helper so error-detail extraction and runtime validation remain consistent across all endpoints.
    2. In `frontend/src/net/wsClient.ts`:
       - Import `isReflectionMessage` and `type ReflectionMessage` from `../types/sim`.
       - Extend `VillageWsClientCallbacks` with `onReflection?: (msg: ReflectionMessage) => void;`.
       - Inside the `"message"` event listener, add `else if (isReflectionMessage(parsed)) { this.callbacks.onReflection?.(parsed); }`.

    AVOID: Duplicating `fetch` + error-parsing boilerplate across the 5 new REST helpers or hardcoding `http://127.0.0.1:8000`.
    USE: Existing `requestJson` + `resolveApiBaseUrl()` and `encodeURIComponent(agentId)`.
  </action>
  <verify>
    Run from repo root (separate commands):
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
  </verify>
  <done>
    `apiClient.ts` exports `startSim`, `pauseSim`, `setSimSpeed`, `fetchAgentDetail`, and `fetchRelationships`, `wsClient.ts` dispatches `reflection` messages, and `tsc --noEmit` + `vite build` pass cleanly.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `frontend/vite.config.ts` proxies `/sim` and `/relationships` to the backend
- [ ] `frontend/src/types/sim.ts` validates `ReflectionMessage`, `SimControlResponse`, `AgentDetail`, and `RelationshipsResponse` at runtime
- [ ] `frontend/src/net/apiClient.ts` and `wsClient.ts` expose all Phase 4 REST and WebSocket operations cleanly

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] `npm --prefix frontend run typecheck` and `npm --prefix frontend run build` succeed with zero errors
