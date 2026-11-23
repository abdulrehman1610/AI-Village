"""Unit tests for custom heapq A* pathfinding and Manhattan heuristic."""

from __future__ import annotations

from collections.abc import Callable

from sim.astar import GridPos, find_path, manhattan


def _make_grid_walkable(
    width: int,
    height: int,
    walls: set[GridPos] | None = None,
) -> Callable[[int, int], bool]:
    wall_set = walls or set()

    def _is_walkable(x: int, y: int) -> bool:
        return 0 <= x < width and 0 <= y < height and (x, y) not in wall_set

    return _is_walkable


def _assert_valid_path(
    start: GridPos,
    goal: GridPos,
    path: list[GridPos],
    is_walkable: Callable[[int, int], bool],
    blocked: set[GridPos] | None = None,
) -> None:
    assert path, "Expected non-empty path when start != goal"
    assert path[0] != start
    assert path[-1] == goal
    prev = start
    for step in path:
        assert manhattan(prev, step) == 1
        assert is_walkable(*step)
        if blocked is not None:
            assert step not in blocked
        prev = step


def test_manhattan_distance() -> None:
    assert manhattan((0, 0), (0, 0)) == 0
    assert manhattan((2, 3), (5, 7)) == 7
    assert manhattan((5, 7), (2, 3)) == 7
    assert manhattan((-1, 4), (3, -2)) == 10


def test_open_grid_optimal_path() -> None:
    is_walkable = _make_grid_walkable(10, 10)
    start = (1, 2)
    goal = (7, 6)

    path = find_path(start, goal, is_walkable)
    assert path is not None
    _assert_valid_path(start, goal, path, is_walkable)
    assert len(path) == manhattan(start, goal)


def test_start_equals_goal_returns_empty_list() -> None:
    is_walkable = _make_grid_walkable(5, 5)
    assert find_path((2, 2), (2, 2), is_walkable) == []


def test_u_shaped_barrier_detour_is_optimal() -> None:
    # Vertical U-shaped trap forcing path to go around open left/right ends.
    # Barrier blocks direct East route from (2, 4) to (6, 4):
    #   x=4: y=2..6 blocked, plus arms at x=3: y=2 and y=6
    walls: set[GridPos] = {
        (3, 2),
        (4, 2),
        (4, 3),
        (4, 4),
        (4, 5),
        (4, 6),
        (3, 6),
    }
    is_walkable = _make_grid_walkable(10, 10, walls)
    start = (2, 4)
    goal = (6, 4)

    path = find_path(start, goal, is_walkable)
    assert path is not None
    _assert_valid_path(start, goal, path, is_walkable)
    # Shortest route goes up around (2,1)->(6,1) and back down to (6,4) = 10 steps
    assert len(path) == 10


def test_completely_enclosed_goal_returns_none() -> None:
    walls: set[GridPos] = {
        (5, 4),
        (5, 6),
        (4, 5),
        (6, 5),
    }
    is_walkable = _make_grid_walkable(10, 10, walls)

    assert find_path((1, 1), (5, 5), is_walkable) is None


def test_unwalkable_start_or_goal_returns_none() -> None:
    walls: set[GridPos] = {(0, 0), (4, 4)}
    is_walkable = _make_grid_walkable(6, 6, walls)

    assert find_path((0, 0), (2, 2), is_walkable) is None
    assert find_path((2, 2), (4, 4), is_walkable) is None
    assert find_path((-1, 0), (2, 2), is_walkable) is None
    assert find_path((2, 2), (6, 2), is_walkable) is None


def test_dynamic_blocked_tiles_routes_around_and_blocks_occupied_goal() -> None:
    # Narrow 1-tile corridor at y=2 with a wider bypass at y=1, y=3
    walls: set[GridPos] = {
        (3, 0),
        (3, 1),
        # (3, 2) is open corridor unless dynamically blocked
        (3, 4),
    }
    is_walkable = _make_grid_walkable(7, 5, walls)
    start = (1, 2)
    goal = (5, 2)

    direct_path = find_path(start, goal, is_walkable)
    assert direct_path is not None
    assert (3, 2) in direct_path
    assert len(direct_path) == 4

    # Dynamic agent occupies (3, 2): path must detour through (3, 3)
    blocked = {(3, 2)}
    detour_path = find_path(start, goal, is_walkable, blocked_tiles=blocked)
    assert detour_path is not None
    _assert_valid_path(start, goal, detour_path, is_walkable, blocked=blocked)
    assert (3, 2) not in detour_path
    assert (3, 3) in detour_path
    assert len(detour_path) == 6

    # If both (3, 2) and (3, 3) are dynamically blocked, goal becomes unreachable
    assert find_path(start, goal, is_walkable, blocked_tiles={(3, 2), (3, 3)}) is None

    # Goal itself in blocked_tiles returns None immediately
    assert find_path(start, goal, is_walkable, blocked_tiles={goal}) is None


def test_pathfinding_is_deterministic() -> None:
    walls: set[GridPos] = {(3, 1), (3, 2), (3, 3)}
    is_walkable = _make_grid_walkable(8, 8, walls)
    start = (1, 2)
    goal = (6, 2)

    first = find_path(start, goal, is_walkable, blocked_tiles={(4, 4)})
    for _ in range(5):
        assert find_path(start, goal, is_walkable, blocked_tiles={(4, 4)}) == first


def test_max_iterations_exhaustion_returns_none() -> None:
    is_walkable = _make_grid_walkable(20, 20)
    assert find_path((0, 0), (15, 15), is_walkable, max_iterations=5) is None
    assert find_path((0, 0), (15, 15), is_walkable, max_iterations=0) is None
