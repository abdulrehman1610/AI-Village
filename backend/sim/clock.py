"""Simulation tick clock managing simulated calendar time and speed control."""

from __future__ import annotations

import math
from dataclasses import dataclass

VALID_SPEEDS: tuple[int, ...] = (1, 4, 16)
TICKS_PER_DAY = 1440


@dataclass
class SimClock:
    """Discrete simulation clock where 1 tick equals 1 simulated minute."""

    tick: int = 0
    start_minute_of_day: int = 360  # 06:00 AM on Day 1
    speed: int = 1
    running: bool = True
    base_tick_seconds: float = 1.0

    def __post_init__(self) -> None:
        if isinstance(self.tick, bool) or self.tick < 0:
            raise ValueError(f"tick must be >= 0, got {self.tick!r}")
        if (
            isinstance(self.start_minute_of_day, bool)
            or not 0 <= self.start_minute_of_day < TICKS_PER_DAY
        ):
            raise ValueError(
                f"start_minute_of_day must be in [0, {TICKS_PER_DAY}), "
                f"got {self.start_minute_of_day!r}"
            )
        if isinstance(self.speed, bool) or self.speed not in VALID_SPEEDS:
            raise ValueError(f"Invalid speed {self.speed!r}; must be one of {VALID_SPEEDS}")
        if not math.isfinite(self.base_tick_seconds) or self.base_tick_seconds <= 0:
            raise ValueError(
                f"base_tick_seconds must be a finite number > 0, got {self.base_tick_seconds!r}"
            )

    @property
    def total_minutes(self) -> int:
        """Return total elapsed simulated minutes since Day 1 00:00."""
        return self.start_minute_of_day + self.tick

    @property
    def day(self) -> int:
        """Return 1-indexed simulated day number."""
        return (self.total_minutes // TICKS_PER_DAY) + 1

    @property
    def minute_of_day(self) -> int:
        """Return simulated minute offset within the current day [0, 1439]."""
        return self.total_minutes % TICKS_PER_DAY

    @property
    def hour(self) -> int:
        """Return simulated hour of day [0, 23]."""
        return self.minute_of_day // 60

    @property
    def minute(self) -> int:
        """Return simulated minute of hour [0, 59]."""
        return self.minute_of_day % 60

    @property
    def sim_time_str(self) -> str:
        """Return formatted simulated timestamp such as 'Day 1 06:00'."""
        return f"Day {self.day} {self.hour:02d}:{self.minute:02d}"

    @property
    def tick_interval_seconds(self) -> float:
        """Return real-time seconds per simulation tick at current speed."""
        return self.base_tick_seconds / float(self.speed)

    def advance(self, steps: int = 1) -> int:
        """Advance the clock by a positive integer number of ticks."""
        if isinstance(steps, bool) or steps < 1:
            raise ValueError(f"steps must be >= 1, got {steps!r}")
        self.tick += steps
        return self.tick

    def start(self) -> None:
        """Mark the simulation clock as running."""
        self.running = True

    def pause(self) -> None:
        """Mark the simulation clock as paused."""
        self.running = False

    def set_speed(self, speed: int) -> None:
        """Set playback multiplier to one of VALID_SPEEDS (1, 4, or 16)."""
        if isinstance(speed, bool) or speed not in VALID_SPEEDS:
            raise ValueError(f"Invalid speed {speed!r}; must be one of {VALID_SPEEDS}")
        self.speed = speed
