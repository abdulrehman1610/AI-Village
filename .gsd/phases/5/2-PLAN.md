---
phase: 5
plan: 2
wave: 1
depends_on: []
files_modified:
  - frontend/package.json
  - frontend/package-lock.json
  - frontend/vite.config.ts
  - frontend/src/types/sim.ts
  - frontend/src/net/apiClient.ts
  - frontend/src/net/wsClient.ts
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`chart.js`, `cytoscape`, and `@types/cytoscape` are installed in `frontend/package.json` and `frontend/package-lock.json` cleanly"
    - "`frontend/vite.config.ts` proxies `/metrics` and `/replay` to `http://127.0.0.1:8000`"
    - "`frontend/src/types/sim.ts` defines strict TypeScript interfaces and runtime type guards for `MetricsSnapshot`, `MetricsMessage`, `ReplayDaysResponse`, `ReplayFrame`, and `ReplayLogResponse`"
    - "`apiClient.ts` exposes `fetchMetrics()`, `fetchReplayDays()`, and `fetchReplayDay(day)`, and `wsClient.ts` dispatches `metrics` frames to `onMetrics`"
  artifacts:
    - "frontend/package.json and frontend/package-lock.json include `chart.js`, `cytoscape`, and `@types/cytoscape`"
    - "frontend/vite.config.ts adds `/metrics` and `/replay` proxy entries"
    - "frontend/src/types/sim.ts exports Metrics and Replay types and guards (`isMetricsSnapshot`, `isMetricsMessage`, `isReplayDaysResponse`, `isReplayLogResponse`, `isReplayFrame`)"
    - "frontend/src/net/apiClient.ts and frontend/src/net/wsClient.ts implement guarded REST and WS support"
  key_links:
    - "frontend/src/net/apiClient.ts validates `/metrics`, `/replay`, and `/replay/{day}` responses using guards from `../types/sim`"
    - "frontend/src/net/wsClient.ts validates incoming WS JSON via `isMetricsMessage` before invoking `callbacks.onMetrics`"
---

# Plan 5.2: Frontend Phase 5 Packages, Vite Proxies, Types & API/WS Clients

## Objective
Install `chart.js`, `cytoscape`, and `@types/cytoscape` in `frontend/`, add `/metrics` and `/replay` Vite dev proxies, define strict TypeScript interfaces and runtime guards for Metrics and Day Replay payloads, and wire `apiClient.ts` and `wsClient.ts` (`REQ-10`, `REQ-13`, `REQ-14`, `NFR-04`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/5/RESEARCH.md
- frontend/package.json
- frontend/tsconfig.json
- frontend/vite.config.ts
- frontend/src/types/sim.ts
- frontend/src/net/apiClient.ts
- frontend/src/net/wsClient.ts

## Tasks

<task type="auto">
  <name>Install Chart.js and Cytoscape packages and add Vite /metrics and /replay proxies</name>
  <files>
    frontend/package.json
    frontend/package-lock.json
    frontend/vite.config.ts
  </files>
  <action>
    Install the Phase 5 visualization dependencies in `frontend/` and configure the Vite dev server proxy for the new backend endpoints.

    Steps:
    1. Run `npm --prefix frontend install chart.js cytoscape` and `npm --prefix frontend install -D @types/cytoscape` (as separate commands) so `frontend/package.json` and `frontend/package-lock.json` stay locked and compatible with `npm ci` in CI.
    2. In `frontend/vite.config.ts`, add `"/metrics"` and `"/replay"` entries inside `server.proxy` pointing to `"http://127.0.0.1:8000"` with `changeOrigin: true` (matching `/agents`, `/sim`, and `/relationships`).

    AVOID: Skipping `@types/cytoscape` (Cytoscape ships without strict bundled types and `frontend/tsconfig.json` enforces `"strict": true`) or hand-editing `package-lock.json`.
    USE: `npm --prefix frontend install` commands so `package-lock.json` stays valid for `npm ci`.
  </action>
  <verify>
    Run from repo root (separate commands):
    npm --prefix frontend ls chart.js cytoscape @types/cytoscape
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
  </verify>
  <done>
    `chart.js`, `cytoscape`, and `@types/cytoscape` are recorded in `frontend/package.json` + `frontend/package-lock.json`, `/metrics` and `/replay` proxies exist in `frontend/vite.config.ts`, and `typecheck` + `build` succeed.
  </done>
</task>

<task type="auto">
  <name>Add Metrics and Replay TypeScript interfaces and runtime type guards in frontend/src/types/sim.ts</name>
  <files>
    frontend/src/types/sim.ts
  </files>
  <action>
    Extend `frontend/src/types/sim.ts` with exact TypeScript types and strict runtime type guards matching the Phase 5 backend `MetricsSnapshot`, WS `metrics` envelope, and `ReplayDaysResponse` / `ReplayDayLog` schemas.

    Steps:
    1. Add Metrics interfaces:
       - `PurposeMetrics`: `{ purpose: string; calls: number; cache_hits: number; tokens_in: number; tokens_out: number; total_tokens: number; cost_est: number; avg_latency_ms: number }`
       - `ModelMetrics`: `{ model: string; calls: number; cache_hits: number; tokens_in: number; tokens_out: number; total_tokens: number; cost_est: number; avg_latency_ms: number }`
       - `TickMetricsPoint`: `{ tick: number; calls: number; cache_hits: number; tokens_in: number; tokens_out: number; total_tokens: number; cost_est: number; avg_latency_ms: number; cumulative_tokens: number; cumulative_cost_est: number }`
       - `MetricsSnapshot`: `{ tick: number; sim_time: string; day: number; total_calls: number; cache_hits: number; cache_hit_rate: number; tokens_in: number; tokens_out: number; total_tokens: number; cost_est: number; avg_latency_ms: number; max_latency_ms: number; daily_budget_usd: number; daily_token_limit: number; budget_day: number; budget_tokens_used: number; budget_cost_used: number; by_purpose: PurposeMetrics[]; by_model: ModelMetrics[]; history: TickMetricsPoint[] }`
       - `MetricsMessage`: `MetricsSnapshot & { type: "metrics" }`
    2. Add Replay interfaces:
       - `ReplayDaySummary`: `{ day: number; tick_count: number; frame_count: number; first_tick: number; last_tick: number; first_sim_time: string; last_sim_time: string }`
       - `ReplayDaysResponse`: `{ current_day: number; days: ReplayDaySummary[] }`
       - `ReplayFrame`: `TickMessage | DialogueMessage | EventMessage | ReflectionMessage`
       - `ReplayLogResponse`: `{ day: number; tick_count: number; first_tick: number | null; last_tick: number | null; frames: ReplayFrame[] }`
    3. Implement runtime type guards using existing `isRecord`, `isInteger`, `isFiniteNumber`, `isNullableInteger`, `isTickMessage`, `isDialogueMessage`, `isEventMessage`, and `isReflectionMessage` helpers:
       - `isPurposeMetrics`, `isModelMetrics`, `isTickMetricsPoint`, `isMetricsSnapshot`, `isMetricsMessage`
       - `isReplayDaySummary`, `isReplayDaysResponse`, `isReplayFrame`, `isReplayLogResponse`

    AVOID: Using `any` or unsafe `as` type assertions, or forgetting `isNullableInteger` on `first_tick`/`last_tick` in `ReplayLogResponse`.
    USE: Strict runtime validation for every nested object and array element.
  </action>
  <verify>
    Run from repo root:
    npm --prefix frontend run typecheck
  </verify>
  <done>
    All Metrics and Replay interfaces and runtime guards in `frontend/src/types/sim.ts` pass strict `tsc --noEmit` with zero unused locals/parameters.
  </done>
</task>

<task type="auto">
  <name>Add fetchMetrics, fetchReplayDays, fetchReplayDay to apiClient.ts and onMetrics to wsClient.ts</name>
  <files>
    frontend/src/net/apiClient.ts
    frontend/src/net/wsClient.ts
  </files>
  <action>
    Wire the new REST endpoints and WebSocket message type into the frontend networking layer.

    Steps:
    1. In `frontend/src/net/apiClient.ts`:
       - Import `isMetricsSnapshot`, `isReplayDaysResponse`, `isReplayLogResponse`, `type MetricsSnapshot`, `type ReplayDaysResponse`, and `type ReplayLogResponse` from `../types/sim`.
       - Export `fetchMetrics(): Promise<MetricsSnapshot>` calling `requestJson("/metrics", undefined, isMetricsSnapshot)`.
       - Export `fetchReplayDays(): Promise<ReplayDaysResponse>` calling `requestJson("/replay", undefined, isReplayDaysResponse)`.
       - Export `fetchReplayDay(day: number): Promise<ReplayLogResponse>`: validate `Number.isInteger(day) && day >= 1` (else throw `new Error("Replay day must be a positive integer")`), then call `requestJson(\`/replay/${day}\`, undefined, isReplayLogResponse)`.
    2. In `frontend/src/net/wsClient.ts`:
       - Import `isMetricsMessage` and `type MetricsMessage` from `../types/sim`.
       - Add `onMetrics?: (msg: MetricsMessage) => void;` to `VillageWsClientCallbacks`.
       - In the WebSocket `message` handler, add `else if (isMetricsMessage(parsed)) { this.callbacks.onMetrics?.(parsed); }`.

    AVOID: Bypassing runtime type guards or allowing non-integer/negative day queries to build malformed paths.
    USE: Existing `requestJson` helper in `apiClient.ts` and `isMetricsMessage` in `wsClient.ts`.
  </action>
  <verify>
    Run from repo root (separate commands):
    npm --prefix frontend ls chart.js cytoscape @types/cytoscape
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
  </verify>
  <done>
    `apiClient.ts` and `wsClient.ts` expose typed, runtime-guarded Metrics and Replay helpers, and `npm --prefix frontend run typecheck` + `npm --prefix frontend run build` pass cleanly.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `chart.js`, `cytoscape`, and `@types/cytoscape` are installed with updated `frontend/package-lock.json`
- [ ] `frontend/vite.config.ts` proxies `/metrics` and `/replay` to `http://127.0.0.1:8000`
- [ ] `frontend/src/types/sim.ts` provides strict interfaces and runtime guards for Metrics and Replay payloads
- [ ] `apiClient.ts` and `wsClient.ts` handle `/metrics`, `/replay`, `/replay/{day}`, and WS `metrics` frames and compile cleanly under `tsc --noEmit` and `vite build`

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in existing frontend typecheck or build
