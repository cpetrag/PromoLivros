"""A fila que a Curadoria mostra. Cada post leva uma oferta da Amazon e uma do Mercado Livre."""
from __future__ import annotations

from promo_livros.fila import OpcoesFila, item_de_livro, montar_fila
from promo_livros.formatter import format_brl


def plan_rows(amazon_picks: list, ml_picks: list, clocks: list[str]) -> list[dict]:
    """Uma linha por post, com o lugar de cada loja. Lugar vazio é marcação que ficou sem par."""
    fila = montar_fila(
        [item_de_livro(book) for book in amazon_picks],
        [item_de_livro(book) for book in ml_picks],
        OpcoesFila(
            agora="00:00",
            inicio="00:00",
            fim="23:59",
            intervalo=1,
            horarios=tuple(clocks),
            ordem="mine",
        ),
    )
    return [
        {
            "clock": slot.clock,
            "amazon": _slot(slot.amazon) if slot.amazon else None,
            "ml": _slot(slot.ml) if slot.ml else None,
        }
        for slot in fila.slots
    ]


def plan_summary(rows: list[dict]) -> dict:
    """Os números que a página mostra acima da fila."""
    both = sum(1 for row in rows if row["amazon"] and row["ml"])
    return {
        "posts": len(rows),
        "both": both,
        "alone": len(rows) - both,
        "fits": sum(1 for row in rows if row["clock"]),
    }


def _slot(item) -> dict:
    price = ""
    if item.price_cents:
        price = format_brl(item.price_cents)
    return {
        "asin": item.id,
        "title": item.title,
        "price": price,
        "store": item.store,
    }
