"""Deterministic offline asset and Tiled v1.10 village map generator.

Produces:
- frontend/public/assets/tileset.png (256x128 RGBA, 8x4 grid of 32x32 tiles)
- frontend/public/assets/sprites.png (128x128 RGBA, 4x4 grid of 32x32 villager frames)
- frontend/public/assets/map.json (40x30 orthogonal Tiled JSON v1.10 map)
"""

from __future__ import annotations

import json
import struct
import zlib
from collections import deque
from pathlib import Path
from typing import TypedDict

RGBA = tuple[int, int, int, int]
GridPos = tuple[int, int]


class TiledProperty(TypedDict):
    name: str
    type: str
    value: int | str


class TiledObject(TypedDict):
    id: int
    name: str
    type: str
    x: int
    y: int
    width: int
    height: int
    rotation: int
    visible: bool
    properties: list[TiledProperty]

TILE_SIZE = 32
MAP_WIDTH = 40
MAP_HEIGHT = 30

TILESET_COLS = 8
TILESET_ROWS = 4
TILESET_WIDTH = TILESET_COLS * TILE_SIZE  # 256
TILESET_HEIGHT = TILESET_ROWS * TILE_SIZE  # 128

SPRITE_COLS = 4
SPRITE_ROWS = 4
SPRITESHEET_WIDTH = SPRITE_COLS * TILE_SIZE  # 128
SPRITESHEET_HEIGHT = SPRITE_ROWS * TILE_SIZE  # 128

# Tile GIDs (1-indexed, matching Tiled firstgid=1)
GID_EMPTY = 0
GID_GRASS = 1
GID_FLOWER_GRASS = 2
GID_COBBLE_ROAD = 3
GID_PLAZA_STONE = 4
GID_WOOD_FLOOR = 5
GID_CAFE_FLOOR = 6
GID_WATER_POND = 7
GID_TREE_HEDGE = 8
GID_STONE_WALL = 9
GID_TIMBER_WALL = 10
GID_RED_ROOF = 11
GID_BLUE_ROOF = 12
GID_GREEN_ROOF = 13
GID_AMBER_ROOF = 14
GID_DOORWAY = 15
GID_PARK_BENCH = 16
GID_MARKET_STALL = 17
GID_CAFE_COUNTER = 18
GID_BOOKSHELF = 19
GID_COLLISION = 20

ASSETS_DIR = Path(__file__).resolve().parents[1] / "frontend" / "public" / "assets"


class Canvas:
    """Minimal RGBA pixel buffer with deterministic integer drawing primitives."""

    def __init__(self, width: int, height: int, fill: RGBA = (0, 0, 0, 0)) -> None:
        self.width = width
        self.height = height
        self.data = bytearray(width * height * 4)
        if fill != (0, 0, 0, 0):
            r, g, b, a = fill
            row = bytes((r, g, b, a)) * width
            for y in range(height):
                start = y * width * 4
                self.data[start : start + width * 4] = row

    def set_pixel(self, x: int, y: int, color: RGBA) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        idx = (y * self.width + x) * 4
        self.data[idx : idx + 4] = bytes(color)

    def blend_pixel(self, x: int, y: int, color: RGBA) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        sr, sg, sb, sa = color
        if sa == 0:
            return
        if sa == 255:
            self.set_pixel(x, y, color)
            return
        idx = (y * self.width + x) * 4
        dr, dg, db, da = self.data[idx], self.data[idx + 1], self.data[idx + 2], self.data[idx + 3]
        alpha = sa / 255.0
        inv = 1.0 - alpha
        out_a = int(sa + da * inv)
        if out_a == 0:
            return
        out_r = int((sr * sa + dr * da * inv) / out_a)
        out_g = int((sg * sa + dg * da * inv) / out_a)
        out_b = int((sb * sa + db * da * inv) / out_a)
        self.data[idx : idx + 4] = bytes((out_r, out_g, out_b, min(255, out_a)))

    def fill_rect(self, x: int, y: int, w: int, h: int, color: RGBA) -> None:
        for py in range(y, y + h):
            for px in range(x, x + w):
                self.set_pixel(px, py, color)

    def blend_rect(self, x: int, y: int, w: int, h: int, color: RGBA) -> None:
        for py in range(y, y + h):
            for px in range(x, x + w):
                self.blend_pixel(px, py, color)

    def fill_circle(self, cx: int, cy: int, radius: int, color: RGBA) -> None:
        r2 = radius * radius
        for py in range(cy - radius, cy + radius + 1):
            for px in range(cx - radius, cx + radius + 1):
                if (px - cx) * (px - cx) + (py - cy) * (py - cy) <= r2:
                    self.set_pixel(px, py, color)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def write_png(path: Path, width: int, height: int, rgba: bytearray) -> None:
    """Encode an RGBA buffer as an uncompressed-filter PNG using stdlib zlib."""
    stride = width * 4
    raw = bytearray((stride + 1) * height)
    for y in range(height):
        raw_offset = y * (stride + 1)
        src_offset = y * stride
        raw[raw_offset] = 0
        raw[raw_offset + 1 : raw_offset + 1 + stride] = rgba[src_offset : src_offset + stride]

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=9)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes)


def _tile_origin(gid: int) -> tuple[int, int]:
    idx = gid - 1
    return (idx % TILESET_COLS) * TILE_SIZE, (idx // TILESET_COLS) * TILE_SIZE


def _hash2(x: int, y: int, seed: int = 17) -> int:
    val = (x * 73856093) ^ (y * 19349663) ^ (seed * 83492791)
    return (val ^ (val >> 13)) & 0xFF


def _draw_grass(canvas: Canvas, ox: int, oy: int, with_flowers: bool = False) -> None:
    base_colors = [
        (95, 166, 78, 255),
        (102, 174, 83, 255),
        (88, 158, 72, 255),
    ]
    for ty in range(TILE_SIZE):
        for tx in range(TILE_SIZE):
            h = _hash2(tx, ty, seed=11)
            c = base_colors[h % len(base_colors)]
            if h % 19 == 0:
                c = (118, 188, 92, 255)
            canvas.set_pixel(ox + tx, oy + ty, c)
    # Small grass blade tufts
    for bx, by in ((5, 7), (18, 12), (9, 24), (25, 21)):
        canvas.set_pixel(ox + bx, oy + by, (74, 138, 60, 255))
        canvas.set_pixel(ox + bx, oy + by - 1, (124, 196, 98, 255))
    if with_flowers:
        flowers = [
            (7, 9, (250, 232, 108, 255)),
            (21, 7, (244, 148, 178, 255)),
            (14, 19, (248, 248, 244, 255)),
            (25, 24, (148, 206, 248, 255)),
        ]
        for fx, fy, petal in flowers:
            canvas.set_pixel(ox + fx, oy + fy, (245, 188, 60, 255))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                canvas.set_pixel(ox + fx + dx, oy + fy + dy, petal)


def _draw_cobble_road(canvas: Canvas, ox: int, oy: int) -> None:
    mortar = (110, 102, 92, 255)
    canvas.fill_rect(ox, oy, TILE_SIZE, TILE_SIZE, mortar)
    stones = [
        (1, 1, 8, 6), (11, 1, 9, 6), (22, 1, 9, 6),
        (1, 9, 5, 6), (8, 9, 10, 6), (20, 9, 11, 6),
        (1, 17, 9, 6), (12, 17, 8, 6), (22, 17, 9, 6),
        (1, 25, 6, 6), (9, 25, 10, 6), (21, 25, 10, 6),
    ]
    for i, (sx, sy, sw, sh) in enumerate(stones):
        shade = 152 + ((i * 17) % 24)
        stone = (shade + 8, shade + 2, shade - 6, 255)
        hi = (min(255, stone[0] + 18), min(255, stone[1] + 18), min(255, stone[2] + 16), 255)
        canvas.fill_rect(ox + sx, oy + sy, sw, sh, stone)
        canvas.fill_rect(ox + sx, oy + sy, sw, 1, hi)
        canvas.fill_rect(ox + sx, oy + sy, 1, sh, hi)


def _draw_plaza_stone(canvas: Canvas, ox: int, oy: int) -> None:
    grout = (146, 140, 130, 255)
    canvas.fill_rect(ox, oy, TILE_SIZE, TILE_SIZE, grout)
    for row in range(2):
        for col in range(2):
            sx = ox + col * 16 + 1
            sy = oy + row * 16 + 1
            tone = (206, 198, 184, 255) if (row + col) % 2 == 0 else (196, 188, 174, 255)
            canvas.fill_rect(sx, sy, 14, 14, tone)
            canvas.fill_rect(sx, sy, 14, 1, (224, 218, 206, 255))
            canvas.fill_rect(sx, sy + 13, 14, 1, (168, 160, 148, 255))


def _draw_wood_floor(canvas: Canvas, ox: int, oy: int) -> None:
    plank_tones = [
        (164, 114, 72, 255),
        (154, 106, 66, 255),
        (172, 122, 78, 255),
        (148, 100, 62, 255),
    ]
    for p in range(4):
        py = oy + p * 8
        canvas.fill_rect(ox, py, TILE_SIZE, 7, plank_tones[p])
        canvas.fill_rect(ox, py + 7, TILE_SIZE, 1, (108, 72, 42, 255))
        seam_x = (p * 11 + 6) % TILE_SIZE
        canvas.fill_rect(ox + seam_x, py, 1, 7, (108, 72, 42, 255))


def _draw_cafe_floor(canvas: Canvas, ox: int, oy: int) -> None:
    cream = (228, 214, 190, 255)
    sage = (176, 194, 174, 255)
    grout = (142, 134, 122, 255)
    canvas.fill_rect(ox, oy, TILE_SIZE, TILE_SIZE, grout)
    for r in range(2):
        for c in range(2):
            col = cream if (r + c) % 2 == 0 else sage
            canvas.fill_rect(ox + c * 16 + 1, oy + r * 16 + 1, 14, 14, col)


def _draw_water_pond(canvas: Canvas, ox: int, oy: int) -> None:
    for ty in range(TILE_SIZE):
        for tx in range(TILE_SIZE):
            wave = (tx + ty * 2) % 9
            if wave == 0 and (tx % 6 < 3):
                c = (128, 204, 236, 255)
            elif (tx + ty) % 5 == 0:
                c = (54, 136, 194, 255)
            else:
                c = (66, 152, 208, 255)
            canvas.set_pixel(ox + tx, oy + ty, c)
    # Shoreline border accent
    canvas.fill_rect(ox, oy, TILE_SIZE, 2, (44, 112, 166, 255))
    canvas.fill_rect(ox, oy, 2, TILE_SIZE, (44, 112, 166, 255))


def _draw_tree_hedge(canvas: Canvas, ox: int, oy: int) -> None:
    # Transparent outside canopy so ground grass peeks cleanly around corners
    canvas.fill_rect(ox + 13, oy + 22, 6, 9, (104, 70, 42, 255))
    canvas.fill_rect(ox + 14, oy + 22, 2, 9, (124, 86, 52, 255))
    canvas.fill_circle(ox + 16, oy + 14, 12, (38, 102, 48, 255))
    canvas.fill_circle(ox + 15, oy + 12, 10, (54, 134, 62, 255))
    canvas.fill_circle(ox + 13, oy + 10, 6, (78, 162, 82, 255))


def _draw_stone_wall(canvas: Canvas, ox: int, oy: int) -> None:
    canvas.fill_rect(ox, oy, TILE_SIZE, TILE_SIZE, (104, 106, 112, 255))
    for row in range(4):
        by = oy + row * 8
        offset = 8 if row % 2 == 1 else 0
        for col in range(-1, 3):
            bx = col * 16 + offset
            x0 = max(0, bx + 1)
            x1 = min(TILE_SIZE, bx + 15)
            if x1 > x0:
                tone = (158, 160, 168, 255) if (row + col) % 2 == 0 else (146, 148, 156, 255)
                canvas.fill_rect(ox + x0, by + 1, x1 - x0, 6, tone)
                canvas.fill_rect(ox + x0, by + 1, x1 - x0, 1, (184, 186, 194, 255))
    canvas.fill_rect(ox, oy + 29, TILE_SIZE, 3, (78, 80, 86, 255))


def _draw_timber_wall(canvas: Canvas, ox: int, oy: int) -> None:
    plaster = (232, 222, 198, 255)
    timber = (112, 74, 44, 255)
    canvas.fill_rect(ox, oy, TILE_SIZE, TILE_SIZE, plaster)
    canvas.fill_rect(ox, oy, TILE_SIZE, 3, timber)
    canvas.fill_rect(ox, oy + 29, TILE_SIZE, 3, timber)
    canvas.fill_rect(ox, oy, 3, TILE_SIZE, timber)
    canvas.fill_rect(ox + 29, oy, 3, TILE_SIZE, timber)
    canvas.fill_rect(ox + 15, oy, 2, TILE_SIZE, timber)
    canvas.fill_rect(ox, oy + 15, TILE_SIZE, 2, timber)


def _draw_roof(canvas: Canvas, ox: int, oy: int, base: RGBA, light: RGBA, dark: RGBA) -> None:
    canvas.fill_rect(ox, oy, TILE_SIZE, TILE_SIZE, base)
    for row in range(4):
        ry = oy + row * 8
        canvas.fill_rect(ox, ry, TILE_SIZE, 1, light)
        canvas.fill_rect(ox, ry + 7, TILE_SIZE, 1, dark)
        shift = 4 if row % 2 else 0
        for col in range(0, TILE_SIZE, 8):
            canvas.fill_rect(ox + (col + shift) % TILE_SIZE, ry, 1, 7, dark)


def _draw_doorway(canvas: Canvas, ox: int, oy: int) -> None:
    canvas.fill_rect(ox, oy, TILE_SIZE, TILE_SIZE, (176, 154, 126, 255))
    canvas.fill_rect(ox + 3, oy + 4, TILE_SIZE - 6, TILE_SIZE - 8, (148, 96, 62, 255))
    canvas.fill_rect(ox + 5, oy + 6, TILE_SIZE - 10, TILE_SIZE - 12, (174, 118, 76, 255))
    canvas.fill_rect(ox, oy, 3, TILE_SIZE, (108, 72, 44, 255))
    canvas.fill_rect(ox + TILE_SIZE - 3, oy, 3, TILE_SIZE, (108, 72, 44, 255))


def _draw_park_bench(canvas: Canvas, ox: int, oy: int) -> None:
    wood = (162, 108, 56, 255)
    wood_hi = (190, 134, 74, 255)
    iron = (56, 60, 68, 255)
    canvas.fill_rect(ox + 4, oy + 21, 24, 4, (0, 0, 0, 60))
    canvas.fill_rect(ox + 5, oy + 8, 22, 5, wood)
    canvas.fill_rect(ox + 5, oy + 8, 22, 2, wood_hi)
    canvas.fill_rect(ox + 5, oy + 15, 22, 5, wood_hi)
    canvas.fill_rect(ox + 4, oy + 7, 3, 16, iron)
    canvas.fill_rect(ox + 25, oy + 7, 3, 16, iron)


def _draw_market_stall(canvas: Canvas, ox: int, oy: int) -> None:
    canvas.fill_rect(ox + 2, oy + 14, 28, 15, (142, 92, 52, 255))
    canvas.fill_rect(ox + 4, oy + 17, 10, 9, (214, 86, 68, 255))
    canvas.fill_rect(ox + 18, oy + 17, 10, 9, (110, 178, 72, 255))
    # Striped awning
    for x in range(2, 30):
        stripe = (212, 68, 60, 255) if ((x - 2) // 4) % 2 == 0 else (244, 236, 218, 255)
        canvas.fill_rect(ox + x, oy + 3, 1, 12, stripe)
    canvas.fill_rect(ox + 2, oy + 14, 28, 2, (152, 48, 42, 255))


def _draw_cafe_counter(canvas: Canvas, ox: int, oy: int) -> None:
    canvas.fill_rect(ox + 2, oy + 6, 28, 20, (124, 78, 44, 255))
    canvas.fill_rect(ox + 2, oy + 6, 28, 8, (194, 152, 104, 255))
    canvas.fill_rect(ox + 6, oy + 8, 7, 5, (92, 96, 108, 255))  # espresso machine
    canvas.fill_rect(ox + 17, oy + 8, 9, 5, (232, 214, 166, 255))  # pastry tray


def _draw_bookshelf(canvas: Canvas, ox: int, oy: int) -> None:
    frame = (108, 68, 38, 255)
    back = (64, 42, 24, 255)
    canvas.fill_rect(ox + 3, oy + 2, 26, 28, frame)
    canvas.fill_rect(ox + 5, oy + 5, 22, 10, back)
    canvas.fill_rect(ox + 5, oy + 17, 22, 10, back)
    book_colors = [
        (196, 72, 68, 255),
        (74, 138, 196, 255),
        (82, 166, 98, 255),
        (218, 172, 68, 255),
        (158, 98, 178, 255),
    ]
    for shelf_y in (6, 18):
        for i in range(6):
            canvas.fill_rect(ox + 6 + i * 3, oy + shelf_y, 2, 9, book_colors[(i + shelf_y) % 5])


def _draw_collision_marker(canvas: Canvas, ox: int, oy: int) -> None:
    canvas.blend_rect(ox + 1, oy + 1, TILE_SIZE - 2, TILE_SIZE - 2, (220, 48, 48, 45))
    border = (224, 52, 52, 155)
    for i in range(TILE_SIZE):
        canvas.set_pixel(ox + i, oy, border)
        canvas.set_pixel(ox + i, oy + TILE_SIZE - 1, border)
        canvas.set_pixel(ox, oy + i, border)
        canvas.set_pixel(ox + TILE_SIZE - 1, oy + i, border)
    cross = (232, 64, 64, 155)
    for i in range(4, TILE_SIZE - 4):
        canvas.set_pixel(ox + i, oy + i, cross)
        canvas.set_pixel(ox + TILE_SIZE - 1 - i, oy + i, cross)


def generate_tileset(path: Path) -> None:
    """Create the 256x128 RGBA tileset PNG with 32x32 tiles."""
    canvas = Canvas(TILESET_WIDTH, TILESET_HEIGHT)

    _draw_grass(canvas, *_tile_origin(GID_GRASS), with_flowers=False)
    _draw_grass(canvas, *_tile_origin(GID_FLOWER_GRASS), with_flowers=True)
    _draw_cobble_road(canvas, *_tile_origin(GID_COBBLE_ROAD))
    _draw_plaza_stone(canvas, *_tile_origin(GID_PLAZA_STONE))
    _draw_wood_floor(canvas, *_tile_origin(GID_WOOD_FLOOR))
    _draw_cafe_floor(canvas, *_tile_origin(GID_CAFE_FLOOR))
    _draw_water_pond(canvas, *_tile_origin(GID_WATER_POND))
    _draw_tree_hedge(canvas, *_tile_origin(GID_TREE_HEDGE))
    _draw_stone_wall(canvas, *_tile_origin(GID_STONE_WALL))
    _draw_timber_wall(canvas, *_tile_origin(GID_TIMBER_WALL))
    _draw_roof(
        canvas,
        *_tile_origin(GID_RED_ROOF),
        base=(178, 66, 56, 255),
        light=(204, 88, 76, 255),
        dark=(136, 46, 40, 255),
    )
    _draw_roof(
        canvas,
        *_tile_origin(GID_BLUE_ROOF),
        base=(64, 108, 158, 255),
        light=(88, 134, 188, 255),
        dark=(46, 80, 122, 255),
    )
    _draw_roof(
        canvas,
        *_tile_origin(GID_GREEN_ROOF),
        base=(62, 134, 88, 255),
        light=(84, 160, 112, 255),
        dark=(44, 98, 64, 255),
    )
    _draw_roof(
        canvas,
        *_tile_origin(GID_AMBER_ROOF),
        base=(204, 146, 54, 255),
        light=(226, 170, 74, 255),
        dark=(158, 108, 36, 255),
    )
    _draw_doorway(canvas, *_tile_origin(GID_DOORWAY))
    _draw_park_bench(canvas, *_tile_origin(GID_PARK_BENCH))
    _draw_market_stall(canvas, *_tile_origin(GID_MARKET_STALL))
    _draw_cafe_counter(canvas, *_tile_origin(GID_CAFE_COUNTER))
    _draw_bookshelf(canvas, *_tile_origin(GID_BOOKSHELF))
    _draw_collision_marker(canvas, *_tile_origin(GID_COLLISION))

    write_png(path, TILESET_WIDTH, TILESET_HEIGHT, canvas.data)


def _draw_villager_frame(
    canvas: Canvas,
    ox: int,
    oy: int,
    shirt: RGBA,
    hair: RGBA,
    pants: RGBA,
    skin: RGBA,
    pose: int,
) -> None:
    outline = (28, 26, 30, 255)
    # Drop shadow
    canvas.blend_rect(ox + 9, oy + 27, 14, 3, (0, 0, 0, 95))

    bob = -1 if pose in (1, 3) else 0
    left_leg_y = 22 + (-1 if pose == 1 else 0)
    right_leg_y = 22 + (-1 if pose == 3 else 0)

    # Legs
    canvas.fill_rect(ox + 11, oy + left_leg_y, 4, 6, outline)
    canvas.fill_rect(ox + 12, oy + left_leg_y, 2, 5, pants)
    canvas.fill_rect(ox + 17, oy + right_leg_y, 4, 6, outline)
    canvas.fill_rect(ox + 18, oy + right_leg_y, 2, 5, pants)

    # Torso & arms
    ty = oy + 14 + bob
    canvas.fill_rect(ox + 10, ty, 12, 9, outline)
    canvas.fill_rect(ox + 11, ty + 1, 10, 7, shirt)
    # Arm swing
    l_arm_dy = 1 if pose == 1 else (-1 if pose == 3 else 0)
    r_arm_dy = -1 if pose == 1 else (1 if pose == 3 else 0)
    canvas.fill_rect(ox + 8, ty + 1 + l_arm_dy, 2, 6, shirt)
    canvas.fill_rect(ox + 22, ty + 1 + r_arm_dy, 2, 6, shirt)
    canvas.fill_rect(ox + 8, ty + 6 + l_arm_dy, 2, 2, skin)
    canvas.fill_rect(ox + 22, ty + 6 + r_arm_dy, 2, 2, skin)

    # Head & hair
    hy = oy + 4 + bob
    canvas.fill_rect(ox + 10, hy, 12, 10, outline)
    canvas.fill_rect(ox + 11, hy + 2, 10, 7, skin)
    canvas.fill_rect(ox + 10, hy, 12, 4, hair)
    canvas.fill_rect(ox + 10, hy + 3, 2, 4, hair)
    canvas.fill_rect(ox + 20, hy + 3, 2, 4, hair)
    # Eyes
    canvas.set_pixel(ox + 13, hy + 6, outline)
    canvas.set_pixel(ox + 18, hy + 6, outline)


def generate_spritesheet(path: Path) -> None:
    """Create the 128x128 RGBA character spritesheet (4 villagers x 4 poses)."""
    canvas = Canvas(SPRITESHEET_WIDTH, SPRITESHEET_HEIGHT)
    palettes = [
        # Maya (teal)
        ((38, 166, 154, 255), (56, 36, 28, 255), (44, 68, 92, 255), (240, 200, 170, 255)),
        # Liam (amber)
        ((230, 158, 40, 255), (124, 76, 36, 255), (68, 56, 48, 255), (244, 208, 178, 255)),
        # Elena (violet)
        ((142, 84, 200, 255), (138, 54, 38, 255), (58, 44, 78, 255), (235, 192, 162, 255)),
        # Noah (emerald)
        ((46, 160, 92, 255), (34, 36, 42, 255), (52, 62, 74, 255), (214, 168, 134, 255)),
    ]
    for row, (shirt, hair, pants, skin) in enumerate(palettes):
        for col in range(SPRITE_COLS):
            _draw_villager_frame(
                canvas,
                col * TILE_SIZE,
                row * TILE_SIZE,
                shirt=shirt,
                hair=hair,
                pants=pants,
                skin=skin,
                pose=col,
            )
    write_png(path, SPRITESHEET_WIDTH, SPRITESHEET_HEIGHT, canvas.data)


def _idx(x: int, y: int) -> int:
    return y * MAP_WIDTH + x


def _fill_layer_rect(
    layer: list[int],
    x: int,
    y: int,
    w: int,
    h: int,
    gid: int,
) -> None:
    for py in range(y, y + h):
        for px in range(x, x + w):
            layer[_idx(px, py)] = gid


def _place_building(
    ground: list[int],
    structures: list[int],
    x0: int,
    y0: int,
    w: int,
    h: int,
    roof_gid: int,
    wall_gid: int,
    floor_gid: int,
    door_x: int,
    furniture: list[tuple[int, int, int]],
) -> None:
    # Interior & doorway floor
    _fill_layer_rect(ground, x0 + 1, y0 + 2, w - 2, h - 3, floor_gid)
    # 2-tile doorway on south wall
    ground[_idx(door_x, y0 + h - 1)] = GID_DOORWAY
    ground[_idx(door_x + 1, y0 + h - 1)] = GID_DOORWAY

    # Roof across top two rows
    _fill_layer_rect(structures, x0, y0, w, 2, roof_gid)

    # Side walls
    for py in range(y0 + 2, y0 + h):
        structures[_idx(x0, py)] = wall_gid
        structures[_idx(x0 + w - 1, py)] = wall_gid

    # South front wall with 2-tile doorway gap
    for px in range(x0, x0 + w):
        if px not in (door_x, door_x + 1):
            structures[_idx(px, y0 + h - 1)] = wall_gid

    # Interior furniture
    for fx, fy, fgid in furniture:
        structures[_idx(fx, fy)] = fgid


def _verify_reachability(collision: list[int], locations: list[TiledObject]) -> None:
    loc_by_name = {loc["name"]: loc for loc in locations}
    town_square = loc_by_name["Town Square"]
    ts_props = {p["name"]: p["value"] for p in town_square["properties"]}
    start: GridPos = (int(ts_props["anchor_x"]), int(ts_props["anchor_y"]))

    if collision[_idx(*start)] != 0:
        raise RuntimeError(f"Town Square anchor {start} is blocked")

    visited: set[GridPos] = {start}
    queue: deque[GridPos] = deque([start])
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < MAP_WIDTH and 0 <= ny < MAP_HEIGHT:
                nxt = (nx, ny)
                if nxt not in visited and collision[_idx(nx, ny)] == 0:
                    visited.add(nxt)
                    queue.append(nxt)

    for loc in locations:
        props = {p["name"]: p["value"] for p in loc["properties"]}
        anchor: GridPos = (int(props["anchor_x"]), int(props["anchor_y"]))
        if collision[_idx(*anchor)] != 0:
            raise RuntimeError(f"Location {loc['name']} anchor {anchor} is blocked")
        if anchor not in visited:
            raise RuntimeError(f"Location {loc['name']} anchor {anchor} unreachable from {start}")


def _make_location(
    obj_id: int,
    name: str,
    category: str,
    tx: int,
    ty: int,
    tw: int,
    th: int,
    anchor_x: int,
    anchor_y: int,
) -> TiledObject:
    return {
        "id": obj_id,
        "name": name,
        "type": category,
        "x": tx * TILE_SIZE,
        "y": ty * TILE_SIZE,
        "width": tw * TILE_SIZE,
        "height": th * TILE_SIZE,
        "rotation": 0,
        "visible": True,
        "properties": [
            {"name": "anchor_x", "type": "int", "value": anchor_x},
            {"name": "anchor_y", "type": "int", "value": anchor_y},
            {"name": "category", "type": "string", "value": category},
        ],
    }


def generate_map(path: Path) -> None:
    """Build the 40x30 Tiled v1.10 village map JSON and verify BFS reachability."""
    size = MAP_WIDTH * MAP_HEIGHT
    ground = [GID_GRASS] * size
    structures = [GID_EMPTY] * size

    # Flower grass accents across scenic meadows
    for y in range(1, MAP_HEIGHT - 1):
        for x in range(1, MAP_WIDTH - 1):
            if _hash2(x, y, seed=42) % 7 == 0:
                ground[_idx(x, y)] = GID_FLOWER_GRASS

    # Road network (2-tile wide cobblestone roads)
    _fill_layer_rect(ground, 2, 9, 36, 2, GID_COBBLE_ROAD)   # North Avenue (y=9..10)
    _fill_layer_rect(ground, 2, 18, 36, 2, GID_COBBLE_ROAD)  # South Avenue (y=18..19)
    _fill_layer_rect(ground, 2, 27, 36, 2, GID_COBBLE_ROAD)  # Garden Lane  (y=27..28)
    _fill_layer_rect(ground, 10, 9, 2, 20, GID_COBBLE_ROAD)  # West Avenue  (x=10..11)
    _fill_layer_rect(ground, 28, 9, 2, 20, GID_COBBLE_ROAD)  # East Avenue  (x=28..29)

    # Town Square central plaza & connectors (x=13..26, y=11..17)
    _fill_layer_rect(ground, 14, 12, 12, 5, GID_PLAZA_STONE)
    _fill_layer_rect(ground, 19, 11, 2, 1, GID_PLAZA_STONE)  # North connector
    _fill_layer_rect(ground, 19, 17, 2, 1, GID_PLAZA_STONE)  # South connector
    _fill_layer_rect(ground, 12, 14, 2, 2, GID_PLAZA_STONE)  # West connector
    _fill_layer_rect(ground, 26, 14, 2, 2, GID_PLAZA_STONE)  # East connector
    structures[_idx(15, 12)] = GID_PARK_BENCH
    structures[_idx(24, 12)] = GID_PARK_BENCH
    structures[_idx(13, 12)] = GID_TREE_HEDGE
    structures[_idx(26, 12)] = GID_TREE_HEDGE
    structures[_idx(13, 16)] = GID_TREE_HEDGE
    structures[_idx(26, 16)] = GID_TREE_HEDGE

    # Park (x=13..26, y=20..26) with flower lawn, pond, benches, and walking paths
    _fill_layer_rect(ground, 13, 20, 14, 7, GID_FLOWER_GRASS)
    _fill_layer_rect(ground, 19, 20, 2, 7, GID_PLAZA_STONE)   # North-south park path
    _fill_layer_rect(ground, 14, 22, 12, 2, GID_PLAZA_STONE)  # East-west park path
    _fill_layer_rect(ground, 14, 24, 4, 2, GID_WATER_POND)    # Scenic pond
    for bx, by in ((15, 21), (22, 21), (24, 21), (23, 25)):
        structures[_idx(bx, by)] = GID_PARK_BENCH
    for tx, ty in ((13, 20), (26, 20), (13, 26), (26, 26)):
        structures[_idx(tx, ty)] = GID_TREE_HEDGE

    # Buildings (all facing south onto 2-tile avenues with >= 3x3 open interiors)
    _place_building(
        ground, structures,
        x0=2, y0=2, w=7, h=7,
        roof_gid=GID_BLUE_ROOF, wall_gid=GID_TIMBER_WALL, floor_gid=GID_WOOD_FLOOR,
        door_x=4,
        furniture=[(3, 4, GID_BOOKSHELF), (7, 4, GID_PARK_BENCH)],
    )  # Home_Maya
    _place_building(
        ground, structures,
        x0=13, y0=2, w=6, h=7,
        roof_gid=GID_RED_ROOF, wall_gid=GID_STONE_WALL, floor_gid=GID_CAFE_FLOOR,
        door_x=15,
        furniture=[(14, 4, GID_CAFE_COUNTER), (15, 4, GID_CAFE_COUNTER)],
    )  # Cafe
    _place_building(
        ground, structures,
        x0=21, y0=2, w=6, h=7,
        roof_gid=GID_AMBER_ROOF, wall_gid=GID_TIMBER_WALL, floor_gid=GID_CAFE_FLOOR,
        door_x=23,
        furniture=[(22, 4, GID_CAFE_COUNTER), (23, 4, GID_CAFE_COUNTER)],
    )  # Bakery
    _place_building(
        ground, structures,
        x0=31, y0=2, w=7, h=7,
        roof_gid=GID_GREEN_ROOF, wall_gid=GID_TIMBER_WALL, floor_gid=GID_WOOD_FLOOR,
        door_x=33,
        furniture=[(32, 4, GID_BOOKSHELF), (36, 4, GID_PARK_BENCH)],
    )  # Home_Liam
    _place_building(
        ground, structures,
        x0=2, y0=11, w=7, h=7,
        roof_gid=GID_BLUE_ROOF, wall_gid=GID_STONE_WALL, floor_gid=GID_WOOD_FLOOR,
        door_x=4,
        furniture=[
            (3, 13, GID_BOOKSHELF),
            (4, 13, GID_BOOKSHELF),
            (6, 13, GID_BOOKSHELF),
            (7, 13, GID_BOOKSHELF),
        ],
    )  # Library
    _place_building(
        ground, structures,
        x0=31, y0=11, w=7, h=7,
        roof_gid=GID_GREEN_ROOF, wall_gid=GID_STONE_WALL, floor_gid=GID_PLAZA_STONE,
        door_x=33,
        furniture=[
            (32, 13, GID_MARKET_STALL),
            (33, 13, GID_MARKET_STALL),
            (35, 13, GID_MARKET_STALL),
            (36, 13, GID_MARKET_STALL),
        ],
    )  # Market
    _place_building(
        ground, structures,
        x0=2, y0=20, w=7, h=7,
        roof_gid=GID_RED_ROOF, wall_gid=GID_TIMBER_WALL, floor_gid=GID_WOOD_FLOOR,
        door_x=4,
        furniture=[(3, 22, GID_BOOKSHELF), (7, 22, GID_PARK_BENCH)],
    )  # Home_Elena
    _place_building(
        ground, structures,
        x0=31, y0=20, w=7, h=7,
        roof_gid=GID_AMBER_ROOF, wall_gid=GID_STONE_WALL, floor_gid=GID_WOOD_FLOOR,
        door_x=33,
        furniture=[(32, 22, GID_BOOKSHELF), (36, 22, GID_PARK_BENCH)],
    )  # Home_Noah

    # Decorative trees between top buildings and along avenue borders
    for tx, ty in ((10, 4), (11, 6), (19, 4), (20, 6), (28, 5), (29, 3)):
        structures[_idx(tx, ty)] = GID_TREE_HEDGE

    # Perimeter forest border
    for x in range(MAP_WIDTH):
        structures[_idx(x, 0)] = GID_TREE_HEDGE
        structures[_idx(x, MAP_HEIGHT - 1)] = GID_TREE_HEDGE
    for y in range(MAP_HEIGHT):
        structures[_idx(0, y)] = GID_TREE_HEDGE
        structures[_idx(MAP_WIDTH - 1, y)] = GID_TREE_HEDGE

    # Derive collision layer strictly from ground water + impassable structures
    collision = [
        GID_COLLISION
        if (
            ground[i] == GID_WATER_POND
            or (structures[i] != GID_EMPTY and structures[i] != GID_DOORWAY)
        )
        else GID_EMPTY
        for i in range(size)
    ]

    locations: list[TiledObject] = [
        _make_location(1, "Cafe", "cafe", 13, 2, 6, 7, anchor_x=16, anchor_y=6),
        _make_location(2, "Park", "park", 13, 20, 14, 7, anchor_x=19, anchor_y=23),
        _make_location(3, "Market", "market", 31, 11, 7, 7, anchor_x=34, anchor_y=15),
        _make_location(4, "Town Square", "plaza", 13, 11, 14, 7, anchor_x=19, anchor_y=14),
        _make_location(5, "Bakery", "bakery", 21, 2, 6, 7, anchor_x=24, anchor_y=6),
        _make_location(6, "Library", "library", 2, 11, 7, 7, anchor_x=5, anchor_y=15),
        _make_location(7, "Home_Maya", "home", 2, 2, 7, 7, anchor_x=5, anchor_y=6),
        _make_location(8, "Home_Liam", "home", 31, 2, 7, 7, anchor_x=34, anchor_y=6),
        _make_location(9, "Home_Elena", "home", 2, 20, 7, 7, anchor_x=5, anchor_y=24),
        _make_location(10, "Home_Noah", "home", 31, 20, 7, 7, anchor_x=34, anchor_y=24),
    ]

    _verify_reachability(collision, locations)

    tiled_map: dict[str, object] = {
        "compressionlevel": -1,
        "height": MAP_HEIGHT,
        "infinite": False,
        "layers": [
            {
                "data": ground,
                "height": MAP_HEIGHT,
                "id": 1,
                "name": "ground",
                "opacity": 1,
                "type": "tilelayer",
                "visible": True,
                "width": MAP_WIDTH,
                "x": 0,
                "y": 0,
            },
            {
                "data": structures,
                "height": MAP_HEIGHT,
                "id": 2,
                "name": "structures",
                "opacity": 1,
                "type": "tilelayer",
                "visible": True,
                "width": MAP_WIDTH,
                "x": 0,
                "y": 0,
            },
            {
                "data": collision,
                "height": MAP_HEIGHT,
                "id": 3,
                "name": "collision",
                "opacity": 1,
                "type": "tilelayer",
                "visible": False,
                "width": MAP_WIDTH,
                "x": 0,
                "y": 0,
            },
            {
                "draworder": "topdown",
                "id": 4,
                "name": "locations",
                "objects": locations,
                "opacity": 1,
                "type": "objectgroup",
                "visible": True,
                "x": 0,
                "y": 0,
            },
        ],
        "nextlayerid": 5,
        "nextobjectid": len(locations) + 1,
        "orientation": "orthogonal",
        "renderorder": "right-down",
        "tiledversion": "1.10.2",
        "tileheight": TILE_SIZE,
        "tilesets": [
            {
                "columns": TILESET_COLS,
                "firstgid": 1,
                "image": "tileset.png",
                "imageheight": TILESET_HEIGHT,
                "imagewidth": TILESET_WIDTH,
                "margin": 0,
                "name": "village_tiles",
                "spacing": 0,
                "tilecount": TILESET_COLS * TILESET_ROWS,
                "tileheight": TILE_SIZE,
                "tilewidth": TILE_SIZE,
            }
        ],
        "tilewidth": TILE_SIZE,
        "type": "map",
        "version": "1.10",
        "width": MAP_WIDTH,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tiled_map, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    generate_tileset(ASSETS_DIR / "tileset.png")
    generate_spritesheet(ASSETS_DIR / "sprites.png")
    generate_map(ASSETS_DIR / "map.json")
    print(f"Generated village assets in {ASSETS_DIR}")


if __name__ == "__main__":
    main()
