"""Small pictures drawn in pure Python: the app icon and the table checkboxes.

Pillow is not a dependency (the exe stays small), so shapes are rasterised here
with 3x3 supersampling for smooth edges and written out as PNG with zlib.
Everything is described in unit coordinates (0..1), so any size can be made.
"""
from __future__ import annotations

import struct
import zlib
from typing import Callable

Shader = Callable[[float, float], "tuple[int, int, int, float] | None"]

SUPERSAMPLE = 3
INDIGO_TOP = (99, 102, 241)
INDIGO_BOTTOM = (67, 56, 202)
RIBBON = [(0.33, 0.15), (0.67, 0.15), (0.67, 0.82), (0.50, 0.66), (0.33, 0.82)]
CHECK_MARK = [(0.26, 0.52), (0.44, 0.70), (0.76, 0.32)]


def hex_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


# ----------------------------------------------------------------- geometry
def _in_round_rect(x: float, y: float, x1: float, y1: float, x2: float, y2: float, r: float) -> bool:
    if x < x1 or x > x2 or y < y1 or y > y2:
        return False
    cx = min(max(x, x1 + r), x2 - r)
    cy = min(max(y, y1 + r), y2 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _in_polygon(x: float, y: float, points: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(points) - 1
    for i in range(len(points)):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _near_polyline(x: float, y: float, points: list[tuple[float, float]], half_width: float) -> bool:
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length2))
        px, py = ax + t * dx, ay + t * dy
        if (x - px) ** 2 + (y - py) ** 2 <= half_width * half_width:
            return True
    return False


# ------------------------------------------------------------------ output
def png_bytes(width: int, height: int, rgba: bytearray) -> bytes:
    stride = width * 4
    raw = bytearray()
    for row in range(height):
        raw.append(0)                                  # filter type: none
        raw += rgba[row * stride:(row + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def rasterize(size: int, shader: Shader, width: int | None = None) -> bytes:
    """Draw `shader` into an RGBA PNG `size` tall and `width` wide (default square).
    Coordinates are in units of the height, so a wider image just has empty room to the right.
    The shader returns (r, g, b, alpha 0..1) or None."""
    width = width or size
    pixels = bytearray(width * size * 4)
    samples = SUPERSAMPLE * SUPERSAMPLE
    for j in range(size):
        for i in range(width):
            red = green = blue = alpha = 0.0
            for sj in range(SUPERSAMPLE):
                for si in range(SUPERSAMPLE):
                    colour = shader((i + (si + 0.5) / SUPERSAMPLE) / size, (j + (sj + 0.5) / SUPERSAMPLE) / size)
                    if colour is None:
                        continue
                    r, g, b, a = colour
                    red += r * a
                    green += g * a
                    blue += b * a
                    alpha += a
            if alpha > 0:
                o = (j * width + i) * 4
                pixels[o] = round(red / alpha)
                pixels[o + 1] = round(green / alpha)
                pixels[o + 2] = round(blue / alpha)
                pixels[o + 3] = round(255 * alpha / samples)
    return png_bytes(width, size, pixels)


# ------------------------------------------------------------------ shapes
def app_icon_shader(x: float, y: float):
    """A rounded indigo tile with a white bookmark ribbon."""
    if not _in_round_rect(x, y, 0.03, 0.03, 0.97, 0.97, 0.23):
        return None
    if _in_polygon(x, y, RIBBON):
        return 255, 255, 255, 1.0
    mix = min(1.0, max(0.0, y))
    top, bottom = INDIGO_TOP, INDIGO_BOTTOM
    return (round(top[0] + (bottom[0] - top[0]) * mix), round(top[1] + (bottom[1] - top[1]) * mix),
            round(top[2] + (bottom[2] - top[2]) * mix), 1.0)


def checkbox_shader(checked: bool, accent: str, border: str) -> Shader:
    accent_rgb, border_rgb = hex_rgb(accent), hex_rgb(border)
    margin, radius, ring = 0.05, 0.24, 0.085

    def shader(x: float, y: float):
        if not _in_round_rect(x, y, margin, margin, 1 - margin, 1 - margin, radius):
            return None
        if checked:
            if _near_polyline(x, y, CHECK_MARK, 0.075):
                return 255, 255, 255, 1.0
            return (*accent_rgb, 1.0)
        inner = margin + ring
        if not _in_round_rect(x, y, inner, inner, 1 - inner, 1 - inner, max(radius - ring, 0.05)):
            return (*border_rgb, 1.0)
        return 255, 255, 255, 1.0

    return shader


def render_app_icon(size: int) -> bytes:
    return rasterize(size, app_icon_shader)


def render_checkbox(size: int, checked: bool, accent: str, border: str, gap: int = 0) -> bytes:
    """A checkbox `size` px square, plus `gap` transparent pixels on its right (room before a label)."""
    return rasterize(size, checkbox_shader(checked, accent, border), width=size + gap)


def ico_bytes(sizes: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)) -> bytes:
    """A Windows .ico holding one PNG per size (supported since Vista)."""
    images = [render_app_icon(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for size, data in zip(sizes, images):
        edge = size if size < 256 else 0
        entries += struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return header + entries + b"".join(images)
