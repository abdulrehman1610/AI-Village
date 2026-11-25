"""Asynchronous JSONL replay log writer and reader partitioned by simulated day."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from sim.clock import TICKS_PER_DAY

logger = logging.getLogger(__name__)

ALLOWED_REPLAY_FRAME_TYPES: frozenset[str] = frozenset(
    {"tick", "dialogue", "event", "reflection"}
)
_DAY_FILE_RE = re.compile(r"^day_([1-9]\d*)\.jsonl$")


class ReplayDaySummary(BaseModel):
    """Metadata summary describing one recorded simulation day JSONL file."""

    day: int
    tick_count: int
    frame_count: int
    first_tick: int
    last_tick: int
    first_sim_time: str
    last_sim_time: str


class ReplayDayLog(BaseModel):
    """Ordered replay frames and tick bounds loaded from a single day JSONL file."""

    day: int
    tick_count: int
    first_tick: int | None
    last_tick: int | None
    frames: list[dict[str, Any]]


def replay_day_for_tick(tick: int, *, start_minute_of_day: int = 360) -> int:
    """Map a simulation tick to its 1-indexed SimClock day for replay log partitioning."""
    if isinstance(tick, bool) or not isinstance(tick, int):
        raise ValueError(f"tick must be an integer, got {tick!r}")
    if (
        isinstance(start_minute_of_day, bool)
        or not isinstance(start_minute_of_day, int)
        or not 0 <= start_minute_of_day < TICKS_PER_DAY
    ):
        raise ValueError(
            f"start_minute_of_day must be in [0, {TICKS_PER_DAY}), got {start_minute_of_day!r}"
        )
    return ((start_minute_of_day + max(0, tick)) // TICKS_PER_DAY) + 1


def _read_day_frames_sync(path: Path) -> list[dict[str, Any]]:
    """Read and parse JSON dict frames from a day JSONL file, skipping corrupt lines."""
    frames: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Skipping corrupt replay JSON line in %s:%d: %s",
                    path,
                    line_no,
                    exc,
                )
                continue
            if not isinstance(parsed, dict):
                logger.warning(
                    "Skipping non-object replay JSON line in %s:%d",
                    path,
                    line_no,
                )
                continue
            frames.append({str(key): value for key, value in parsed.items()})
    return frames


class ReplayLogger:
    """Non-blocking per-day JSONL replay log writer and reader using asyncio.to_thread."""

    def __init__(self, log_dir: Path | str, *, start_minute_of_day: int = 360) -> None:
        if (
            isinstance(start_minute_of_day, bool)
            or not isinstance(start_minute_of_day, int)
            or not 0 <= start_minute_of_day < TICKS_PER_DAY
        ):
            raise ValueError(
                f"start_minute_of_day must be in [0, {TICKS_PER_DAY}), got {start_minute_of_day!r}"
            )
        self.log_dir = Path(log_dir)
        self.start_minute_of_day = start_minute_of_day
        self._lock = asyncio.Lock()

    def day_path(self, day: int) -> Path:
        """Return the JSONL file path for a 1-indexed simulated day."""
        if isinstance(day, bool) or not isinstance(day, int) or day < 1:
            raise ValueError(f"day must be an integer >= 1, got {day!r}")
        return self.log_dir / f"day_{day}.jsonl"

    async def log_frame(
        self,
        frame: Mapping[str, Any],
        *,
        start_minute_of_day: int | None = None,
    ) -> None:
        """Append a single replayable frame to its corresponding day JSONL file."""
        await self.log_frames([frame], start_minute_of_day=start_minute_of_day)

    async def log_frames(
        self,
        frames: Sequence[Mapping[str, Any]],
        *,
        start_minute_of_day: int | None = None,
    ) -> None:
        """Filter, partition by SimClock day, and append replay frames non-blockingly."""
        effective_start = (
            self.start_minute_of_day if start_minute_of_day is None else start_minute_of_day
        )
        grouped: dict[int, list[str]] = {}
        for frame in frames:
            frame_type = frame.get("type")
            if not isinstance(frame_type, str) or frame_type not in ALLOWED_REPLAY_FRAME_TYPES:
                continue
            tick = frame.get("tick")
            if isinstance(tick, bool) or not isinstance(tick, int):
                continue
            day = replay_day_for_tick(tick, start_minute_of_day=effective_start)
            try:
                serialized = json.dumps(
                    dict(frame),
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            except (TypeError, ValueError) as exc:
                logger.warning("Skipping non-serializable replay frame (%s): %s", frame_type, exc)
                continue
            grouped.setdefault(day, []).append(serialized)

        if not grouped:
            return

        async with self._lock:
            await asyncio.to_thread(self._append_grouped_sync, grouped)

    async def ensure_initial_tick(
        self,
        tick_payload: Mapping[str, Any],
        *,
        start_minute_of_day: int | None = None,
    ) -> bool:
        """Write an initial tick frame only if the target day log does not exist or is empty."""
        if tick_payload.get("type") != "tick":
            raise ValueError("ensure_initial_tick requires a frame with type='tick'")
        tick = tick_payload.get("tick")
        if isinstance(tick, bool) or not isinstance(tick, int):
            raise ValueError(f"tick must be an integer, got {tick!r}")

        effective_start = (
            self.start_minute_of_day if start_minute_of_day is None else start_minute_of_day
        )
        day = replay_day_for_tick(tick, start_minute_of_day=effective_start)
        serialized = (
            json.dumps(dict(tick_payload), separators=(",", ":"), ensure_ascii=False) + "\n"
        )

        async with self._lock:
            return await asyncio.to_thread(self._ensure_initial_tick_sync, day, serialized)

    async def list_days(self) -> list[ReplayDaySummary]:
        """Return sorted metadata summaries for all non-empty recorded replay days."""
        async with self._lock:
            return await asyncio.to_thread(self._list_days_sync)

    async def read_day(self, day: int) -> ReplayDayLog | None:
        """Load ordered frames for a simulated day, or None if no log file exists."""
        path = self.day_path(day)
        async with self._lock:
            return await asyncio.to_thread(self._read_day_sync, day, path)

    def _append_grouped_sync(self, grouped: dict[int, list[str]]) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for day in sorted(grouped):
            path = self.day_path(day)
            lines = grouped[day]
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
                handle.flush()

    def _ensure_initial_tick_sync(self, day: int, serialized_line: str) -> bool:
        path = self.day_path(day)
        if path.exists() and path.stat().st_size > 0:
            return False
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(serialized_line)
            handle.flush()
        return True

    def _list_days_sync(self) -> list[ReplayDaySummary]:
        if not self.log_dir.exists() or not self.log_dir.is_dir():
            return []

        summaries: list[ReplayDaySummary] = []
        for entry in self.log_dir.iterdir():
            if not entry.is_file():
                continue
            match = _DAY_FILE_RE.match(entry.name)
            if match is None:
                continue
            day = int(match.group(1))
            frames = _read_day_frames_sync(entry)
            if not frames:
                continue

            tick_count = 0
            ticks: list[int] = []
            sim_times: list[str] = []
            for frame in frames:
                if frame.get("type") == "tick":
                    tick_count += 1
                tick_val = frame.get("tick")
                if isinstance(tick_val, int) and not isinstance(tick_val, bool):
                    ticks.append(tick_val)
                sim_time_val = frame.get("sim_time")
                if isinstance(sim_time_val, str):
                    sim_times.append(sim_time_val)

            summaries.append(
                ReplayDaySummary(
                    day=day,
                    tick_count=tick_count,
                    frame_count=len(frames),
                    first_tick=ticks[0] if ticks else 0,
                    last_tick=ticks[-1] if ticks else 0,
                    first_sim_time=sim_times[0] if sim_times else "",
                    last_sim_time=sim_times[-1] if sim_times else "",
                )
            )

        summaries.sort(key=lambda item: item.day)
        return summaries

    def _read_day_sync(self, day: int, path: Path) -> ReplayDayLog | None:
        if not path.exists() or not path.is_file():
            return None

        frames = _read_day_frames_sync(path)
        tick_count = 0
        ticks: list[int] = []
        for frame in frames:
            if frame.get("type") == "tick":
                tick_count += 1
            tick_val = frame.get("tick")
            if isinstance(tick_val, int) and not isinstance(tick_val, bool):
                ticks.append(tick_val)

        return ReplayDayLog(
            day=day,
            tick_count=tick_count,
            first_tick=ticks[0] if ticks else None,
            last_tick=ticks[-1] if ticks else None,
            frames=frames,
        )
