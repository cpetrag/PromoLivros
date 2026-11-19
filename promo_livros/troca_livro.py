"""Trocar um livro entre dois posts da fila, sem mexer nos horários.

Os links, descrições e cupons já gravados vão junto com o livro. Só a legenda e o card
dos dois posts são refeitos; nada é buscado de novo nas lojas.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable

from PIL import Image

from promo_livros.board_store import BoardBook, BoardPost
from promo_livros.lojas import STORE_ORDER, store_of
from promo_livros.post_card import extract_covers, render_card
from promo_livros.post_copy import render_caption, sign_line, signature_of

LADOS = ("amazon", "segunda")
_PLACEHOLDER = (245, 241, 232)
_log = logging.getLogger("promo_livros")

CoverFetcher = Callable[[str], bytes]


@dataclass(frozen=True)
class _Livro:
    book: BoardBook
    covers: tuple[Image.Image, ...]
    lado: str


def trocar_livro(board, cards_dir: Path, day: str, post_id: int, com_id: int, lado: str, fetch_cover: CoverFetcher | None = None) -> dict:
    if lado not in LADOS:
        return {"ok": False, "error": "Escolha o livro da Amazon ou o da outra loja."}
    if post_id == com_id:
        return {"ok": False, "error": "Escolha outro post para trocar."}
    posts = {post.id: post for post in board.posts_for(day)}
    first, second = posts.get(post_id), posts.get(com_id)
    if first is None or second is None:
        return {"ok": False, "error": "Esse post não está mais na fila."}
    first_books = _livros(first, cards_dir, fetch_cover)
    second_books = _livros(second, cards_dir, fetch_cover)
    moving = [item for item in first_books if item.lado == lado]
    coming = [item for item in second_books if item.lado == lado]
    if not moving and not coming:
        return {"ok": False, "error": "Nenhum dos dois posts tem livro desse lado."}
    new_first = _ordenar([item for item in first_books if item.lado != lado] + coming)
    new_second = _ordenar([item for item in second_books if item.lado != lado] + moving)
    for post, books in ((first, new_first), (second, new_second)):
        if not books:
            return {"ok": False, "error": f"O post das {post.clock} ficaria sem livro."}
        if len(books) > 3:
            return {"ok": False, "error": f"O post das {post.clock} ficaria com livros demais."}
    temp_cards = {}
    try:
        for post, books in ((first, new_first), (second, new_second)):
            target = cards_dir / f"{post.id}.jpg.novo"
            render_card([cover for item in books for cover in item.covers], target)
            temp_cards[post.id] = target
        error = board.replace_post_books(
            day,
            {
                first.id: (first.books, [item.book for item in new_first], _legenda(first, new_first)),
                second.id: (second.books, [item.book for item in new_second], _legenda(second, new_second)),
            },
        )
        if error:
            return {"ok": False, "error": error}
        for post_key, temp in temp_cards.items():
            os.replace(temp, cards_dir / f"{post_key}.jpg")
            board.set_image(post_key, f"data/cards/{post_key}.jpg")
        temp_cards = {}
    finally:
        for temp in temp_cards.values():
            temp.unlink(missing_ok=True)
    message = _mensagem(first, second, moving, coming)
    return {"ok": True, "message": message, "undo": {"id": post_id, "com": com_id, "lado": lado}}


def _livros(post: BoardPost, cards_dir: Path, fetch_cover: CoverFetcher | None) -> list[_Livro]:
    """Cada livro leva as capas que ocupa no card. Livro antigo com link alternativo ocupa duas."""
    widths = [2 if book.alt_url else 1 for book in post.books]
    cut = extract_covers(cards_dir / f"{post.id}.jpg", sum(widths))
    if cut is None:
        _log.info("Card do post %s não recortou; buscando as capas de novo.", post.id)
    lados = _lados(list(post.books))
    found = []
    cursor = 0
    for index, (book, width) in enumerate(zip(post.books, widths)):
        if cut is not None:
            covers = tuple(cut[cursor:cursor + width])
        else:
            covers = (_buscar_capa(book, fetch_cover),) + tuple(_vazia() for _ in range(width - 1))
        cursor += width
        found.append(_Livro(book, covers, lados[index]))
    return found


def _lados(books: list[BoardBook]) -> list[str]:
    """Duas ofertas da mesma loja ocupam os dois lados do post, na ordem em que foram gravadas."""
    if len(books) >= 2 and len({store_of(book) for book in books}) == 1:
        return ["amazon" if index == 0 else "segunda" for index in range(len(books))]
    return ["amazon" if store_of(book) == "amazon" else "segunda" for book in books]


def _buscar_capa(book: BoardBook, fetch_cover: CoverFetcher | None) -> Image.Image:
    product_id = (book.product_id or "").strip().upper()
    if fetch_cover is None or not product_id or store_of(book) == "shopee":
        return _vazia()
    try:
        return Image.open(BytesIO(fetch_cover(product_id))).convert("RGB")
    except Exception:
        _log.warning("Não achei a capa de %s para o card novo.", product_id)
        return _vazia()


def _vazia() -> Image.Image:
    return Image.new("RGB", (280, 400), _PLACEHOLDER)


def _ordenar(items: list[_Livro]) -> list[_Livro]:
    return sorted(items, key=lambda item: STORE_ORDER.get(store_of(item.book), 9))


def _legenda(post: BoardPost, books: list[_Livro]) -> str:
    # A assinatura alterna entre posts; cada post mantém a dele.
    signature = signature_of(post.caption) or sign_line(max(0, post.position))
    return render_caption([_payload(item.book) for item in books], signature=signature)


def _payload(book: BoardBook) -> dict:
    return {
        "title": book.title,
        "blurb": book.blurb,
        "price_cents": book.price_cents,
        "list_price_cents": book.list_price_cents,
        "discount_pct": book.discount_pct,
        "lowest_label": book.lowest_label,
        "coupon": book.coupon,
        "url": book.url,
        "alt_url": book.alt_url,
        "alt_price_cents": book.alt_price_cents,
        "product_id": book.product_id,
    }


def _mensagem(first: BoardPost, second: BoardPost, moving: list[_Livro], coming: list[_Livro]) -> str:
    def nome(items: list[_Livro]) -> str:
        title = items[0].book.title
        return f"“{title[:40]}{'…' if len(title) > 40 else ''}”"

    if moving and coming:
        return f"{nome(moving)} foi para as {second.clock} e {nome(coming)} veio para as {first.clock}."
    if moving:
        return f"{nome(moving)} foi para o post das {second.clock}."
    return f"{nome(coming)} veio para o post das {first.clock}."
