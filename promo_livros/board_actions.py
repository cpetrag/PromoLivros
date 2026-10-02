"""Grava um post manual: texto, capas originais e card."""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.post_card import download_image, render_card
from promo_livros.post_copy import render_caption

_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def revise_manual(
    store: BoardStore,
    day: str,
    post_id: int,
    form: dict[str, list[str]],
    cards_dir: Path,
    resolve_urls=None,
) -> str | None:
    """Atualiza um post que ainda está na fila. A capa só troca se vier uma URL nova."""
    existing = store.post_by_id(post_id)
    if existing is None or existing.day != day or not existing.books:
        return "Post não encontrado."
    clock = _value(form, "clock")
    if _CLOCK.fullmatch(clock) is None:
        return "Horário inválido. Use 21:00."
    title = _value(form, "title")
    price = _value(form, "price")
    url = _value(form, "url")
    if not title or not price or not url:
        return "O livro precisa de nome, preço e link."
    cents = _cents(price)
    if cents is None:
        return "Preço inválido."
    listed = _cents(_value(form, "list_price"))
    discount = None
    if listed and listed > cents:
        discount = (listed - cents) * 100 / listed
    if resolve_urls is not None:
        resolved = resolve_urls([url])
        if resolved:
            url = resolved[0]
    current = existing.books[0]
    books = [
        replace(
            current,
            title=title,
            blurb=_value(form, "blurb"),
            price_cents=cents,
            list_price_cents=listed,
            discount_pct=discount,
            url=url,
        ),
        *existing.books[1:],
    ]
    caption = render_caption(
        [
            {
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
            }
            for book in books
        ],
        signature=_signature(existing.caption),
    )
    if not store.update_scheduled(day, post_id, clock=clock, books=books, caption=caption):
        return "Só dá para editar um post que ainda está na fila."
    cover_url = _value(form, "cover")
    if not cover_url:
        return None
    destination = cards_dir / f"{post_id}.jpg"
    try:
        render_card([download_image(cover_url)], destination)
    except (OSError, ValueError):
        return "O texto foi salvo, mas a capa nova não entrou."
    store.set_image(post_id, f"data/cards/{post_id}.jpg")
    return None


def _signature(caption: str) -> str | None:
    from promo_livros.post_copy import signature_of

    return signature_of(caption)


def schedule_manual(
    store: BoardStore,
    day: str,
    form: dict[str, list[str]],
    cards_dir: Path,
    resolve_urls=None,
) -> str | None:
    clock = _value(form, "clock")
    if _CLOCK.fullmatch(clock) is None:
        return "Horário inválido. Use 21:00."
    try:
        books, covers = _books(form)
    except ValueError as exc:
        return str(exc)
    books, covers = _amazon_first(books, covers)
    if resolve_urls is not None:
        resolved = resolve_urls([book.url for book in books])
        if len(resolved) == len(books):
            books = [replace(book, url=url) for book, url in zip(books, resolved)]
    caption = render_caption(
        [
            {
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
            }
            for book in books
        ],
        sign_index=int(clock[:2]) * 60 + int(clock[3:5]),
    )
    post_id = store.add_post(day=day, clock=clock, caption=caption, image_path="", books=books)
    destination = cards_dir / f"{post_id}.jpg"
    try:
        render_card(covers, destination)
    except (OSError, ValueError):
        store.cancel(day, post_id)
        return "Não montei o card."
    store.set_image(post_id, f"data/cards/{post_id}.jpg")
    return None


def _amazon_first(books: list[BoardBook], covers: list) -> tuple[list[BoardBook], list]:
    """A legenda e o card mostram a Amazon antes do Mercado Livre, como na curadoria."""
    from promo_livros.ml_links import is_ml_url

    order = sorted(range(len(books)), key=lambda place: is_ml_url(books[place].url))
    return [books[place] for place in order], [covers[place] for place in order]


def _books(form: dict[str, list[str]]) -> tuple[list[BoardBook], list]:
    books = []
    covers = []
    for suffix, label in (("", "primeiro"), ("2", "segundo"), ("3", "terceiro")):
        title = _value(form, f"title{suffix}")
        price = _value(form, f"price{suffix}")
        url = _value(form, f"url{suffix}")
        cover_url = _value(form, f"cover{suffix}")
        if suffix and not any((title, price, url, cover_url)):
            continue
        if not title or not price or not url or not cover_url:
            raise ValueError(f"O {label} livro precisa de nome, preço, link e capa.")
        cents = _cents(price)
        if cents is None:
            raise ValueError(f"Preço inválido no {label} livro.")
        listed = _cents(_value(form, f"list_price{suffix}"))
        discount = None
        if listed and listed > cents:
            discount = (listed - cents) * 100 / listed
        try:
            covers.append(download_image(cover_url))
        except Exception as exc:
            raise ValueError(f"Não baixei a capa do {label} livro.") from exc
        books.append(
            BoardBook(
                title=title,
                blurb=_value(form, f"blurb{suffix}"),
                price_cents=cents,
                list_price_cents=listed,
                discount_pct=discount,
                lowest_label="",
                url=url,
                coupon="",
            )
        )
    if not books:
        raise ValueError("Informe pelo menos um livro.")
    return books, covers


def _cents(text: str) -> int | None:
    raw = text.strip().replace("R$", "").replace(" ", "")
    if not raw:
        return None
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return int(round(value * 100))


def _value(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name, [])
    return values[0].strip() if values else ""
