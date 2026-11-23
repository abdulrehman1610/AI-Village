---
phase: 1
plan: 4
wave: 2
depends_on:
  - "1"
files_modified:
  - backend/sim/astar.py
  - backend/tests/test_astar.py
  - backend/sim/clock.py
  - backend/tests/test_clock.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "Custom heapq A* finds Manhattan-optimal paths on 4-way grids, detours around walls and dynamic occupied tiles, and returns None when blocked"
    - "SimClock advances 1 simulated minute per tick, rolls over days cleanly every 1440 ticks, and supports 1x/4x/16x speeds plus pause/start"
  artifacts:
    - "backend/sim/astar.py implements custom heapq A* with Manhattan distance heuristic"
    - "backend/tests/test_astar.py covers optimal path length, obstacle detours, completely blocked goals, start==goal, and dynamic blocked tiles"
    - "backend/sim/clock.py implements SimClock with tick formatting and speed control"
    - "backend/tests/test_clock.py covers tick progression, day rollover, speed interval scaling, and pause/start"
  key_links:
    - "backend/sim/astar.py exposes find_path(start, goal, is_walkable, blocked_tiles) independent of map file format"
---

# Plan 1.4: Custom `heapq` A* Pathfinder & Simulation Clock

## Objective
Implement the custom classical AI `heapq` A* pathfinder (Manhattan heuristic, 4-way movement) and the simulation tick clock (`1 tick = 1 simulated minute`, 1x/4x/16x speeds, pause/start), each with deterministic offline unit tests.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/REQUIREMENTS.md
- backend/pyproject.toml

## Tasks

<task type="auto">
  <name>Implement custom heapq A* pathfinder and pathfinding unit tests</name>
  <files>
    backend/sim/astar.py
    backend/tests/test_astar.py
  </files>
  <action>
    Write `backend/sim/astar.py` from scratch using Python stdlib `heapq` and `itertools.count`, plus thorough unit tests in `backend/tests/test_astar.py`.

    Steps:
    1. Define `GridPos = tuple[int, int]` and `CARDINAL_DIRS: tuple[GridPos, ...] = ((0, -1), (1, 0), (0, 1), (-1, 0))`.
    2. Implement `manhattan(a: GridPos, b: GridPos) -> int` returning `abs(a[0] - b[0]) + abs(a[1] - b[1])`.
    3. Implement `find_path(start: GridPos, goal: GridPos, is_walkable: Callable[[int, int], bool], blocked_tiles: set[GridPos] | None = None, max_iterations: int = 20_000) -> list[GridPos] | None`:
       - Return `None` immediately if `not is_walkable(*start)` or `not is_walkable(*goal)`.
       - If `start == goal`, return `[]`.
       - If `blocked_tiles` is provided and `goal in blocked_tiles`, return `None` (never path onto a blocked target; caller resolves adjacent free tiles if desired).
       - Maintain min-heap entries `(f_score, h_score, tie_seq, pos)` using `heapq.heappush`/`heappop`, `g_score: dict[GridPos, int] = {start: 0}`, `came_from: dict[GridPos, GridPos] = {}`, and `closed: set[GridPos] = set()`.
       - Skip any neighbor `nxt` if `not is_walkable(*nxt)` or `(blocked_tiles is not None and nxt in blocked_tiles)`.
       - Stop with `None` if iterations exceed `max_iterations` or heap empties.
       - Reconstruct path as `[step_1, ..., goal]` (excluding `start`, ending with `goal`).
    4. Write `backend/tests/test_astar.py` testing:
       - Open grid optimal path: `len(path) == manhattan(start, goal)` and each step is 4-way adjacent (`manhattan(prev, curr) == 1`).
       - `start == goal` returns `[]`.
       - Wall obstacle / U-shaped barrier detour finds valid optimal path around walls without stepping on any blocked cell.
       - Completely enclosed/walled-off goal returns `None`.
       - Unwalkable `start` or `goal` returns `None`.
       - Dynamic `blocked_tiles` causes path to route around another agent's tile (and returns `None` if `goal` itself is in `blocked_tiles`).
       - Determinism: repeated calls produce identical paths.

    AVOID: Using external pathfinding libraries (`pathfinding`, `networkx`) because REQ-02 requires a custom hand-written `heapq` A* implementation, and AVOID returning `[]` for unreachable paths (use `None` for unreachable vs `[]` for `start == goal`).
    USE: `itertools.count()` tie-breaker in heap tuples so `(f, h, seq, pos)` never fails comparing tuples or varies across runs.
  </action>
  <verify>
    uv --directory backend run pytest tests/test_astar.py -v
    uv --directory backend run ruff check sim/astar.py tests/test_astar.py
    uv --directory backend run mypy sim/astar.py tests/test_astar.py
  </verify>
  <done>
    All tests in `backend/tests/test_astar.py` pass offline, `ruff` reports 0 issues, and `mypy` passes cleanly.
  </done>
</task>

<task type="auto">
  <name>Implement SimClock with speed control and unit tests</name>
  <files>
    backend/sim/clock.py
    backend/tests/test_clock.py
  </files>
  <action>
    Write `backend/sim/clock.py` managing simulated ticks, day/hour/minute formatting, and speed scaling, plus unit tests in `backend/tests/test_clock.py`.

    Steps:
    1. Define `VALID_SPEEDS: tuple[int, ...] = (1, 4, 16)` and `TICKS_PER_DAY = 1440`.
    2. Implement `SimClock` dataclass with fields:
       - `tick: int = 0`
       - `start_minute_of_day: int = 360` (06:00 AM on Day 1)
       - `speed: int = 1`
       - `running: bool = True`
       - `base_tick_seconds: float = 1.0`
       - Validate `speed in VALID_SPEEDS` and `base_tick_seconds > 0` in `__post_init__` (raise `ValueError`).
    3. Implement computed properties:
       - `total_minutes -> int`: `self.start_minute_of_day + self.tick`
       - `day -> int`: `(self.total_minutes // TICKS_PER_DAY) + 1`
       - `minute_of_day -> int`: `self.total_minutes % TICKS_PER_DAY`
       - `hour -> int`: `self.minute_of_day // 60`
       - `minute -> int`: `self.minute_of_day % 60`
       - `sim_time_str -> str`: `f"Day {self.day} {self.hour:02d}:{self.minute:02d}"`
       - `tick_interval_seconds -> float`: `self.base_tick_seconds / float(self.speed)`
    4. Implement methods:
       - `advance(steps: int = 1) -> int`: validates `steps >= 1`, increments `self.tick += steps`, returns updated `self.tick`.
       - `start() -> None`: sets `self.running = True`.
       - `pause() -> None`: sets `self.running = False`.
       - `set_speed(speed: int) -> None`: validates `speed in VALID_SPEEDS` else raises `ValueError`, sets `self.speed = speed`.
    5. Write `backend/tests/test_clock.py` testing:
       - Initial state at `tick=0` formats `"Day 1 06:00"`, `day == 1`, `hour == 6`, `minute == 0`.
       - `advance()` increments tick and minute by 1 (`"Day 1 06:01"`), and `advance(60)` reaches `"Day 1 07:01"`.
       - Day rollover: advancing from `start_minute_of_day=360` by `1080` ticks reaches `"Day 2 00:00"`, and `1440` ticks reaches `"Day 2 06:00"`.
       - `tick_interval_seconds` yields `1.0` at `1x`, `0.25` at `4x`, `0.0625` at `16x`.
       - Invalid speed (`2`, `0`, `-1`) raises `ValueError`.
       - `pause()` and `start()` toggle `running`.

    AVOID: Blocking sleeps inside `SimClock` methods (sleep belongs in `SimulationEngine` async loop, keeping `SimClock` pure and synchronous).
    USE: Integer minute arithmetic (`TICKS_PER_DAY = 1440`) so tick-to-clock conversion never suffers floating-point drift.
  </action>
  <verify>
    uv --directory backend run pytest tests/test_clock.py -v
    uv --directory backend run ruff check sim/clock.py tests/test_clock.py
    uv --directory backend run mypy sim/clock.py tests/test_clock.py
  </verify>
  <done>
    All tests in `backend/tests/test_clock.py` pass offline, `ruff` reports 0 issues, and `mypy` passes cleanly.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `backend/sim/astar.py` implements custom `heapq` A* with Manhattan heuristic and passes optimal/blocked/dynamic obstacle tests
- [ ] `backend/sim/clock.py` models 1 tick = 1 simulated minute, day rollover, pause/start, and 1x/4x/16x speeds cleanly
- [ ] Both modules pass `pytest`, `ruff`, and `mypy` offline

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in tests
