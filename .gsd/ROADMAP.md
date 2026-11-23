---
milestone: v1.0 — AI Village (P0 + P1)
version: 1.0.0
updated: 2026-11-23T23:39:00+05:00
---

# Roadmap

> **Current Phase:** 1 - World, A* Navigation & Real-Time Sync
> **Status:** planning

## Must-Haves (from SPEC)

- [ ] Tile-based village map built in Tiled JSON and rendered in Phaser 3 with named locations and collision layer
- [ ] Hand-written A* pathfinding (`heapq`, Manhattan heuristic) navigating agents without wall clipping or tile overlap
- [ ] 6–10 autonomous agents with SQLite persistence, memory stream, local embeddings, and weighted retrieval scoring (`recency + importance + relevance`)
- [ ] Single schema-enforcing LLM gateway with Pydantic v2 validation, retry, prompt cache, call budget, cost logging, Gemini Flash provider, and deterministic mock provider
- [ ] Full agent cognitive loop: hierarchical daily planning (day → hour → minute), proximity conversations (≤6 turns + summary), god-mode event injection, and threshold-triggered reflections
- [ ] Interactive UI panels: Agent Inspector, Time Controls (Pause/Play/1x/4x/16x), Cytoscape.js Relationship Graph, Chart.js Cost/Token Dashboard, and JSONL Day Replay
- [ ] 100-tick deterministic integration test, passing `ruff` + `mypy` + `pytest` CI pipeline, Docker setup, README, and AI Lab Report

---

## Phases

### Phase 1: World, A* Navigation & Real-Time Sync
**Status:** 🔄 In Progress
**Objective:** Scaffold the monorepo (`backend/` Python FastAPI + `frontend/` Phaser 3 TypeScript Vite), build the Tiled JSON village map with collision layer and named locations, implement custom `heapq` A* pathfinding and the async simulation tick clock/engine, and synchronize 3+ moving agents in real time over WebSocket `/ws` to Phaser 3.
**Requirements:** REQ-01, REQ-02, REQ-03 (initial), NFR-01, NFR-04, NFR-05

**Plans:**
- [ ] TBD by `/plan 1`

---

### Phase 2: Memory Stream, Embeddings, Retrieval Scoring & LLM Gateway
**Status:** ⬜ Not Started
**Objective:** Implement the full SQLite schema (`SQLModel` + `aiosqlite` for all 7 tables), build the schema-enforcing LLM gateway (`gateway.py`, Pydantic schemas, prompt cache, call budget, cost logging, deterministic mock provider, and Gemini Flash provider), expand to 6–10 rich agent personas, and implement the memory stream with local embeddings (`all-MiniLM-L6-v2` + deterministic test embedding) and weighted retrieval scoring (`recency + importance + relevance`).
**Depends on:** Phase 1
**Requirements:** REQ-03, REQ-04, REQ-05, REQ-15, NFR-02, NFR-03

---

### Phase 3: Daily Planning, Conversations & Event Injection (P0 MVP)
**Status:** ⬜ Not Started
**Objective:** Wire the complete agent cognitive loop (Perceive → Remember → Decide → Act) with hierarchical planning (wake-up day plan → hourly blocks → minute actions + replanning on interruption), proximity-triggered turn-by-turn agent conversations (up to 6 turns + memory summarization + WS `dialogue` broadcast), and god-mode event injection (`POST /events` + frontend UI bar) that delivers observations to nearby agents and spreads rumors.
**Depends on:** Phase 2
**Requirements:** REQ-06, REQ-07, REQ-08, NFR-05

---

### Phase 4: Reflection, Relationships, Agent Inspector & Time Controls
**Status:** ⬜ Not Started
**Objective:** Add threshold-triggered agent reflections (salient questions → evidence retrieval → cited insights stored as memories), pairwise relationship affinity and notes updates on interactions, the clickable Agent Inspector frontend panel (`GET /agents/{id}` showing plan, memories, mood, relationships), and simulation time controls (`POST /sim/start`, `/sim/pause`, `/sim/speed` for 1x/4x/16x).
**Depends on:** Phase 3
**Requirements:** REQ-09, REQ-10 (backend), REQ-11, REQ-12

---

### Phase 5: Cost Dashboard, Replay, Relationship Graph, Tests & CI
**Status:** ⬜ Not Started
**Objective:** Build the Chart.js cost/token/latency dashboard (`GET /metrics` + live WS `metrics`), the Cytoscape.js interactive relationship graph view (`GET /relationships`), the JSONL event log writer and day replay mode (`GET /replay/{day}` + UI replay controls), the 100-tick deterministic integration and behavior test suite, and the GitHub Actions CI workflow (`ruff`, `mypy`, `pytest`, frontend build).
**Depends on:** Phase 4
**Requirements:** REQ-10 (graph UI), REQ-13, REQ-14, REQ-16 (CI), NFR-03, NFR-04, NFR-05

---

### Phase 6: Packaging, Documentation, Lab Report & Demo Readiness
**Status:** ⬜ Not Started
**Objective:** Package the application with `Dockerfile`s and `docker-compose.yml` for one-command execution, author `README.md` (<5 command setup, architecture diagram, demo flow), `AGENTS.md`, and the academic AI Lab Report (`docs/report.md` covering PRD Sections 1, 5, 6, and 15), and run full end-to-end verification of a simulated village day.
**Depends on:** Phase 5
**Requirements:** REQ-16

---

## Progress Summary

| Phase | Status | Plans | Complete |
|-------|--------|-------|----------|
| 1 | 🔄 | 0/TBD | — |
| 2 | ⬜ | 0/TBD | — |
| 3 | ⬜ | 0/TBD | — |
| 4 | ⬜ | 0/TBD | — |
| 5 | ⬜ | 0/TBD | — |
| 6 | ⬜ | 0/TBD | — |

---

## Timeline

| Phase | Started | Completed | Duration |
|-------|---------|-----------|----------|
| 1 | 2026-11-23 | — | — |
| 2 | — | — | — |
| 3 | — | — | — |
| 4 | — | — | — |
| 5 | — | — | — |
| 6 | — | — | — |
