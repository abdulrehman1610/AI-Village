"""Offline tests for replay configuration and non-blocking JSONL ReplayLogger."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from app.config import DEFAULT_REPLAY_LOG_DIR, REPO_ROOT, Settings, get_settings
from sim.replay import ReplayLogger, replay_day_for_tick


def _tick_frame(tick: int, sim_time: str) -> dict[str, object]:
    return {
        "type": "tick",
        "tick": tick,
        "sim_time": sim_time,
        "day": replay_day_for_tick(tick),
        "speed": 1,
        "running": True,
        "agents": [],
    }


def test_replay_log_dir_settings_default_and_override(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Settings.resolved_replay_log_dir defaults to REPO_ROOT/logs and honors overrides."""
    monkeypatch.delenv("REPLAY_LOG_DIR", raising=False)
    default_settings = Settings()
    assert DEFAULT_REPLAY_LOG_DIR == REPO_ROOT / "logs"
    assert default_settings.resolved_replay_log_dir() == DEFAULT_REPLAY_LOG_DIR

    blank_settings = Settings(replay_log_dir="   ")
    assert blank_settings.resolved_replay_log_dir() == DEFAULT_REPLAY_LOG_DIR

    custom_dir = tmp_path / "custom_logs"
    monkeypatch.setenv("REPLAY_LOG_DIR", str(custom_dir))
    env_settings = get_settings()
    assert env_settings.resolved_replay_log_dir() == custom_dir


def test_replay_day_for_tick_boundary_math() -> None:
    """Replay day partitioning matches SimClock boundaries for start_minute_of_day=360."""
    assert replay_day_for_tick(0) == 1
    assert replay_day_for_tick(1079) == 1
    assert replay_day_for_tick(1080) == 2
    assert replay_day_for_tick(2519) == 2
    assert replay_day_for_tick(2520) == 3

    with pytest.raises(ValueError, match="tick must be an integer"):
        replay_day_for_tick(True)


async def test_ensure_initial_tick_writes_once_without_duplicating(tmp_path: Path) -> None:
    """ensure_initial_tick writes tick 0 once and skips duplicate calls or non-empty files."""
    replay_logger = ReplayLogger(tmp_path / "logs")
    tick_zero = _tick_frame(0, "Day 1 06:00")

    assert await replay_logger.ensure_initial_tick(tick_zero) is True
    assert await replay_logger.ensure_initial_tick(tick_zero) is False

    day_one_log = await replay_logger.read_day(1)
    assert day_one_log is not None
    assert day_one_log.tick_count == 1
    assert day_one_log.first_tick == 0
    assert day_one_log.last_tick == 0
    assert len(day_one_log.frames) == 1

    # A 0-byte file should still accept an initial tick write.
    empty_dir = tmp_path / "empty_logs"
    empty_dir.mkdir(parents=True, exist_ok=True)
    (empty_dir / "day_1.jsonl").write_text("", encoding="utf-8")
    empty_logger = ReplayLogger(empty_dir)
    assert await empty_logger.ensure_initial_tick(tick_zero) is True
    assert await empty_logger.ensure_initial_tick(tick_zero) is False

    with pytest.raises(ValueError, match="type='tick'"):
        await replay_logger.ensure_initial_tick({"type": "event", "tick": 0})
    with pytest.raises(ValueError, match="tick must be an integer"):
        await replay_logger.ensure_initial_tick({"type": "tick", "tick": True})


async def test_log_frames_filters_metrics_routes_days_and_preserves_order(
    tmp_path: Path,
) -> None:
    """log_frames ignores metrics, routes boundary frames by tick day, and stays ordered."""
    replay_logger = ReplayLogger(tmp_path / "logs")

    await replay_logger.log_frames(
        [
            {"type": "metrics", "tick": 1079, "total_calls": 5},
            {"type": "tick", "tick": True, "sim_time": "invalid"},
            {
                "type": "dialogue",
                "tick": 1079,
                "sim_time": "Day 1 23:59",
                "speaker": "Maya",
                "listener": "Liam",
            },
            _tick_frame(1080, "Day 2 00:00"),
            {"type": "metrics", "tick": 1080, "total_calls": 6},
        ]
    )

    day1 = await replay_logger.read_day(1)
    day2 = await replay_logger.read_day(2)
    assert day1 is not None
    assert day2 is not None
    assert len(day1.frames) == 1
    assert day1.frames[0]["type"] == "dialogue"
    assert day1.frames[0]["tick"] == 1079
    assert day1.tick_count == 0
    assert len(day2.frames) == 1
    assert day2.frames[0]["type"] == "tick"
    assert day2.frames[0]["tick"] == 1080
    assert day2.tick_count == 1

    # Concurrent asyncio.gather writes preserve chronological frame order without corruption.
    concurrent_logger = ReplayLogger(tmp_path / "concurrent")
    await asyncio.gather(
        *[
            concurrent_logger.log_frame(
                _tick_frame(idx, f"Day 1 {6 + (idx // 60):02d}:{idx % 60:02d}")
            )
            for idx in range(25)
        ]
    )
    concurrent_day1 = await concurrent_logger.read_day(1)
    assert concurrent_day1 is not None
    assert concurrent_day1.tick_count == 25
    assert [frame["tick"] for frame in concurrent_day1.frames] == list(range(25))


async def test_list_days_and_read_day_edge_cases(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """list_days sorts summaries accurately and read_day tolerates corrupt trailing lines."""
    log_dir = tmp_path / "logs"
    replay_logger = ReplayLogger(log_dir)

    assert await replay_logger.list_days() == []
    assert await replay_logger.read_day(1) is None

    with pytest.raises(ValueError, match="day must be an integer >= 1"):
        await replay_logger.read_day(0)
    with pytest.raises(ValueError, match="day must be an integer >= 1"):
        await replay_logger.read_day(True)

    await replay_logger.log_frames(
        [
            _tick_frame(1080, "Day 2 00:00"),
            {"type": "event", "tick": 1085, "sim_time": "Day 2 00:05", "text": "Market bell"},
            _tick_frame(0, "Day 1 06:00"),
            {"type": "reflection", "tick": 10, "sim_time": "Day 1 06:10", "agent_id": "maya"},
            _tick_frame(11, "Day 1 06:11"),
        ]
    )

    # Empty file and non-matching filenames should be ignored by list_days.
    (log_dir / "day_3.jsonl").write_text("", encoding="utf-8")
    (log_dir / "notes.jsonl").write_text(json.dumps({"type": "tick", "tick": 0}), encoding="utf-8")

    # Append a blank line and malformed trailing line to day_1.jsonl.
    with (log_dir / "day_1.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")
        handle.write('{"type":"tick","tick":12,"truncated"\n')

    summaries = await replay_logger.list_days()
    assert [summary.day for summary in summaries] == [1, 2]

    s1, s2 = summaries
    assert s1.tick_count == 2
    assert s1.frame_count == 3
    assert s1.first_tick == 0
    assert s1.last_tick == 11
    assert s1.first_sim_time == "Day 1 06:00"
    assert s1.last_sim_time == "Day 1 06:11"

    assert s2.tick_count == 1
    assert s2.frame_count == 2
    assert s2.first_tick == 1080
    assert s2.last_tick == 1085
    assert s2.first_sim_time == "Day 2 00:00"
    assert s2.last_sim_time == "Day 2 00:05"

    with caplog.at_level(logging.WARNING):
        day1_log = await replay_logger.read_day(1)
    assert day1_log is not None
    assert day1_log.tick_count == 2
    assert day1_log.first_tick == 0
    assert day1_log.last_tick == 11
    assert len(day1_log.frames) == 3
    assert "Skipping corrupt replay JSON line" in caplog.text
