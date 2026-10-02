"""Card do post: capas originais, só reduzidas, e a logo no canto."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

_LOGO = Path(__file__).resolve().parent / "assets" / "black_livros.jpg"
_BEIGE = (245, 241, 232, 255)


def download_image(url: str, timeout: float = 20) -> Image.Image:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "promo-livros/1.0"})
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def render_card(covers: list[Image.Image], destination: Path, *, logo_path: Path | None = None) -> None:
    if not covers or len(covers) > 3:
        raise ValueError("O card leva de 1 a 3 capas.")
    side = 280 if len(covers) < 3 else 240
    fitted = []
    for cover in covers:
        image = cover.convert("RGB")
        image.thumbnail((side, side), Image.Resampling.LANCZOS)
        fitted.append(image)
    gap, margin, band = 24, 28, 78
    cover_h = max(image.height for image in fitted)
    row_w = sum(image.width for image in fitted) + gap * (len(fitted) - 1)
    width = max(margin * 2 + row_w, 520)
    canvas = Image.new("RGBA", (width, cover_h + margin * 2 + band), _BEIGE)
    cursor = (width - row_w) // 2
    for image in fitted:
        top = margin + (cover_h - image.height) // 2
        canvas.paste(image.convert("RGBA"), (cursor, top))
        cursor += image.width + gap
    mark = _logo(logo_path or _LOGO, 92 if len(fitted) == 1 else 100)
    canvas.alpha_composite(mark, (canvas.width - mark.width - 18, canvas.height - mark.height - 10))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(destination, "JPEG", quality=68, optimize=True)


def _logo(path: Path, max_side: int) -> Image.Image:
    source = Image.open(path).convert("RGBA")
    stamped = Image.new("RGBA", source.size)
    src, dst = source.load(), stamped.load()
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue, _alpha = src[x, y]
            ink = 255 - max(red, green, blue)
            dst[x, y] = (20, 20, 20, int(ink * 0.72))
    cropped = stamped.crop(stamped.getbbox())
    cropped.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return cropped
