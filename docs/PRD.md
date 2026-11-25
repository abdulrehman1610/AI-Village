# AI Village: Product Requirements Document

AbdulRehman · AI Lab Project (6th Semester BSCS, Superior University) · Draft v1

## 1. Overview

AI Village is a 2D town simulation, viewable in the browser, where 6 to 10 autonomous agents live out their days. Each agent is driven by an LLM: it wakes up, makes a plan, walks somewhere, talks to neighbours, remembers what happened, reflects on it, and slowly forms relationships. The viewer watches live and can inject events ("a fire starts at the market", "a rumour spreads about the baker") to see how behaviour and information propagate.

The design follows the idea from Stanford’s Generative Agents ("Smallville") paper, but is built from scratch. It deliberately combines **classical AI** (A\* search, hierarchical planning, knowledge representation) with **LLM reasoning**, so it fits an AI course lab and also works as a portfolio piece.

**This is not a RAG application.** Memory retrieval exists, but only as one internal component of the agent brain.

## 2. Goals and non-goals

**Goals**

- Deliver a working, visually impressive agent simulation that runs a full simulated day without human help.
- Show clear use of course concepts: search, planning, knowledge representation, agents, and LLM integration.
- Produce a GitHub repo and demo that a recruiter understands in 30 seconds (GIF, architecture diagram, live link).
- Keep LLM cost near zero by using free-tier or cheap models and strict call budgeting.

**Non-goals**

- No user accounts, multiplayer, or mobile app.
- No model training or fine-tuning.
- No 3D graphics.
- No claim of scientific realism; this is an engineering demo.

## 3. Users

| User | What they need |
| --- | --- |
| Lab instructor | A clear demo, explainable AI concepts, a short report |
| Recruiters and GitHub visitors | A README with a GIF, a live demo, clean code |
| Viewer (anyone with the link) | Watch the village, click an agent, inject an event |
| Developer (me) | A simple stack I can finish alone, fast |

## 4. Features

P0 is the MVP needed to pass the lab. P1 is what makes it impressive. P2 is stretch.

| ID | Feature | Priority | Notes |
| --- | --- | --- | --- |
| F1 | Tile-based world and rendering | P0 | Map built in Tiled, rendered in Phaser |
| F2 | A\* movement between named locations | P0 | Collision layer from the map |
| F3 | Agent personas | P0 | Name, age, job, traits, home, starting goals |
| F4 | Memory stream | P0 | Observations, plans, reflections with timestamps |
| F5 | Memory retrieval scoring | P0 | Recency + importance + relevance |
| F6 | Daily planning | P0 | Day plan, then hourly, then minute actions |
| F7 | Agent-to-agent conversation | P0 | Triggered by proximity, stored as memory |
| F8 | Event injection (god mode) | P0 | Free text input, delivered to nearby agents |
| F9 | Reflection | P1 | Higher-level insights from recent memories |
| F10 | Relationship tracking and graph | P1 | Affinity score and notes per pair |
| F11 | Agent inspector panel | P1 | Click an agent to see plan, memories, mood |
| F12 | Time controls | P1 | Pause, play, speed 1x/4x/16x |
| F13 | Replay from event log | P1 | Rewatch any simulated day |
| F14 | Cost and token dashboard | P1 | Calls, tokens, estimated cost, latency |
| F15 | Persona-consistency evaluation | P2 | LLM-as-judge plus simple metrics |
| F16 | Local model fallback | P2 | Ollama when API is rate limited |
| F17 | Day/night cycle and weather | P2 | Visual polish, can trigger events |

## 5. Simulation design

### 5.1 Time

The world runs on ticks. One tick equals one simulated minute. The real-time rate is configurable (default one tick per second, so a simulated day takes about 24 minutes). The LLM is called only at decision points, never on every tick.

### 5.2 Agent loop

Each agent runs this loop on every tick, but only calls the LLM when something changes:

1. **Perceive**: read nearby agents, objects, and events within a radius.
2. **Remember**: store observations in the memory stream with an importance score.
3. **Decide**: continue the current plan, replan, or start a conversation.
4. **Act**: move one step along the A\* path, or perform the current action.
5. **Reflect**: if enough importance has accumulated, generate insights.

### 5.3 Memory

Every memory has: id, agent, type (observation, plan, reflection, conversation), text, created time, last-accessed time, importance (1 to 10, rated by the LLM), and an embedding vector.

Retrieval score for a memory:

`score = w_r * recency + w_i * importance + w_v * relevance`

- recency decays exponentially with hours since last access (decay factor around 0.995 per hour)
- importance is normalised to 0 to 1
- relevance is cosine similarity between the query embedding and the memory embedding
- each component is min-max normalised, weights start at 1 each and are tunable
- the top k (default 8) memories go into the agent’s prompt

### 5.4 Planning

At wake-up, the agent generates a day plan of 5 to 8 broad items from its persona and recent memories. Each item is then broken into hourly blocks, and blocks into minute-level actions only when needed. Interruptions (an event, a conversation) trigger a replan of the remaining day.

### 5.5 Conversation

Two agents may talk when they are within 2 tiles, both are free, and a cooldown has passed. The LLM first decides whether the initiator wants to talk, then dialogue is generated turn by turn (maximum 6 turns) using each agent’s relevant memories. A summary of the conversation is stored as a memory for both agents. This is also how rumours spread.

### 5.6 Reflection

When the summed importance of memories since the last reflection passes a threshold (starting at 150), the agent asks itself the 3 most salient questions about recent events, retrieves evidence, and writes insights that cite the memory ids they are based on. Reflections are stored as memories and can themselves be retrieved.

### 5.7 Events

The viewer types an event and optionally picks a location. It becomes an observation for every agent within range, and spreads onward through conversations. This is the main "wow" interaction.

### 5.8 Movement

A\* on the tile grid with a collision layer exported from Tiled. The heuristic is Manhattan distance for 4-way movement. Agents target named locations (Cafe, Park, Market, Home) rather than raw coordinates.

## 6. Architecture

```
 Browser (Phaser 3 + TypeScript)
   |  renders map, sprites, panels, graph, charts
   |  WebSocket (live state)   REST (controls, queries)
   v
 FastAPI server (Python)
   |-- Simulation engine (async tick loop, world state, A*)
   |-- Agent brain (perceive, plan, converse, reflect)
   |-- Memory service (store, embed, retrieve)
   |-- LLM gateway (provider abstraction, JSON schemas,
   |                 cache, rate limit, budget, cost log)
   |-- Event log writer (JSONL, powers replay)
   v
 SQLite (state, memories, relationships, llm_calls)
   v
 LLM provider (Gemini Flash-class model, optional local Ollama)
```

The simulation engine is the source of truth. The frontend only renders what the server sends; it never decides anything.

## 7. Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Language (backend) | Python 3.12 | Fastest for AI work, strong ecosystem |
| Web framework | FastAPI + Uvicorn | Async, native WebSockets, auto API docs |
| Validation | Pydantic v2 | Typed models and strict LLM JSON schemas |
| Concurrency | asyncio | One tick loop, concurrent LLM calls per tick |
| Pathfinding | Custom A\* (heapq) | Written by hand, so it counts as classical AI work |
| Database | SQLite (aiosqlite, SQLModel) | Zero setup, single file, enough for this scale |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2), local | Free, no API calls, fast on CPU |
| Vector search | NumPy cosine similarity | A few thousand memories per agent, no vector DB needed |
| LLM | Gemini Flash-class model for routine calls, stronger model for planning and reflection | Cheap or free tier, good JSON output |
| LLM fallback | Ollama with a small local model | Survives rate limits (P2) |
| Frontend | Phaser 3 + TypeScript + Vite | Real game rendering, tilemap support, fast dev loop |
| Map and art | Tiled editor + a CC0 tileset (for example Kenney) | Free assets, standard JSON map format |
| Graphs and charts | Cytoscape.js (relationships), Chart.js (cost, latency) | Light, easy to embed |
| Logging | structlog + JSONL event log | Structured logs and replay |
| Testing | pytest, pytest-asyncio, a deterministic mock LLM | Tests run with no API key |
| Quality | ruff, mypy, pre-commit | Clean repo signal |
| CI | GitHub Actions | Lint and tests on every push |
| Packaging | uv, Docker, docker-compose | One-command local run |
| Hosting | Backend on a free-tier container host, frontend on a static host | Check current free-tier limits before choosing |

## 8. Data model

| Table | Key fields |
| --- | --- |
| agents | id, name, persona\_json, home\_location, x, y, current\_action, current\_plan\_json |
| memories | id, agent\_id, type, text, importance, created\_tick, last\_access\_tick, embedding (blob) |
| relationships | agent\_a, agent\_b, affinity, notes, last\_interaction\_tick |
| events | id, tick, kind, text, location, source (god or agent) |
| conversations | id, tick\_start, participants, transcript\_json, summary |
| llm\_calls | id, tick, agent\_id, purpose, model, tokens\_in, tokens\_out, latency\_ms, cost\_est, cache\_hit |
| sim\_state | tick, sim\_time, speed, seed |

## 9. API contract

**REST**

| Method and path | Purpose |
| --- | --- |
| POST /sim/start, /sim/pause, /sim/speed | Control the simulation |
| GET /agents, GET /agents/{id} | List agents, inspect one (plan, memories, relationships) |
| POST /events | Inject a god-mode event |
| GET /relationships | Graph data |
| GET /metrics | Token, cost, and latency totals |
| GET /replay/{day} | Event log for a simulated day |

**WebSocket** `/ws`

| Message | Payload |
| --- | --- |
| tick | tick number, sim time, all agent positions and actions |
| dialogue | speaker, listener, line |
| event | injected or agent-generated event |
| reflection | agent, insight text |
| metrics | rolling cost and call counts |

## 10. LLM strategy and cost control

- Every call goes through one gateway that enforces a JSON schema, retries once on invalid output, and logs tokens, latency, and cost.
- Call only at decision points: wake-up planning, replanning, conversation turns, importance rating, reflection.
- Batch importance ratings (several memories per call).
- Cache identical prompts. Hard daily budget with automatic fallback to the cheaper model, then to the local model.
- Keep prompts short: persona summary, current plan item, top-k memories only.
- A fixed random seed and a mock provider make runs reproducible for tests and demos.

## 11. Repository structure

```
ai-village/
  backend/
    app/ (main.py, config.py)
    sim/ (world.py, clock.py, astar.py, engine.py)
    agents/ (agent.py, planner.py, conversation.py, reflection.py)
    memory/ (store.py, retrieval.py, embeddings.py)
    llm/ (gateway.py, providers/, schemas.py, prompts/)
    api/ (rest.py, ws.py)
    tests/
  frontend/
    src/ (scenes/, ui/, net/)
    public/assets/ (tileset, map.json, sprites)
  docs/ (PRD.md, architecture.png, report.md)
  docker-compose.yml
  README.md
  AGENTS.md
```

## 12. Testing and evaluation

- **Unit tests**: A\* (optimal path, blocked paths), retrieval scoring, clock, schema validation.
- **Integration tests**: run 100 ticks with the mock LLM and assert no crashes and valid state.
- **Behaviour checks**: agents never walk through walls, never occupy the same tile, always finish or abandon a plan cleanly.
- **Evaluation (P2)**: persona consistency scored by an LLM judge on 20 sampled lines per agent, plus rumour spread (how many agents learn an injected fact, and how fast).

## 13. Milestones

Assumes about 6 weeks; compress if the deadline is shorter.

| Week | Deliverable |
| --- | --- |
| 1 | Repo, tile map, 3 agents moving with A\*, WebSocket sync to Phaser |
| 2 | Memory stream, embeddings, retrieval scoring, agent brain prompts |
| 3 | Daily planning, conversations, event injection |
| 4 | Reflection, relationships, inspector panel, time controls |
| 5 | Cost dashboard, replay, relationship graph, tests, CI |
| 6 | README with GIF, architecture diagram, deploy, report, demo video |

## 14. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| API rate limits or cost | Call budgeting, caching, cheap model, local fallback |
| Agents behave incoherently | Short grounded prompts, strict schemas, top-k memory only, reflection |
| Sim is slow with many agents | Async concurrent calls, stagger decision points, start with 3 agents |
| Scope creep | P0 first, freeze features at the start of week 5 |
| Art takes too long | Use a ready CC0 tileset, no custom art |
| Live demo fails | Record a replay and a demo video as backup |

## 15. Mapping to AI course concepts

| Course concept | Where it appears |
| --- | --- |
| Intelligent agents (perceive, decide, act) | Agent loop |
| Search (A\*) | Movement and pathfinding |
| Planning | Hierarchical day, hour, and minute plans |
| Knowledge representation | Memory stream, relationships, persona model |
| Reasoning under uncertainty | Importance scoring, probabilistic conversation triggers |
| Multi-agent systems | Conversations, rumour spread, relationships |
| Modern LLM integration | Gateway, schema-constrained generation, cost control |

## 16. Deliverables checklist

- Working demo (local and hosted)
- README with a demo GIF at the top, architecture diagram, and setup in under 5 commands
- 2-minute demo video
- Lab report using sections 1, 5, 6, and 15 of this document
- Tests passing in CI
- Resume bullet: built a multi-agent LLM simulation with memory retrieval, hierarchical planning, A\* navigation, and a cost-aware LLM gateway

## 17. Engineering rules (for me and for any coding agent)

1. Read this PRD before starting a task, and keep changes inside the scope of the current milestone.
2. The server owns all state. The frontend never makes simulation decisions.
3. All LLM calls go through the gateway. No direct provider calls anywhere else.
4. Every LLM response is validated against a Pydantic schema. Never trust raw text.
5. No secrets in code. Use `.env` and commit only `.env.example`.
6. Every new module ships with at least one test, and tests must pass with the mock provider and no network.
7. Keep functions small and typed. Run ruff and mypy before finishing a task.
8. Never call the LLM inside a tight loop. Check the budget first.
9. Log every LLM call with purpose, tokens, and cost.
10. Do not add dependencies without a one-line reason in the pull request.
11. If a requirement is unclear, stop and ask instead of guessing.
