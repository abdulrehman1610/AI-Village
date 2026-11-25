---
phase: 6
plan: 3
wave: 2
depends_on:
  - "1"
  - "2"
files_modified:
  - docs/report.md
  - AGENTS.md
  - README.md
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`docs/report.md` delivers a formal 6th-semester BSCS AI Lab Report (AbdulRehman, Superior University) covering PRD Sections 1, 5, 6, and 15, exact mathematical retrieval/A* equations matching the codebase, `docs/architecture.png`, and empirical tables populated directly from `.gsd/phases/6/day_simulation_metrics.json`"
    - "`AGENTS.md` documents the repository layout, all 11 engineering rules from PRD Section 17, `PROJECT_RULES.md` precedence, `Settings`/Docker/Nginx invariants, and exact offline test/lint/typecheck commands"
    - "`README.md` features `docs/demo.gif` at the top, embeds `docs/architecture.png`, provides <5-command Docker Compose and local quickstarts, summarizes F1–F14 + API/WS routes + 2-minute live demo flow + resume bullet, and cites `docs/PRD.md`, `docs/report.md`, and `AGENTS.md`"
    - "Complete local verification gate (`ruff` on `backend` + `scripts`, `mypy --strict` on `backend` + `scripts`, full `pytest -v`, `npm --prefix frontend run typecheck`, `npm --prefix frontend run build`, and live `scripts/verify_phase1_ws.py`) passes 100% offline"
  artifacts:
    - "docs/report.md provides the academic AI Lab Report grounded in empirical 1,440-tick findings"
    - "AGENTS.md provides coding-agent and contributor onboarding rules"
    - "README.md provides recruiter-ready project documentation and quickstart"
  key_links:
    - "Every empirical metric in `docs/report.md` matches `.gsd/phases/6/day_simulation_metrics.json` verbatim"
    - "`README.md` references valid paths (`docs/demo.gif`, `docs/architecture.png`, `docs/PRD.md`, `docs/report.md`, `AGENTS.md`, `docker-compose.yml`, `.env.example`)"
    - "`AGENTS.md` engineering rules match `AI Village Product Requirements Document.md` Section 17 and `.github/workflows/ci.yml` commands"
---

# Plan 6.3: Academic Lab Report, AGENTS.md, README.md & Milestone v1.0 Verification Gate

## Objective
Author the formal academic AI Lab Report (`docs/report.md`), contributor/coding-agent specification (`AGENTS.md`), and recruiter-ready `README.md`, then execute the full end-to-end verification gate across backend, scripts, frontend, and live WebSocket synchronization to close Phase 6 and Milestone v1.0 (`REQ-16`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/REQUIREMENTS.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/6/day_simulation_metrics.json
- AI Village Product Requirements Document.md
- PROJECT_RULES.md
- backend/app/config.py
- backend/sim/astar.py
- backend/memory/retrieval.py
- backend/llm/gateway.py
- backend/api/rest.py
- backend/api/ws.py
- docker-compose.yml
- .github/workflows/ci.yml

## Tasks

<task type="auto">
  <name>Author formal AI Lab Report in docs/report.md</name>
  <files>
    docs/report.md
  </files>
  <action>
    Write `docs/report.md` as a rigorous, submission-ready academic AI Lab Report for **AbdulRehman · 6th Semester BSCS, Superior University** covering PRD Sections 1, 5, 6, and 15 plus verified empirical findings from `.gsd/phases/6/day_simulation_metrics.json`.

    Steps:
    1. Read `.gsd/phases/6/day_simulation_metrics.json` completely so every single reported count, latency, cache hit rate, memory breakdown, reflection count, relationship statistic, and replay tick bound is empirically exact.
    2. Structure `docs/report.md` cleanly with:
       - **Title Block & Abstract**: Project metadata, Smallville inspiration, hybrid classical-AI + LLM synthesis, headline empirical numbers from the 1,440-tick Day 1 -> Day 2 run.
       - **1. Project Overview & Motivation** (PRD Section 1): 8 autonomous villagers (`Maya`, `Liam`, `Elena`, `Noah`, `Clara`, `Marcus`, `Aria`, `Sam`), browser live view + god-mode event injection, deliberate distinction from generic RAG pipelines.
       - **2. System Architecture** (PRD Section 6): Embed `![AI Village System Architecture](architecture.png)`; explain authoritative FastAPI server, decoupled Phaser 3 + Cytoscape.js + Chart.js client, Nginx reverse proxy, SQLite WAL 7-table schema (`agents`, `memories`, `relationships`, `events`, `conversations`, `llm_calls`, `sim_state`), and day-partitioned JSONL replay logs.
       - **3. Simulation Design & Cognitive Algorithms** (PRD Section 5.1–5.8):
         - **3.1 Discrete Time & Decision-Point Cadence** (`SimClock`: 1 tick = 1 min, `06:00` start, `1,440` ticks/day, `1x/4x/16x` async loop).
         - **3.2 Five-Stage Agent Loop** (`Perceive -> Remember -> Decide -> Act -> Reflect` in `AgentBrain` & `SimulationEngine`).
         - **3.3 Memory Stream & Weighted Retrieval Mathematics** (`MemoryRetriever`: exact equation `score = w_r * recency + w_i * importance + w_v * relevance`, `0.995` hourly exponential decay, 384-d cosine similarity via `all-MiniLM-L6-v2` / `DeterministicEmbeddingProvider`, min-max `[0,1]` normalization, `k=8`).
         - **3.4 Hierarchical Planning & Replanning** (`DailyPlanner`: 5–8 day blocks -> hourly focus -> lazy `MinuteStep`s, `canonicalize_location()`, interruption replanning).
         - **3.5 Multi-Agent Conversations & Rumor Spread** (`ConversationManager`: Manhattan <= 2 tiles, dual cooldowns 60/30 ticks, <= 6 turns, memory summaries, canonical affinity updates).
         - **3.6 Threshold Reflection & Mood Evolution** (`ReflectionManager`: importance threshold `>= 150`, 3 salient questions -> evidence retrieval -> cited insights in `metadata_json`).
         - **3.7 God-Mode Event Injection** (`POST /events`, spatial range observation, replan trigger, multi-hop social propagation).
         - **3.8 Classical A* Grid Search** (`backend/sim/astar.py`: custom `heapq` A* with admissible Manhattan heuristic $h(n)=|x_n-x_g|+|y_n-y_g|$ on 40x30 Tiled grid, cardinal 4-way steps, wall/occupancy avoidance, stall recovery).
       - **4. Schema-Enforced LLM Gateway & Cost Control**: Single gateway (`backend/llm/gateway.py`), Pydantic v2 schemas + 1-retry repair, SHA-256 prompt cache, model tiering (`gemini-2.5-flash` vs `gemini-2.5-pro`), hard daily budget + `MockProvider` fallback.
       - **5. Mapping to AI Course Concepts** (PRD Section 15): Detailed conceptual + implementation table linking Intelligent Agents, Heuristic Search (`A*`), Hierarchical Planning, Knowledge Representation, Reasoning Under Uncertainty, Multi-Agent Systems, and Schema-Constrained LLM Integration to exact modules and equations.
       - **6. Empirical Evaluation: Full 1,440-Tick Simulated Village Day**: Formatted tables using real data from `.gsd/phases/6/day_simulation_metrics.json` (spatial invariants, memory types, conversations & rumor reach, reflections & citations, relationship network stats, LLM calls by purpose & cache efficiency, `day_1.jsonl` + `day_2.jsonl` bounds, plus transparent cost projection for Gemini Flash/Pro).
       - **7. Verification Strategy, Limitations & Future Work**: Offline seed=42 determinism, CI quality gates (`ruff`, `mypy --strict`, `pytest`, `tsc`, `vite build`), known limitations (deterministic mock vs live semantic variety; P2 roadmap F15 LLM-as-judge, F16 Ollama fallback, F17 day/night weather).

    AVOID: Leaving any placeholder (`TODO`, `TBD`, `XX`, `[insert`) or citing unverified numbers not present in `.gsd/phases/6/day_simulation_metrics.json` or actual source files.
  </action>
  <verify>
    `backend/.venv/Scripts/python.exe -c "import json; from pathlib import Path; r=Path('docs/report.md').read_text(encoding='utf-8'); m=json.loads(Path('.gsd/phases/6/day_simulation_metrics.json').read_text()); assert 'architecture.png' in r and '0.995' in r and 'heapq' in r and ('1,440' in r or '1440' in r); assert str(m['llm']['total_calls']) in r; assert not any(tok in r for tok in ('TODO','TBD','[insert')); print('REPORT_OK', len(r))"`
  </verify>
  <done>
    `docs/report.md` is complete, contains zero placeholders, embeds `architecture.png`, covers PRD Sections 1, 5, 6, and 15, and cites exact verified empirical numbers from `.gsd/phases/6/day_simulation_metrics.json`.
  </done>
</task>

<task type="auto">
  <name>Author AGENTS.md and recruiter-ready README.md</name>
  <files>
    AGENTS.md
    README.md
  </files>
  <action>
    Author `AGENTS.md` and `README.md` to complete PRD Section 11 and Section 16 deliverables.

    Steps:
    1. Create `AGENTS.md` covering:
       - Project identity & authoritative spec links (`docs/PRD.md`, `.gsd/SPEC.md`, `.gsd/ARCHITECTURE.md`, `PROJECT_RULES.md`, `adapters/`).
       - Exact repository map (`backend/app/`, `backend/sim/`, `backend/agents/`, `backend/memory/`, `backend/llm/`, `backend/api/`, `backend/tests/`, `frontend/src/`, `frontend/public/assets/`, `scripts/`, `docs/`).
       - All 11 non-negotiable engineering rules from PRD Section 17 (read PRD before changes, server owns state, all LLM calls through `backend/llm/gateway.py`, Pydantic v2 validation on every LLM output, `.env` secrets hygiene, offline mock tests per module, `ruff` + `mypy --strict`, no tight-loop LLM calls + budget gates, `llm_calls` logging, dependency justification, clarify ambiguities).
       - Critical architectural & packaging invariants (e.g., `Settings` env names `MAP_PATH`/`DATABASE_URL`/`REPLAY_LOG_DIR`, SQLite WAL directory volume rule, Nginx `/ws` + 8 REST route prefixes parity, strict `mypy` on `scripts/`, PowerShell/Bash single-command shell discipline).
       - Exact dev/test/CI commands (both PowerShell and Bash forms).
    2. Create `README.md` covering:
       - Top hero section featuring `![AI Village Live Simulation Demo](docs/demo.gif)`, concise 30-second summary, and stack badges (`Python 3.12`, `FastAPI`, `Phaser 3`, `TypeScript`, `SQLite`, `Docker`).
       - Feature Matrix (`F1`–`F14` implemented across v1.0: tilemap, `heapq` A*, 8 personas, memory stream, weighted retrieval, hierarchical planning, proximity conversations, god-mode events, reflections, Cytoscape.js relationships, Agent Inspector, 1x/4x/16x time controls, JSONL replay, Chart.js cost dashboard; plus P2 roadmap `F15`–`F17`).
       - System Architecture section embedding `![AI Village Architecture](docs/architecture.png)` and explaining classical AI vs LLM integration + non-RAG agent architecture.
       - **Quickstart (<5 Commands)**:
         - **Docker Compose (2 commands):** `cp .env.example .env` (PowerShell: `Copy-Item .env.example .env`) then `docker compose up --build`, open `http://localhost:5173` (runs offline out-of-the-box with `LLM_PROVIDER=mock`; optional Gemini Flash/Pro instructions by setting `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` in `.env`).
         - **Local Development:** Backend (3 commands including CPU PyTorch install + `uvicorn`) and Frontend (2 commands: `npm --prefix frontend ci` + `npm --prefix frontend run dev`).
       - **2-Minute Live Demo Walkthrough** (PRD Section 16:270): clear step-by-step live demo script (watch A* travel & conversations, click villager for Inspector, toggle 4x/16x, inject God-Mode event at Market/Bakery, inspect Relationship Graph, Cost Dashboard, and Day Replay scrubber).
       - **REST & WebSocket API Summary** (all 12 REST routes + 5 WS message types).
       - **Testing & CI Verification** commands (`ruff`, `mypy`, `pytest`, `npm run typecheck`, `npm run build`, `scripts/run_day_simulation.py`, `scripts/verify_phase1_ws.py`).
       - **Documentation & Academic Deliverable Links** (`docs/report.md`, `docs/PRD.md`, `AGENTS.md`) + Portfolio Summary / Resume Bullet (PRD line 273).

    AVOID: Putting broken relative image/file links or listing unimplemented P2 features (`F15`–`F17`) as complete.
    AVOID: Chaining commands with `&&` in documented PowerShell examples (honoring `PROJECT_RULES.md` Shell Discipline).
  </action>
  <verify>
    `backend/.venv/Scripts/python.exe -c "from pathlib import Path; r=Path('README.md').read_text(encoding='utf-8'); a=Path('AGENTS.md').read_text(encoding='utf-8'); assert r.splitlines()[0].startswith('#') and 'docs/demo.gif' in r[:600] and 'docs/architecture.png' in r and 'docker compose up --build' in r and 'docs/report.md' in r and 'AGENTS.md' in r; assert 'gateway.py' in a and 'PROJECT_RULES.md' in a and 'ruff' in a and 'mypy' in a; for p in ('docs/demo.gif','docs/architecture.png','docs/PRD.md','docs/report.md','AGENTS.md','docker-compose.yml','.env.example'): assert Path(p).exists(), p; print('README_AND_AGENTS_OK')"`
  </verify>
  <done>
    `AGENTS.md` and `README.md` exist with valid relative links, `docs/demo.gif` at top of `README.md`, `docs/architecture.png`, <5-command Docker & local quickstarts, 2-minute demo script, and full PRD Section 11/16/17 coverage.
  </done>
</task>

<task type="auto">
  <name>Run complete repository verification gate across backend, scripts, frontend, and live WS</name>
  <files>
    docs/report.md
    AGENTS.md
    README.md
  </files>
  <action>
    Execute the complete offline CI and end-to-end verification suite sequentially (one command per invocation) to prove zero regressions across the entire Milestone v1.0 codebase before closing Phase 6.

    Commands to execute one at a time:
    1. `backend/.venv/Scripts/ruff.exe check backend`
    2. `backend/.venv/Scripts/ruff.exe check --config backend/pyproject.toml scripts`
    3. `backend/.venv/Scripts/mypy.exe --config-file backend/pyproject.toml backend`
    4. `backend/.venv/Scripts/mypy.exe --config-file backend/pyproject.toml scripts`
    5. From `backend/` working directory: `.venv/Scripts/pytest.exe -v` (covers all Phase 1–6 unit, integration, 100-tick, 1440-tick, and Docker packaging tests).
    6. `npm --prefix frontend run typecheck`
    7. `npm --prefix frontend run build`
    8. `backend/.venv/Scripts/python.exe scripts/verify_phase1_ws.py` (verifies `frontend/dist` assets, boots Uvicorn, validates `/health`, `/world`, `/agents`, and 6 live `/ws` ticks).
    9. `backend/.venv/Scripts/python.exe -c "from pathlib import Path; required=('docker-compose.yml','.dockerignore','backend/Dockerfile','frontend/Dockerfile','frontend/nginx.conf','docs/PRD.md','docs/architecture.png','docs/demo.gif','docs/report.md','AGENTS.md','README.md'); missing=[p for p in required if not Path(p).is_file() or Path(p).stat().st_size==0]; assert not missing, missing; print('ALL_DELIVERABLES_PRESENT', len(required))"`

    If any check uncovers a defect in a Phase 6 file, repair it cleanly and re-run the affected verification command so all 9 checks pass on the final repository state.

    AVOID: Chaining shell commands with `&&` or `||` (`PROJECT_RULES.md` Shell Discipline).
    AVOID: Reporting any command as passing without observing its actual final exit code and full summary output.
  </action>
  <verify>
    All 9 verification commands above execute sequentially one at a time and exit 0 with zero warnings, errors, or skips (`ruff`, `mypy`, `pytest -v`, `npm run typecheck`, `npm run build`, `scripts/verify_phase1_ws.py`, and deliverable completeness check).
  </verify>
  <done>
    Every backend, script, frontend, packaging, 100-tick, 1440-tick, and live WebSocket verification check passes offline cleanly, completing Phase 6 and Milestone v1.0.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `docs/report.md` covers PRD Sections 1, 5, 6, and 15 with real empirical metrics from `.gsd/phases/6/day_simulation_metrics.json`
- [ ] `AGENTS.md` documents PRD Section 17 engineering rules, repo structure, and verification commands
- [ ] `README.md` opens with `docs/demo.gif`, embeds `docs/architecture.png`, provides <5-command Docker & local setup, and includes the 2-minute demo script and resume bullet
- [ ] Full verification gate (`ruff`, `mypy`, `pytest -v`, `npm run typecheck`, `npm run build`, `scripts/verify_phase1_ws.py`) passes 100%

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] Zero regressions across the entire Milestone v1.0 test suite
