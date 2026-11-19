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


def extract_covers(card: Path, count: int) -> list[Image.Image] | None:
    """Recorta as capas de um card já feito por `render_card`.

    A Shopee não guarda a foto do anúncio; o card é a única cópia da capa. As capas ficam
    lado a lado sobre o bege, com 24 px entre elas, acima da faixa da logo. Se o recorte
    não achar exatamente `count` capas, devolve None e quem chamou busca as capas de outro jeito.
    """
    from PIL import ImageChops

    if count < 1 or not card.is_file():
        return None
    margin, band, gap = 28, 78, 24
    with Image.open(card) as source:
        image = source.convert("RGB")
    top, bottom = margin, image.height - band - margin
    if bottom - top < 40:
        return None
    area = image.crop((0, top, image.width, bottom))
    # Diferença para o bege; o JPEG deixa ruído, por isso o limiar.
    diff = ImageChops.difference(area, Image.new("RGB", area.size, _BEIGE[:3])).convert("L")
    mask = diff.point(lambda value: 255 if value > 24 else 0)
    columns = mask.resize((mask.width, 1), Image.Resampling.BOX)
    filled = [columns.getpixel((x, 0)) > 6 for x in range(columns.width)]
    runs: list[list[int]] = []
    for x, on in enumerate(filled):
        if not on:
            continue
        if runs and x - runs[-1][1] < gap // 2:
            runs[-1][1] = x
        else:
            runs.append([x, x])
    runs = [run for run in runs if run[1] - run[0] >= 20]
    if len(runs) != count:
        return None
    covers = []
    for left, right in runs:
        strip = mask.crop((left, 0, right + 1, mask.height))
        profile = strip.resize((1, strip.height), Image.Resampling.BOX)
        rows = [profile.getpixel((0, y)) > 6 for y in range(profile.height)]
        first = next((y for y, on in enumerate(rows) if on), None)
        last = next((y for y in range(len(rows) - 1, -1, -1) if rows[y]), None)
        if first is None or last is None or last - first < 20:
            return None
        covers.append(image.crop((left, top + first, right + 1, top + last + 1)))
    return covers


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
