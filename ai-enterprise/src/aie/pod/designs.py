"""Egna designer som PNG, med bara standardbiblioteket (arbetsorder 04, D-067).

Printify tar PNG och JPEG men nämner inte SVG. Standardbiblioteket kan skriva PNG (`zlib`) men inte JPEG.
Därför görs alla tryckfiler som PNG med transparent bakgrund.

Två sorters motiv, båda gjorda av systemet självt, utan typsnitt eller bilder från någon annan:
- **Typografi** med en egen pixelfont (`FONT`, 5 × 7 punkter). Varje punkt skalas upp till ett block, så
  texten är skarp i alla storlekar.
- **Mönster** som räknas fram geometriskt: snökristaller, rutor och ränder.

`render_text` och `render_pattern` ger en bild (`Image`). `write_png` sparar den. Storleken väljs efter
produktens tryckyta; Printifys katalog anger den i pixlar (`placeholders`).
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

# 5 × 7-font: varje tecken är sju rader med fem bitar (1 = punkt). Egen ritning för det här projektet.
FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10011", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10011", "10101", "10101", "10101", "11001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    " ": ("00000",) * 7,
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ",": ("00000", "00000", "00000", "00000", "01100", "00100", "01000"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    "'": ("00100", "00100", "01000", "00000", "00000", "00000", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "&": ("01100", "10010", "10100", "01000", "10101", "10010", "01101"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "*": ("00000", "10101", "01110", "11111", "01110", "10101", "00000"),
    "#": ("01010", "01010", "11111", "01010", "11111", "01010", "01010"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
}
GLYPH_W, GLYPH_H = 5, 7


@dataclass
class Image:
    width: int
    height: int
    rows: list[bytearray]  # RGBA, en bytearray per rad


def blank(width: int, height: int) -> Image:
    return Image(width, height, [bytearray(width * 4) for _ in range(height)])


def unsupported(text: str) -> set[str]:
    return {c for c in text.upper() if c not in FONT and c != "\n"}


def _hex(color: str) -> bytes:
    color = color.lstrip("#")
    return bytes(int(color[i:i + 2], 16) for i in (0, 2, 4)) + b"\xff"


def render_text(text: str, width: int, height: int, color: str = "#1f2d2a", margin: float = 0.08,
                line_gap: float = 0.6) -> Image:
    """Texten centrerad, en rad per rad i `text`, med så stora block som får plats."""
    lines = [line.strip().upper() for line in text.split("\n") if line.strip()]
    if not lines:
        raise ValueError("ingen text")
    missing = unsupported(text)
    if missing:
        raise ValueError(f"fonten saknar tecknen {''.join(sorted(missing))}")
    cols = max(len(line) for line in lines) * (GLYPH_W + 1) - 1
    rows = len(lines) * GLYPH_H + (len(lines) - 1) * line_gap * GLYPH_H
    usable_w, usable_h = width * (1 - 2 * margin), height * (1 - 2 * margin)
    block = int(min(usable_w / cols, usable_h / rows))
    if block < 1:
        raise ValueError("texten får inte plats i den här storleken")
    img = blank(width, height)
    pixel = _hex(color)
    total_h = int(rows * block)
    y0 = (height - total_h) // 2
    for n, line in enumerate(lines):
        line_w = (len(line) * (GLYPH_W + 1) - 1) * block
        x0 = (width - line_w) // 2
        top = y0 + int(n * (GLYPH_H + line_gap * GLYPH_H) * block)
        for gy in range(GLYPH_H):
            run = bytearray(width * 4)
            for ci, char in enumerate(line):
                bits = FONT[char][gy]
                for gx, bit in enumerate(bits):
                    if bit == "1":
                        x = x0 + (ci * (GLYPH_W + 1) + gx) * block
                        run[x * 4:(x + block) * 4] = pixel * block
            for y in range(top + gy * block, top + (gy + 1) * block):
                img.rows[y][:] = run
    return img


def render_pattern(kind: str, width: int, height: int, colors: tuple[str, str] = ("#1f3a5f", "#f4f1e8"),
                   cell: int | None = None) -> Image:
    """Ett mönster som täcker hela ytan: `snowflake`, `check` eller `stripes`."""
    fg, bg = _hex(colors[0]), _hex(colors[1])
    cell = cell or max(8, width // 24)
    img = blank(width, height)
    if kind == "stripes":
        for y in range(height):
            img.rows[y][:] = (fg if (y // cell) % 2 == 0 else bg) * width
        return img
    if kind == "check":
        a = b"".join((fg if (x // cell) % 2 == 0 else bg) for x in range(0, width, 1))
        b = b"".join((bg if (x // cell) % 2 == 0 else fg) for x in range(0, width, 1))
        for y in range(height):
            img.rows[y][:] = a if (y // cell) % 2 == 0 else b
        return img
    if kind == "snowflake":
        # En egen snökristall i ett rutnät på 9 × 9 punkter, upprepad med förskjutning.
        flake = ("000010000", "010010010", "001010100", "000111000", "111111111",
                 "000111000", "001010100", "010010010", "000010000")
        dot = max(2, cell // 6)
        tile = 9 * dot + 3 * dot
        for y in range(height):
            ty = y % (2 * tile)
            shift = tile // 2 if ty >= tile else 0
            fy = (ty % tile) // dot
            row = bytearray(bg * width)
            if fy < 9:
                bits = flake[fy]
                for x0 in range(-tile, width, tile):
                    for fx, bit in enumerate(bits):
                        if bit == "1":
                            x = x0 + shift + fx * dot
                            lo, hi = max(0, x), min(width, x + dot)
                            if lo < hi:
                                row[lo * 4:hi * 4] = fg * (hi - lo)
            img.rows[y][:] = row
        return img
    raise ValueError(f"okänt mönster {kind!r}")


def write_png(img: Image, path: Path | str, dpi: int = 300) -> Path:
    """PNG med alfa och upplösning (pHYs) satt till `dpi`."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(r) for r in img.rows)
    ppm = round(dpi / 0.0254)
    data = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0))
            + chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def read_png_size(path: Path | str) -> tuple[int, int]:
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("inte en PNG")
    return struct.unpack(">II", data[16:24])
