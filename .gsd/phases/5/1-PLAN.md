---
phase: 5
plan: 1
wave: 1
depends_on: []
files_modified:
  - backend/app/config.py
  - .env.example
  - backend/sim/replay.py
  - backend/llm/gateway.py
  - backend/tests/test_llm_gateway.py
  - backend/tests/test_replay.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`Settings.replay_log_dir` defaults to `REPO_ROOT / 'logs'` via `resolved_replay_log_dir()` and honors `REPLAY_LOG_DIR` overrides without committing generated `.jsonl` files"
    - "`ReplayLogger` writes `tick`, `dialogue`, `event`, and `reflection` frames asynchronously via `asyncio.Lock` + `asyncio.to_thread` to `day_{day}.jsonl` using SimClock day math (`((start_minute_of_day + tick) // 1440) + 1`), ignoring `metrics` frames and preventing duplicate tick-0 writes on restart"
    - "`LLMGateway.get_metrics_snapshot()` aggregates total calls, cache hits, cache hit rate, tokens in/out, estimated USD cost, average/max latency, daily budget usage, `by_purpose`, `by_model`, and cumulative per-tick `history` over SQLite `llm_calls` (with in-memory fallback when `db is None`)"
  artifacts:
    - "backend/app/config.py exposes `DEFAULT_REPLAY_LOG_DIR`, `Settings.replay_log_dir`, and `Settings.resolved_replay_log_dir()`"
    - ".env.example documents `REPLAY_LOG_DIR=`"
    - "backend/sim/replay.py implements `replay_day_for_tick`, `ReplayDaySummary`, `ReplayDayLog`, and async `ReplayLogger`"
    - "backend/llm/gateway.py defines `PurposeMetrics`, `ModelMetrics`, `TickMetricsPoint`, `MetricsSnapshot`, `total_recorded_calls`, and `get_metrics_snapshot()`"
    - "backend/tests/test_llm_gateway.py and backend/tests/test_replay.py verify metrics aggregation and JSONL replay behavior offline"
  key_links:
    - "backend/sim/replay.py imports `TICKS_PER_DAY` from `sim.clock` so replay file day boundaries align with `SimClock.day`"
    - "backend/llm/gateway.py computes `MetricsSnapshot` from `LLMCallRecord` rows persisted by `_record_call` (or `_memory_records` when `db is None`)"
---

# Plan 5.1: Backend Replay Logger, Config & LLM Metrics Telemetry

## Objective
Add configurable JSONL replay log directory settings, build the non-blocking `ReplayLogger` service (`backend/sim/replay.py`), and extend `LLMGateway` (`backend/llm/gateway.py`) with rich telemetry aggregation (`get_metrics_snapshot()` and `total_recorded_calls`) backed by `llm_calls` and unit-tested offline (`REQ-13`, `REQ-14`, `NFR-03`, `NFR-04`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/5/RESEARCH.md
- backend/app/config.py
- .env.example
- backend/sim/clock.py
- backend/llm/gateway.py
- backend/memory/models.py
- backend/tests/test_llm_gateway.py

## Tasks

<task type="auto">
  <name>Add Settings.replay_log_dir and implement non-blocking ReplayLogger in backend/sim/replay.py</name>
  <files>
    backend/app/config.py
    .env.example
    backend/sim/replay.py
  </files>
  <action>
    Extend `Settings` for configurable replay log storage and build `backend/sim/replay.py` to write and read per-day JSONL replay logs without blocking the asyncio event loop.

    Steps:
    1. In `backend/app/config.py`:
       - Add `DEFAULT_REPLAY_LOG_DIR: Path = REPO_ROOT / "logs"` below `DEFAULT_DB_PATH`.
       - Add `replay_log_dir: str = ""` to `Settings`.
       - Add `resolved_replay_log_dir(self) -> Path` returning `Path(configured)` when `self.replay_log_dir.strip()` is non-empty, else `DEFAULT_REPLAY_LOG_DIR`.
    2. In `.env.example`:
       - Append `REPLAY_LOG_DIR=` so users can override the log directory via environment variables.
    3. Create `backend/sim/replay.py`:
       - Import `TICKS_PER_DAY` from `sim.clock`.
       - Define `ALLOWED_REPLAY_FRAME_TYPES: frozenset[str] = frozenset({"tick", "dialogue", "event", "reflection"})`.
       - Define `replay_day_for_tick(tick: int, *, start_minute_of_day: int = 360) -> int`: validate `not isinstance(tick, bool)` and return `((start_minute_of_day + max(0, tick)) // TICKS_PER_DAY) + 1`.
       - Define Pydantic v2 models `ReplayDaySummary(BaseModel)` (`day: int`, `tick_count: int`, `frame_count: int`, `first_tick: int`, `last_tick: int`, `first_sim_time: str`, `last_sim_time: str`) and `ReplayDayLog(BaseModel)` (`day: int`, `tick_count: int`, `first_tick: int | None`, `last_tick: int | None`, `frames: list[dict[str, Any]]`).
       - Implement `ReplayLogger`:
         - `__init__(self, log_dir: Path | str, *, start_minute_of_day: int = 360) -> None` with `self.log_dir = Path(log_dir)`, `self.start_minute_of_day = start_minute_of_day`, `self._lock = asyncio.Lock()`.
         - `day_path(self, day: int) -> Path`: reject `isinstance(day, bool) or day < 1` with `ValueError`, return `self.log_dir / f"day_{day}.jsonl"`.
         - `async def log_frame(self, frame: Mapping[str, Any], *, start_minute_of_day: int | None = None) -> None` delegating to `log_frames([frame], start_minute_of_day=start_minute_of_day)`.
         - `async def log_frames(self, frames: Sequence[Mapping[str, Any]], *, start_minute_of_day: int | None = None) -> None`: filter to frames where `frame.get("type") in ALLOWED_REPLAY_FRAME_TYPES` and `tick = frame.get("tick")` is a non-bool `int` (silently skipping `"metrics"` or invalid payloads), group serialized compact JSON lines by `replay_day_for_tick(tick, start_minute_of_day=effective_start)`, acquire `self._lock`, and call `await asyncio.to_thread(self._append_grouped_sync, grouped)` which creates `self.log_dir.mkdir(parents=True, exist_ok=True)` and opens/appends/flushes each `day_{day}.jsonl` UTF-8 file.
         - `async def ensure_initial_tick(self, tick_payload: Mapping[str, Any], *, start_minute_of_day: int | None = None) -> bool`: validate `tick_payload.get("type") == "tick"` and integer `tick`, compute `day`, acquire `self._lock`, and via `await asyncio.to_thread` write the single line ONLY if `day_{day}.jsonl` does not exist or has size 0 (returning `True` if written, `False` otherwise).
         - `async def list_days(self) -> list[ReplayDaySummary]`: acquire `self._lock` and run `await asyncio.to_thread` scanning `self.log_dir` (returning `[]` if directory does not exist) for filenames matching `^day_([1-9]\d*)\.jsonl$`, parsing valid JSON dict frames, computing `tick_count` (count of `type == "tick"` frames), `frame_count`, `first_tick`, `last_tick`, `first_sim_time`, `last_sim_time`, skipping empty files, sorted ascending by `day`.
         - `async def read_day(self, day: int) -> ReplayDayLog | None`: validate `day >= 1`, acquire `self._lock`, read `self.day_path(day)` via `await asyncio.to_thread`; return `None` if file does not exist; skip blank or corrupt JSON lines with `logger.warning`, return `ReplayDayLog` with ordered `frames`, `tick_count`, `first_tick`, and `last_tick`.

    AVOID: Synchronous disk I/O directly on the asyncio event loop, adding `aiofiles`, logging `"metrics"` frames into `.jsonl`, or computing file day from `clock.day` after `clock.advance()` instead of each frame's own `tick`.
    USE: `asyncio.Lock` + `asyncio.to_thread`, `replay_day_for_tick`, and `TICKS_PER_DAY` from `sim.clock`.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check app/config.py sim/replay.py
    .venv\Scripts\mypy.exe app/config.py sim/replay.py
  </verify>
  <done>
    `Settings.resolved_replay_log_dir()` and `backend/sim/replay.py` exist, enforce non-blocking JSONL persistence with day-boundary accuracy, and pass `ruff` and strict `mypy`.
  </done>
</task>

<task type="auto">
  <name>Add LLMGateway.get_metrics_snapshot and call tracking in backend/llm/gateway.py</name>
  <files>
    backend/llm/gateway.py
  </files>
  <action>
    Extend `backend/llm/gateway.py` with structured Pydantic v2 metrics models, `total_recorded_calls`, in-memory fallback record tracking when `db is None`, and `get_metrics_snapshot()` aggregating over `LLMCallRecord` rows.

    Steps:
    1. Define Pydantic v2 models in `backend/llm/gateway.py` (exported cleanly for `api/rest.py`):
       - `PurposeMetrics(BaseModel)`: `purpose: str`, `calls: int`, `cache_hits: int`, `tokens_in: int`, `tokens_out: int`, `total_tokens: int`, `cost_est: float`, `avg_latency_ms: float`
       - `ModelMetrics(BaseModel)`: `model: str`, `calls: int`, `cache_hits: int`, `tokens_in: int`, `tokens_out: int`, `total_tokens: int`, `cost_est: float`, `avg_latency_ms: float`
       - `TickMetricsPoint(BaseModel)`: `tick: int`, `calls: int`, `cache_hits: int`, `tokens_in: int`, `tokens_out: int`, `total_tokens: int`, `cost_est: float`, `avg_latency_ms: float`, `cumulative_tokens: int`, `cumulative_cost_est: float`
       - `MetricsSnapshot(BaseModel)`: `tick: int = 0`, `sim_time: str = "Day 1 06:00"`, `day: int = 1`, `total_calls: int`, `cache_hits: int`, `cache_hit_rate: float`, `tokens_in: int`, `tokens_out: int`, `total_tokens: int`, `cost_est: float`, `avg_latency_ms: float`, `max_latency_ms: float`, `daily_budget_usd: float`, `daily_token_limit: int`, `budget_day: int`, `budget_tokens_used: int`, `budget_cost_used: float`, `by_purpose: list[PurposeMetrics]`, `by_model: list[ModelMetrics]`, `history: list[TickMetricsPoint]`
    2. In `LLMGateway.__init__`:
       - Initialize `self._recorded_call_count: int = 0` and `self._memory_records: list[LLMCallRecord] = []`.
       - Expose `@property def total_recorded_calls(self) -> int` returning `self._recorded_call_count`.
    3. In `LLMGateway._record_call`:
       - Increment `self._recorded_call_count += 1` inside `async with self._lock:`.
       - When `self.db is None`, append `record` to `self._memory_records` inside `async with self._lock:` so `get_metrics_snapshot()` works identically in unit tests without SQLite.
    4. Implement `async def get_metrics_snapshot(self, *, tick: int = 0, sim_time: str = "Day 1 06:00", day: int = 1, max_history_points: int = 120) -> MetricsSnapshot`:
       - When `self.db is not None`, select `LLMCallRecord` ordered by `(col(LLMCallRecord.tick), col(LLMCallRecord.id))`. Otherwise copy `self._memory_records` under `self._lock` sorted by `row.tick`.
       - Compute scalar totals (`total_calls`, `cache_hits`, `cache_hit_rate`, `tokens_in`, `tokens_out`, `total_tokens`, `cost_est`, `avg_latency_ms`, `max_latency_ms`).
       - Compute `budget_day = self.day_for_tick(tick)` and aggregate `budget_tokens_used` and `budget_cost_used` from non-cached rows where `self.day_for_tick(row.tick) == budget_day`.
       - Group `by_purpose` sorted by `(-calls, purpose)` and `by_model` sorted by `(-calls, model)`.
       - Build ascending `history` per unique `row.tick` with running `cumulative_tokens` and `cumulative_cost_est` across all ticks, then slice `history[-max_history_points:]` when `max_history_points > 0` so cumulative totals remain exact.
       - Preserve `get_usage_summary` unchanged so all existing Phase 2–4 tests keep passing.

    AVOID: Modifying `LLMGateway.day_for_tick` (Phase 2 budget tests depend on `(max(0, tick) // 1440) + 1`) or breaking `get_usage_summary` return keys.
    USE: Existing `LLMCallRecord` SQLModel table and `self._lock` concurrency safety.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\ruff.exe check llm/gateway.py
    .venv\Scripts\mypy.exe llm/gateway.py
  </verify>
  <done>
    `LLMGateway.get_metrics_snapshot()` and `total_recorded_calls` compile cleanly with zero `ruff` or strict `mypy` errors while keeping `get_usage_summary` intact.
  </done>
</task>

<task type="auto">
  <name>Add unit tests for ReplayLogger and LLMGateway metrics aggregation</name>
  <files>
    backend/tests/test_replay.py
    backend/tests/test_llm_gateway.py
  </files>
  <action>
    Create `backend/tests/test_replay.py` and extend `backend/tests/test_llm_gateway.py` to test all config, JSONL replay, and metrics aggregation edge cases offline.

    Steps:
    1. Create `backend/tests/test_replay.py` testing:
       - `Settings().resolved_replay_log_dir() == DEFAULT_REPLAY_LOG_DIR == REPO_ROOT / "logs"` and `REPLAY_LOG_DIR` env override via `monkeypatch.setenv`.
       - `replay_day_for_tick` boundary math: `tick=0 -> 1`, `tick=1079 -> 1`, `tick=1080 -> 2`, `tick=2519 -> 2`, `tick=2520 -> 3` for `start_minute_of_day=360`.
       - `ReplayLogger.ensure_initial_tick` writes tick 0 once and returns `False` without duplicating on repeated calls.
       - `ReplayLogger.log_frames` filters out `"metrics"` frames, routes `tick=1079` cognitive event to `day_1.jsonl` while `tick=1080` goes to `day_2.jsonl`, and preserves chronological ordering under concurrent `asyncio.gather` writes.
       - `list_days()` returns sorted `ReplayDaySummary` entries with accurate `tick_count`, `frame_count`, `first_tick`, `last_tick`, `first_sim_time`, `last_sim_time`.
       - `read_day(day)` returns `None` for missing days, raises `ValueError` for `day < 1`, and tolerates malformed trailing lines cleanly.
    2. Extend `backend/tests/test_llm_gateway.py` testing:
       - `get_metrics_snapshot()` on an empty DB returns zeros and empty lists.
       - `get_metrics_snapshot()` with mixed live calls, retry repair attempts, prompt-cache hits, multiple `purpose`s, and multiple `model`s returns exact `total_calls`, `cache_hits`, `cache_hit_rate`, `tokens_in`, `tokens_out`, `total_tokens`, `cost_est`, `avg_latency_ms`, `max_latency_ms`, `budget_tokens_used`, `budget_cost_used`, `by_purpose`, `by_model`, and monotonic `history` with exact `cumulative_tokens` and `cumulative_cost_est`.
       - `get_metrics_snapshot()` works identically when `db=None` via the in-memory record fallback, and `total_recorded_calls` increments on every call including cache hits.

    AVOID: Writing any test files into the repository `logs/` directory; always use `tmp_path`.
    USE: `pytest` `tmp_path` and `monkeypatch` fixtures.
  </action>
  <verify>
    Run in backend/ (Cwd: backend, separate commands):
    .venv\Scripts\pytest.exe -v tests/test_replay.py tests/test_llm_gateway.py tests/test_config.py
    .venv\Scripts\ruff.exe check tests/test_replay.py tests/test_llm_gateway.py
    .venv\Scripts\mypy.exe tests/test_replay.py tests/test_llm_gateway.py
  </verify>
  <done>
    All tests in `test_replay.py`, `test_llm_gateway.py`, and `test_config.py` pass offline with zero `ruff` or `mypy` issues.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `Settings.resolved_replay_log_dir()` defaults to `REPO_ROOT / "logs"` and supports `REPLAY_LOG_DIR` overrides
- [ ] `ReplayLogger` writes per-day JSONL logs via `asyncio.Lock` + `asyncio.to_thread` aligned to `SimClock` day boundaries
- [ ] `LLMGateway.get_metrics_snapshot()` aggregates totals, latency, cache hit rate, budget usage, `by_purpose`, `by_model`, and `history` from `llm_calls` (with `db=None` fallback)
- [ ] `pytest`, `ruff`, and `mypy` pass for all modified/created files

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in existing gateway or config tests
