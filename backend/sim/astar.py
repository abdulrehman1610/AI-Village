"""Custom hand-written heapq A* pathfinder on a 4-way movement grid."""

from __future__ import annotations

import heapq
from collections.abc import Callable
from itertools import count

GridPos = tuple[int, int]

# Cardinal movement directions: North, East, South, West.
CARDINAL_DIRS: tuple[GridPos, ...] = ((0, -1), (1, 0), (0, 1), (-1, 0))


def manhattan(a: GridPos, b: GridPos) -> int:
    """Return Manhattan (L1) distance between two integer grid coordinates."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _reconstruct_path(
    came_from: dict[GridPos, GridPos],
    start: GridPos,
    goal: GridPos,
) -> list[GridPos]:
    """Reconstruct path from start (exclusive) to goal (inclusive)."""
    path: list[GridPos] = []
    node = goal
    while node != start:
        path.append(node)
        node = came_from[node]
    path.reverse()
    return path


def find_path(
    start: GridPos,
    goal: GridPos,
    is_walkable: Callable[[int, int], bool],
    blocked_tiles: set[GridPos] | None = None,
    max_iterations: int = 20_000,
) -> list[GridPos] | None:
    """Find a Manhattan-optimal 4-way path from start to goal using heapq A*.

    Returns:
        - `[]` when `start == goal` and both are walkable.
        - `[step_1, ..., goal]` (excluding `start`) when reachable.
        - `None` when `start` or `goal` is unwalkable, `goal` is in `blocked_tiles`,
          no valid path exists, or `max_iterations` is exceeded.
    """
    if not is_walkable(*start) or not is_walkable(*goal):
        return None
    if start == goal:
        return []
    if blocked_tiles is not None and goal in blocked_tiles:
        return None
    if max_iterations <= 0:
        return None

    tie_breaker = count()
    start_h = manhattan(start, goal)
    # Heap items: (f_score, h_score, tie_seq, pos)
    open_heap: list[tuple[int, int, int, GridPos]] = [
        (start_h, start_h, next(tie_breaker), start)
    ]
    g_score: dict[GridPos, int] = {start: 0}
    came_from: dict[GridPos, GridPos] = {}
    closed: set[GridPos] = set()

    iterations = 0
    while open_heap and iterations < max_iterations:
        _, _, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal:
            return _reconstruct_path(came_from, start, goal)

        closed.add(current)
        iterations += 1

        current_g = g_score[current]
        cx, cy = current
        for dx, dy in CARDINAL_DIRS:
            nxt: GridPos = (cx + dx, cy + dy)
            if nxt in closed:
                continue
            if not is_walkable(nxt[0], nxt[1]):
                continue
            if blocked_tiles is not None and nxt in blocked_tiles:
                continue

            tentative_g = current_g + 1
            prev_g = g_score.get(nxt)
            if prev_g is None or tentative_g < prev_g:
                came_from[nxt] = current
                g_score[nxt] = tentative_g
                h = manhattan(nxt, goal)
                heapq.heappush(open_heap, (tentative_g + h, h, next(tie_breaker), nxt))

    return None
