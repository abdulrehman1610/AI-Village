---
phase: 5
plan: 4
wave: 2
depends_on:
  - "2"
files_modified:
  - frontend/src/ui/relationshipGraph.ts
  - frontend/src/ui/metricsDashboard.ts
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`RelationshipGraphModal` fetches `GET /relationships`, renders an interactive Cytoscape.js network with villager nodes (name, role, mood) and affinity-colored/thickness-scaled edges, displays edge notes/metadata on click, invokes `onSelectAgent` when tapping a villager node, and resizes/fits via `requestAnimationFrame` after un-hiding"
    - "`MetricsDashboardPanel` fetches `GET /metrics` on open and applies live WS `metrics` messages, rendering KPI cards (calls, cache hit rate, tokens in/out, cost, budget usage, avg/max latency) and responsive Chart.js v4 charts (token/cost history, calls/tokens by purpose, average latency + model summary) without `display: none` 0x0 canvas bugs"
    - "Both panels construct all DOM nodes safely using `document.createElement` and `textContent` (zero `innerHTML`) and pass strict `tsc --noEmit`"
  artifacts:
    - "frontend/src/ui/relationshipGraph.ts implements `RelationshipGraphModal` powered by `cytoscape`"
    - "frontend/src/ui/metricsDashboard.ts implements `MetricsDashboardPanel` powered by tree-shaken `chart.js`"
  key_links:
    - "frontend/src/ui/relationshipGraph.ts calls `fetchRelationships()` from `../net/apiClient` and notifies `options.onSelectAgent`"
    - "frontend/src/ui/metricsDashboard.ts calls `fetchMetrics()` from `../net/apiClient` and consumes `MetricsMessage` live updates"
---

# Plan 5.4: Cytoscape.js Relationship Graph & Chart.js Cost Dashboard Components

## Objective
Build the interactive Cytoscape.js Relationship Graph panel (`frontend/src/ui/relationshipGraph.ts`) and the live Chart.js Cost, Token & Latency Dashboard panel (`frontend/src/ui/metricsDashboard.ts`) using strict TypeScript and XSS-safe DOM rendering (`REQ-10`, `REQ-14`, `NFR-04`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/5/RESEARCH.md
- frontend/tsconfig.json
- frontend/src/types/sim.ts
- frontend/src/net/apiClient.ts
- frontend/src/ui/agentInspector.ts

## Tasks

<task type="auto">
  <name>Build interactive Cytoscape.js RelationshipGraphModal in frontend/src/ui/relationshipGraph.ts</name>
  <files>
    frontend/src/ui/relationshipGraph.ts
  </files>
  <action>
    Implement `frontend/src/ui/relationshipGraph.ts` rendering the village social network with Cytoscape.js, affinity-colored edges, node/edge inspection, and click-to-inspect callbacks.

    Steps:
    1. Export `RelationshipGraphOptions`: `{ onSelectAgent?: (agentId: string) => void; onClose?: () => void }`.
    2. Export `RelationshipGraphModal`:
       - Methods: `open(): Promise<void>`, `close(): void`, `isOpen(): boolean`, `refresh(): Promise<void>`, `handleDialogue(): void` (triggers throttled refresh if currently open), `destroy(): void`.
       - Construct header (`Relationship Network`, node/edge summary pill, Refresh button, Close button `×`), legend strip (`Positive` green `#10b981`, `Neutral` slate `#94a3b8`, `Negative` red `#ef4444`), graph viewport container (`div.graph-canvas`), empty/status banner, and selection detail card (`div.graph-detail`) purely using `document.createElement` and `textContent` (no `innerHTML`).
       - Fetch `fetchRelationships()` on open/refresh with a monotonic `requestSeq` guard to discard stale async responses.
       - Remove `.hidden` before initializing/updating Cytoscape, then inside `requestAnimationFrame` initialize or update `cytoscape({ container, elements, layout, style })` and call `cy.resize(); cy.fit(undefined, 28);` so the canvas never renders at `0x0`.
       - Configure node styling (labeled with villager `name` + `mood` tint/border, draggable, clear selected highlight) and edge styling (`line-color` green `#10b981` for `affinity > 0.05`, red `#ef4444` for `affinity < -0.05`, slate `#94a3b8` otherwise; edge `width` scaled `2 + Math.min(1, Math.abs(affinity)) * 5`; label displaying signed affinity `+0.25`).
       - Bind `cy.on("tap", "node", ...)` to display the clicked villager's profile & connected relationships in `.graph-detail` AND invoke `this.options.onSelectAgent?.(nodeId)`.
       - Bind `cy.on("tap", "edge", ...)` to display `agent_a_name ↔ agent_b_name`, signed affinity score, `last_interaction_tick`, and `notes` in `.graph-detail`.
       - Listen to `window.addEventListener("resize", ...)` when open and clean up `cy.destroy()` + DOM listeners inside `destroy()`.

    AVOID: Using `innerHTML`, initializing Cytoscape while the panel has `display: none`, or leaving Cytoscape `Core` instances/listeners leaked after `destroy()`.
    USE: `document.createElement` + `textContent`, `circle` layout (deterministic non-overlapping 8-node layout while keeping nodes grabbable), and `requestAnimationFrame` resize/fit.
  </action>
  <verify>
    Run from repo root:
    npm --prefix frontend run typecheck
  </verify>
  <done>
    `frontend/src/ui/relationshipGraph.ts` compiles cleanly under `tsc --noEmit` with strict `@types/cytoscape` typing and zero unused locals/parameters.
  </done>
</task>

<task type="auto">
  <name>Build live Chart.js MetricsDashboardPanel in frontend/src/ui/metricsDashboard.ts</name>
  <files>
    frontend/src/ui/metricsDashboard.ts
  </files>
  <action>
    Implement `frontend/src/ui/metricsDashboard.ts` rendering KPI telemetry cards, daily budget progress, and 3 responsive Chart.js v4 visualizations fed by `GET /metrics` and live WS `metrics` frames.

    Steps:
    1. Import and explicitly register only needed Chart.js v4 components (`Chart`, `LineController`, `BarController`, `CategoryScale`, `LinearScale`, `PointElement`, `LineElement`, `BarElement`, `Tooltip`, `Legend`, `Filler`) so bundle size stays minimal.
    2. Export `MetricsDashboardOptions`: `{ onClose?: () => void }`.
    3. Export `MetricsDashboardPanel`:
       - Methods: `open(): Promise<void>`, `close(): void`, `isOpen(): boolean`, `refresh(): Promise<void>`, `applyMetrics(msg: MetricsMessage): void`, `destroy(): void`.
       - Build DOM purely via `document.createElement` and `textContent`:
         - Header (`LLM Cost & Telemetry`, live `Tick · Sim Time` badge, Refresh button, Close button `×`).
         - KPI card grid (`Total Calls`, `Cache Hit Rate`, `Total Tokens`, `Estimated Cost`, `Avg Latency`, `Max Latency`) plus daily token/USD budget bar.
         - Three chart cards, each wrapping `<canvas>` inside a fixed-height container (`div.metrics-chart-box`):
           1. **Tokens Over Time** (`Chart<"line">` over `history`: `tokens_in` + `tokens_out` per tick or cumulative tokens, labeled `Tick N`).
           2. **Tokens & Calls by Purpose** (`Chart<"bar">` over `by_purpose`: `total_tokens` & `calls`).
           3. **Average Latency by Purpose (ms)** (`Chart<"bar">` over `by_purpose`: `avg_latency_ms`).
         - Compact **By Model** summary table (`Model`, `Calls`, `Cache Hits`, `Tokens`, `Avg ms`, `Cost USD`) showing graceful empty state when `by_model` is empty.
       - When `applyMetrics(msg)` arrives, always store `this.latestSnapshot = msg`. If currently open (`this.isOpen()`), update KPI cards, budget meter, model table, and Chart.js datasets in-place using `chart.update("none")` (no flicker or canvas teardown!); if hidden, defer DOM/Chart rendering until `open()` removes `.hidden` and creates/updates charts inside `requestAnimationFrame` (`chart.resize()`).
       - Cleanly `destroy()` all Chart instances and event listeners in `destroy()`.

    AVOID: Registering `Chart.register(...registerables)` (bloats bundle), leaving `maintainAspectRatio: true` without fixed-height `.metrics-chart-box`, or using `innerHTML`.
    USE: Explicit tree-shaken Chart.js imports, `.update("none")`, `requestAnimationFrame` resize after un-hiding, and XSS-safe DOM updates.
  </action>
  <verify>
    Run from repo root (separate commands):
    npm --prefix frontend run typecheck
    npm --prefix frontend run build
  </verify>
  <done>
    `frontend/src/ui/metricsDashboard.ts` compiles cleanly under strict `tsc --noEmit` and bundles cleanly via `vite build`.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `RelationshipGraphModal` renders Cytoscape.js nodes & affinity-colored edges, shows edge notes on tap, triggers `onSelectAgent` on node tap, and handles resize after un-hiding
- [ ] `MetricsDashboardPanel` renders live KPI cards, budget progress, model breakdown table, and 3 Chart.js v4 charts updated via `GET /metrics` and WS `metrics`
- [ ] Both modules avoid `innerHTML`, avoid `any`, and pass `npm --prefix frontend run typecheck` and `vite build`

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero TypeScript strict-mode warnings or errors
