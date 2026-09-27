from __future__ import annotations

import re
from urllib.parse import urlencode

from promo_livros.models import Deal, RenderedMessage

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_TITLE_LIMIT = 300


def render_deal(deal: Deal, affiliate_tag: str) -> RenderedMessage:
    title = deal.title if len(deal.title) <= _TITLE_LIMIT else deal.title[: _TITLE_LIMIT - 1].rstrip() + "…"
    url = amazon_url(deal.asin, affiliate_tag)
    lines = [f"📚 *{_whatsapp_text(title)}*"]
    if deal.niche_label:
        lines.append(_whatsapp_text(deal.niche_label))
    if deal.blurb:
        lines.append("")
        lines.append(_whatsapp_text(deal.blurb))
    lines.append("")
    lines.append(f"{format_brl(deal.price_cents)}. {lowest_phrase(deal.lowest_for_days)}")
    lines.append(url)
    return RenderedMessage(caption="\n".join(lines), image_url=deal.image_url, price_cents=deal.price_cents)


def lowest_phrase(days: int | None) -> str:
    if days is None:
        return "Menor preço registrado."
    if days <= 0:
        return "Menor preço de hoje."
    if days == 1:
        return "Menor preço em 1 dia."
    return f"Menor preço em {days} dias."


def amazon_url(asin: str, affiliate_tag: str) -> str:
    normalized = asin.strip().upper()
    if not _ASIN_RE.fullmatch(normalized):
        raise ValueError(f"ASIN inválido: {asin}")
    base = f"https://www.amazon.com.br/dp/{normalized}"
    if not affiliate_tag:
        return base
    return f"{base}?{urlencode({'tag': affiliate_tag})}"


def format_brl(cents: int) -> str:
    if cents < 0:
        raise ValueError("preço negativo")
    whole, frac = divmod(cents, 100)
    whole_text = f"{whole:,}".replace(",", ".")
    return f"R$ {whole_text},{frac:02d}"


def format_rating(keepa_rating: int) -> str:
    whole, frac = divmod(keepa_rating, 10)
    return f"{whole},{frac}"


def format_thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _whatsapp_text(value: str) -> str:
    # O asterisco é o negrito do WhatsApp. Tirá-lo do título evita quebrar a marcação.
    return value.replace("*", "").replace("_", " ")
