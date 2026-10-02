"""Grava a fila de 2026-09-29 com a vitrine já coletada. Não chama Keepa nem abre páginas."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.config import load_config
from promo_livros.day_cut import JUNK, MAX_POSTS, load_vitrine
from promo_livros.post_copy import render_caption
from promo_livros.send_schedule import plan_day_clocks

DAY = "2026-09-29"


def main() -> int:
    config = load_config(ROOT / "config.yaml")
    store = BoardStore(config.sqlite_path)
    try:
        if store.has_day(DAY):
            posts = store.posts_for(DAY)
            print(f"A fila de {DAY} já tem {len(posts)} posts.")
            return 0
        rows = [row for row in load_vitrine(ROOT / "data" / "fila_dia" / f"{DAY}.csv") if not _junk(row)]
        chosen = rows[:MAX_POSTS]
        clocks = plan_day_clocks(store.send_schedule().start, len(chosen))
        for index, (row, clock) in enumerate(zip(chosen, clocks)):
            price = _cents(row.get("preco"))
            listed = _cents(row.get("preco_de"))
            if price is None:
                continue
            discount = _num(row.get("desconto_pct"))
            payload = {
                "title": row.get("titulo") or row.get("asin") or "Livro",
                "blurb": "",
                "price_cents": price,
                "list_price_cents": listed,
                "discount_pct": discount,
                "lowest_label": "",
                "coupon": "",
                "url": row.get("url") or "",
            }
            store.add_post(
                day=DAY,
                clock=clock,
                caption=render_caption([payload], sign_index=index),
                image_path="",
                books=[
                    BoardBook(
                        title=payload["title"],
                        blurb="",
                        price_cents=price,
                        list_price_cents=listed,
                        discount_pct=discount,
                        lowest_label="",
                        url=payload["url"],
                        coupon="",
                    )
                ],
            )
            print(f"{clock}  {payload['title']}")
        store.put_setting("fila_building", "")
        print(f"FILA {DAY} {len(clocks)} posts. Nada enviado.")
        return 0
    finally:
        store.close()


def _junk(row: dict) -> bool:
    title = (row.get("titulo") or "").casefold()
    return any(word in title for word in JUNK)


def _cents(value) -> int | None:
    if value is None or value == "":
        return None
    return int(round(float(value) * 100))


def _num(value):
    if value is None or value == "":
        return None
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
