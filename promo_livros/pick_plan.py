"""A fila que a Curadoria mostra. Cada post leva uma oferta da Amazon e uma do Mercado Livre."""
from __future__ import annotations

from promo_livros.book_match import pair_posts
from promo_livros.formatter import format_brl


def plan_rows(amazon_picks: list, ml_picks: list, clocks: list[str]) -> list[dict]:
    """Uma linha por post, com o lugar de cada loja. Lugar vazio é marcação que ficou sem par."""
    amazon = [book for book in amazon_picks if book.price_cents]
    mercado = [book for book in ml_picks if book.price_cents]
    rows = []
    for index, (book, alt) in enumerate(pair_posts(amazon, mercado, amazon, mercado)):
        slots = {"amazon": None, "ml": None}
        for item in (book, alt):
            if item is not None:
                slots[_store_of(item)] = _slot(item)
        rows.append(
            {
                "clock": clocks[index] if index < len(clocks) else "",
                "amazon": slots["amazon"],
                "ml": slots["ml"],
            }
        )
    return rows


def plan_summary(rows: list[dict]) -> dict:
    """Os números que a página mostra acima da fila."""
    both = sum(1 for row in rows if row["amazon"] and row["ml"])
    return {
        "posts": len(rows),
        "both": both,
        "alone": len(rows) - both,
        "fits": sum(1 for row in rows if row["clock"]),
    }


def _store_of(book) -> str:
    return "ml" if getattr(book, "store", "amazon") == "ml" else "amazon"


def _slot(book) -> dict:
    return {
        "asin": book.asin,
        "title": book.title,
        "price": format_brl(book.price_cents) if book.price_cents else "",
        "store": _store_of(book),
    }
