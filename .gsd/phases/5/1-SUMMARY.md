---
phase: 5
plan: 1
completed_at: 2026-11-25T12:05:39+05:00
duration_minutes: 7
---

# Summary: Plan 5.1 — Backend Replay Logger, Config & LLM Metrics Telemetry

## Results
- 3 tasks completed
- All verifications passed offline (`pytest`, `ruff check .`, `mypy .`)

## Tasks Completed
| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Add `Settings.replay_log_dir` and implement non-blocking `ReplayLogger` in `backend/sim/replay.py` | `22d5517` | ✅ |
| 2 | Add `LLMGateway.get_metrics_snapshot` and call tracking in `backend/llm/gateway.py` | `57b40b7` | ✅ |
| 3 | Add unit tests for `ReplayLogger` and `LLMGateway` metrics aggregation | `64bdd5a` | ✅ |

## Deviations Applied
None — executed as planned.

## Files Changed
- `backend/app/config.py` — Added `DEFAULT_REPLAY_LOG_DIR`, `Settings.replay_log_dir`, and `Settings.resolved_replay_log_dir()`.
- `.env.example` — Added `REPLAY_LOG_DIR=` configuration key.
- `backend/sim/replay.py` — Implemented `ALLOWED_REPLAY_FRAME_TYPES`, `replay_day_for_tick`, `ReplayDaySummary`, `ReplayDayLog`, and async `ReplayLogger` (`day_path`, `log_frame`, `log_frames`, `ensure_initial_tick`, `list_days`, `read_day`) using `asyncio.Lock` and `asyncio.to_thread`.
- `backend/llm/gateway.py` — Added `PurposeMetrics`, `ModelMetrics`, `TickMetricsPoint`, `MetricsSnapshot`, `total_recorded_calls`, in-memory fallback tracking in `_record_call` when `db is None`, and `get_metrics_snapshot()` while preserving `get_usage_summary` and `day_for_tick`.
- `backend/tests/test_replay.py` — Added offline unit tests covering `Settings.resolved_replay_log_dir()`, `replay_day_for_tick` boundaries, `ensure_initial_tick`, `log_frames` filtering/day routing/concurrency, `list_days()`, and `read_day()` corrupt-line handling using `tmp_path`.
- `backend/tests/test_llm_gateway.py` — Added offline unit tests covering `get_metrics_snapshot()` on empty DB, mixed live/retry/cache/multi-day/multi-model calls, `max_history_points` slicing, and `db=None` parity.

## Verification
- `Set-Location backend; .\.venv\Scripts\pytest.exe -v tests/test_replay.py tests/test_llm_gateway.py tests/test_config.py`: ✅ Passed (`27 passed in 2.53s`)
- `Set-Location backend; .\.venv\Scripts\ruff.exe check tests/test_replay.py tests/test_llm_gateway.py`: ✅ Passed (`All checks passed!`)
- `Set-Location backend; .\.venv\Scripts\mypy.exe tests/test_replay.py tests/test_llm_gateway.py`: ✅ Passed (`Success: no issues found in 2 source files`)
- `Set-Location backend; .\.venv\Scripts\ruff.exe check .`: ✅ Passed (`All checks passed!`)
- `Set-Location backend; .\.venv\Scripts\mypy.exe .`: ✅ Passed (`Success: no issues found in 53 source files`)
- `Set-Location backend; .\.venv\Scripts\pytest.exe -v`: ✅ Passed (`114 passed in 13.13s`)
