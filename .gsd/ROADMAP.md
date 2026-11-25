---
milestone: v1.0 — AI Village (P0 + P1)
version: 1.0.0
updated: 2026-11-23T23:39:00+05:00
---

# Roadmap

> **Current Phase:** Complete (All 6 Phases Verified — Milestone v1.0 Shipped)
> **Status:** verified

## Must-Haves (from SPEC)

- [x] Tile-based village map built in Tiled JSON and rendered in Phaser 3 with named locations and collision layer
- [x] Hand-written A* pathfinding (`heapq`, Manhattan heuristic) navigating agents without wall clipping or tile overlap
- [x] 6–10 autonomous agents with SQLite persistence, memory stream, local embeddings, and weighted retrieval scoring (`recency + importance + relevance`)
- [x] Single schema-enforcing LLM gateway with Pydantic v2 validation, retry, prompt cache, call budget, cost logging, Gemini Flash provider, and deterministic mock provider
- [x] Full agent cognitive loop: hierarchical daily planning (day → hour → minute), proximity conversations (≤6 turns + summary), god-mode event injection, and threshold-triggered reflections
- [x] Interactive UI panels: Agent Inspector, Time Controls (Pause/Play/1x/4x/16x), Cytoscape.js Relationship Graph, Chart.js Cost/Token Dashboard, and JSONL Day Replay
- [x] 100-tick deterministic integration test, passing `ruff` + `mypy` + `pytest` CI pipeline, Docker setup, README, and AI Lab Report

---

## Phases

### Phase 1: World, A* Navigation & Real-Time Sync
**Status:** ✅ Complete
**Objective:** Scaffold the monorepo (`backend/` Python FastAPI + `frontend/` Phaser 3 TypeScript Vite), build the Tiled JSON village map with collision layer and named locations, implement custom `heapq` A* pathfinding and the async simulation tick clock/engine, and synchronize 3+ moving agents in real time over WebSocket `/ws` to Phaser 3.
**Requirements:** REQ-01, REQ-02, REQ-03 (initial), NFR-01, NFR-04, NFR-05

**Plans:**
- [x] Plan 1.1: Scaffold root config, Python 3.12 FastAPI pyproject, and Settings (Wave 1)
- [x] Plan 1.2: Scaffold Phaser 3 + TypeScript + Vite frontend and shared payload types (Wave 1)
- [x] Plan 1.3: Generate Tiled JSON village map/assets and implement WorldMap loader (Wave 2)
- [x] Plan 1.4: Implement custom heapq A* pathfinder and SimClock with unit tests (Wave 2)
- [x] Plan 1.5: Build async SimulationEngine, 4 seeded agents, REST endpoints, and WebSocket /ws (Wave 3)
- [x] Plan 1.6: Wire Phaser 3 VillageScene renderer, /ws client, HUD, and e2e verification (Wave 4)

---

### Phase 2: Memory Stream, Embeddings, Retrieval Scoring & LLM Gateway
**Status:** ✅ Complete
**Objective:** Implement the full SQLite schema (`SQLModel` + `aiosqlite` for all 7 tables), build the schema-enforcing LLM gateway (`gateway.py`, Pydantic schemas, prompt cache, call budget, cost logging, deterministic mock provider, and Gemini Flash provider), expand to 6–10 rich agent personas, and implement the memory stream with local embeddings (`all-MiniLM-L6-v2` + deterministic test embedding) and weighted retrieval scoring (`recency + importance + relevance`).
**Depends on:** Phase 1
**Requirements:** REQ-03, REQ-04, REQ-05, REQ-15, NFR-02, NFR-03

**Plans:**
- [x] Plan 2.1: Install CPU-only Phase 2 dependencies, extend Settings/.env.example, implement async Database and all 7 SQLModel tables (Wave 1)
- [x] Plan 2.2: Implement Pydantic v2 LLM schemas, LLMProvider protocol, MockProvider, GeminiProvider, and LLMGateway (Wave 2)
- [x] Plan 2.3: Implement DeterministicEmbeddingProvider, SentenceTransformerEmbeddingProvider, MemoryStore, and weighted MemoryRetriever (Wave 2)
- [x] Plan 2.4: Define 8 rich AgentPersona villagers, expand sprites.png to 8 rows (128x256), and add frame wrapping in VillageScene.ts (Wave 2)
- [x] Plan 2.5: Wire 8 personas, Database, MemoryStore, MemoryRetriever, and LLMGateway into SimulationEngine and FastAPI lifespan (Wave 3)

---

### Phase 3: Daily Planning, Conversations & Event Injection (P0 MVP)
**Status:** ✅ Complete
**Objective:** Wire the complete agent cognitive loop (Perceive → Remember → Decide → Act) with hierarchical planning (wake-up day plan → hourly blocks → minute actions + replanning on interruption), proximity-triggered turn-by-turn agent conversations (up to 6 turns + memory summarization + WS `dialogue` broadcast), and god-mode event injection (`POST /events` + frontend UI bar) that delivers observations to nearby agents and spreads rumors.
**Depends on:** Phase 2
**Requirements:** REQ-06, REQ-07, REQ-08, NFR-05

**Plans:**
- [x] Plan 3.1: Add Replan/Hourly LLM schemas, prompt templates, gateway helpers, and rumor-preserving MockProvider (Wave 1)
- [x] Plan 3.2: Add MemoryStore conversation, event, and relationship query methods with unit tests (Wave 1)
- [x] Plan 3.3: Add frontend Dialogue/Event types, WS callbacks, REST apiClient, and Vite /events proxy (Wave 1)
- [x] Plan 3.4: Implement hierarchical DailyPlanner, location canonicalization, and AgentBrain cognitive loop (Wave 2)
- [x] Plan 3.5: Implement proximity ConversationManager with dual cooldowns, memory summaries, and 2-hop rumor spread (Wave 2)
- [x] Plan 3.6: Integrate cognitive loop, conversations, POST /events, and WS broadcasts into SimulationEngine and FastAPI (Wave 3)
- [x] Plan 3.7: Render depth>=60 speech bubbles, event pulses, ActivityFeed, God-Mode UI, and input-guarded keydown-C (Wave 4)
- [x] Plan 3.8: Gap closure — Guard MockProvider urgent rumor extraction against seeded persona bios and verify 80-tick peaceful baseline stability (Gap Closure)

---

### Phase 4: Reflection, Relationships, Agent Inspector & Time Controls
**Status:** ✅ Complete
**Objective:** Add threshold-triggered agent reflections (salient questions → evidence retrieval → cited insights stored as memories), pairwise relationship affinity and notes updates on interactions, the clickable Agent Inspector frontend panel (`GET /agents/{id}` showing plan, memories, mood, relationships), and simulation time controls (`POST /sim/start`, `/sim/pause`, `/sim/speed` for 1x/4x/16x).
**Depends on:** Phase 3
**Requirements:** REQ-09, REQ-10 (backend), REQ-11, REQ-12

**Plans:**
- [x] Plan 4.1: Add reflection prompts, mood schema fields, LLMGateway reflection helpers, and mood/topic-aware MockProvider (Wave 1)
- [x] Plan 4.2: Add Settings.reflection_threshold, AgentRecord.mood with idempotent SQLite migration, and canonical relationship upserts (Wave 1)
- [x] Plan 4.3: Add frontend Phase 4 types/runtime guards, REST apiClient helpers, WS reflection dispatch, and Vite proxies (Wave 1)
- [x] Plan 4.4: Implement ReflectionManager, AgentBrain plan/reflection importance accounting, and ConversationManager mood/relationship updates (Wave 2)
- [x] Plan 4.5: Add HUD TimeControls, drag-safe sprite/chip selection, left-docked AgentInspector, and reflection UI/Phaser cues (Wave 2)
- [x] Plan 4.6: Wire ReflectionManager, agent mood sync, and interruptible start/pause/speed controls into SimulationEngine and main.py (Wave 3)
- [x] Plan 4.7: Implement /sim/*, /agents/{id}, and /relationships REST endpoints plus Phase 4 offline integration and full-stack verification (Wave 4)

---

### Phase 5: Cost Dashboard, Replay, Relationship Graph, Tests & CI
**Status:** ✅ Complete
**Objective:** Build the Chart.js cost/token/latency dashboard (`GET /metrics` + live WS `metrics`), the Cytoscape.js interactive relationship graph view (`GET /relationships`), the JSONL event log writer and day replay mode (`GET /replay/{day}` + UI replay controls), the 100-tick deterministic integration and behavior test suite, and the GitHub Actions CI workflow (`ruff`, `mypy`, `pytest`, frontend build).
**Depends on:** Phase 4
**Requirements:** REQ-10 (graph UI), REQ-13, REQ-14, REQ-16 (CI), NFR-03, NFR-04, NFR-05

**Plans:**
- [x] Plan 5.1: Add Settings.replay_log_dir, non-blocking ReplayLogger, and LLMGateway.get_metrics_snapshot() with unit tests (Wave 1)
- [x] Plan 5.2: Install chart.js/cytoscape/@types/cytoscape, add Vite /metrics+/replay proxies, strict TS guards, apiClient & wsClient hooks (Wave 1)
- [x] Plan 5.3: Wire ReplayLogger & WS metrics broadcasts into SimulationEngine/main.py, expose /metrics+/replay/{day}, update WS allowlists (Wave 2)
- [x] Plan 5.4: Build Cytoscape.js RelationshipGraphModal and live Chart.js MetricsDashboardPanel components (Wave 2)
- [x] Plan 5.5: Add VillageScene reset/immediate-snap hooks, ActivityFeed.clear(), and client-side ReplayController scrubber (Wave 2)
- [x] Plan 5.6: Integrate HUD tool toggles, drawer panels, Replay bar, and live/replay lastLiveTick gating in index.html/style.css/main.ts (Wave 3)
- [x] Plan 5.7: Author 100-tick invariant & determinism suite, .github/workflows/ci.yml, and run full local verification gate (Wave 4)

---

### Phase 6: Packaging, Documentation, Lab Report & Demo Readiness
**Status:** ✅ Complete
**Objective:** Package the application with `Dockerfile`s and `docker-compose.yml` for one-command execution, author `README.md` (<5 command setup, architecture diagram, demo flow), `AGENTS.md`, and the academic AI Lab Report (`docs/report.md` covering PRD Sections 1, 5, 6, and 15), and run full end-to-end verification of a simulated village day.
**Depends on:** Phase 5
**Requirements:** REQ-16

**Plans:**
- [x] Plan 6.1: Package backend/frontend via Docker, Nginx reverse proxy (/ws + 8 REST prefixes), contract test, and CI compose validation (Wave 1)
- [x] Plan 6.2: Run 1,440-tick Day 1->2 simulation verification + empirical telemetry export, sync docs/PRD.md, and generate docs/architecture.png & docs/demo.gif (Wave 1)
- [x] Plan 6.3: Author docs/report.md (PRD 1/5/6/15 + empirical metrics), AGENTS.md, and README.md, and pass full Milestone v1.0 verification gate (Wave 2)

---

## Progress Summary

| Phase | Status | Plans | Complete |
|-------|--------|-------|----------|
| 1 | ✅ | 6/6 | 100% |
| 2 | ✅ | 5/5 | 100% |
| 3 | ✅ | 8/8 | 100% |
| 4 | ✅ | 7/7 | 100% |
| 5 | ✅ | 7/7 | 100% |
| 6 | ✅ | 3/3 | 100% |

---

## Timeline

| Phase | Started | Completed | Duration |
|-------|---------|-----------|----------|
| 1 | 2026-11-23 | 2026-11-24 | ~50m |
| 2 | 2026-11-24 | 2026-11-24 | ~70m |
| 3 | 2026-11-24 | 2026-11-24 | ~90m |
| 4 | 2026-11-24 | 2026-11-25 | ~55m |
| 5 | 2026-11-25 | 2026-11-25 | ~75m |
| 6 | 2026-11-25 | 2026-11-26 | ~75m |
