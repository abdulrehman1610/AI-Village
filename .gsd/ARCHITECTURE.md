# Architecture — AI Village

> Derived from `AI Village Product Requirements Document.md` on 2026-11-23

## Overview

AI Village is a client-server 2D multi-agent town simulation. The Python FastAPI backend owns all simulation state, tick execution, classical A* navigation, memory embeddings/retrieval, and schema-enforced LLM calls. The Phaser 3 + TypeScript frontend is a pure rendering and control layer connected via WebSocket (`/ws`) and REST endpoints.

```
┌──────────────────────────────────────────────────────────────────────┐
│                   Browser (Phaser 3 + TypeScript + Vite)             │
│  • Tilemap & Sprite Renderer (scenes/)                               │
│  • Inspector Panel, Time Controls, Event Injector (ui/)              │
│  • Cytoscape.js Relationship Graph & Chart.js Cost Dashboard (ui/)   │
└──────────────────┬─────────────────────────────────┬─────────────────┘
                   │ WebSocket /ws (live ticks,      │ REST (/sim/*, /agents,
                   │ dialogue, events, reflections)  │ /events, /metrics, /replay)
                   ▼                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       FastAPI Server (Python 3.12)                   │
│  ├── Simulation Engine (sim/clock.py, world.py, astar.py, engine.py) │
│  ├── Agent Brain (agents/agent.py, planner.py, conversation.py,      │
│  │                reflection.py)                                     │
│  ├── Memory Service (memory/store.py, embeddings.py, retrieval.py)   │
│  ├── LLM Gateway (llm/gateway.py, schemas.py, prompts/, providers/)  │
│  └── Event Log Writer (JSONL per simulated day for replay)           │
└──────────────────┬─────────────────────────────────┬─────────────────┘
                   │                                 │
                   ▼                                 ▼
┌──────────────────────────────────┐  ┌────────────────────────────────┐
│   SQLite (SQLModel + aiosqlite)  │  │          LLM Providers         │
│  • agents, memories, events      │  │  • Deterministic MockLLM (CI)  │
│  • relationships, conversations  │  │  • Gemini Flash / Pro          │
│  • llm_calls, sim_state          │  │  • Optional Local Ollama (P2)  │
└──────────────────────────────────┘  └────────────────────────────────┘
```

## Repository Structure

```
ai-village/
  backend/
    app/ (main.py, config.py, db.py)
    sim/ (world.py, clock.py, astar.py, engine.py)
    agents/ (agent.py, personas.py, planner.py, conversation.py, reflection.py)
    memory/ (models.py, store.py, retrieval.py, embeddings.py)
    llm/ (gateway.py, providers/, schemas.py, prompts/)
    api/ (rest.py, ws.py)
    tests/
  frontend/
    src/ (scenes/, ui/, net/, types/)
    public/assets/ (tileset, map.json, sprites)
  docs/ (PRD.md, architecture.png, report.md)
  docker-compose.yml
  README.md
  AGENTS.md
```

## Core Components

### 1. Simulation Engine (`backend/sim/`)
- **`clock.py`**: Manages simulation ticks (1 tick = 1 simulated minute; configurable speed 1x/4x/16x and pause/resume).
- **`world.py`**: Loads the Tiled JSON map, parses the collision grid and named locations (Cafe, Park, Market, Homes), tracks agent coordinates and tile occupancy.
- **`astar.py`**: Hand-written `heapq` A* pathfinder using Manhattan distance heuristic on 4-way movement grid.
- **`engine.py`**: Orchestrates the per-tick loop across all agents concurrently via `asyncio`, emits WebSocket events, and writes JSONL replay logs.

### 2. Agent Brain (`backend/agents/`)
- **`agent.py`**: Encapsulates the 5-step cognitive loop (`perceive`, `remember`, `decide`, `act`, `reflect`).
- **`planner.py`**: Generates 5–8 broad daily plan items at wake-up, decomposes into hourly blocks and minute actions, and replans on interruption.
- **`conversation.py`**: Handles proximity (≤2 tiles) and cooldown checks, turn-by-turn dialogue generation (max 6 turns), conversation summarization, and relationship updates.
- **`reflection.py`**: Watches accumulated importance score (≥150), queries 3 salient questions, retrieves evidence memories, and synthesizes cited reflection memories.

### 3. Memory Service (`backend/memory/`)
- **`store.py`**: Async CRUD operations against SQLite (`memories`, `relationships`, `events`, `conversations`, `agents`, `sim_state`).
- **`embeddings.py`**: Local `sentence-transformers` (`all-MiniLM-L6-v2`) embedding generator with a fast deterministic hashing fallback for unit/CI tests.
- **`retrieval.py`**: Computes `score = w_r * recency + w_i * importance + w_v * relevance` with exponential recency decay ($0.995^{\Delta hours}$), NumPy cosine similarity, and min-max normalization to return top-$k$ ($k=8$) memories.

### 4. LLM Gateway (`backend/llm/`)
- **`gateway.py`**: Single entry point for all LLM requests. Enforces Pydantic v2 output schemas (`schemas.py`), retries once on validation error, caches identical prompts, enforces daily token/cost budget, and logs every call to `llm_calls`.
- **`providers/`**: Pluggable provider interface with `MockProvider` (deterministic, zero-network) and `GeminiProvider` (Gemini Flash/Pro).

### 5. Frontend (`frontend/src/`)
- **`scenes/`**: Phaser 3 scene rendering Tiled map layers, named location labels, agent sprites, speech bubbles, and path interpolation.
- **`net/`**: WebSocket client (`/ws`) and REST API client (`/sim/*`, `/agents/*`, `/events`, `/relationships`, `/metrics`, `/replay/*`).
- **`ui/`**: DOM/Canvas overlay panels for Time Controls, God-Mode Event Injection, Agent Inspector, Cytoscape.js Relationship Graph, Chart.js Cost Dashboard, and Day Replay Scrubber.

---

*Last updated: 2026-11-23*
