"""Card do post: capas originais, logos de loja opcionais sob cada capa, logo no canto."""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image

logger = logging.getLogger(__name__)

_LOGO = Path(__file__).resolve().parent / "assets" / "black_livros.jpg"
_BEIGE = (245, 241, 232, 255)
_ASSETS = Path(__file__).resolve().parent / "assets"
_STORE_LOGOS = {
    "amazon": _ASSETS / "store_amazon.webp",
    "ml": _ASSETS / "store_ml.png",
    "shopee": _ASSETS / "store_shopee.webp",
    "magalu": _ASSETS / "store_magalu.png",
}
_STORE_SCALE = 0.55
_MAGALU_SCALE = _STORE_SCALE * 0.85
_MAGALU_EXTRA_DOWN = 12
_STORE_GAP = 10
# Faixa reservada sob as capas quando há logos (gap + altura típica + folga Magalu).
_STORE_STRIP = _STORE_GAP + 56 + _MAGALU_EXTRA_DOWN


_RETRY_STATUS = {403, 429, 500, 502, 503, 504}
_RETRY_DELAYS = (1.0, 3.0)
# O CDN da Magalu recusa rajadas sem Referer da loja com 403 intermitente.
_REFERERS = {"mlcdn.com.br": "https://www.magazineluiza.com.br/"}


def download_image(url: str, timeout: float = 20, *, sleep=time.sleep, get=requests.get) -> Image.Image:
    headers = {"User-Agent": "promo-livros/1.0"}
    host = (urlsplit(url).hostname or "").lower()
    referer = next((value for marker, value in _REFERERS.items() if host.endswith(marker)), "")
    if referer:
        headers["Referer"] = referer
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        response = get(url, timeout=timeout, headers=headers)
        if response.status_code not in _RETRY_STATUS:
            break
        logger.info("Capa recusada (%s) na tentativa %s: %s", response.status_code, attempt, host)
        sleep(delay)
    else:
        response = get(url, timeout=timeout, headers=headers)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def _prepare_store_logo(path: Path, max_w: int, *, store: str) -> Image.Image:
    source = Image.open(path).convert("RGBA")
    pixels = source.load()
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue, _alpha = pixels[x, y]
            if store == "amazon":
                is_orange = red > 180 and 70 < green < 170 and blue < 90
                is_ink = max(red, green, blue) < 70
                if not (is_orange or is_ink):
                    pixels[x, y] = (0, 0, 0, 0)
            elif red <= 28 and green <= 28 and blue <= 28:
                pixels[x, y] = (0, 0, 0, 0)
    box = source.getbbox()
    if box:
        source = source.crop(box)
    source.thumbnail((max_w, max_w), Image.Resampling.LANCZOS)
    return source


@lru_cache(maxsize=len(_STORE_LOGOS))
def store_logo_png(store: str, width: int = 120) -> bytes | None:
    """Logo da loja já recortada e com fundo transparente, para o painel."""
    path = _STORE_LOGOS.get(store)
    if path is None or not path.is_file():
        return None
    buffer = BytesIO()
    _prepare_store_logo(path, max_w=width, store=store).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def _store_marks(fitted: list[Image.Image], stores: list[str]) -> list[Image.Image | None]:
    marks: list[Image.Image | None] = []
    for image, store in zip(fitted, stores):
        path = _STORE_LOGOS.get(store)
        if path is None or not path.is_file():
            marks.append(None)
            continue
        scale = _MAGALU_SCALE if store == "magalu" else _STORE_SCALE
        marks.append(_prepare_store_logo(path, max_w=int(image.width * scale), store=store))
    return marks


def render_card(
    covers: list[Image.Image],
    destination: Path,
    *,
    stores: list[str] | None = None,
    logo_path: Path | None = None,
) -> None:
    if not covers or len(covers) > 3:
        raise ValueError("O card leva de 1 a 3 capas.")
    side = 280 if len(covers) < 3 else 240
    fitted = [_fit(cover.convert("RGB"), side) for cover in covers]
    use_stores = stores is not None and len(stores) == len(fitted)
    marks = _store_marks(fitted, stores) if use_stores else []
    gap, margin, band = 24, 28, 78
    cover_h = max(image.height for image in fitted)
    mark_h = 0
    if marks:
        mark_h = max(
            (mark.height + (_MAGALU_EXTRA_DOWN if store == "magalu" else 0))
            for mark, store in zip(marks, stores)
            if mark is not None
        ) if any(mark is not None for mark in marks) else 0
    store_band = (_STORE_GAP + mark_h) if mark_h else 0
    row_w = sum(image.width for image in fitted) + gap * (len(fitted) - 1)
    width = max(margin * 2 + row_w, 520)
    if store_band:
        height = margin + cover_h + store_band + band
    else:
        height = cover_h + margin * 2 + band
    canvas = Image.new("RGBA", (width, height), _BEIGE)
    cursor = (width - row_w) // 2
    for index, image in enumerate(fitted):
        top = margin + (cover_h - image.height) // 2
        canvas.paste(image.convert("RGBA"), (cursor, top))
        if store_band and index < len(marks) and marks[index] is not None:
            mark = marks[index]
            down = _MAGALU_EXTRA_DOWN if stores[index] == "magalu" else 0
            mx = cursor + (image.width - mark.width) // 2
            my = margin + cover_h + _STORE_GAP + down
            canvas.alpha_composite(mark, (mx, my))
        cursor += image.width + gap
    brand = _logo(logo_path or _LOGO, 92 if len(fitted) == 1 else 100)
    canvas.alpha_composite(brand, (canvas.width - brand.width - 18, canvas.height - brand.height - 10))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(destination, "JPEG", quality=68, optimize=True)


def _fit(image: Image.Image, side: int) -> Image.Image:
    # Amplia também: há lojas que só devolvem miniatura, e ela sumiria ao lado de uma capa cheia.
    scale = side / max(image.width, image.height)
    if scale == 1:
        return image
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def extract_covers(card: Path, count: int) -> list[Image.Image] | None:
    """Recorta as capas de um card já feito por `render_card`.

    A Shopee não guarda a foto do anúncio; o card é a única cópia da capa. As capas ficam
    lado a lado sobre o bege, com 24 px entre elas, acima da faixa da logo. Cards novos
    ainda têm logos de loja sob as capas — essa faixa é excluída. Se o recorte não achar
    exatamente `count` capas, devolve None.
    """
    if count < 1 or not card.is_file():
        return None
    margin, band, gap = 28, 78, 24
    with Image.open(card) as source:
        image = source.convert("RGB")
    # As capas cabem num quadrado de `side`; abaixo dele começam as logos das lojas (cards novos) ou a margem (antigos).
    side = 280 if count < 3 else 240
    old_bottom = image.height - band - margin
    for bottom in (min(margin + side, image.height - band), old_bottom, image.height - band - _STORE_STRIP):
        found = _covers_in_band(image, margin, bottom, gap, count)
        if found is not None:
            return found
    return None


def _covers_in_band(
    image: Image.Image, top: int, bottom: int, gap: int, count: int
) -> list[Image.Image] | None:
    from PIL import ImageChops

    if bottom - top < 40:
        return None
    area = image.crop((0, top, image.width, bottom))
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