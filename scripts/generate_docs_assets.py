"""Deterministic documentation visual asset generator (architecture.png and demo.gif)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import tempfile
import zlib
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from sim.engine import SimulationEngine

RGBA = tuple[int, int, int, int]

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = REPO_ROOT / "frontend" / "public" / "assets"
DOCS_DIR = REPO_ROOT / "docs"

ARCH_WIDTH = 1400
ARCH_HEIGHT = 820

DEMO_WIDTH = 960
DEMO_HEIGHT = 620
DEMO_TILE_PX = 16
MAP_X0 = 14
MAP_Y0 = 58
FEED_X0 = 668
FEED_Y0 = 58
FEED_W = 278
FEED_H = 480

# Compact 5x7 pixel font bitmaps (each row is 5 bits wide, MSB on left).
_FONT_5X7: dict[str, tuple[int, ...]] = {
    " ": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    "!": (0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04),
    '"': (0x0A, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00),
    "#": (0x0A, 0x1F, 0x0A, 0x0A, 0x1F, 0x0A, 0x00),
    "%": (0x19, 0x1A, 0x04, 0x04, 0x0B, 0x13, 0x00),
    "&": (0x0C, 0x12, 0x14, 0x08, 0x15, 0x12, 0x0D),
    "'": (0x04, 0x04, 0x08, 0x00, 0x00, 0x00, 0x00),
    "(": (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ")": (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    "*": (0x00, 0x0A, 0x04, 0x1F, 0x04, 0x0A, 0x00),
    "+": (0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00),
    ",": (0x00, 0x00, 0x00, 0x00, 0x04, 0x04, 0x08),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    "/": (0x01, 0x02, 0x02, 0x04, 0x08, 0x08, 0x10),
    ":": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00),
    ";": (0x00, 0x0C, 0x0C, 0x00, 0x04, 0x04, 0x08),
    "<": (0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02),
    "=": (0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00),
    ">": (0x08, 0x04, 0x02, 0x01, 0x02, 0x04, 0x08),
    "?": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04),
    "@": (0x0E, 0x11, 0x17, 0x15, 0x17, 0x10, 0x0E),
    "[": (0x0E, 0x08, 0x08, 0x08, 0x08, 0x08, 0x0E),
    "]": (0x0E, 0x02, 0x02, 0x02, 0x02, 0x02, 0x0E),
    "_": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F),
    "|": (0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1F),
    "3": (0x0E, 0x11, 0x01, 0x06, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "D": (0x1C, 0x12, 0x11, 0x11, 0x11, 0x12, 0x1C),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "J": (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11),
    "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),
    "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    "a": (0x00, 0x00, 0x0E, 0x01, 0x0F, 0x11, 0x0F),
    "b": (0x10, 0x10, 0x16, 0x19, 0x11, 0x11, 0x1E),
    "c": (0x00, 0x00, 0x0E, 0x10, 0x10, 0x11, 0x0E),
    "d": (0x01, 0x01, 0x0D, 0x13, 0x11, 0x11, 0x0F),
    "e": (0x00, 0x00, 0x0E, 0x11, 0x1F, 0x10, 0x0E),
    "f": (0x06, 0x09, 0x08, 0x1C, 0x08, 0x08, 0x08),
    "g": (0x00, 0x0F, 0x11, 0x11, 0x0F, 0x01, 0x0E),
    "h": (0x10, 0x10, 0x16, 0x19, 0x11, 0x11, 0x11),
    "i": (0x04, 0x00, 0x0C, 0x04, 0x04, 0x04, 0x0E),
    "j": (0x02, 0x00, 0x06, 0x02, 0x02, 0x12, 0x0C),
    "k": (0x10, 0x10, 0x12, 0x14, 0x18, 0x14, 0x12),
    "l": (0x0C, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "m": (0x00, 0x00, 0x1A, 0x15, 0x15, 0x11, 0x11),
    "n": (0x00, 0x00, 0x16, 0x19, 0x11, 0x11, 0x11),
    "o": (0x00, 0x00, 0x0E, 0x11, 0x11, 0x11, 0x0E),
    "p": (0x00, 0x00, 0x1E, 0x11, 0x1E, 0x10, 0x10),
    "q": (0x00, 0x00, 0x0D, 0x13, 0x0F, 0x01, 0x01),
    "r": (0x00, 0x00, 0x16, 0x19, 0x10, 0x10, 0x10),
    "s": (0x00, 0x00, 0x0E, 0x10, 0x0E, 0x01, 0x1E),
    "t": (0x08, 0x08, 0x1C, 0x08, 0x08, 0x09, 0x06),
    "u": (0x00, 0x00, 0x11, 0x11, 0x11, 0x13, 0x0D),
    "v": (0x00, 0x00, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "w": (0x00, 0x00, 0x11, 0x11, 0x15, 0x15, 0x0A),
    "x": (0x00, 0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11),
    "y": (0x00, 0x00, 0x11, 0x11, 0x0F, 0x01, 0x0E),
    "z": (0x00, 0x00, 0x1F, 0x02, 0x04, 0x08, 0x1F),
}


@dataclass(frozen=True)
class RgbaImage:
    """Decoded RGBA raster pixel buffer."""

    width: int
    height: int
    data: bytearray


@dataclass(frozen=True)
class MapLocation:
    """Named location rectangle and anchor tile coordinate from Tiled map JSON."""

    name: str
    center_x: int
    center_y: int
    anchor_x: int
    anchor_y: int


@dataclass(frozen=True)
class FeedCard:
    """Recent activity feed entry shown in the right-hand sidebar."""

    kind: str
    badge: str
    meta: str
    subject: str
    body: str


class RasterCanvas:
    """Pure-Python RGBA frame buffer supporting alpha blending, rects, rings, and text."""

    def __init__(self, width: int, height: int, fill: RGBA = (0, 0, 0, 255)) -> None:
        self.width = width
        self.height = height
        self.data = bytearray(width * height * 4)
        r, g, b, a = fill
        if (r, g, b, a) != (0, 0, 0, 0):
            row = bytes((r, g, b, a)) * width
            for y in range(height):
                start = y * width * 4
                self.data[start : start + width * 4] = row

    def clone(self) -> RasterCanvas:
        """Return an independent pixel copy of this canvas."""
        copy = RasterCanvas(self.width, self.height, fill=(0, 0, 0, 0))
        copy.data[:] = self.data
        return copy

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
        dr = self.data[idx]
        dg = self.data[idx + 1]
        db = self.data[idx + 2]
        da = self.data[idx + 3]
        alpha = sa / 255.0
        inv = 1.0 - alpha
        out_a = int(sa + da * inv)
        if out_a <= 0:
            return
        out_r = int((sr * sa + dr * da * inv) / out_a)
        out_g = int((sg * sa + dg * da * inv) / out_a)
        out_b = int((sb * sa + db * da * inv) / out_a)
        self.data[idx : idx + 4] = bytes(
            (min(255, out_r), min(255, out_g), min(255, out_b), min(255, out_a))
        )

    def fill_rect(self, x: int, y: int, w: int, h: int, color: RGBA) -> None:
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.width, x + w)
        y1 = min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        if color[3] == 255:
            row = bytes(color) * (x1 - x0)
            for py in range(y0, y1):
                start = (py * self.width + x0) * 4
                self.data[start : start + (x1 - x0) * 4] = row
        else:
            for py in range(y0, y1):
                for px in range(x0, x1):
                    self.blend_pixel(px, py, color)

    def stroke_rect(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        color: RGBA,
        thickness: int = 1,
    ) -> None:
        if w <= 0 or h <= 0 or thickness <= 0:
            return
        self.fill_rect(x, y, w, thickness, color)
        self.fill_rect(x, y + h - thickness, w, thickness, color)
        self.fill_rect(x, y, thickness, h, color)
        self.fill_rect(x + w - thickness, y, thickness, h, color)

    def draw_ring(
        self,
        cx: int,
        cy: int,
        radius: int,
        thickness: int,
        stroke_color: RGBA,
        fill_color: RGBA | None = None,
    ) -> None:
        outer2 = radius * radius
        inner = max(0, radius - thickness)
        inner2 = inner * inner
        for py in range(cy - radius - 1, cy + radius + 2):
            for px in range(cx - radius - 1, cx + radius + 2):
                d2 = (px - cx) * (px - cx) + (py - cy) * (py - cy)
                if inner2 <= d2 <= outer2:
                    self.blend_pixel(px, py, stroke_color)
                elif fill_color is not None and d2 < inner2:
                    self.blend_pixel(px, py, fill_color)

    def blit_scaled_nearest(
        self,
        src: RgbaImage,
        sx: int,
        sy: int,
        sw: int,
        sh: int,
        dx: int,
        dy: int,
        dw: int,
        dh: int,
    ) -> None:
        """Blit a rectangular sub-region using crisp nearest-neighbor scaling and alpha blend."""
        if dw <= 0 or dh <= 0 or sw <= 0 or sh <= 0:
            return
        for oy in range(dh):
            src_y = sy + (oy * sh) // dh
            if not (0 <= src_y < src.height):
                continue
            dst_y = dy + oy
            if not (0 <= dst_y < self.height):
                continue
            for ox in range(dw):
                src_x = sx + (ox * sw) // dw
                if not (0 <= src_x < src.width):
                    continue
                sidx = (src_y * src.width + src_x) * 4
                sa = src.data[sidx + 3]
                if sa == 0:
                    continue
                color: RGBA = (
                    src.data[sidx],
                    src.data[sidx + 1],
                    src.data[sidx + 2],
                    sa,
                )
                self.blend_pixel(dx + ox, dst_y, color)

    def draw_text(
        self,
        x: int,
        y: int,
        text: str,
        color: RGBA,
        *,
        scale: int = 1,
        spacing: int = 1,
    ) -> None:
        """Render an ASCII string using the embedded 5x7 bitmap font."""
        cursor_x = x
        step = (5 + spacing) * scale
        for ch in text:
            bitmap = _FONT_5X7.get(ch)
            if bitmap is None:
                bitmap = _FONT_5X7.get(ch.upper(), _FONT_5X7[" "])
            for row_idx, row_bits in enumerate(bitmap):
                for col_idx in range(5):
                    if row_bits & (1 << (4 - col_idx)):
                        self.fill_rect(
                            cursor_x + col_idx * scale,
                            y + row_idx * scale,
                            scale,
                            scale,
                            color,
                        )
            cursor_x += step


def measure_text_width(text: str, *, scale: int = 1, spacing: int = 1) -> int:
    """Compute exact rendered pixel width for a string in the 5x7 font."""
    if not text:
        return 0
    return len(text) * (5 * scale) + max(0, len(text) - 1) * (spacing * scale)


def wrap_text(text: str, max_chars: int) -> list[str]:
    """Word-wrap text cleanly to fit inside max_chars columns."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        if len(word) > max_chars:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[: max(1, max_chars - 3)] + "...")
            continue
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def write_png(path: Path, width: int, height: int, rgba: bytearray) -> None:
    """Encode an RGBA buffer to an uncompressed-filter PNG using stdlib zlib."""
    stride = width * 4
    raw = bytearray((stride + 1) * height)
    for y in range(height):
        raw_offset = y * (stride + 1)
        src_offset = y * stride
        raw[raw_offset] = 0
        raw[raw_offset + 1 : raw_offset + 1 + stride] = rgba[src_offset : src_offset + stride]

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=6)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes)


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png(path: Path) -> RgbaImage:
    """Decode an 8-bit RGB or RGBA PNG file into an RgbaImage using stdlib zlib."""
    raw_bytes = path.read_bytes()
    if not raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"Not a valid PNG signature: {path}")

    pos = 8
    width = 0
    height = 0
    bit_depth = 0
    color_type = 0
    idat_parts: list[bytes] = []

    while pos + 8 <= len(raw_bytes):
        length = struct.unpack(">I", raw_bytes[pos : pos + 4])[0]
        chunk_type = raw_bytes[pos + 4 : pos + 8]
        chunk_data = raw_bytes[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if bit_depth != 8 or interlace != 0 or color_type not in (2, 6):
                raise ValueError(
                    f"Unsupported PNG format in {path}: "
                    f"depth={bit_depth}, color={color_type}, interlace={interlace}"
                )
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    bpp = 4 if color_type == 6 else 3
    stride = width * bpp
    decompressed = zlib.decompress(b"".join(idat_parts))
    expected_len = (stride + 1) * height
    if len(decompressed) != expected_len:
        raise ValueError(
            f"Unexpected decompressed PNG size for {path}: "
            f"{len(decompressed)} != {expected_len}"
        )

    unfiltered = bytearray(width * height * bpp)
    prev_row = bytearray(stride)

    for y in range(height):
        src_offset = y * (stride + 1)
        filter_type = decompressed[src_offset]
        scanline = decompressed[src_offset + 1 : src_offset + 1 + stride]
        cur_row = bytearray(stride)

        for i in range(stride):
            x_val = scanline[i]
            a_val = cur_row[i - bpp] if i >= bpp else 0
            b_val = prev_row[i]
            c_val = prev_row[i - bpp] if i >= bpp else 0
            if filter_type == 0:
                recon = x_val
            elif filter_type == 1:
                recon = (x_val + a_val) & 0xFF
            elif filter_type == 2:
                recon = (x_val + b_val) & 0xFF
            elif filter_type == 3:
                recon = (x_val + ((a_val + b_val) >> 1)) & 0xFF
            elif filter_type == 4:
                recon = (x_val + _paeth_predictor(a_val, b_val, c_val)) & 0xFF
            else:
                raise ValueError(f"Unsupported PNG filter {filter_type} in {path}")
            cur_row[i] = recon

        unfiltered[y * stride : (y + 1) * stride] = cur_row
        prev_row = cur_row

    if bpp == 4:
        return RgbaImage(width=width, height=height, data=unfiltered)

    rgba = bytearray(width * height * 4)
    for idx in range(width * height):
        rgba[idx * 4 : idx * 4 + 3] = unfiltered[idx * 3 : idx * 3 + 3]
        rgba[idx * 4 + 3] = 255
    return RgbaImage(width=width, height=height, data=rgba)


def _find_headless_browser() -> str | None:
    """Locate Microsoft Edge or Google Chrome executable if installed on the host."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    for binary in ("msedge", "microsoft-edge", "google-chrome", "chromium"):
        found = shutil.which(binary)
        if found is not None:
            return found
    return None


def _build_architecture_html() -> str:
    """Return standalone 1400x820 HTML/SVG markup depicting the exact AI Village stack."""
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>AI Village Architecture</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    width: 1400px;
    height: 820px;
    overflow: hidden;
    background: #0b1120;
    color: #f8fafc;
    font-family: "Segoe UI", Inter, system-ui, -apple-system, sans-serif;
  }
  .board {
    position: relative;
    width: 1400px;
    height: 820px;
    padding: 24px 28px;
    background:
      radial-gradient(circle at 15% 15%, rgba(56, 189, 248, 0.08), transparent 40%),
      radial-gradient(circle at 85% 82%, rgba(168, 85, 247, 0.09), transparent 42%),
      #0b1120;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 14px;
    border-bottom: 1px solid #1e293b;
    margin-bottom: 18px;
  }
  .title { font-size: 24px; font-weight: 800; letter-spacing: -0.02em; color: #f8fafc; }
  .subtitle { font-size: 13px; color: #94a3b8; margin-top: 3px; }
  .pill-row { display: flex; gap: 8px; }
  .pill {
    padding: 5px 11px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.03em;
    border: 1px solid #334155;
    background: #111c33;
    color: #cbd5e1;
  }
  .pill.accent { border-color: rgba(56, 189, 248, 0.45); color: #38bdf8; }
  .grid {
    display: grid;
    grid-template-columns: 300px 210px 490px 308px;
    gap: 12px;
    height: 676px;
    align-items: stretch;
  }
  .tier {
    background: rgba(15, 23, 42, 0.9);
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .tier-browser { border-top: 3px solid #38bdf8; }
  .tier-proxy { border-top: 3px solid #10b981; justify-content: center; }
  .tier-server { border-top: 3px solid #f59e0b; }
  .tier-storage { border-top: 3px solid #a855f7; }
  .tier-title {
    font-size: 13px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #e2e8f0;
  }
  .tier-sub { font-size: 11px; color: #94a3b8; margin-top: -6px; }
  .card {
    background: #16223a;
    border: 1px solid #293956;
    border-radius: 8px;
    padding: 10px 11px;
  }
  .card h3 { font-size: 12.5px; font-weight: 700; color: #f8fafc; margin-bottom: 4px; }
  .card p, .card li { font-size: 11px; line-height: 1.42; color: #cbd5e1; }
  .card ul { padding-left: 15px; }
  .mono {
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 10.5px;
    color: #7dd3fc;
  }
  .formula {
    margin-top: 5px;
    padding: 5px 8px;
    border-radius: 6px;
    background: #0b1324;
    border: 1px solid #334155;
    font-family: Consolas, monospace;
    font-size: 10.5px;
    color: #fbbf24;
  }
  .arrow-box {
    text-align: center;
    padding: 9px 8px;
    border-radius: 8px;
    background: #0f1b30;
    border: 1px dashed #334155;
  }
  .arrow-dir { font-size: 12px; font-weight: 800; color: #34d399; margin-bottom: 4px; }
  .badge-list { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
  .tag {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 4px;
    background: rgba(56, 189, 248, 0.14);
    color: #bae6fd;
    border: 1px solid rgba(56, 189, 248, 0.3);
  }
  .tag.amber {
    background: rgba(245, 158, 11, 0.14);
    color: #fde68a;
    border-color: rgba(245, 158, 11, 0.35);
  }
  .tag.violet {
    background: rgba(168, 85, 247, 0.16);
    color: #e9d5ff;
    border-color: rgba(168, 85, 247, 0.35);
  }
  .footer {
    margin-top: 10px;
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: #94a3b8;
  }
</style>
</head>
<body>
<div class="board">
  <div class="header">
    <div>
      <div class="title">AI Village — System Architecture</div>
      <div class="subtitle">
        Server-Authoritative Multi-Agent Town Simulation: Classical A* + Hierarchical Planning +
        Weighted Memory Retrieval + Budget-Aware LLM Gateway
      </div>
    </div>
    <div class="pill-row">
      <span class="pill accent">8 Autonomous Villagers</span>
      <span class="pill">40x30 Tiled Grid</span>
      <span class="pill">Offline Deterministic Mock + Gemini</span>
    </div>
  </div>

  <div class="grid">
    <section class="tier tier-browser">
      <div class="tier-title">1. Browser Client</div>
      <div class="tier-sub">Phaser 3 · TypeScript · Vite (:5173)</div>

      <div class="card">
        <h3>Phaser 3 World Scene</h3>
        <ul>
          <li>Renders <span class="mono">map.json</span> layers &amp; 10 locations</li>
          <li>4-frame villager walk sprites + name tags</li>
          <li>Staggered dialogue speech bubbles</li>
          <li>God-mode amber &amp; reflection violet pulses</li>
        </ul>
      </div>

      <div class="card">
        <h3>Interactive UI &amp; Analytics</h3>
        <ul>
          <li><strong>Time Controls:</strong> Pause, Play, 1x / 4x / 16x</li>
          <li><strong>God-Mode Injector:</strong> Location + event prompt</li>
          <li><strong>Agent Inspector:</strong> Plan, top memories, mood</li>
          <li><strong>Cytoscape.js:</strong> Pairwise relationship graph</li>
          <li><strong>Chart.js:</strong> Cost, token &amp; latency dashboard</li>
          <li><strong>Day Replay:</strong> JSONL scrubber &amp; frame playback</li>
        </ul>
      </div>

      <div class="card">
        <h3>Pure View Contract</h3>
        <p>
          Zero client pathfinding or state mutation; all rendering follows authoritative
          server frames.
        </p>
      </div>
    </section>

    <section class="tier tier-proxy">
      <div class="tier-title">2. Edge Proxy</div>
      <div class="tier-sub">Nginx 1.27 / Vite Proxy</div>

      <div class="arrow-box">
        <div class="arrow-dir">&lt;--- HTTP REST ---&gt;</div>
        <div class="mono">12 Endpoints</div>
        <div class="badge-list">
          <span class="tag">/health</span>
          <span class="tag">/world</span>
          <span class="tag">/agents</span>
          <span class="tag">/agents/{id}</span>
          <span class="tag">/events</span>
          <span class="tag">/sim/start|pause|speed</span>
          <span class="tag">/relationships</span>
          <span class="tag">/metrics</span>
          <span class="tag">/replay</span>
          <span class="tag">/replay/{day}</span>
        </div>
      </div>

      <div class="arrow-box">
        <div class="arrow-dir">&lt;=== WebSocket ===&gt;</div>
        <div class="mono">/ws (3600s timeout)</div>
        <p style="font-size:10.5px;color:#cbd5e1;margin-top:4px;">
          Live broadcast frames: <span class="mono">tick</span>, <span class="mono">dialogue</span>,
          <span class="mono">event</span>, <span class="mono">reflection</span>,
          <span class="mono">metrics</span>
        </p>
      </div>

      <div class="card">
        <h3>Container Port Map</h3>
        <p class="mono">Host :5173 -&gt; nginx :80</p>
        <p class="mono">nginx -&gt; backend:8000</p>
      </div>
    </section>

    <section class="tier tier-server">
      <div class="tier-title">3. FastAPI Simulation Server (Authoritative Source of Truth)</div>
      <div class="tier-sub">Python 3.12 · FastAPI · asyncio · Pydantic v2</div>

      <div class="card">
        <h3>SimulationEngine &amp; Classical A* (<span class="mono">sim/</span>)</h3>
        <ul>
          <li>
            <span class="mono">SimClock</span>: 1 tick = 1 sim min (1,440 ticks/day, 06:00)
          </li>
          <li>
            <span class="mono">astar.py</span>: Custom <span class="mono">heapq</span> 4-way
            Manhattan A* on collision grid
          </li>
          <li>Tile reservation prevents wall collisions &amp; same-tile overlaps</li>
        </ul>
      </div>

      <div class="card">
        <h3>AgentBrain 5-Stage Cognitive Loop (<span class="mono">agents/</span>)</h3>
        <div class="badge-list">
          <span class="tag amber">1. Perceive</span>
          <span class="tag amber">2. Remember</span>
          <span class="tag amber">3. Decide</span>
          <span class="tag amber">4. Act</span>
          <span class="tag amber">5. Reflect</span>
        </div>
        <ul style="margin-top:6px;">
          <li>
            <strong>DailyPlanner:</strong> 5-8 day blocks -&gt; hourly focus -&gt; minute steps
          </li>
          <li>
            <strong>ConversationManager:</strong> &lt;=2 tiles, cooldowns, max 6 turns, affinity
          </li>
          <li>
            <strong>ReflectionManager:</strong> Importance &gt;= 150 -&gt; 3 questions -&gt; cited
          </li>
        </ul>
      </div>

      <div class="card">
        <h3>MemoryRetriever (<span class="mono">memory/retrieval.py</span>)</h3>
        <p>Min-max normalized top-k (k=8) with exponential decay (0.995/hr) + NumPy cosine:</p>
        <div class="formula">score = w_r * recency + w_i * importance + w_v * relevance</div>
      </div>

      <div class="card">
        <h3>LLMGateway (<span class="mono">llm/gateway.py</span>)</h3>
        <p>
          Pydantic v2 schema enforcement + 1 repair retry, SHA-256 prompt cache, daily token/USD
          budget gate with fallback, and <span class="mono">llm_calls</span> audit logging.
        </p>
      </div>
    </section>

    <section class="tier tier-storage">
      <div class="tier-title">4. Data &amp; Providers</div>
      <div class="tier-sub">SQLite WAL · JSONL · Embeddings · LLMs</div>

      <div class="card">
        <h3>SQLite WAL Persistence (7 Tables)</h3>
        <div class="badge-list">
          <span class="tag violet">agents</span>
          <span class="tag violet">memories</span>
          <span class="tag violet">relationships</span>
          <span class="tag violet">events</span>
          <span class="tag violet">conversations</span>
          <span class="tag violet">llm_calls</span>
          <span class="tag violet">sim_state</span>
        </div>
      </div>

      <div class="card">
        <h3>Day-Partitioned Replay Logs</h3>
        <p class="mono">logs/day_{N}.jsonl</p>
        <p style="margin-top:3px;">
          Async <span class="mono">asyncio.to_thread</span> writer rotating at Day N 00:00
          (e.g. tick 1080).
        </p>
      </div>

      <div class="card">
        <h3>Local Embeddings (<span class="mono">embeddings.py</span>)</h3>
        <ul>
          <li>Production: <span class="mono">all-MiniLM-L6-v2</span> (384-d)</li>
          <li>CI / Mock: <span class="mono">DeterministicEmbeddingProvider</span></li>
        </ul>
      </div>

      <div class="card">
        <h3>Pluggable LLM Providers</h3>
        <ul>
          <li><span class="mono">GeminiProvider</span>: Flash routine + Pro planning</li>
          <li><span class="mono">MockProvider(seed=42)</span>: Offline zero-cost CI</li>
        </ul>
      </div>
    </section>
  </div>

  <div class="footer">
    <span>AI Village (BSCS AI Lab Project) · FastAPI + Phaser 3 + SQLite WAL</span>
    <span>
      No client simulation logic · Decision-point-only LLM calls · Zero-network test suite
    </span>
  </div>
</div>
</body>
</html>
"""


def _render_architecture_fallback_png(output_path: Path) -> None:
    """Pure-Python stdlib fallback renderer if neither Edge nor Chrome is installed."""
    canvas = RasterCanvas(ARCH_WIDTH, ARCH_HEIGHT, fill=(11, 17, 32, 255))
    canvas.fill_rect(24, 20, ARCH_WIDTH - 48, 56, (22, 34, 58, 255))
    canvas.stroke_rect(24, 20, ARCH_WIDTH - 48, 56, (51, 65, 85, 255), thickness=2)
    canvas.draw_text(
        42,
        38,
        "AI VILLAGE - SYSTEM ARCHITECTURE",
        (248, 250, 252, 255),
        scale=3,
    )

    tiers: list[tuple[str, str, RGBA, list[str]]] = [
        (
            "1. BROWSER CLIENT",
            "Phaser 3 + TS + Vite",
            (56, 189, 248, 255),
            [
                "Phaser 3 Tilemap & Sprites",
                "HUD Time Controls (1x/4x/16x)",
                "God-Mode Event Injector",
                "Agent Inspector Panel",
                "Cytoscape.js Relationship Graph",
                "Chart.js Cost Dashboard",
                "JSONL Day Replay Scrubber",
            ],
        ),
        (
            "2. EDGE PROXY",
            "Nginx 1.27 / Vite Proxy",
            (16, 185, 129, 255),
            [
                "12 REST API Endpoints",
                "/health /world /agents",
                "/events /sim/* /metrics",
                "/relationships /replay",
                "WebSocket /ws (3600s)",
                "tick, dialogue, event,",
                "reflection, metrics frames",
            ],
        ),
        (
            "3. FASTAPI SERVER",
            "Authoritative Engine",
            (245, 158, 11, 255),
            [
                "SimulationEngine + SimClock",
                "Custom heapq 4-Way A* Search",
                "AgentBrain 5-Stage Loop",
                "DailyPlanner (Day->Hr->Min)",
                "Conversation & Reflection Mgr",
                "MemoryRetriever (rec+imp+rel)",
                "LLMGateway Cache & Budget",
            ],
        ),
        (
            "4. DATA & PROVIDERS",
            "SQLite WAL + Providers",
            (168, 85, 247, 255),
            [
                "SQLite WAL (7 Tables)",
                "day_{N}.jsonl Replay Logs",
                "Gemini 2.5 Flash & Pro",
                "MockProvider(seed=42)",
                "all-MiniLM-L6-v2 Embeddings",
                "Deterministic Test Embedder",
                "Zero-Network CI Verified",
            ],
        ),
    ]

    box_w = 315
    gap = 24
    start_x = 34
    box_y = 104
    box_h = 670
    for idx, (title, sub, accent, bullets) in enumerate(tiers):
        bx = start_x + idx * (box_w + gap)
        canvas.fill_rect(bx, box_y, box_w, box_h, (15, 23, 42, 255))
        canvas.stroke_rect(bx, box_y, box_w, box_h, (51, 65, 85, 255), thickness=2)
        canvas.fill_rect(bx, box_y, box_w, 6, accent)
        canvas.draw_text(bx + 14, box_y + 22, title, (248, 250, 252, 255), scale=2)
        canvas.draw_text(bx + 14, box_y + 44, sub, accent, scale=1)
        for b_idx, line in enumerate(bullets):
            cy = box_y + 84 + b_idx * 78
            canvas.fill_rect(bx + 14, cy, box_w - 28, 60, (22, 34, 58, 255))
            canvas.stroke_rect(bx + 14, cy, box_w - 28, 60, (41, 57, 86, 255), thickness=1)
            canvas.draw_text(bx + 24, cy + 23, line, (226, 232, 240, 255), scale=1)

    write_png(output_path, ARCH_WIDTH, ARCH_HEIGHT, canvas.data)


def generate_architecture_png(output_path: Path) -> str:
    """Render docs/architecture.png via headless browser when available, else stdlib fallback."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    browser = _find_headless_browser()
    if browser is not None:
        with tempfile.TemporaryDirectory(prefix="ai_village_arch_") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            html_path = tmp_dir / "architecture.html"
            raw_png = tmp_dir / "architecture_raw.png"
            html_path.write_text(_build_architecture_html(), encoding="utf-8")

            cmd = [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--force-device-scale-factor=1",
                "--hide-scrollbars",
                f"--window-size={ARCH_WIDTH},{ARCH_HEIGHT}",
                f"--screenshot={raw_png}",
                html_path.as_uri(),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0 and raw_png.is_file() and raw_png.stat().st_size > 10_000:
                shutil.copyfile(raw_png, output_path)
                return f"headless:{Path(browser).name}"

    _render_architecture_fallback_png(output_path)
    return "stdlib-fallback"


def _load_map_assets() -> tuple[
    int,
    int,
    int,
    list[int],
    list[int],
    list[MapLocation],
    RgbaImage,
    RgbaImage,
]:
    map_data = json.loads((ASSETS_DIR / "map.json").read_text(encoding="utf-8"))
    map_w = int(map_data["width"])
    map_h = int(map_data["height"])
    tileset_cols = int(map_data["tilesets"][0]["columns"])

    ground: list[int] = []
    structures: list[int] = []
    locations: list[MapLocation] = []

    for layer in map_data["layers"]:
        layer_name = str(layer.get("name", ""))
        if layer_name == "ground":
            ground = [int(v) for v in layer["data"]]
        elif layer_name == "structures":
            structures = [int(v) for v in layer["data"]]
        elif layer_name == "locations":
            tile_size = int(map_data.get("tilewidth", 32))
            for obj in layer.get("objects", []):
                props = {
                    str(p["name"]): p["value"] for p in obj.get("properties", [])
                }
                cx = int((float(obj["x"]) + float(obj["width"]) / 2.0) * DEMO_TILE_PX / tile_size)
                cy = int(
                    (float(obj["y"]) + float(obj["height"]) / 2.0) * DEMO_TILE_PX / tile_size
                )
                locations.append(
                    MapLocation(
                        name=str(obj["name"]),
                        center_x=cx,
                        center_y=cy,
                        anchor_x=int(props["anchor_x"]),
                        anchor_y=int(props["anchor_y"]),
                    )
                )

    tileset = decode_png(ASSETS_DIR / "tileset.png")
    sprites = decode_png(ASSETS_DIR / "sprites.png")
    return map_w, map_h, tileset_cols, ground, structures, locations, tileset, sprites


def _build_map_backdrop(
    map_w: int,
    map_h: int,
    tileset_cols: int,
    ground: Sequence[int],
    structures: Sequence[int],
    locations: Sequence[MapLocation],
    tileset: RgbaImage,
) -> RasterCanvas:
    """Pre-bake static UI chrome, scaled 40x30 village tilemap, and location badges."""
    canvas = RasterCanvas(DEMO_WIDTH, DEMO_HEIGHT, fill=(15, 23, 42, 255))

    # Top HUD bar
    canvas.fill_rect(0, 0, DEMO_WIDTH, 46, (30, 41, 59, 255))
    canvas.fill_rect(0, 45, DEMO_WIDTH, 1, (51, 65, 85, 255))
    canvas.draw_text(16, 16, "AI Village", (248, 250, 252, 255), scale=2)

    # Live pill
    canvas.fill_rect(144, 13, 52, 20, (16, 85, 65, 255))
    canvas.stroke_rect(144, 13, 52, 20, (52, 211, 153, 255), thickness=1)
    canvas.draw_text(154, 19, "LIVE", (110, 231, 183, 255), scale=1)

    # Right sidebar container
    canvas.fill_rect(FEED_X0, FEED_Y0, FEED_W, FEED_H, (17, 28, 51, 255))
    canvas.stroke_rect(FEED_X0, FEED_Y0, FEED_W, FEED_H, (51, 65, 85, 255), thickness=1)
    canvas.fill_rect(FEED_X0, FEED_Y0, FEED_W, 28, (24, 38, 66, 255))
    canvas.fill_rect(FEED_X0, FEED_Y0 + 28, FEED_W, 1, (51, 65, 85, 255))
    canvas.draw_text(FEED_X0 + 10, FEED_Y0 + 10, "LIVE VILLAGE ACTIVITY", (226, 232, 240, 255))

    # Bottom God-Mode bar
    canvas.fill_rect(0, 554, DEMO_WIDTH, 66, (30, 41, 59, 255))
    canvas.fill_rect(0, 554, DEMO_WIDTH, 1, (51, 65, 85, 255))
    canvas.draw_text(16, 566, "GOD MODE", (251, 191, 36, 255), scale=1)
    canvas.fill_rect(16, 580, 928, 28, (15, 23, 42, 255))
    canvas.stroke_rect(16, 580, 928, 28, (51, 65, 85, 255), thickness=1)

    # Map border
    map_px_w = map_w * DEMO_TILE_PX
    map_px_h = map_h * DEMO_TILE_PX
    canvas.stroke_rect(
        MAP_X0 - 1,
        MAP_Y0 - 1,
        map_px_w + 2,
        map_px_h + 2,
        (51, 65, 85, 255),
        thickness=1,
    )

    # Ground + structures layers
    for ty in range(map_h):
        for tx in range(map_w):
            idx = ty * map_w + tx
            dx = MAP_X0 + tx * DEMO_TILE_PX
            dy = MAP_Y0 + ty * DEMO_TILE_PX
            for gid in (ground[idx], structures[idx]):
                if gid <= 0:
                    continue
                tile_idx = gid - 1
                sx = (tile_idx % tileset_cols) * 32
                sy = (tile_idx // tileset_cols) * 32
                canvas.blit_scaled_nearest(
                    tileset,
                    sx,
                    sy,
                    32,
                    32,
                    dx,
                    dy,
                    DEMO_TILE_PX,
                    DEMO_TILE_PX,
                )

    # Location labels
    for loc in locations:
        label_w = measure_text_width(loc.name, scale=1) + 8
        lx = max(
            MAP_X0 + 2,
            min(MAP_X0 + map_px_w - label_w - 2, MAP_X0 + loc.center_x - label_w // 2),
        )
        ly = max(MAP_Y0 + 2, min(MAP_Y0 + map_px_h - 14, MAP_Y0 + loc.center_y - 6))
        canvas.fill_rect(lx, ly, label_w, 11, (15, 23, 42, 200))
        canvas.draw_text(lx + 4, ly + 2, loc.name, (241, 245, 249, 255), scale=1)

    return canvas


def _collect_demo_frames(
    *,
    replay_jsonl: Path | None,
    seed: int,
) -> list[dict[str, Any]]:
    """Load replay frames from JSONL or run a deterministic 120-tick simulation snippet."""
    if replay_jsonl is not None:
        raw_frames: list[dict[str, Any]] = []
        for raw_line in replay_jsonl.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                raw_frames.append({str(k): v for k, v in parsed.items()})
        return raw_frames

    collected: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ai_village_demo_sim_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        db_path = tmp_dir / "demo.db"
        replay_dir = tmp_dir / "logs"
        app = create_app(
            Settings(
                sim_auto_start=False,
                sim_tick_seconds=0.05,
                sim_seed=seed,
                llm_provider="mock",
                embedding_provider="mock",
                database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
                replay_log_dir=str(replay_dir),
            )
        )
        with TestClient(app) as client:
            if client.portal is None:
                raise RuntimeError("TestClient portal unavailable")
            engine: SimulationEngine = app.state.engine
            for step_idx in range(1, 121):
                client.portal.call(engine.step_once)
                if step_idx == 35:
                    resp = client.post(
                        "/events",
                        json={
                            "text": "Sudden spice delivery arrived at the Bakery",
                            "location": "Bakery",
                        },
                    )
                    if resp.status_code != 200:
                        raise RuntimeError(f"Demo event injection failed: {resp.status_code}")

        day1_file = replay_dir / "day_1.jsonl"
        for raw_line in day1_file.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                collected.append({str(k): v for k, v in parsed.items()})
    return collected


def _draw_feed_cards(canvas: RasterCanvas, cards: Sequence[FeedCard]) -> None:
    cursor_y = FEED_Y0 + 36
    card_w = FEED_W - 16
    card_x = FEED_X0 + 8

    for card in cards[:5]:
        body_lines = wrap_text(card.body, max_chars=38)[:2]
        subject_lines = wrap_text(card.subject, max_chars=38)[:1] if card.subject else []
        card_h = 26 + len(subject_lines) * 11 + len(body_lines) * 10 + 6
        if cursor_y + card_h > FEED_Y0 + FEED_H - 6:
            break

        accent: RGBA = (56, 189, 248, 255)
        badge_bg: RGBA = (24, 62, 92, 255)
        if card.kind == "event":
            accent = (245, 158, 11, 255)
            badge_bg = (92, 54, 16, 255)
        elif card.kind == "reflection":
            accent = (168, 85, 247, 255)
            badge_bg = (68, 32, 98, 255)

        canvas.fill_rect(card_x, cursor_y, card_w, card_h, (24, 34, 54, 245))
        canvas.stroke_rect(card_x, cursor_y, card_w, card_h, (51, 65, 85, 255), thickness=1)
        canvas.fill_rect(card_x, cursor_y, 3, card_h, accent)

        badge_w = measure_text_width(card.badge) + 8
        canvas.fill_rect(card_x + 8, cursor_y + 6, badge_w, 12, badge_bg)
        canvas.draw_text(card_x + 12, cursor_y + 8, card.badge, accent)
        canvas.draw_text(
            card_x + 12 + badge_w + 4,
            cursor_y + 8,
            card.meta[:26],
            (148, 163, 184, 255),
        )

        text_y = cursor_y + 23
        for sline in subject_lines:
            canvas.draw_text(card_x + 8, text_y, sline, (226, 232, 240, 255))
            text_y += 11
        for bline in body_lines:
            canvas.draw_text(card_x + 8, text_y, bline, (248, 250, 252, 255))
            text_y += 10

        cursor_y += card_h + 7


def _draw_speech_bubble(
    canvas: RasterCanvas,
    *,
    anchor_x: int,
    anchor_y: int,
    speaker: str,
    text: str,
) -> None:
    lines = wrap_text(f"{speaker}: {text}", max_chars=28)[:2]
    if not lines:
        return
    max_line_w = max(measure_text_width(line) for line in lines)
    box_w = max(60, max_line_w + 12)
    box_h = len(lines) * 10 + 10
    bx = max(MAP_X0 + 4, min(MAP_X0 + 40 * DEMO_TILE_PX - box_w - 4, anchor_x - box_w // 2))
    by = max(MAP_Y0 + 4, anchor_y - box_h - 14)

    canvas.fill_rect(bx, by, box_w, box_h, (15, 23, 42, 242))
    canvas.stroke_rect(bx, by, box_w, box_h, (56, 189, 248, 255), thickness=1)
    for idx, line in enumerate(lines):
        canvas.draw_text(bx + 6, by + 5 + idx * 10, line, (248, 250, 252, 255))


def generate_demo_gif(
    output_path: Path,
    *,
    replay_jsonl: Path | None = None,
    seed: int = 42,
) -> int:
    """Render an animated palette-optimized GIF of live village ticks, dialogues, and events."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        raise RuntimeError("ffmpeg binary is required on PATH to encode docs/demo.gif")

    map_w, map_h, tileset_cols, ground, structures, locations, tileset, sprites = (
        _load_map_assets()
    )
    backdrop = _build_map_backdrop(
        map_w,
        map_h,
        tileset_cols,
        ground,
        structures,
        locations,
        tileset,
    )
    location_by_name = {loc.name.lower(): loc for loc in locations}
    frames = _collect_demo_frames(replay_jsonl=replay_jsonl, seed=seed)

    # Group frames by tick while maintaining chronological event feed history.
    tick_frames: list[dict[str, Any]] = []
    events_by_tick: dict[int, list[dict[str, Any]]] = {}
    for frame in frames:
        ftype = str(frame.get("type", ""))
        tick_val = int(frame.get("tick", 0))
        if ftype == "tick":
            tick_frames.append(frame)
        else:
            events_by_tick.setdefault(tick_val, []).append(frame)

    if not tick_frames:
        raise RuntimeError("No tick frames available for demo.gif generation")

    # Select an 80-tick window centered around the first god-mode event if present.
    event_ticks = [
        tick
        for tick, items in sorted(events_by_tick.items())
        if any(item.get("type") == "event" for item in items)
    ]
    start_tick = max(0, event_ticks[0] - 18) if event_ticks else 0
    end_tick = start_tick + 79

    feed_history: deque[FeedCard] = deque(maxlen=10)
    prev_coords: dict[str, tuple[int, int]] = {}
    active_bubble: tuple[int, str, str, str] | None = None  # (until_tick, speaker_id, name, txt)
    active_event: tuple[int, int, int, int] | None = None  # (start_tick, until_tick, loc_x, loc_y)
    active_event_banner = ""
    god_mode_prompt = "Waiting for god-mode event..."

    selected_ticks = [t for t in tick_frames if int(t["tick"]) <= end_tick]
    rendered_count = 0

    with tempfile.TemporaryDirectory(prefix="ai_village_gif_") as tmp_dir_str:
        frame_dir = Path(tmp_dir_str)
        for tick_frame in selected_ticks:
            tick_num = int(tick_frame["tick"])
            sim_time = str(tick_frame.get("sim_time", f"Tick {tick_num}"))

            for ev in events_by_tick.get(tick_num, []):
                etype = str(ev.get("type", ""))
                if etype == "event":
                    ev_loc = str(ev.get("location") or "Village")
                    ev_text = str(ev.get("text", ""))
                    affected = ev.get("affected_agents", [])
                    aff_count = len(affected) if isinstance(affected, list) else 0
                    feed_history.appendleft(
                        FeedCard(
                            kind="event",
                            badge="EVENT",
                            meta=f"{sim_time} @ {ev_loc}",
                            subject="",
                            body=f"{ev_text} ({aff_count} alerted)",
                        )
                    )
                    loc_obj = location_by_name.get(ev_loc.lower())
                    if loc_obj is not None:
                        px = MAP_X0 + loc_obj.anchor_x * DEMO_TILE_PX + DEMO_TILE_PX // 2
                        py = MAP_Y0 + loc_obj.anchor_y * DEMO_TILE_PX + DEMO_TILE_PX // 2
                    else:
                        px = MAP_X0 + (map_w * DEMO_TILE_PX) // 2
                        py = MAP_Y0 + (map_h * DEMO_TILE_PX) // 2
                    active_event = (tick_num, tick_num + 16, px, py)
                    active_event_banner = f"[{ev_loc}] {ev_text[:48]}"
                    god_mode_prompt = f"[{ev_loc}] {ev_text}"
                elif etype == "dialogue":
                    names = ev.get("participant_names", [])
                    pair_label = " & ".join(str(n) for n in names[:2]) if names else "Dialogue"
                    turns = ev.get("turns", [])
                    summary = str(ev.get("summary", ""))
                    if isinstance(turns, list) and turns and isinstance(turns[0], dict):
                        t0 = turns[0]
                        active_bubble = (
                            tick_num + 8,
                            str(t0.get("speaker_id", "")),
                            str(t0.get("speaker_name", "")),
                            str(t0.get("text", "")),
                        )
                    feed_history.appendleft(
                        FeedCard(
                            kind="dialogue",
                            badge="CHAT",
                            meta=f"{sim_time} @ {ev.get('location') or 'Village'}",
                            subject=pair_label,
                            body=summary,
                        )
                    )
                elif etype == "reflection":
                    feed_history.appendleft(
                        FeedCard(
                            kind="reflection",
                            badge="REFLECT",
                            meta=f"{sim_time} - {ev.get('agent_name', '')}",
                            subject="",
                            body=str(ev.get("insight", "")),
                        )
                    )

            agents = tick_frame.get("agents", [])
            if not isinstance(agents, list):
                continue

            if tick_num < start_tick:
                for agent in agents:
                    if isinstance(agent, dict):
                        prev_coords[str(agent["id"])] = (int(agent["x"]), int(agent["y"]))
                continue

            frame_canvas = backdrop.clone()

            # HUD time + tick
            clock_label = f"{sim_time}  |  16x"
            frame_canvas.draw_text(216, 19, clock_label, (226, 232, 240, 255), scale=1)
            tick_badge = f"Tick {tick_num:04d}"
            frame_canvas.fill_rect(410, 13, 86, 20, (15, 23, 42, 255))
            frame_canvas.stroke_rect(410, 13, 86, 20, (51, 65, 85, 255), thickness=1)
            frame_canvas.draw_text(418, 19, tick_badge, (125, 211, 252, 255), scale=1)
            frame_canvas.draw_text(
                676,
                19,
                "8 AGENTS  |  A* + MEMORY + LLM",
                (148, 163, 184, 255),
                scale=1,
            )

            # Agents (sorted by y for clean top-down overlap)
            agent_screen_pos: dict[str, tuple[int, int]] = {}
            sorted_agents = sorted(
                (a for a in agents if isinstance(a, dict)),
                key=lambda item: (int(item["y"]), str(item["id"])),
            )
            for agent in sorted_agents:
                aid = str(agent["id"])
                ax = int(agent["x"])
                ay = int(agent["y"])
                moved = prev_coords.get(aid) != (ax, ay)
                prev_coords[aid] = (ax, ay)

                sprite_idx = max(0, int(agent.get("sprite_index", 0))) % 8
                pose = (tick_num % 4) if moved else 0
                sx = pose * 32
                sy = sprite_idx * 32
                dx = MAP_X0 + ax * DEMO_TILE_PX
                dy = MAP_Y0 + ay * DEMO_TILE_PX
                agent_screen_pos[aid] = (dx + DEMO_TILE_PX // 2, dy + DEMO_TILE_PX // 2)

                if aid == "maya":
                    frame_canvas.draw_ring(
                        dx + DEMO_TILE_PX // 2,
                        dy + DEMO_TILE_PX // 2 + 2,
                        10,
                        2,
                        (56, 189, 248, 230),
                        fill_color=(56, 189, 248, 35),
                    )

                frame_canvas.blit_scaled_nearest(
                    sprites,
                    sx,
                    sy,
                    32,
                    32,
                    dx,
                    dy,
                    DEMO_TILE_PX,
                    DEMO_TILE_PX,
                )
                name_str = str(agent.get("name", aid))
                nw = measure_text_width(name_str) + 4
                nx = max(MAP_X0 + 1, dx + DEMO_TILE_PX // 2 - nw // 2)
                ny = max(MAP_Y0 + 1, dy - 10)
                frame_canvas.fill_rect(nx, ny, nw, 9, (15, 23, 42, 210))
                frame_canvas.draw_text(nx + 2, ny + 1, name_str, (248, 250, 252, 255))

            # Active god-mode event pulse ring + banner
            if active_event is not None and tick_num <= active_event[1]:
                ev_start, _ev_end, px, py = active_event
                age = tick_num - ev_start
                radius = 12 + age * 4
                alpha = max(60, 245 - age * 12)
                frame_canvas.draw_ring(
                    px,
                    py,
                    radius,
                    3,
                    (245, 158, 11, alpha),
                    fill_color=(245, 158, 11, max(20, alpha // 5)),
                )
                if age >= 2:
                    frame_canvas.draw_ring(
                        px,
                        py,
                        max(8, radius - 10),
                        2,
                        (239, 68, 68, max(50, alpha - 30)),
                    )
                bw = measure_text_width(active_event_banner) + 12
                bx = max(MAP_X0 + 4, min(MAP_X0 + map_w * DEMO_TILE_PX - bw - 4, px - bw // 2))
                by = max(MAP_Y0 + 6, py - 26)
                frame_canvas.fill_rect(bx, by, bw, 15, (120, 53, 15, 235))
                frame_canvas.stroke_rect(bx, by, bw, 15, (251, 191, 36, 255), thickness=1)
                frame_canvas.draw_text(bx + 6, by + 4, active_event_banner, (254, 243, 199, 255))

            # Active dialogue speech bubble
            if active_bubble is not None and tick_num <= active_bubble[0]:
                _until, spk_id, spk_name, spk_text = active_bubble
                pos = agent_screen_pos.get(spk_id)
                if pos is not None:
                    _draw_speech_bubble(
                        frame_canvas,
                        anchor_x=pos[0],
                        anchor_y=pos[1],
                        speaker=spk_name,
                        text=spk_text,
                    )

            # Right activity feed + god-mode footer text
            _draw_feed_cards(frame_canvas, list(feed_history))
            frame_canvas.draw_text(24, 590, god_mode_prompt[:112], (254, 243, 199, 255), scale=1)

            frame_path = frame_dir / f"frame_{rendered_count:04d}.png"
            write_png(frame_path, DEMO_WIDTH, DEMO_HEIGHT, frame_canvas.data)
            rendered_count += 1

        if rendered_count < 10:
            raise RuntimeError(f"Expected >= 10 rendered demo frames, got {rendered_count}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        palette_filter = (
            "split[s0][s1];"
            "[s0]palettegen=max_colors=128:stats_mode=diff[p];"
            "[s1][p]paletteuse=dither=bayer:bayer_scale=3"
        )
        cmd = [
            ffmpeg_bin,
            "-y",
            "-framerate",
            "8",
            "-i",
            str(frame_dir / "frame_%04d.png"),
            "-vf",
            palette_filter,
            "-loop",
            "0",
            str(output_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr}")

    return rendered_count


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic docs/architecture.png and docs/demo.gif assets."
    )
    parser.add_argument(
        "--arch-out",
        type=Path,
        default=DOCS_DIR / "architecture.png",
        help="Output path for the architecture diagram PNG.",
    )
    parser.add_argument(
        "--gif-out",
        type=Path,
        default=DOCS_DIR / "demo.gif",
        help="Output path for the animated demo GIF.",
    )
    parser.add_argument(
        "--replay-jsonl",
        type=Path,
        default=None,
        help="Optional existing day_1.jsonl replay log to render instead of running sim.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic simulation seed when running in-process demo snippet.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    args = _parse_args(argv)
    arch_mode = generate_architecture_png(args.arch_out)
    gif_frames = generate_demo_gif(
        args.gif_out,
        replay_jsonl=args.replay_jsonl,
        seed=args.seed,
    )
    print(
        f"Generated {args.arch_out} ({args.arch_out.stat().st_size} bytes, {arch_mode}) "
        f"and {args.gif_out} ({args.gif_out.stat().st_size} bytes, {gif_frames} frames)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
