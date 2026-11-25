---
phase: 6
plan: 2
wave: 1
depends_on: []
files_modified:
  - scripts/run_day_simulation.py
  - backend/tests/test_full_day_simulation.py
  - docs/PRD.md
  - scripts/generate_docs_assets.py
  - docs/architecture.png
  - docs/demo.gif
  - .gsd/phases/6/day_simulation_metrics.json
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "A complete 1,440-tick simulated village day (`Day 1 06:00` -> `Day 2 06:00`) executes offline via `MockProvider(seed=42)` + injected god-mode events with zero crashes, zero wall collisions, zero tile overlaps, valid 4-way A* paths, Day 1 & Day 2 hierarchical plans + event replans, multi-turn dialogues + rumor spread, threshold reflections (>=150 importance with citations), relationship updates, and valid `day_1.jsonl` (`tick 0..1079`) + `day_2.jsonl` (`tick 1080..1440`) replay logs"
    - "Real empirical metrics from the 1,440-tick run are persisted to `.gsd/phases/6/day_simulation_metrics.json` for `docs/report.md`"
    - "`docs/PRD.md` matches `AI Village Product Requirements Document.md`, and `scripts/generate_docs_assets.py` generates crisp `docs/architecture.png` and animated palette-optimized `docs/demo.gif` using existing host tools (Edge headless / stdlib PNG + `ffmpeg`) with zero new pip dependencies"
    - "All scripts in `scripts/` and tests in `backend/tests/` pass `ruff check` and strict `mypy`"
  artifacts:
    - "scripts/run_day_simulation.py runs 1,440 ticks offline, asserts invariants, and writes empirical telemetry JSON"
    - "backend/tests/test_full_day_simulation.py verifies the full 1,440-tick Day 1 -> Day 2 lifecycle inside pytest"
    - "docs/PRD.md preserves canonical PRD v1 inside docs/ per PRD Section 11"
    - "scripts/generate_docs_assets.py deterministically creates docs/architecture.png and docs/demo.gif from real tilemap, villager sprites, and simulation replay frames"
    - "docs/architecture.png, docs/demo.gif, and .gsd/phases/6/day_simulation_metrics.json exist and are non-empty"
  key_links:
    - "`scripts/run_day_simulation.py` uses `create_app`, `SimulationEngine.step_once`, `POST /events`, `GET /relationships`, `GET /metrics`, `GET /replay/1`, and `GET /replay/2` to collect real SQLite + replay + gateway telemetry"
    - "`scripts/generate_docs_assets.py` reads `frontend/public/assets/map.json`, `frontend/public/assets/tileset.png`, and `frontend/public/assets/sprites.png` plus real deterministic simulation replay frames to render `docs/demo.gif` via `ffmpeg` `palettegen`/`paletteuse`"
    - "Both scripts in `scripts/` strictly satisfy `ruff check --config backend/pyproject.toml scripts` and `mypy --config-file backend/pyproject.toml scripts` (`strict = true`)"
---

# Plan 6.2: Full-Day (1,440-Tick) Verification, Empirical Runner & Visual Docs Assets

## Objective
Verify a complete 24-hour simulated village day (1,440 ticks, `Day 1 06:00` -> `Day 2 06:00`, crossing midnight rollover) offline using `MockProvider(seed=42)`, capture empirical telemetry for the AI Lab Report (`docs/report.md`), sync `docs/PRD.md`, and deterministically generate `docs/architecture.png` and `docs/demo.gif` with zero new Python dependencies (`REQ-16`, `NFR-03`, `NFR-04`, `NFR-05`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/6/RESEARCH.md
- AI Village Product Requirements Document.md
- backend/pyproject.toml
- backend/sim/clock.py
- backend/sim/replay.py
- backend/agents/agent.py
- backend/llm/gateway.py
- backend/tests/test_100_ticks_invariants.py
- scripts/generate_village_map.py

## Tasks

<task type="auto">
  <name>Create strict-typed 1,440-tick empirical runner and pytest full-day invariant suite</name>
  <files>
    scripts/run_day_simulation.py
    backend/tests/test_full_day_simulation.py
  </files>
  <action>
    Implement both a standalone CLI empirical runner (`scripts/run_day_simulation.py`) and an offline pytest integration test (`backend/tests/test_full_day_simulation.py`) covering a full 1,440-tick village day (`Day 1 06:00` -> `Day 2 06:00`).

    Steps:
    1. Create `scripts/run_day_simulation.py` (fully type-annotated for `mypy --strict` and clean for `ruff`):
       - Use standard top-level imports (`from app.config import Settings`, `from app.main import create_app`, `from memory.store import MemoryStore`, `from sim.engine import SimulationEngine`, `from sim.replay import ALLOWED_REPLAY_FRAME_TYPES`, `from sim.world import WorldMap`) matching the editable package installed in `backend/.venv` and CI.
       - Accept CLI args (`--ticks` default `1440`, `--seed` default `42`, `--output-json` optional `Path`, `--replay-dir` optional `Path` using `tempfile.TemporaryDirectory()` if omitted).
       - Boot `create_app(Settings(sim_auto_start=False, sim_tick_seconds=0.05, sim_seed=seed, llm_provider="mock", embedding_provider="mock", database_url=..., replay_log_dir=...))` inside `TestClient(app)`.
       - Step ticks `1..ticks` via `client.portal.call(engine.step_once)`, verifying at every tick:
         - 8 active agents, zero wall collisions (`world.is_walkable(agent.x, agent.y)`), zero tile overlaps (`len(set(positions)) == 8`), and valid 4-way walkable A* `agent.path` steps.
       - Inject two mid-day god-mode events via `POST /events`:
         - Tick `180` (`Day 1 09:00`): `"Sudden fire near the Market spice stalls"` at `"Market"`
         - Tick `540` (`Day 1 15:00`): `"Rumor spreads that Maya hid rare saffron loaves at the Bakery"` at `"Bakery"`
       - After completing 1,440 ticks, query `/metrics`, `/relationships`, `/replay`, `/replay/1`, `/replay/2`, plus SQLite (`memories` grouped by `type`, `conversations`, `events`, `llm_calls`, cited `reflection` IDs, and rumor propagation across distinct agents whose memories mention `"fire"` or `"saffron"`/`"rumor"`), and output a structured JSON metrics summary (wall-clock runtime, invariant pass counts, Day 1 & Day 2 plan stats, memory counts by type, conversations, rumor reach, reflections & citation count, relationship edges & affinity min/max/avg, LLM calls by purpose & model, cache hits/rate, total tokens in/out, projected Gemini Flash/Pro cost from `llm.gateway.estimate_cost_usd`, and `day_1.jsonl`/`day_2.jsonl` frame counts).
    2. Create `backend/tests/test_full_day_simulation.py` (independent of `scripts/` so `pytest` works from `working-directory: backend` in CI):
       - Run 1,440 offline ticks (`Day 1 06:00` -> `Day 2 06:00`) using `MockProvider(seed=42)` and `DeterministicEmbeddingProvider` with an injected mid-day god-mode event at tick 360 (`"Sudden fire near the Market spice stalls"`, `"Market"`).
       - Assert:
         - Zero crashes, `payload.tick == 1440`, `payload.sim_time == "Day 2 06:00"`, `payload.day == 2`.
         - Zero wall collisions, zero tile overlaps, valid 4-way A* paths on every tick.
         - Day 1 wake-up plans created AND Day 2 morning/midnight rollover plans (`plan_state.day == 2` after tick `1080`) created; event-affected agents clear `needs_replan` cleanly.
         - `conversations >= 1` (each <= 6 turns), rumor/event text appears in memories of more agents than just the initially affected event recipients (verifying multi-agent rumor propagation), threshold reflections (`type == "reflection"`) created (`>= 1`) with non-empty `cited_memory_ids` in `metadata_json`, and canonical `GET /relationships` edges (`>= 1`) updated with `-1.0 <= affinity <= 1.0`.
         - `GET /replay` lists Days `1` and `2`: `day_1.jsonl` covers ticks `0..1079` (`tick_count == 1080`), `day_2.jsonl` covers ticks `1080..1440` (`tick_count == 361`), sorted ticks, only `ALLOWED_REPLAY_FRAME_TYPES`, and contains `tick`, `event`, `dialogue`, and `reflection` frames.
         - `GET /metrics` matches SQLite `llm_calls` row aggregates (`total_calls`, `cache_hits`, `tokens_in`, `tokens_out`, `cost_est`).

    AVOID: Importing from `scripts/` inside `backend/tests/test_full_day_simulation.py` because CI runs `pytest` inside `working-directory: backend` where `scripts/` is not on `PYTHONPATH`.
    AVOID: Placing top-level imports after `sys.path.insert(...)` in `scripts/run_day_simulation.py` because Ruff rule `E402` flags module imports not at top of file.
    AVOID: Asserting `budget_tokens_used <= daily_token_limit` in a 1,440-tick run with default `250_000` limit because `LLMGateway` switches gracefully to `fallback_provider` once the cap is reached while continuing to log fallback call tokens (`backend/llm/gateway.py:279-329`).
  </action>
  <verify>
    Run each command individually (never chain with `&&`):
    - `backend/.venv/Scripts/ruff.exe check --config backend/pyproject.toml scripts/run_day_simulation.py backend/tests/test_full_day_simulation.py`
    - `backend/.venv/Scripts/mypy.exe --config-file backend/pyproject.toml scripts/run_day_simulation.py backend/tests/test_full_day_simulation.py`
    - From `backend/` working directory: `.venv/Scripts/pytest.exe -v tests/test_full_day_simulation.py`
  </verify>
  <done>
    `test_full_day_simulation.py` passes all 1,440-tick Day 1 -> Day 2 invariants offline in pytest, and `scripts/run_day_simulation.py` passes `ruff` and strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Sync docs/PRD.md and author deterministic docs visual asset generator</name>
  <files>
    docs/PRD.md
    scripts/generate_docs_assets.py
  </files>
  <action>
    Sync `docs/PRD.md` per PRD Section 11 without breaking root `.gsd/` links, and build `scripts/generate_docs_assets.py` to generate `docs/architecture.png` and `docs/demo.gif` using zero extra Python dependencies.

    Steps:
    1. Copy `AI Village Product Requirements Document.md` verbatim to `docs/PRD.md` (preserving the original root file intact).
    2. Create `scripts/generate_docs_assets.py` (fully typed for `mypy --strict` and clean for `ruff`):
       - **Part A — `docs/architecture.png`**:
         - Render a high-resolution (`1400x820`) clean technical SVG/HTML architecture diagram illustrating the exact AI Village architecture: Browser (`Phaser 3`, `Cytoscape.js`, `Chart.js`, Inspector/Time/Replay UI) <-> Nginx / Vite Proxy (`12 REST endpoints` + `/ws` WebSocket) <-> FastAPI Server (`SimulationEngine`, `heapq` A*, `AgentBrain` 5-stage loop, `DailyPlanner`, `ConversationManager`, `ReflectionManager`, `MemoryRetriever` `w_r*recency + w_i*importance + w_v*relevance`, `LLMGateway` Pydantic v2/Cache/Budget) <-> Persistence & Providers (`SQLite WAL` 7 tables, `day_{N}.jsonl` Replay Logs, `Gemini Flash/Pro` + `MockProvider` + `all-MiniLM-L6-v2`).
         - Detect Microsoft Edge (`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`, `msedge`, or `google-chrome`) and capture via `--headless=new --disable-gpu --screenshot=... --window-size=1400,820 --hide-scrollbars`; provide a clean pure-Python stdlib RGBA fallback if headless browser binary is absent.
       - **Part B — `docs/demo.gif`**:
         - Decode `frontend/public/assets/map.json`, `frontend/public/assets/tileset.png`, and `frontend/public/assets/sprites.png` using stdlib `json`, `struct`, and `zlib` (note: `tileset.png` and `sprites.png` are 8-bit RGBA filter-0 PNGs generated by `scripts/generate_village_map.py`).
         - Run a deterministic simulation snippet (or accept `--replay-jsonl` + slice around a rich event window, defaulting to an in-process 120-tick `MockProvider(seed=42)` run with an injected god-mode event `"Sudden spice delivery arrived at the Bakery"` at `"Bakery"` on tick 35 so movement, speech bubbles, event pulse, and activity updates are guaranteed within ~80 captured ticks).
         - Composite clean 960x620 frames showing:
           - Top HUD bar (`AI Village`, `Live`, `Day 1 · HH:MM · 16x`, `Tick N`)
           - Scaled real tilemap (`ground` + `structures` layers + named location labels) with animated villager sprites (4-frame walk cycle along A* routes), active speech bubbles above conversing agents, and an expanding concentric gold/crimson event pulse ring + banner when the god-mode event triggers
           - Right-hand Activity Feed sidebar listing recent tick/dialogue/event entries rendered cleanly with a crisp bitmap font (`5x7` scaled integer glyph renderer in pure Python)
         - Encode PNG frames into `docs/demo.gif` using `ffmpeg -y -framerate 8 -i frame_%04d.png -vf "split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" -loop 0 docs/demo.gif` inside a `TemporaryDirectory` so no frame clutter remains.

    AVOID: Adding `Pillow`, `matplotlib`, or `playwright` to `backend/pyproject.toml` (PRD Rule 10 forbids unrequested dependencies).
    AVOID: Deleting or renaming `AI Village Product Requirements Document.md` at repo root because existing `.gsd/` artifacts reference it directly.
  </action>
  <verify>
    `backend/.venv/Scripts/ruff.exe check --config backend/pyproject.toml scripts/generate_docs_assets.py`
    `backend/.venv/Scripts/mypy.exe --config-file backend/pyproject.toml scripts/generate_docs_assets.py`
    `backend/.venv/Scripts/python.exe -c "from pathlib import Path; assert Path('docs/PRD.md').read_text(encoding='utf-8') == Path('AI Village Product Requirements Document.md').read_text(encoding='utf-8'); print('PRD_SYNC_OK')"`
  </verify>
  <done>
    `docs/PRD.md` is byte-identical to `AI Village Product Requirements Document.md`, and `scripts/generate_docs_assets.py` passes `ruff` and strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Execute full-day empirical run and generate docs visual assets</name>
  <files>
    .gsd/phases/6/day_simulation_metrics.json
    docs/architecture.png
    docs/demo.gif
  </files>
  <action>
    Run both scripts end-to-end to produce verified empirical simulation telemetry and final visual assets for `README.md` and `docs/report.md`.

    Steps:
    1. Execute `backend/.venv/Scripts/python.exe scripts/run_day_simulation.py --output-json .gsd/phases/6/day_simulation_metrics.json` to run the complete 1,440-tick simulation (`Day 1 06:00` -> `Day 2 06:00`) and record exact empirical JSON telemetry.
    2. Execute `backend/.venv/Scripts/python.exe scripts/generate_docs_assets.py` to generate `docs/architecture.png` and `docs/demo.gif`.
    3. Inspect `.gsd/phases/6/day_simulation_metrics.json`, `docs/architecture.png`, and `docs/demo.gif` to confirm valid file headers (`\x89PNG`, `GIF89a`), non-zero sizes (e.g., >20 KB for `architecture.png`, >100 KB and <10 MB for `demo.gif`), and confirm `docs/architecture.png` and `docs/demo.gif` visually look crisp (read `docs/architecture.png` via `read_file` if supported or verify dimensions/metadata + inspect JSON telemetry numbers).

    AVOID: Hand-estimating or fabricating numbers in `.gsd/phases/6/day_simulation_metrics.json`; every metric must come straight from `scripts/run_day_simulation.py` output.
  </action>
  <verify>
    `backend/.venv/Scripts/python.exe -c "import json; from pathlib import Path; m=json.loads(Path('.gsd/phases/6/day_simulation_metrics.json').read_text()); assert m['ticks_completed']==1440 and m['invariants']['wall_collisions']==0 and m['invariants']['tile_overlaps']==0; a=Path('docs/architecture.png').read_bytes(); g=Path('docs/demo.gif').read_bytes(); assert a.startswith(bytes([137,80,78,71])) and len(a)>20000; assert g[:6] in (b'GIF89a', b'GIF87a') and len(g)>50000; print('ASSETS_AND_METRICS_OK', len(a), len(g), m['llm']['total_calls'])"`
  </verify>
  <done>
    `.gsd/phases/6/day_simulation_metrics.json`, `docs/architecture.png`, and `docs/demo.gif` exist, pass magic-byte and size checks, and contain verified 1,440-tick empirical telemetry.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `backend/tests/test_full_day_simulation.py` passes all 1,440-tick Day 1 -> Day 2 invariants (`day_1.jsonl` + `day_2.jsonl`, plans/replans, conversations + rumor reach, reflections + citations, relationships, metrics parity)
- [ ] `scripts/run_day_simulation.py` and `scripts/generate_docs_assets.py` pass `ruff` and strict `mypy` (`--config-file backend/pyproject.toml scripts`)
- [ ] `.gsd/phases/6/day_simulation_metrics.json`, `docs/PRD.md`, `docs/architecture.png`, and `docs/demo.gif` are generated and verified

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in tests, `ruff`, or `mypy`
