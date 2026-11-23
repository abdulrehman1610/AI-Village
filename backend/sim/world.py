"""Tiled village map loader, static collision grid, and occupancy helpers."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, TypeGuard

from pydantic import BaseModel, ConfigDict

GridPos = tuple[int, int]

_CARDINAL_DIRS: tuple[GridPos, ...] = ((0, -1), (1, 0), (0, 1), (-1, 0))


class NamedLocation(BaseModel):
    """Named point of interest parsed from the Tiled 'locations' objectgroup."""

    model_config = ConfigDict(frozen=True)

    name: str
    category: str
    anchor_x: int
    anchor_y: int
    x: int
    y: int
    width: int
    height: int

    @property
    def anchor(self) -> GridPos:
        """Return the walkable tile coordinate used as navigation target."""
        return (self.anchor_x, self.anchor_y)


def _is_strict_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_positive_int(value: Any, field_name: str) -> int:
    if not _is_strict_int(value) or value <= 0:
        raise ValueError(f"Invalid {field_name!r} in Tiled JSON: {value!r}")
    return value


def _to_int_coord(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Expected numeric value for {field_name!r}, got {value!r}")
    return int(round(float(value)))


def _extract_properties(raw_props: Any) -> dict[str, Any]:
    if raw_props is None:
        return {}
    if not isinstance(raw_props, list):
        raise ValueError("Tiled object 'properties' must be a list")
    parsed: dict[str, Any] = {}
    for entry in raw_props:
        if not isinstance(entry, dict) or "name" not in entry or "value" not in entry:
            raise ValueError(f"Malformed Tiled property entry: {entry!r}")
        parsed[str(entry["name"])] = entry["value"]
    return parsed


class WorldMap:
    """Static village grid parsed from Tiled JSON with walkability and location queries."""

    def __init__(
        self,
        width: int,
        height: int,
        tile_size: int,
        collision_grid: list[list[bool]],
        locations: dict[str, NamedLocation],
    ) -> None:
        if width <= 0 or height <= 0 or tile_size <= 0:
            raise ValueError("Map dimensions and tile_size must be positive integers")
        if len(collision_grid) != height or any(len(row) != width for row in collision_grid):
            raise ValueError("collision_grid dimensions do not match map width/height")
        self.width = width
        self.height = height
        self.tile_size = tile_size
        self.collision_grid = collision_grid
        self._locations = dict(locations)

    @property
    def locations(self) -> dict[str, NamedLocation]:
        """Return a shallow copy of the named locations dictionary."""
        return dict(self._locations)

    @classmethod
    def from_tiled_json(cls, path: Path) -> WorldMap:
        """Load and validate a Tiled JSON map file."""
        raw_text = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in map file {path}: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Tiled map root must be a JSON object")

        width = _require_positive_int(payload.get("width"), "width")
        height = _require_positive_int(payload.get("height"), "height")
        tile_size = _require_positive_int(payload.get("tilewidth"), "tilewidth")
        _require_positive_int(payload.get("tileheight", tile_size), "tileheight")

        layers = payload.get("layers")
        if not isinstance(layers, list):
            raise ValueError("Tiled map missing 'layers' list")

        collision_layer = next(
            (
                layer
                for layer in layers
                if isinstance(layer, dict)
                and layer.get("name") == "collision"
                and layer.get("type") == "tilelayer"
            ),
            None,
        )
        if collision_layer is None:
            raise ValueError("Tiled map missing required 'collision' tilelayer")

        data = collision_layer.get("data")
        expected_len = width * height
        if not isinstance(data, list) or len(data) != expected_len:
            raise ValueError(
                f"'collision' layer data must have length {expected_len}, "
                f"got {len(data) if isinstance(data, list) else type(data).__name__}"
            )
        if not all(_is_strict_int(gid) for gid in data):
            raise ValueError("'collision' layer data must contain only integers")

        collision_grid: list[list[bool]] = [
            [data[y * width + x] != 0 for x in range(width)] for y in range(height)
        ]

        locations_layer = next(
            (
                layer
                for layer in layers
                if isinstance(layer, dict)
                and layer.get("name") == "locations"
                and layer.get("type") == "objectgroup"
            ),
            None,
        )
        if locations_layer is None:
            raise ValueError("Tiled map missing required 'locations' objectgroup")

        raw_objects = locations_layer.get("objects")
        if not isinstance(raw_objects, list):
            raise ValueError("'locations' objectgroup missing 'objects' list")

        locations: dict[str, NamedLocation] = {}
        for obj in raw_objects:
            if not isinstance(obj, dict):
                raise ValueError(f"Malformed location object: {obj!r}")
            name = str(obj.get("name", "")).strip()
            if not name:
                raise ValueError("Location object is missing a non-empty 'name'")
            if name in locations:
                raise ValueError(f"Duplicate location name: {name!r}")

            px = _to_int_coord(obj.get("x", 0), "x")
            py = _to_int_coord(obj.get("y", 0), "y")
            pw = _to_int_coord(obj.get("width", tile_size), "width")
            ph = _to_int_coord(obj.get("height", tile_size), "height")

            props = _extract_properties(obj.get("properties"))
            raw_category = props.get("category", obj.get("type", ""))
            category = str(raw_category).strip() if raw_category else "unknown"

            if "anchor_x" in props:
                raw_ax = props["anchor_x"]
                if not _is_strict_int(raw_ax):
                    raise ValueError(f"Location {name!r} anchor_x must be int, got {raw_ax!r}")
                anchor_x = int(raw_ax)
            else:
                anchor_x = int((px + pw / 2) // tile_size)

            if "anchor_y" in props:
                raw_ay = props["anchor_y"]
                if not _is_strict_int(raw_ay):
                    raise ValueError(f"Location {name!r} anchor_y must be int, got {raw_ay!r}")
                anchor_y = int(raw_ay)
            else:
                anchor_y = int((py + ph / 2) // tile_size)

            if not (0 <= anchor_x < width and 0 <= anchor_y < height):
                raise ValueError(
                    f"Location {name!r} anchor ({anchor_x}, {anchor_y}) is out of map bounds"
                )
            if collision_grid[anchor_y][anchor_x]:
                raise ValueError(
                    f"Location {name!r} anchor ({anchor_x}, {anchor_y}) is on a collision tile"
                )

            locations[name] = NamedLocation(
                name=name,
                category=category,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                x=px,
                y=py,
                width=pw,
                height=ph,
            )

        return cls(
            width=width,
            height=height,
            tile_size=tile_size,
            collision_grid=collision_grid,
            locations=locations,
        )

    def in_bounds(self, x: int, y: int) -> bool:
        """Return True when tile coordinate (x, y) lies inside the map grid."""
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        """Return True when (x, y) is in bounds and not marked blocked in collision_grid."""
        return self.in_bounds(x, y) and not self.collision_grid[y][x]

    def get_location(self, name: str) -> NamedLocation:
        """Look up a named location by exact name, raising KeyError if unknown."""
        if name not in self._locations:
            raise KeyError(f"Unknown location: {name!r}")
        return self._locations[name]

    def list_locations(self) -> list[NamedLocation]:
        """Return all named locations defined in the map."""
        return list(self._locations.values())

    def neighbors_4(self, x: int, y: int) -> list[GridPos]:
        """Return walkable 4-way cardinal neighbors around (x, y)."""
        result: list[GridPos] = []
        for dx, dy in _CARDINAL_DIRS:
            nx, ny = x + dx, y + dy
            if self.is_walkable(nx, ny):
                result.append((nx, ny))
        return result

    def find_free_adjacent(
        self,
        x: int,
        y: int,
        occupied: set[GridPos],
        max_radius: int = 3,
    ) -> GridPos | None:
        """Return (x, y) if walkable and unoccupied, else nearest free walkable tile via BFS."""
        if max_radius < 0:
            return None

        start: GridPos = (x, y)
        if self.is_walkable(x, y) and start not in occupied:
            return start

        visited: set[GridPos] = {start}
        queue: deque[tuple[int, int, int]] = deque([(x, y, 0)])

        while queue:
            cx, cy, dist = queue.popleft()
            if dist > 0 and self.is_walkable(cx, cy) and (cx, cy) not in occupied:
                return (cx, cy)
            if dist >= max_radius:
                continue
            for nx, ny in self.neighbors_4(cx, cy):
                nxt = (nx, ny)
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nx, ny, dist + 1))

        return None

    def reachable_from(self, start: GridPos) -> set[GridPos]:
        """Return all walkable coordinates reachable from start via 4-way movement."""
        if not self.is_walkable(*start):
            return set()

        visited: set[GridPos] = {start}
        queue: deque[GridPos] = deque([start])

        while queue:
            cx, cy = queue.popleft()
            for nxt in self.neighbors_4(cx, cy):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)

        return visited
