"""Avisa quando o mesmo título existe nas duas lojas e forma o par de cada post."""
from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class _Row:
    text: str
    bundle: bool
    book: object


class TitleIndex:
    """Índice dos dois CSVs. A página e a fila consultam isto uma vez."""

    def __init__(self, amazon: list, mercado: list) -> None:
        self._amazon = [_row(book, strip_book=False) for book in amazon]
        mercado_rows = [_row(book, strip_book=True) for book in mercado]
        mercado_rows.sort(key=lambda row: row.text)
        self._mercado = mercado_rows
        self._mercado_keys = [row.text for row in mercado_rows]

    def ml_for(self, book) -> object | None:
        amazon = _fold(book.title)
        if len(amazon) < 6:
            return None
        bundled = _bundle(book.title)
        start = bisect.bisect_left(self._mercado_keys, amazon)
        hits = []
        for row in self._mercado[start:]:
            if not row.text.startswith(amazon):
                break
            if row.bundle != bundled:
                continue
            if row.text == amazon or row.text.startswith(amazon + " "):
                hits.append(row.book)
        return _closest(hits)

    def amazon_for(self, book) -> object | None:
        mercado = _strip_book(_fold(book.title))
        if not mercado:
            return None
        bundled = _bundle(book.title)
        hits = [
            row.book
            for row in self._amazon
            if len(row.text) >= 6
            and row.bundle == bundled
            and (mercado == row.text or mercado.startswith(row.text + " "))
        ]
        if not hits:
            return None
        hits.sort(key=lambda item: (-len(_fold(item.title)), item.position))
        return hits[0]


def pair_posts(amazon_picks: list, ml_picks: list, amazon_all: list, ml_all: list) -> list[tuple]:
    """Cada post leva uma oferta da Amazon e uma do Mercado Livre. O que sobra vira post de uma loja."""
    del amazon_all, ml_all
    remaining = list(ml_picks)
    paired: list[tuple] = []
    for book in amazon_picks:
        paired.append((book, _take_other_title(book, remaining)))
    for book in remaining:
        paired.append((book, None))
    return paired


def _take_other_title(amazon_book, remaining: list):
    """O mesmo título não ocupa os dois lugares do post."""
    for index, candidate in enumerate(remaining):
        if titles_match(amazon_book.title, candidate.title):
            continue
        return remaining.pop(index)
    return None


def titles_match(amazon_title: str, ml_title: str) -> bool:
    """O título da Amazon abre o anúncio do Mercado Livre, e um kit não cola num livro só."""
    amazon = _fold(amazon_title)
    mercado = _strip_book(_fold(ml_title))
    if len(amazon) < 6 or not mercado:
        return False
    if _bundle(amazon_title) != _bundle(ml_title):
        return False
    return mercado == amazon or mercado.startswith(amazon + " ")


def _row(book, *, strip_book: bool) -> _Row:
    text = _fold(book.title)
    if strip_book:
        text = _strip_book(text)
    return _Row(text, _bundle(book.title), book)


def _closest(hits: list):
    if not hits:
        return None
    hits.sort(key=lambda item: (len(_fold(item.title)), item.price_cents if item.price_cents is not None else 10**12, item.position))
    return hits[0]


def _strip_book(text: str) -> str:
    for prefix in ("livro ", "livros "):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(char for char in normalized if not unicodedata.combining(char))
    cleaned = re.sub(r"[^a-z0-9]+", " ", stripped.casefold())
    return " ".join(cleaned.split())


def _bundle(title: str) -> bool:
    folded = f" {_fold(title)} "
    if any(marker in folded for marker in (" kit ", " combo ", " box ")):
        return True
    raw = title or ""
    return "+" in raw or "&" in raw
