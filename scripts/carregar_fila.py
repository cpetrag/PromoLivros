"""Grava a prévia de amanhã/hoje no painel. Não envia nada."""
import json
from datetime import datetime
from pathlib import Path

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.config import load_config
from promo_livros.lojas import store_of
from promo_livros.post_card import download_image, render_card
from promo_livros.post_copy import blurb_for, product_coupon, render_caption
from promo_livros.schedule_plan import service_day, zone

ROOT = Path(__file__).resolve().parents[1]


def clocks() -> list[str]:
    hour, minute = 8, 0
    result = []
    for _ in range(20):
        result.append(f"{hour:02d}:{minute:02d}")
        minute += 40
        hour += minute // 60
        minute %= 60
    return result


def cents(value) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 100))


def main() -> None:
    config = load_config(ROOT / "config.yaml")
    day = service_day(datetime.now(zone(config.schedule.timezone)), config.schedule.timezone)
    store = BoardStore(config.sqlite_path)
    if store.has_day(day):
        print(f"A fila de {day} já está no painel.")
        return
    rows = json.loads((ROOT / "data" / "fila_paginas.json").read_text(encoding="utf-8"))[:30]
    cards = ROOT / "data" / "cards"
    cursor = 0
    for index, clock in enumerate(clocks()):
        count = 2 if index % 2 == 0 else 1
        chunk = rows[cursor : cursor + count]
        cursor += count
        if len(chunk) < count:
            break
        books = []
        covers = []
        payloads = []
        for row in chunk:
            blurb = blurb_for(row["titulo"], row.get("sinopse") or "")
            coupon = product_coupon(row.get("cupom") or []) or ""
            price = cents(row["preco"])
            listed = cents(row.get("preco_de"))
            books.append(
                BoardBook(
                    title=row["pagina_titulo"] or row["titulo"],
                    blurb=blurb,
                    price_cents=price,
                    list_price_cents=listed,
                    discount_pct=row.get("off_pagina"),
                    lowest_label="Menor preço em 120 dias.",
                    url=row["url"],
                    coupon=coupon,
                )
            )
            payloads.append(
                {
                    "title": books[-1].title,
                    "blurb": blurb,
                    "price_cents": price,
                    "list_price_cents": listed,
                    "discount_pct": row.get("off_pagina"),
                    "lowest_label": "Menor preço em 120 dias.",
                    "coupon": coupon,
                    "url": row["url"],
                }
            )
            covers.append(download_image(row["capa"]))
        post_id = store.add_post(
            day=day,
            clock=clock,
            caption=render_caption(payloads),
            image_path="",
            books=books,
        )
        destination = cards / f"{post_id}.jpg"
        render_card(covers, destination, stores=[store_of(book) for book in books])
        store.set_image(post_id, f"data/cards/{post_id}.jpg")
        print(f"{clock} {count} livro(s) -> {post_id}", flush=True)
    print(f"Fila de {day} pronta.", flush=True)


if __name__ == "__main__":
    main()
