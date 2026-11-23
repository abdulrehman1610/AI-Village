---
milestone: v1.0 — AI Village (P0 + P1)
updated: 2026-11-23T23:39:00+05:00
---

# Requirements

## Overview

Formal requirements derived from `.gsd/SPEC.md` and `AI Village Product Requirements Document.md` for traceability and verification across all 6 phases.

---

## Functional Requirements

| ID | Requirement | Source | Phase | Status |
|----|-------------|--------|-------|--------|
| REQ-01 | **Tile-Based World & Phaser Rendering (F1)**: Render a 2D town tilemap in Phaser 3 from a Tiled JSON map with distinct collision layer and named locations (Cafe, Park, Market, Homes, etc.) and smooth agent sprite rendering. | SPEC F1 | 1 | Pending |
| REQ-02 | **Custom A* Pathfinding (F2)**: Hand-written `heapq` A* search with Manhattan distance heuristic on a 4-way grid that routes agents between named locations while respecting wall collisions and tile occupancy rules. | SPEC F2 | 1 | Pending |
| REQ-03 | **Agent Personas & World State (F3)**: Define 6–10 rich agent personas (id, name, age, job, traits, home location, starting goals) persisted in SQLite (`agents` table) and synchronized live over WebSocket `/ws`. | SPEC F3 | 1, 2 | Pending |
| REQ-04 | **Memory Stream Storage (F4)**: Persist agent memories (`observation`, `plan`, `conversation`, `reflection`) in SQLite (`memories` table) with created tick, last-access tick, importance (1–10), and embedding vector blob. | SPEC F4 | 2 | Pending |
| REQ-05 | **Memory Retrieval Scoring (F5)**: Score and retrieve top-$k$ ($k=8$) memories using min-max normalized `w_r * recency + w_i * importance + w_v * relevance` with exponential recency decay (0.995 per simulated hour) and NumPy cosine similarity over `all-MiniLM-L6-v2` embeddings. | SPEC F5 | 2 | Pending |
| REQ-06 | **Hierarchical Daily Planning (F6)**: Generate wake-up day plans (5–8 broad items) decomposed into hourly blocks and minute-level actions, with automatic replanning of the remaining day upon interruptions (events or conversations). | SPEC F6 | 3 | Pending |
| REQ-07 | **Agent-to-Agent Conversation (F7)**: Trigger proximity dialogues (within 2 tiles, both free, cooldown elapsed) where LLM decides initiation, generates up to 6 turns grounded in retrieved memories, broadcasts `dialogue` WS messages, and stores a conversation summary for both agents. | SPEC F7 | 3 | Pending |
| REQ-08 | **God-Mode Event Injection (F8)**: Provide `POST /events` and a frontend UI control allowing viewers to inject free-text events at an optional location, creating observations for nearby agents and broadcasting `event` WS messages. | SPEC F8 | 3 | Pending |
| REQ-09 | **Threshold-Triggered Reflection (F9)**: When an agent's accumulated memory importance since last reflection reaches ≥150, generate 3 salient questions, retrieve supporting memories, synthesize cited insights, store as `reflection` memories, and broadcast `reflection` WS messages. | SPEC F9 | 4 | Pending |
| REQ-10 | **Relationship Tracking & Graph (F10)**: Track pairwise `affinity` scores and interaction notes in SQLite (`relationships` table), expose `GET /relationships`, and render an interactive Cytoscape.js relationship network in the frontend. | SPEC F10 | 4, 5 | Pending |
| REQ-11 | **Agent Inspector Panel (F11)**: Expose `GET /agents` and `GET /agents/{id}` and render a clickable Agent Inspector UI panel showing persona details, current action/plan, recent/top memories, mood, and relationships. | SPEC F11 | 4 | Pending |
| REQ-12 | **Simulation Time Controls (F12)**: Implement `POST /sim/start`, `POST /sim/pause`, and `POST /sim/speed` (1x, 4x, 16x) and wire frontend playback controls to dynamically adjust the async simulation clock. | SPEC F12 | 4 | Pending |
| REQ-13 | **Event Log & Day Replay (F13)**: Write structured simulation events to a JSONL event log per simulated day, expose `GET /replay/{day}`, and provide a frontend replay mode to scrub/rewatch a recorded day. | SPEC F13 | 5 | Pending |
| REQ-14 | **Cost & Token Dashboard (F14)**: Expose `GET /metrics` and WS `metrics` payloads aggregating calls, tokens in/out, latency, cache hits, and estimated cost from `llm_calls`, rendered via Chart.js in the frontend. | SPEC F14 | 5 | Pending |
| REQ-15 | **Schema-Enforced LLM Gateway**: Route all LLM calls through `backend/llm/gateway.py` with Pydantic v2 JSON validation, 1-retry repair, prompt caching, batched importance rating, hard budget enforcement, Gemini Flash provider, and deterministic mock provider. | SPEC Goal 4 | 2 | Pending |
| REQ-16 | **Packaging, CI & Academic Deliverables**: Provide `docker-compose.yml`, GitHub Actions CI (`ruff`, `mypy`, `pytest`), `README.md` (<5 commands setup + architecture diagram), `AGENTS.md`, and `docs/report.md` (AI Lab Report). | SPEC Goal 3 | 5, 6 | Pending |

---

## Non-Functional Requirements

| ID | Requirement | Category | Phase | Status |
|----|-------------|----------|-------|--------|
| NFR-01 | **Configurable Tick Cadence**: Default 1 tick = 1 simulated minute at 1 tick/sec real-time (1x), scaling cleanly to 4x and 16x without blocking the event loop on concurrent async LLM calls. | Performance | 1, 3, 4 | Pending |
| NFR-02 | **Strict LLM Call Budgeting**: Never invoke the LLM on every tick; enforce configurable daily token/cost caps and prompt caching to keep operational cost near zero. | Cost Control | 2, 3 | Pending |
| NFR-03 | **Offline Deterministic Verification**: All unit, behavior, and 100-tick integration tests must run offline using a fixed seed and the mock LLM provider. | Reliability | All | Pending |
| NFR-04 | **Static Typing & Lint Cleanliness**: All backend Python code must pass `ruff check` and `mypy`, and frontend TypeScript code must pass `tsc --noEmit`. | Maintainability | All | Pending |
| NFR-05 | **Spatial & Plan Invariants**: Agents never walk through collision tiles, never finish a tick occupying the same tile as another stationary agent, and always complete or cleanly replan active goals. | Correctness | 1, 3, 5 | Pending |

---

## Constraints

| ID | Constraint | Source | Impact |
|----|------------|--------|--------|
| CON-01 | Server owns all simulation state; frontend is strictly a renderer and control surface. | PRD Rule 2 | `backend/sim/`, `frontend/src/` |
| CON-02 | No direct LLM SDK calls outside `backend/llm/gateway.py` and `backend/llm/providers/`. | PRD Rule 3 | `backend/agents/`, `backend/memory/` |
| CON-03 | Every LLM response must be validated against a Pydantic v2 schema. | PRD Rule 4 | `backend/llm/schemas.py` |
| CON-04 | No secrets committed to git; `.env.example` only. | PRD Rule 5 | Root & `backend/app/config.py` |
| CON-05 | Every new module ships with at least one automated test passing with mock provider and no network. | PRD Rule 6 | `backend/tests/` |

---

## Traceability Matrix

| Requirement | Phase | Plans | Tests | Status |
|-------------|-------|-------|-------|--------|
| REQ-01 | 1 | TBD | TBD | Pending |
| REQ-02 | 1 | TBD | TBD | Pending |
| REQ-03 | 1, 2 | TBD | TBD | Pending |
| REQ-04 | 2 | TBD | TBD | Pending |
| REQ-05 | 2 | TBD | TBD | Pending |
| REQ-06 | 3 | TBD | TBD | Pending |
| REQ-07 | 3 | TBD | TBD | Pending |
| REQ-08 | 3 | TBD | TBD | Pending |
| REQ-09 | 4 | TBD | TBD | Pending |
| REQ-10 | 4, 5 | TBD | TBD | Pending |
| REQ-11 | 4 | TBD | TBD | Pending |
| REQ-12 | 4 | TBD | TBD | Pending |
| REQ-13 | 5 | TBD | TBD | Pending |
| REQ-14 | 5 | TBD | TBD | Pending |
| REQ-15 | 2 | TBD | TBD | Pending |
| REQ-16 | 5, 6 | TBD | TBD | Pending |
