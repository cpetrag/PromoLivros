"""Troca a frase dos posts ainda não enviados. Não manda WhatsApp."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promo_livros.blurb import OpenAIAuthError, OpenAIBlurb
from promo_livros.board_store import BoardStore
from promo_livros.config import load_config
from promo_livros.schedule_plan import zone


def main() -> int:
    config = load_config(ROOT / "config.yaml")
    key = config.openai_api_key
    if not key or key[:1] in {'"', "'"} or "cole_a_chave" in key or not key.startswith("sk-") or len(key) < 20:
        print("CHAVE invalida")
        return 1
    print("CHAVE ok", len(key))
    now = datetime.now(zone(config.schedule.timezone))
    day = now.date().isoformat()
    store = BoardStore(config.sqlite_path)
    writer = OpenAIBlurb(key, config.openai_model, config.openai_max_chars)
    try:
        posts = store.posts_for(day)
        synopses = _synopses(ROOT / "data" / "fila_dia" / f"{day}-paginas.json")
        planned: list[tuple[int, str, list[tuple[str, str]]]] = []
        for post in posts:
            lines: list[tuple[str, str]] = []
            for book in post.books:
                source = synopses.get(_fold(book.title)) or book.blurb
                try:
                    line = writer.pitch(title=book.title, synopsis=source) or ""
                except OpenAIAuthError:
                    print("CHAVE recusada")
                    return 1
                lines.append((book.title, line or book.blurb))
            planned.append((post.id, post.clock, lines))
        changed = 0
        for post_id, clock, lines in planned:
            blurbs = [line for _title, line in lines]
            before = next(post for post in posts if post.id == post_id)
            if [book.blurb for book in before.books] == blurbs:
                print(clock, "igual")
                continue
            store.set_book_blurbs(post_id, blurbs)
            changed += 1
            print(clock)
            for title, line in lines:
                print(" -", title[:40], "|", line)
        print("atualizados", changed, "de", len(posts))
        return 0
    finally:
        writer.close()
        store.close()


def _synopses(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, dict):
            continue
        synopsis = " ".join(str(row.get("sinopse") or "").split())
        if not synopsis:
            continue
        for key in (row.get("pagina_titulo"), row.get("titulo")):
            if isinstance(key, str) and key.strip():
                found.setdefault(_fold(key), synopsis)
    return found


def _fold(value: str) -> str:
    return " ".join(value.casefold().split())


if __name__ == "__main__":
    raise SystemExit(main())
