"""Typografiska designer med Pillow (D-070 punkt 8: Pillow, licens HPND, är tillåtet bara här).

`render(spec, size)` ritar en design på en transparent bakgrund och sparar den som PNG med 300 dpi.
Printify tar PNG och JPEG men nämner inte SVG. Varje rad skalas till tryckytans bredd, med marginal.

Typsnitten finns i `assets/fonts/`. Alla har SIL Open Font License, och licensen ligger bredvid varje fil.
Arabisk text formas i `arabic.shape`, eftersom raqm saknas i många miljöer.

Resten av systemet använder bara standardbiblioteket. Importera därför bara den här modulen där designer ritas.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .arabic import is_arabic, shape

FONT_DIR = Path(__file__).resolve().parents[4] / "assets" / "fonts"
FONTS = {
    "bebas": "bebasneue/BebasNeue-Regular.ttf",
    "archivo": "archivoblack/ArchivoBlack-Regular.ttf",
    "abril": "abrilfatface/AbrilFatface-Regular.ttf",
    "pacifico": "pacifico/Pacifico-Regular.ttf",
    "amiri": "amiri/Amiri-Bold.ttf",
}
DPI = 300


def font_path(key: str) -> Path:
    path = FONT_DIR / FONTS[key]
    if not (path.parent / "OFL.txt").is_file():
        raise FileNotFoundError(f"licensen saknas för {key}: varje typsnitt ska ha OFL.txt bredvid sig")
    return path


def _fit(text: str, font_key: str, max_w: int, max_h: int) -> ImageFont.FreeTypeFont:
    lo, hi = 10, max_h
    best = ImageFont.truetype(str(font_path(font_key)), lo)
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(str(font_path(font_key)), mid)
        left, top, right, bottom = f.getbbox(text)
        if right - left <= max_w and bottom - top <= max_h:
            best, lo = f, mid + 1
        else:
            hi = mid - 1
    return best


def render(spec: dict, size: tuple[int, int], out: Path | str) -> Path:
    """`spec`: {"lines": [...], "fonts": [...] (ett per rad eller ett för alla), "color": "#rrggbb",
    "weights": [...] (andel av höjden per rad, valfritt), "width_ratio": andel av bredden som texten får ta
    (standard 0,88; en mugg använder mindre så att texten inte går runt handtaget)}."""
    width, height = size
    lines = [shape(line) if is_arabic(line) else line for line in spec["lines"]]
    fonts = spec.get("fonts") or [spec.get("font", "bebas")]
    fonts = fonts if len(fonts) == len(lines) else [fonts[0]] * len(lines)
    weights = spec.get("weights") or [1] * len(lines)
    margin_x = int(width * (1 - spec.get("width_ratio", 0.88)) / 2)
    margin_y, gap = int(height * 0.08), int(height * 0.03)
    usable_h = height - 2 * margin_y - gap * (len(lines) - 1)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rendered = []
    for line, font_key, w in zip(lines, fonts, weights):
        max_h = int(usable_h * w / sum(weights))
        f = _fit(line, font_key, width - 2 * margin_x, max_h)
        left, top, right, bottom = f.getbbox(line)
        rendered.append((line, f, (left, top, right, bottom)))
    total = sum(b[3] - b[1] for _, _, b in rendered) + gap * (len(rendered) - 1)
    y = (height - total) // 2
    for line, f, (left, top, right, bottom) in rendered:
        x = (width - (right - left)) // 2 - left
        draw.text((x, y - top), line, font=f, fill=spec.get("color", "#1f2d2a"))
        y += bottom - top + gap
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", dpi=(DPI, DPI), optimize=True)
    return out


def preview(png: Path | str, out: Path | str, width: int = 600, background: str = "#f4f1e8") -> Path:
    """En liten förhandsvisning på ljus bakgrund, för LISTA.md."""
    src = Image.open(png)
    h = round(width * src.height / src.width)
    small = src.resize((width, h), Image.LANCZOS)
    canvas = Image.new("RGB", (width, h), background)
    canvas.paste(small, (0, 0), small)
    out = Path(out)
    canvas.save(out, "PNG", optimize=True)
    return out


# Standardmått (300 dpi) när Printifys tryckyta inte är hämtad via API:t.
SIZES = {"tee": (4500, 5400), "hoodie": (4500, 5400), "mug": (2700, 1050), "poster": (5400, 7200)}


def save(design: dict, folder: Path | str) -> tuple[Path, Path]:
    """`<mapp>/design.png` för designens första produkttyp och `<mapp>/meta.json` med tema, text och produkttyp.

    `design`: en post ur `products/q4/designs.toml` (key, lines, font, color, products, title)."""
    import json

    folder = Path(folder)
    product = design["products"][0]
    spec = {"lines": design["lines"], "fonts": [design["font"]], "color": design["color"]}
    if product == "mug":
        spec["width_ratio"] = 0.45  # muggens tryck går runt; texten bara på framsidan
    png = render(spec, SIZES[product], folder / "design.png")
    meta = {"key": design["key"], "theme": design.get("theme", design["title"].split(",")[0]),
            "text": "\n".join(design["lines"]), "product_type": product, "products": design["products"],
            "font": FONTS[design["font"]], "font_license": "SIL Open Font License 1.1 (assets/fonts/)",
            "size_px": list(SIZES[product]), "dpi": DPI, "background": "transparent"}
    meta_path = folder / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return png, meta_path
