# SPEC.md — Project Specification

> **Status**: `FINALIZED`
>
> ⚠️ **Planning Lock**: Satisfied (`FINALIZED`). Reference source: `AI Village Product Requirements Document.md`.

## Vision
AI Village is a 2D browser-based town simulation where 6 to 10 autonomous LLM-driven agents live out their daily routines—waking up, generating hierarchical plans, walking between named town locations via custom A* pathfinding, talking with neighbors, storing memories, reflecting on accumulated experiences, and forming evolving relationships. Viewers watch the simulation live via Phaser 3 and can inject god-mode events (e.g., "a fire starts at the market", "a rumour spreads about the baker") to observe emergent multi-agent behavior and information propagation. Inspired by Stanford's Generative Agents ("Smallville") paper and built from scratch for a 6th-semester BSCS AI Lab Project and technical portfolio, it deliberately integrates **classical AI** (A* search, hierarchical planning, knowledge representation) with **modern LLM reasoning** under strict cost and schema controls.

## Goals
1. **Autonomous Full-Day Simulation** — Deliver a visually compelling 2D village simulation where 6–10 agents run a complete simulated day (1 tick = 1 simulated minute) without human intervention.
2. **Classical + Generative AI Integration** — Demonstrate clear, explainable implementation of AI course concepts: A* pathfinding (`heapq`), hierarchical planning (day → hour → minute), structured knowledge representation (memory stream, persona model, pairwise relationship graph), weighted memory retrieval (`recency + importance + relevance`), and LLM decision-making.
3. **Recruiter-Ready Portfolio & Lab Deliverable** — Produce a clean monorepo with interactive UI panels (agent inspector, relationship graph, cost/token dashboard, replay mode, time controls), Docker packaging, CI pipeline, architecture documentation, and a formal AI Lab Report.
4. **Near-Zero LLM Cost & Deterministic Testing** — Route every LLM call through a single schema-enforcing gateway with prompt caching, batch importance rating, daily token/cost budgets, Gemini Flash support, and a deterministic mock LLM provider so all tests pass offline without an API key.

## Non-Goals (Out of Scope)
- No user accounts, authentication, multiplayer, or mobile app.
- No custom model training or fine-tuning.
- No 3D graphics or custom pixel art creation (use standard Tiled JSON maps and CC0 tilesets).
- No claim of scientific realism; this is an engineering and AI concepts demonstration.

## Users
| User | Needs |
| --- | --- |
| **Lab Instructor** | Clear live demo, explainable classical + LLM AI concepts, formal lab report mapping to course topics |
| **Recruiters & GitHub Visitors** | Clean code, 30-second comprehension via README/diagram, <5 command local setup, live/replay demo |
| **Viewer** | Watch village activity in browser, click agents to inspect internal state, control time speed, inject god-mode events |
| **Developer** | Simple, well-typed stack (`Python 3.12 + FastAPI + SQLite` and `Phaser 3 + TypeScript + Vite`) with fast feedback loops |

## Constraints
- **Server Authority**: The FastAPI simulation engine is the single source of truth. The Phaser frontend only renders state received over WebSocket/REST and sends user control/event requests.
- **LLM Gateway Exclusivity**: All LLM calls must pass through `backend/llm/gateway.py`, validate output against Pydantic v2 schemas (with 1 retry on invalid output), check budget limits, and log tokens, latency, and estimated cost to SQLite (`llm_calls`).
- **Decision-Point Only LLM Calls**: Never invoke the LLM on every tick or in a tight loop; call only at wake-up planning, replanning on interruption, conversation turns, batched importance scoring, and threshold-triggered reflections.
- **Zero-Network Test Suite**: Every module must include tests (`pytest`, `pytest-asyncio`) running against the deterministic mock LLM provider with no external network calls.
- **Code Quality & Security**: Strictly typed Python (`mypy`) formatted/linted with `ruff`. No secrets in code (`.env` ignored, `.env.example` committed).

## Success Criteria
- [x] Tile-based village map renders in Phaser 3 with named locations (e.g., Cafe, Park, Market, Homes) and collision walls.
- [x] Custom hand-written A* pathfinder (`heapq`, Manhattan heuristic, 4-way movement) navigates agents between named locations without walking through walls or overlapping tiles.
- [x] 6–10 distinct agent personas wake up, generate hierarchical plans (day → hourly → minute actions), and execute the Perceive → Remember → Decide → Act → Reflect loop across a full simulated day.
- [x] Memory stream stores observations, plans, conversations, and reflections with embeddings (`sentence-transformers` `all-MiniLM-L6-v2` in production, deterministic embedding in mock mode) and retrieves top-$k$ ($k=8$) memories using normalized `w_r * recency + w_i * importance + w_v * relevance`.
- [x] Agents within 2 tiles initiate cooldown-gated turn-by-turn dialogues (up to 6 turns), summarize the conversation into memory, and update pairwise relationship affinity and notes.
- [x] Viewer can inject god-mode events (`POST /events`) with optional location, delivering observations to nearby agents that propagate via subsequent conversations.
- [x] When accumulated memory importance exceeds threshold (150), agents generate cited higher-level reflections stored back into the memory stream.
- [x] Frontend provides an Agent Inspector panel (plan, memories, mood, relationships), Time Controls (pause, play, 1x/4x/16x), a Cytoscape.js Relationship Graph, a Chart.js Cost/Token/Latency Dashboard, and JSONL Day Replay.
- [x] 100-tick integration test with deterministic mock LLM passes with zero crashes, valid state invariants, and passing `ruff` + `mypy` checks in CI.

## Technical Requirements (v1.0 Scope: P0 + P1)

| ID | Feature | Priority | Notes |
| --- | --- | --- | --- |
| F1 | Tile-based world and rendering | P0 | Map built in Tiled JSON format, rendered in Phaser 3 |
| F2 | A* movement between named locations | P0 | Custom `heapq` A* using collision layer from map |
| F3 | Agent personas | P0 | Name, age, job, traits, home location, starting goals (6–10 agents) |
| F4 | Memory stream | P0 | Observations, plans, conversations, reflections with tick timestamps |
| F5 | Memory retrieval scoring | P0 | Exponential recency decay (0.995/hr) + importance + cosine relevance |
| F6 | Daily planning | P0 | Day plan (5–8 items) → hourly blocks → minute actions + replanning |
| F7 | Agent-to-agent conversation | P0 | Proximity (≤2 tiles) + cooldown, max 6 turns, summary stored |
| F8 | Event injection (god mode) | P0 | Free-text event + optional location delivered to nearby agents |
| F9 | Reflection | P1 | Triggered at importance sum ≥ 150; 3 salient questions → cited insights |
| F10 | Relationship tracking and graph | P1 | Pairwise affinity score, notes, and Cytoscape.js graph view |
| F11 | Agent inspector panel | P1 | Click agent to inspect current plan, top memories, mood, relationships |
| F12 | Time controls | P1 | Pause, play, speed 1x / 4x / 16x via REST & UI controls |
| F13 | Replay from event log | P1 | JSONL event log writer + `GET /replay/{day}` playback in UI |
| F14 | Cost and token dashboard | P1 | Calls, tokens in/out, estimated cost, latency, cache hits via Chart.js |

---

*Last updated: 2026-11-23*
