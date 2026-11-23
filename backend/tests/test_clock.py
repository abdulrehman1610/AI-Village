"""Unit tests for SimClock tick progression, day rollover, and speed controls."""

from __future__ import annotations

import pytest

from sim.clock import TICKS_PER_DAY, VALID_SPEEDS, SimClock


def test_initial_clock_state_defaults() -> None:
    clock = SimClock()
    assert clock.tick == 0
    assert clock.day == 1
    assert clock.hour == 6
    assert clock.minute == 0
    assert clock.sim_time_str == "Day 1 06:00"
    assert clock.running is True
    assert clock.speed == 1
    assert clock.tick_interval_seconds == 1.0


def test_advance_single_and_multi_steps() -> None:
    clock = SimClock()

    assert clock.advance() == 1
    assert clock.sim_time_str == "Day 1 06:01"

    assert clock.advance(60) == 61
    assert clock.hour == 7
    assert clock.minute == 1
    assert clock.sim_time_str == "Day 1 07:01"


def test_day_rollover_after_1440_minutes() -> None:
    clock = SimClock(start_minute_of_day=360)

    # 1079 ticks from 06:00 reaches 23:59 on Day 1
    clock.advance(1079)
    assert clock.sim_time_str == "Day 1 23:59"

    # 1 more tick (1080 total) rolls over to Day 2 00:00
    clock.advance()
    assert clock.tick == 1080
    assert clock.day == 2
    assert clock.hour == 0
    assert clock.minute == 0
    assert clock.sim_time_str == "Day 2 00:00"

    # Full 1440 ticks from 06:00 reaches Day 2 06:00
    clock2 = SimClock(start_minute_of_day=360)
    clock2.advance(TICKS_PER_DAY)
    assert clock2.day == 2
    assert clock2.hour == 6
    assert clock2.minute == 0
    assert clock2.sim_time_str == "Day 2 06:00"


def test_speed_interval_scaling() -> None:
    clock = SimClock(base_tick_seconds=1.0)
    expected = {1: 1.0, 4: 0.25, 16: 0.0625}
    assert VALID_SPEEDS == (1, 4, 16)

    for speed, interval in expected.items():
        clock.set_speed(speed)
        assert clock.speed == speed
        assert clock.tick_interval_seconds == interval


@pytest.mark.parametrize("bad_speed", [2, 0, -1, 8, 32])
def test_invalid_speed_raises_value_error(bad_speed: int) -> None:
    clock = SimClock()
    with pytest.raises(ValueError):
        clock.set_speed(bad_speed)

    with pytest.raises(ValueError):
        SimClock(speed=bad_speed)


def test_pause_and_start_toggle_running() -> None:
    clock = SimClock()
    assert clock.running is True

    clock.pause()
    assert clock.running is False

    clock.start()
    assert clock.running is True


def test_validation_guards_for_advance_and_init() -> None:
    clock = SimClock()
    with pytest.raises(ValueError):
        clock.advance(0)
    with pytest.raises(ValueError):
        clock.advance(-3)
    with pytest.raises(ValueError):
        SimClock(base_tick_seconds=0.0)
    with pytest.raises(ValueError):
        SimClock(base_tick_seconds=-1.0)
    with pytest.raises(ValueError):
        SimClock(tick=-1)
    with pytest.raises(ValueError):
        SimClock(start_minute_of_day=TICKS_PER_DAY)
