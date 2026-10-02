"""Monta a fila do dia a partir da vitrine da Amazon. Não publica e não liga o WhatsApp."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.day_cut import (
    DEALS_URL,
    KEEPA_BATCH,
    INFANTIL_SHARE,
    MAX_ASINS,
    MAX_POSTS,
    TARGET_PASSERS,
    from_keepa,
    load_vitrine,
    passes,
    rank_passers,
    take_with_infantil_cap,
    is_infantil,
)
from promo_livros.keepa_client import KeepaClient
from promo_livros.models import AppConfig, KeepaError
from promo_livros.post_card import download_image, render_card
from promo_livros.post_copy import blurb_for, product_coupon, render_caption
from promo_livros.schedule_plan import service_day, zone
from promo_livros.send_schedule import SendSchedule, plan_day_clocks

logger = logging.getLogger("promo_livros.morning")
BUILDING = "fila_building"
PREVIEW = "fila_preview"
MIN_CRAWL_ROWS = 50


def begin_day(store: BoardStore, day: str) -> str:
    """'skip' se a fila do dia já está pronta. Retoma uma montagem que quebrou no meio.

    'replace' quando a fila no painel é só a prévia: ela continua lá até a nova ficar pronta.
    """
    if store.setting(PREVIEW) == day and store.has_day(day):
        store.put_setting(BUILDING, day)
        return "replace"
    building = store.setting(BUILDING) or ""
    if store.has_day(day) and building != day:
        return "skip"
    if building == day:
        store.cancel_day(day)
    store.put_setting(BUILDING, day)
    return "build"


def finish_day(store: BoardStore) -> None:
    store.put_setting(BUILDING, "")


def build_today(config: AppConfig, root: Path, *, python: str | None = None, day: str | None = None) -> int:
    day = day or service_day(datetime.now(zone(config.schedule.timezone)), config.schedule.timezone)
    store = BoardStore(config.sqlite_path)
    try:
        if store.setting("curation") == "manual":
            logger.info("Curadoria manual. A fila de %s não é montada sozinha.", day)
            return 0
        mode = begin_day(store, day)
        if mode == "skip":
            logger.info("A fila de %s já está no painel.", day)
            return 0
        previous = [post.id for post in store.posts_for(day)] if mode == "replace" else []
        folder = root / "data" / "fila_dia"
        folder.mkdir(parents=True, exist_ok=True)
        csv_path = folder / f"{day}.csv"
        db_path = folder / f"{day}.db"
        if _crawl(root, csv_path, db_path, python or sys.executable) != 0:
            logger.error("O crawler da Amazon falhou. A fila de %s não foi gravada.", day)
            return 1
        rows = _csv_rows(csv_path)
        if len(rows) < MIN_CRAWL_ROWS:
            logger.error("A vitrine veio com %s itens. Pouco para montar o dia.", len(rows))
            return 1
        vitrine = load_vitrine(csv_path)
        logger.info("Vitrine: %s itens, %s no corte de página.", len(rows), len(vitrine))
        annotated = _annotate(config, vitrine, target=_book_budget(store))
        (folder / f"{day}-keepa.json").write_text(
            json.dumps(annotated, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ranked = rank_passers(annotated)
        slots = min(len(ranked), MAX_POSTS)
        chosen = take_with_infantil_cap(ranked, slots, spare=max(_book_budget(store) - slots, 0))
        kids = sum(1 for item in chosen if is_infantil(item))
        logger.info(
            "Corte: %s livros, %s infantil (teto de %s%% em %s posts).",
            len(chosen),
            kids,
            int(INFANTIL_SHARE * 100),
            slots,
        )
        if not chosen:
            logger.error("Nenhum livro passou no corte do Keepa.")
            return 1
        pages = _pages(chosen)
        (folder / f"{day}-paginas.json").write_text(
            json.dumps(pages, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        writer = _pitch_writer(config)
        try:
            written = write_board(
                store,
                day,
                pages,
                root / "data" / "cards",
                schedule=store.send_schedule(),
                pitch=None if writer is None else writer.pitch,
                resolve_urls=_affiliate_resolver(config),
            )
        finally:
            if writer is not None:
                writer.close()
        if written == 0:
            logger.error("Nenhum card foi gerado.")
            return 1
        for post_id in previous:
            store.cancel(day, post_id)
        store.put_setting(PREVIEW, "")
        finish_day(store)
        logger.info("Fila de %s pronta: %s posts. Nada foi enviado.", day, written)
        return 0
    finally:
        store.close()


def write_board(
    store: BoardStore,
    day: str,
    books: list[dict],
    cards_dir: Path,
    download=download_image,
    schedule: SendSchedule | None = None,
    pitch=None,
    resolve_urls=None,
    clocks: list[str] | None = None,
) -> int:
    cards_dir.mkdir(parents=True, exist_ok=True)
    needed = len(clocks) if clocks is not None else _book_budget(store)
    ready: list[tuple[dict, object]] = []
    for book in books:
        if len(ready) >= needed:
            break
        if _cents(book.get("preco")) is None:
            logger.info("Sem preço, fora do dia: %s", book.get("asin"))
            continue
        cover_url = book.get("capa") or ""
        if not cover_url:
            logger.info("Sem capa, fora do dia: %s", book.get("asin"))
            continue
        try:
            cover = download(cover_url)
        except Exception:
            logger.info("Capa não baixou, fora do dia: %s", book.get("asin"))
            continue
        ready.append((book, cover))
    if clocks is None:
        start = (schedule or store.send_schedule()).start
        clocks = plan_day_clocks(start, len(ready))
    chosen = ready[: len(clocks)]
    for _book, cover in ready[len(chosen) :]:
        cover.close()
    written = 0
    for index, ((book, cover), clock) in enumerate(zip(chosen, clocks)):
        payload = _payload(book, pitch=pitch)
        if resolve_urls is not None:
            resolved = resolve_urls([payload["url"]])
            if len(resolved) == 1:
                payload["url"] = resolved[0]
        post_id = store.add_post(
            day=day,
            clock=clock,
            caption=render_caption([payload], sign_index=index),
            image_path="",
            books=[_stored_book(payload)],
        )
        render_card([cover], cards_dir / f"{post_id}.jpg")
        cover.close()
        store.set_image(post_id, f"data/cards/{post_id}.jpg")
        written += 1
        logger.info("%s com 1 livro", clock)
    return written


def _crawl(root: Path, csv_path: Path, db_path: Path, python: str) -> int:
    command = [
        python,
        "-u",
        str(root / "scripts" / "amazon_livros_crawler.py"),
        "--url",
        DEALS_URL,
        "--headless",
        "--csv",
        str(csv_path),
        "--db",
        str(db_path),
        "--perfil",
        str(root / "data" / "perfil_amazon_mac"),
    ]
    logger.info("Crawler da vitrine de livros em oferta.")
    completed = subprocess.run(command, cwd=root, check=False)
    return completed.returncode


def _csv_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    import csv

    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def _book_budget(store: BoardStore) -> int:
    del store
    return MAX_POSTS + 6


def _annotate(config: AppConfig, rows: list[dict], *, target: int = TARGET_PASSERS) -> list[dict]:
    client = KeepaClient(config)
    found: list[dict] = []
    try:
        limit = rows[:MAX_ASINS]
        for start in range(0, len(limit), KEEPA_BATCH):
            if sum(1 for item in found if passes(item)) >= target:
                break
            chunk = limit[start : start + KEEPA_BATCH]
            try:
                products = client.deal_stats([str(row.get("asin") or "") for row in chunk])
            except KeepaError:
                logger.exception("Keepa parou. Sigo com %s livros já lidos.", len(found))
                break
            by_asin = {
                product.get("asin"): product
                for product in products
                if isinstance(product, dict) and product.get("asin")
            }
            for offset, row in enumerate(chunk):
                product = by_asin.get(row.get("asin"))
                if not product:
                    continue
                found.append(from_keepa(row, product, start + offset + 1))
            ready = sum(1 for item in found if passes(item))
            logger.info("Keepa: %s lidos, %s no corte.", len(found), ready)
    finally:
        client.close()
    return found


def _pages(books: list[dict]) -> list[dict]:
    from promo_livros.product_page import read_product_pages

    logger.info("Abrindo a página de %s livros para capa e cupom.", len(books))
    return read_product_pages(books)


def _payload(book: dict, pitch=None) -> dict:
    title = book.get("pagina_titulo") or book.get("titulo") or ""
    price = _cents(book.get("preco"))
    listed = _cents(book.get("preco_de"))
    discount = book.get("off_pagina")
    if price and listed and listed > price:
        discount = round((listed - price) * 100 / listed, 1)
    return {
        "title": title,
        "blurb": _blurb(title, book.get("sinopse") or "", pitch),
        "price_cents": price,
        "list_price_cents": listed,
        "discount_pct": discount,
        "lowest_label": "Menor preço em 120 dias.",
        "coupon": product_coupon(book.get("cupom") or []) or "",
        "url": book.get("url") or "",
    }


def _blurb(title: str, synopsis: str, pitch) -> str:
    if pitch is None:
        return blurb_for(title, synopsis)
    return pitch(title=title, synopsis=synopsis) or ""


def _affiliate_resolver(config: AppConfig):
    from promo_livros.amz_links import affiliate_resolver

    return affiliate_resolver(config)


def _pitch_writer(config: AppConfig):
    if not config.openai_api_key:
        return None
    from promo_livros.blurb import OpenAIBlurb

    return OpenAIBlurb(config.openai_api_key, config.openai_model, config.openai_max_chars)


def _stored_book(payload: dict) -> BoardBook:
    return BoardBook(
        title=payload["title"],
        blurb=payload["blurb"],
        price_cents=payload["price_cents"],
        list_price_cents=payload["list_price_cents"],
        discount_pct=payload["discount_pct"],
        lowest_label=payload["lowest_label"],
        url=payload["url"],
        coupon=payload["coupon"],
    )


def _cents(value) -> int | None:
    if value is None or value == "":
        return None
    return int(round(float(value) * 100))
