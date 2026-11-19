"""Texto do post no formato do WhatsApp. A frase só entra se for deste livro."""
from __future__ import annotations

import re

from promo_livros.formatter import format_brl
from promo_livros.ml_links import is_ml_url
from promo_livros.shopee_links import is_shopee_url

MAX_BLURB_WORDS = 40
_SENTENCE = re.compile(r".+?[.!?](?:\s|$)")
_WORD = re.compile(r"\w{4,}", re.UNICODE)
_GENERIC_COUPON = (
    "primeira compra",
    "20leitura",
    "cupomnoapp",
    "compranoapp",
    "mais por menos",
    "pelo app",
)


def blurb_for(title: str, synopsis: str) -> str:
    """Primeira frase longa da sinopse, se ela fala deste título."""
    text = " ".join((synopsis or "").replace("*", " ").replace("_", " ").split())
    if not text:
        return ""
    tokens = {word.casefold() for word in _WORD.findall(title)}
    if tokens and not any(token in text.casefold() for token in tokens):
        return ""
    sentences = [part.strip() for part in _SENTENCE.findall(text)] or [text]
    chosen = next((part for part in sentences if len(part) >= 40), "")
    if not chosen:
        chosen = " ".join(sentences)[:180].strip()
    if len(chosen) > 180:
        trimmed = chosen[:180].rsplit(" ", 1)[0].rstrip(".,;:")
        chosen = f"{trimmed}."
    return chosen


def product_coupon(chunks: list[str]) -> str | None:
    """Cupom do produto. Ignora o banner de primeira compra da Amazon."""
    for raw in chunks:
        text = " ".join(raw.split())
        folded = text.casefold()
        if "cupom" not in folded:
            continue
        if any(marker in folded for marker in _GENERIC_COUPON):
            continue
        if folded in {"oferta", "menor preço em 365 dias"}:
            continue
        return text[:140]
    return None


def price_line(
    *,
    price_cents: int,
    list_price_cents: int | None,
    discount_pct: float | None,
    lowest_label: str,
) -> str:
    line = format_brl(price_cents)
    tail: list[str] = []
    if list_price_cents and list_price_cents > price_cents and discount_pct:
        percent = int(round(discount_pct))
        tail.append(f"({percent}%)" if _lowest_tail(lowest_label) else f"({percent}% de desconto)")
    low = _lowest_tail(lowest_label)
    if low:
        tail.append(low)
    if tail:
        line = f"{line}, {' '.join(tail)}"
    return line


_DISCOUNT_LINK = "https://link.amazon/B01bzXpmN"
_KINDLE_LINK = "https://link.amazon/A0g7KCGdE"
_DISCOUNT_LINES = (
    "Livros com até 60% de desconto",
    "Livros em oferta, com até 60% de desconto",
    "Uma seleção de livros com até 60% off",
    "Livros com desconto de até 60%",
    "Ofertas de livros com até 60% de desconto",
    "Livros por até 60% mais baratos",
)
_KINDLE_LINES = (
    "Assine o Kindle Unlimited com até 3 meses grátis",
    "Kindle Unlimited com até 3 meses grátis",
    "Experimente o Kindle Unlimited: até 3 meses grátis",
    "Leia no Kindle Unlimited com até 3 meses grátis",
    "Até 3 meses grátis no Kindle Unlimited",
    "Comece o Kindle Unlimited com até 3 meses grátis",
)


def sign_line(index: int) -> str:
    """Alterna as duas ofertas e muda o texto. O link de cada oferta não muda."""
    if index % 2 == 0:
        text = _DISCOUNT_LINES[(index // 2) % len(_DISCOUNT_LINES)]
        return f"ℹ️ {text}: {_DISCOUNT_LINK}"
    text = _KINDLE_LINES[(index // 2) % len(_KINDLE_LINES)]
    return f"ℹ️ {text}: {_KINDLE_LINK}"


def signature_of(caption: str) -> str | None:
    for line in reversed((caption or "").splitlines()):
        if "https://link.amazon/" in line:
            return line.strip()
    return None


def render_caption(books: list[dict], *, sign_index: int = 0, signature: str | None = None) -> str:
    expanded = [block for book in books for block in _expand(book)]
    label_amazon = any(
        is_ml_url(str(book.get("url") or "")) or is_shopee_url(str(book.get("url") or ""))
        for book in expanded
    ) or len(expanded) > 1
    blocks = []
    for book in expanded:
        lines = [f"📖 *{_plain(book['title'])}*"]
        blurb = _cap_words(_plain(book.get("blurb") or ""))
        if blurb:
            lines.append(f"ℹ️ _{blurb}_")
        lines.append(
            "💲 "
            + price_line(
                price_cents=book["price_cents"],
                list_price_cents=book.get("list_price_cents"),
                discount_pct=book.get("discount_pct"),
                lowest_label=book.get("lowest_label") or "",
            )
        )
        coupon = _plain(book.get("coupon") or "")
        if coupon:
            lines.append("")
            lines.append(coupon)
        lines.append("")
        lines.extend(_link_lines(book, label_amazon=label_amazon))
        blocks.append("\n".join(lines))
    sign = signature or sign_line(sign_index)
    if not blocks:
        return sign
    return "\n\n".join(blocks) + "\n\n" + sign


def _expand(book: dict) -> list[dict]:
    """Amazon e Mercado Livre viram dois blocos. O título de cada loja fica o dela."""
    alt = str(book.get("alt_url") or "").strip()
    if not alt:
        return [book]
    primary = {**book, "alt_url": "", "alt_price_cents": None}
    price = book.get("alt_price_cents")
    secondary = {
        "title": book.get("alt_title") or book.get("title") or "",
        "blurb": book.get("alt_blurb") or "",
        "price_cents": price if isinstance(price, int) else book.get("price_cents") or 0,
        "list_price_cents": book.get("alt_list_price_cents"),
        "discount_pct": book.get("alt_discount_pct"),
        "lowest_label": book.get("alt_lowest_label") or "",
        "coupon": "",
        "url": alt,
    }
    if is_ml_url(str(primary.get("url") or "")) and not is_ml_url(alt):
        return [secondary, primary]
    return [primary, secondary]


def _link_lines(book: dict, *, label_amazon: bool) -> list[str]:
    url = str(book.get("url") or "")
    if is_ml_url(url):
        return [f"🔗 Mercado Livre: {url}"]
    if is_shopee_url(url):
        return [f"🔗 Shopee: {url}"]
    if label_amazon:
        return [f"🔗 Amazon: {url}"]
    return [f"🔗 {url}"]


def _plain(value: str) -> str:
    return value.replace("*", "").replace("_", " ").strip()


def _cap_words(text: str) -> str:
    """A resenha já vem no tamanho que o prompt pediu. O teto só segura texto descontrolado."""
    words = text.split()
    if len(words) <= MAX_BLURB_WORDS:
        return text
    trimmed = " ".join(words[:MAX_BLURB_WORDS]).rstrip(".,;:")
    return f"{trimmed}."


def _lowest_tail(label: str) -> str:
    text = " ".join((label or "").split()).rstrip(".")
    if not text:
        return ""
    folded = text.casefold()
    if "hoje" in folded:
        return "menor preço de hoje"
    if "registrado" in folded:
        return "menor preço já registrado"
    match = re.search(r"(\d+)", text)
    if match and "dia" in folded:
        days = int(match.group(1))
        if days <= 1:
            return "menor preço do último dia"
        return f"menor preço dos últimos {days} dias"
    return folded
