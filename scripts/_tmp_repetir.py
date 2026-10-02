"""Cancela o que ainda está atrasado e reprograma os melhores, repetindo os que já saíram."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from promo_livros.board_store import BoardStore
from promo_livros.config import load_config
from promo_livros.morning import _affiliate_resolver, _pitch_writer, write_board
from promo_livros.schedule_plan import zone
from promo_livros.send_schedule import plan_span_clocks

DAY = "2026-09-28"
END = "23:00"
ROOT = Path(".")


def main() -> None:
    config = load_config(ROOT / "config.yaml")
    connection = sqlite3.connect("data/promo_livros.sqlite")
    pending = [
        row[0]
        for row in connection.execute(
            """
            SELECT id FROM scheduled_posts
            WHERE day = ? AND status = 'scheduled'
              AND NOT EXISTS (
                SELECT 1 FROM board_sends
                WHERE board_sends.post_id = scheduled_posts.id
                  AND board_sends.status IN ('sent', 'sending')
              )
            """,
            (DAY,),
        )
    ]
    store = BoardStore(config.sqlite_path)
    for post_id in pending:
        store.cancel(DAY, post_id)
    print(f"Cancelados {len(pending)} posts atrasados.", flush=True)

    pages = json.loads((ROOT / "data" / "fila_dia" / f"{DAY}-paginas.json").read_text(encoding="utf-8"))
    books = [page for page in pages if page.get("capa") and page.get("preco")]
    now = datetime.now(zone(config.schedule.timezone)) + timedelta(minutes=4)
    start = f"{now.hour:02d}:{now.minute:02d}"
    clocks = plan_span_clocks(start, END, min(12, len(books)))
    if len(clocks) < 1:
        raise SystemExit("Não cabe mais post antes das 23:00.")
    chosen = books[: len(clocks)]
    print(f"Horários: {clocks[0]} até {clocks[-1]}.", flush=True)
    for clock, book in zip(clocks, chosen):
        print(clock, book.get("pagina_titulo") or book.get("titulo"), flush=True)

    writer = _pitch_writer(config)

    def safe_pitch(**kwargs):
        try:
            return None if writer is None else writer.pitch(**kwargs)
        except Exception as exc:
            print(f"Frase não saiu: {exc}", flush=True)
            return None

    try:
        written = write_board(
            store,
            DAY,
            chosen,
            ROOT / "data" / "cards",
            pitch=None if writer is None else safe_pitch,
            resolve_urls=_affiliate_resolver(config),
            clocks=clocks,
        )
    finally:
        if writer is not None:
            writer.close()
        store.close()
    print(f"Programados: {written}.", flush=True)


if __name__ == "__main__":
    main()
