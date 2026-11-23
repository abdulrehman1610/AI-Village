"""Unit tests for WorldMap Tiled JSON loading, collision grid, and reachability."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import get_settings
from sim.world import NamedLocation, WorldMap

REQUIRED_LOCATIONS = {
    "Cafe",
    "Park",
    "Market",
    "Town Square",
    "Bakery",
    "Library",
    "Home_Maya",
    "Home_Liam",
    "Home_Elena",
    "Home_Noah",
}


def _load_village_world() -> WorldMap:
    map_path = get_settings().resolved_map_path()
    return WorldMap.from_tiled_json(map_path)


def test_load_generated_village_map_dimensions_and_locations() -> None:
    world = _load_village_world()

    assert world.width == 40
    assert world.height == 30
    assert world.tile_size == 32

    names = {loc.name for loc in world.list_locations()}
    assert REQUIRED_LOCATIONS.issubset(names)
    assert len(world.list_locations()) == 10


def test_every_named_location_anchor_is_walkable_with_neighbor() -> None:
    world = _load_village_world()

    for loc in world.list_locations():
        assert isinstance(loc, NamedLocation)
        assert world.is_walkable(*loc.anchor) is True
        assert len(world.neighbors_4(*loc.anchor)) >= 1


def test_bfs_from_town_square_reaches_all_locations() -> None:
    world = _load_village_world()
    town_square = world.get_location("Town Square")
    reachable = world.reachable_from(town_square.anchor)

    assert len(reachable) > 100
    for loc in world.list_locations():
        assert loc.anchor in reachable, f"{loc.name} anchor {loc.anchor} not reachable"


def test_collision_and_out_of_bounds_tiles() -> None:
    world = _load_village_world()

    # Perimeter trees and park pond / walls / interior counter
    assert world.is_walkable(0, 0) is False
    assert world.is_walkable(39, 29) is False
    assert world.is_walkable(14, 24) is False  # Park pond
    assert world.is_walkable(2, 8) is False    # Home_Maya front wall
    assert world.is_walkable(14, 4) is False   # Cafe counter

    # Road / plaza / doorway should be walkable
    assert world.is_walkable(19, 14) is True   # Town Square center
    assert world.is_walkable(15, 8) is True    # Cafe doorway threshold

    # Out-of-bounds checks
    for ox, oy in ((-1, 0), (0, -1), (40, 0), (0, 30), (40, 30)):
        assert world.in_bounds(ox, oy) is False
        assert world.is_walkable(ox, oy) is False

    with pytest.raises(KeyError):
        world.get_location("Nonexistent_Place")


def test_find_free_adjacent_skips_occupied_and_blocked_without_mutating_grid() -> None:
    world = _load_village_world()
    cafe = world.get_location("Cafe")
    ax, ay = cafe.anchor

    # Snapshot static collision grid before query
    grid_before = [row.copy() for row in world.collision_grid]

    # When target itself is free, returns target
    assert world.find_free_adjacent(ax, ay, occupied=set()) == (ax, ay)

    # Occupy anchor + north/east/south neighbors to force search to skip occupied and blocked tiles
    occupied = {(ax, ay), (ax, ay - 1), (ax + 1, ay), (ax, ay + 1)}
    candidate = world.find_free_adjacent(ax, ay, occupied=occupied, max_radius=3)

    assert candidate is not None
    assert candidate not in occupied
    assert world.is_walkable(*candidate) is True
    assert world.collision_grid == grid_before

    # When surrounded completely within radius=1, returns None
    neighbors = set(world.neighbors_4(ax, ay))
    assert world.find_free_adjacent(ax, ay, occupied={(ax, ay)} | neighbors, max_radius=1) is None


def test_synthetic_invalid_maps_raise_value_error(tmp_path: Path) -> None:
    # 1. Missing collision layer
    no_collision = {
        "width": 4,
        "height": 4,
        "tilewidth": 32,
        "tileheight": 32,
        "layers": [
            {"name": "ground", "type": "tilelayer", "data": [1] * 16},
            {"name": "locations", "type": "objectgroup", "objects": []},
        ],
    }
    p1 = tmp_path / "no_collision.json"
    p1.write_text(json.dumps(no_collision), encoding="utf-8")
    with pytest.raises(ValueError, match="collision"):
        WorldMap.from_tiled_json(p1)

    # 2. Blocked anchor tile
    blocked_anchor = {
        "width": 4,
        "height": 4,
        "tilewidth": 32,
        "tileheight": 32,
        "layers": [
            {"name": "collision", "type": "tilelayer", "data": [20] * 16},
            {
                "name": "locations",
                "type": "objectgroup",
                "objects": [
                    {
                        "id": 1,
                        "name": "BlockedSpot",
                        "type": "test",
                        "x": 32,
                        "y": 32,
                        "width": 32,
                        "height": 32,
                        "properties": [
                            {"name": "anchor_x", "type": "int", "value": 1},
                            {"name": "anchor_y", "type": "int", "value": 1},
                        ],
                    }
                ],
            },
        ],
    }
    p2 = tmp_path / "blocked_anchor.json"
    p2.write_text(json.dumps(blocked_anchor), encoding="utf-8")
    with pytest.raises(ValueError, match="collision tile"):
        WorldMap.from_tiled_json(p2)

    # 3. Missing locations layer
    no_locations = {
        "width": 4,
        "height": 4,
        "tilewidth": 32,
        "tileheight": 32,
        "layers": [
            {"name": "collision", "type": "tilelayer", "data": [0] * 16},
        ],
    }
    p3 = tmp_path / "no_locations.json"
    p3.write_text(json.dumps(no_locations), encoding="utf-8")
    with pytest.raises(ValueError, match="locations"):
        WorldMap.from_tiled_json(p3)


def test_omitted_anchor_properties_fall_back_to_object_center(tmp_path: Path) -> None:
    fallback_map = {
        "width": 5,
        "height": 5,
        "tilewidth": 32,
        "tileheight": 32,
        "layers": [
            {"name": "collision", "type": "tilelayer", "data": [0] * 25},
            {
                "name": "locations",
                "type": "objectgroup",
                "objects": [
                    {
                        "id": 1,
                        "name": "Plaza",
                        "type": "plaza",
                        "x": 32,
                        "y": 64,
                        "width": 64,
                        "height": 64,
                    }
                ],
            },
        ],
    }
    path = tmp_path / "fallback.json"
    path.write_text(json.dumps(fallback_map), encoding="utf-8")
    world = WorldMap.from_tiled_json(path)
    plaza = world.get_location("Plaza")
    assert plaza.anchor == (2, 3)
    assert plaza.category == "plaza"
