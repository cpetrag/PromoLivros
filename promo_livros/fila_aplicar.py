"""Prévia, aplicar e desfazer. A prévia não grava a fila."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from datetime import date, timedelta

from promo_livros.catalog import CatalogBook, CatalogError, publish_selection
from promo_livros.fila import OpcoesFila, chave_obra, item_de_livro, montar_fila, produto_de_url
from promo_livros.shopee_links import is_shopee_product

UNDO_SECONDS = 10 * 60
PREVIA_SECONDS = 10 * 60
_APPLY_LOCK = threading.Lock()


class MemoriaPrevia:
    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    def guardar(self, payload: dict, fingerprint: str) -> str:
        self._expirar()
        previa_id = secrets.token_urlsafe(12)
        self._items[previa_id] = {"at": time.time(), "payload": payload, "fingerprint": fingerprint}
        return previa_id

    def pegar(self, previa_id: str) -> dict | None:
        self._expirar()
        return self._items.get(previa_id)

    def _expirar(self) -> None:
        now = time.time()
        for key in [item for item, row in self._items.items() if now - row["at"] > PREVIA_SECONDS]:
            del self._items[key]


ORDEM_MANUAL_KEY = "curadoria_ordem_manual"
_ID_FILA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{2,39}$")
_MAX_IDS = 200


def ordem_manual(board, day: str) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    raw = board.setting(ORDEM_MANUAL_KEY) or ""
    if not raw:
        return None
    try:
        saved = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(saved, dict) or saved.get("day") != day:
        return None
    return tuple(str(item) for item in saved.get("amazon") or ()), tuple(str(item) for item in saved.get("segunda") or ())


def salvar_ordem_manual(board, day: str, amazon: list[str], segunda: list[str]) -> None:
    """Guarda a arrumação da grade. Id fora do formato é recusado, não ignorado em silêncio."""
    columns = []
    for ids in (amazon, segunda):
        if len(ids) > _MAX_IDS:
            raise CatalogError("Lista grande demais. Atualize a página.")
        clean = []
        for raw in ids:
            item = raw.strip()
            if not _ID_FILA.fullmatch(item):
                raise CatalogError("A ordem veio com um livro inválido. Atualize a página.")
            if item.upper() not in {value.upper() for value in clean}:
                clean.append(item)
        columns.append(clean)
    board.put_setting(ORDEM_MANUAL_KEY, json.dumps({"day": day, "amazon": columns[0], "segunda": columns[1]}))


def limpar_ordem_manual(board) -> None:
    board.put_setting(ORDEM_MANUAL_KEY, "")


def calcular(catalog, board, day: str, agora: str, ordem: str):
    amazon, mercado = catalog.queue_for(day)
    enviados, obras = _enviados(catalog, board, day)
    amazon = _com_bloqueados(amazon, catalog.books(), enviados)
    mercado = _com_bloqueados(mercado, catalog.ml_books(), enviados)
    # Shopee não tem catálogo: o livro só existe no post que veio da fila importada.
    shopee, imagens = _shopee_dos_posts(catalog, board.posts_for(day))
    fila = montar_fila(
        [item_de_livro(book) for book in amazon],
        [item_de_livro(book) for book in mercado],
        OpcoesFila(
            agora=agora,
            inicio=board.send_schedule().start,
            fim=board.send_schedule().end,
            intervalo=board.send_schedule().post_interval_minutes,
            enviados=enviados,
            ordem=ordem if ordem in {"mine", "desc", "mix"} else "mine",
            obras_enviadas=obras,
            ordem_manual=ordem_manual(board, day) if ordem == "mine" else None,
        ),
        shopee=[item_de_livro(book) for book in shopee],
    )
    return fila, shopee, imagens


def previa(catalog, board, day: str, agora: str, ordem: str, memoria: MemoriaPrevia) -> dict:
    fila, shopee, imagens = calcular(catalog, board, day, agora, ordem)
    payload = _guardar_previa(fila, catalog, board, day, memoria)
    payload["manual"] = ordem == "mine" and ordem_manual(board, day) is not None
    if shopee:
        payload["livros"] = [_livro_json(book) for book in shopee]
        payload["imagens"] = imagens
    return payload


def previa_caixa(catalog, board, day: str, agora: str, ordem: str, memoria: MemoriaPrevia) -> dict:
    """Prévia só com o que está na caixa da extensão."""
    amazon, mercado = catalog.caixa()
    enviados, obras = _enviados(catalog, board, day)
    schedule = board.send_schedule()
    fila = montar_fila(
        [item_de_livro(book) for book in amazon],
        [item_de_livro(book) for book in mercado],
        OpcoesFila(
            agora=agora,
            inicio=schedule.start,
            fim=schedule.end,
            intervalo=schedule.post_interval_minutes,
            enviados=enviados,
            ordem=ordem if ordem in {"mine", "desc", "mix"} else "mine",
            obras_enviadas=obras,
        ),
    )
    return _guardar_previa(fila, catalog, board, day, memoria)


def _guardar_previa(fila, catalog, board, day: str, memoria: MemoriaPrevia) -> dict:
    payload = _payload(fila, board.posts_for(day), catalog)
    payload["previa_id"] = memoria.guardar(payload, fingerprint(board, catalog, day))
    return payload


def aplicar(catalog, board, day: str, previa_id: str, memoria: MemoriaPrevia, cards_dir, **kwargs) -> str:
    with _APPLY_LOCK:
        return _aplicar(catalog, board, day, previa_id, memoria, cards_dir, **kwargs)


def _aplicar(catalog, board, day: str, previa_id: str, memoria: MemoriaPrevia, cards_dir, **kwargs) -> str:
    guardada = memoria.pegar(previa_id)
    if guardada is None:
        raise CatalogError("A prévia expirou. Revise a fila de novo.")
    if guardada["fingerprint"] != fingerprint(board, catalog, day):
        raise CatalogError("A fila mudou desde a prévia. Revise de novo antes de aplicar.")
    payload = guardada["payload"]
    _salvar_desfazer(board, catalog, day)
    if payload.get("livros"):
        from promo_livros.fila_csv import livros_da_previa

        kwargs = {**kwargs, "livros_extra": livros_da_previa(payload)}
    notice = publish_selection(
        catalog,
        board,
        day,
        "00:00",
        cards_dir,
        slots_fixos=payload["slots_ids"],
        sobras_fixas=[(item["store"], item["id"]) for item in payload["amanha"]],
        bloqueados_fixos=[(item["store"], item["id"]) for item in payload["bloqueados"]],
        **kwargs,
    )
    return notice


def desfazer(catalog, board, day: str) -> str:
    raw = board.setting("queue_undo") or ""
    if not raw:
        raise CatalogError("Não há fila anterior para desfazer.")
    payload = json.loads(raw)
    if payload.get("day") != day or time.time() - float(payload.get("at") or 0) > UNDO_SECONDS:
        raise CatalogError("O prazo de desfazer acabou.")
    board.replace_scheduled(day)
    for post in payload["posts"]:
        from promo_livros.board_store import BoardBook

        board.add_post(
            day=day,
            clock=post["clock"],
            caption=post["caption"],
            image_path=post["image_path"],
            books=[
                BoardBook(
                    title=book["title"],
                    blurb=book["blurb"],
                    price_cents=book["price_cents"],
                    list_price_cents=book["list_price_cents"],
                    discount_pct=book["discount_pct"],
                    lowest_label=book["lowest_label"],
                    url=book["url"],
                    coupon=book["coupon"],
                    alt_url=book.get("alt_url") or "",
                    alt_price_cents=book.get("alt_price_cents"),
                    product_id=book.get("product_id") or "",
                )
                for book in post["books"]
            ],
        )
    catalog.restore_picks(payload["picks"])
    board.put_setting("queue_undo", "")
    return "A fila anterior voltou."


def reorganizar(catalog, board, day: str, agora: str, cards_dir, **kwargs) -> str:
    """Recoloca o que ainda não saiu nos horários que ainda cabem, sem repetir enviado."""
    posts = board.posts_for(day)
    if not posts:
        return "Não há posts para reorganizar."
    enviados, obras = _enviados(catalog, board, day)
    amazon, mercado, shopee, extras = _livros_dos_posts(catalog, posts, enviados)
    schedule = board.send_schedule()
    fila = montar_fila(
        [item_de_livro(book) for book in amazon],
        [item_de_livro(book) for book in mercado],
        OpcoesFila(
            agora=agora,
            inicio=schedule.start,
            fim=schedule.end,
            intervalo=schedule.post_interval_minutes,
            enviados=enviados,
            ordem="mine",
            obras_enviadas=obras,
        ),
        shopee=[item_de_livro(book) for book in shopee],
    )
    if not fila.slots:
        return "A janela de hoje já fechou. Os horários não mudaram."
    _salvar_desfazer(board, catalog, day)
    slots_ids = [
        {
            "clock": slot.clock,
            "amazon": slot.amazon.id if slot.amazon else "",
            "ml": slot.ml.id if slot.ml else "",
            "shopee": slot.shopee.id if slot.shopee else "",
            "extra": slot.extra.id if slot.extra else "",
        }
        for slot in fila.slots
    ]
    notice = publish_selection(
        catalog,
        board,
        day,
        agora,
        cards_dir,
        slots_fixos=slots_ids,
        sobras_fixas=[(item.store, item.id) for item in fila.sobras],
        bloqueados_fixos=[(item.item.store, item.item.id) for item in fila.bloqueados],
        livros_extra=extras,
        **kwargs,
    )
    dropped = len(fila.bloqueados)
    if dropped:
        notice = f"{notice} {dropped} já tinham saído e ficaram de fora."
    return notice


def fingerprint(board, catalog, day: str) -> str:
    parts = []
    for post in board.posts_for(day):
        ids = ",".join(sorted(_ids_do_post(post, catalog)))
        parts.append(f"{post.id}|{post.clock}|{ids}")
    sent = _enviados(catalog, board, day)[0]
    sent_part = ",".join(f"{key}:{','.join(clocks)}" for key, clocks in sorted(sent.items()))
    raw = "\n".join(parts) + "\n" + sent_part
    return hashlib.sha256(raw.encode()).hexdigest()


def _payload(fila, posts, catalog) -> dict:
    atual = []
    for post in posts:
        ids = _ids_do_post(post, catalog)
        amazon = next((item for item in ids if not _segunda_loja(item)), "")
        segunda = next((item for item in ids if _segunda_loja(item)), "")
        atual.append((post.clock, amazon, segunda, post.books[0].title if post.books else ""))
    nova = []
    for slot in fila.slots:
        segunda = slot.ml or slot.shopee
        nova.append(
            (
                slot.clock,
                slot.amazon.id if slot.amazon else "",
                segunda.id if segunda else "",
                _titulo_slot(slot),
            )
        )
    atual_set = {(clock, amazon, mercado) for clock, amazon, mercado, _title in atual}
    nova_set = {(clock, amazon, mercado) for clock, amazon, mercado, _title in nova}
    entram = [row for row in nova if (row[0], row[1], row[2]) not in atual_set]
    saem = [row for row in atual if (row[0], row[1], row[2]) not in nova_set]
    continuam = [row for row in nova if (row[0], row[1], row[2]) in atual_set]
    return {
        "slots": [_slot_json(slot) for slot in fila.slots],
        "slots_ids": [
            {
                "clock": slot.clock,
                "amazon": slot.amazon.id if slot.amazon else "",
                "ml": slot.ml.id if slot.ml else "",
                "shopee": slot.shopee.id if slot.shopee else "",
                "extra": slot.extra.id if slot.extra else "",
            }
            for slot in fila.slots
        ],
        "entram": [_diff_json(row) for row in entram],
        "saem": [_diff_json(row) for row in saem],
        "continuam": [_diff_json(row) for row in continuam],
        "bloqueados": [
            {
                "id": item.item.id,
                "store": item.item.store,
                "title": item.item.title,
                "clocks": list(item.clocks),
            }
            for item in fila.bloqueados
        ],
        "amanha": [
            {"id": item.id, "store": item.store, "title": item.title, "discount": item.discount}
            for item in fila.sobras
        ],
        "clocks": list(fila.clocks),
        "avisos": sum(
            len(slot.amazon_avisos) + len(slot.ml_avisos) + len(slot.shopee_avisos) + len(slot.extra_avisos)
            for slot in fila.slots
        ),
    }


def _segunda_loja(product_id: str) -> bool:
    return product_id.startswith("MLB") or is_shopee_product(product_id)


def _slot_json(slot) -> dict:
    return {
        "clock": slot.clock,
        "amazon": _item_json(slot.amazon, slot.amazon_avisos),
        "ml": _item_json(slot.ml, slot.ml_avisos),
        "shopee": _item_json(slot.shopee, slot.shopee_avisos),
        "extra": _item_json(slot.extra, slot.extra_avisos),
    }


def _item_json(item, avisos) -> dict | None:
    if item is None:
        return None
    return {
        "id": item.id,
        "asin": item.id,
        "title": item.title,
        "store": item.store,
        "discount": item.discount,
        "price_cents": item.price_cents,
        "url": item.url,
        "avisos": list(avisos),
    }


def _diff_json(row) -> dict:
    clock, amazon, mercado, title = row
    return {"clock": clock, "amazon": amazon, "ml": mercado, "title": title}


def _titulo_slot(slot) -> str:
    titles = [item.title for item in (slot.amazon, slot.ml, slot.shopee, slot.extra) if item is not None]
    return " · ".join(titles)


def _enviados(catalog, board, day: str) -> tuple[dict[str, tuple[str, ...]], tuple[tuple[str, str], ...]]:
    clocks = board.sent_product_clocks(day)
    obras: list[tuple[str, str]] = []
    missing = []
    for post in _posts_enviados(board, day):
        for book in post.books:
            product_id = (book.product_id or produto_de_url(book.url) or "").upper()
            if not product_id:
                product_id = catalog.id_por_titulo(book.title).upper()
                if product_id:
                    clocks.setdefault(product_id, []).append(post.clock)
            if product_id:
                obras.append((chave_obra(book.title), post.clock))
            else:
                missing.append(book.title)
                obras.append((chave_obra(book.title), post.clock))
    del missing
    unique = {key: tuple(dict.fromkeys(values)) for key, values in clocks.items()}
    return unique, tuple(obras)


def _posts_enviados(board, day: str):
    from datetime import date as date_cls

    window = board.repeat_days()
    end = date_cls.fromisoformat(day)
    start = (end - timedelta(days=max(1, window) - 1)).isoformat()
    rows = []
    with board._lock:
        found = board._connection.execute(
            """
            SELECT id, day, position, clock, caption, image_path, status
            FROM scheduled_posts
            WHERE day >= ? AND day <= ? AND status = 'sent'
            ORDER BY day, clock, id
            """,
            (start, day),
        ).fetchall()
        rows = [board._post(row) for row in found]
    return rows


def _ids_do_post(post, catalog) -> list[str]:
    ids = []
    for book in post.books:
        product_id = (book.product_id or produto_de_url(book.url) or catalog.id_por_titulo(book.title)).upper()
        if product_id:
            ids.append(product_id)
    return ids


def _livros_dos_posts(catalog, posts, enviados: dict[str, tuple[str, ...]]):
    by_id = {book.asin: book for book in (*catalog.books(), *catalog.ml_books())}
    amazon = []
    mercado = []
    shopee = []
    extras = []
    for post in posts:
        for book in post.books:
            product_id = (book.product_id or produto_de_url(book.url) or catalog.id_por_titulo(book.title)).upper()
            if not product_id or product_id in enviados:
                continue
            known = by_id.get(product_id)
            if known is None:
                known = _livro_do_post(book, product_id, _loja_do_post(book, product_id))
                extras.append(known)
            if known.store == "shopee":
                shopee.append(known)
            elif known.store == "ml" or product_id.startswith("MLB"):
                mercado.append(known)
            else:
                amazon.append(known)
    return amazon, mercado, shopee, extras


def _shopee_dos_posts(catalog, posts) -> tuple[list[CatalogBook], dict[str, str]]:
    """Livros da Shopee nos posts que ainda não saíram, na ordem dos horários.

    O post não guarda a foto do anúncio, então a miniatura é o card que o post já tem.
    """
    found: dict[str, CatalogBook] = {}
    imagens: dict[str, str] = {}
    for post in posts:
        for book in post.books:
            product_id = (book.product_id or produto_de_url(book.url) or catalog.id_por_titulo(book.title)).upper()
            if product_id and product_id not in found and _loja_do_post(book, product_id) == "shopee":
                found[product_id] = _livro_do_post(book, product_id, "shopee")
                if post.image_path:
                    imagens[product_id] = f"/cards/{post.id}.jpg"
    return list(found.values()), imagens


def _loja_do_post(book, product_id: str) -> str:
    if is_shopee_product(product_id, book.url):
        return "shopee"
    return "ml" if product_id.startswith("MLB") else "amazon"


def _livro_do_post(book, product_id: str, store: str) -> CatalogBook:
    return CatalogBook(
        asin=product_id,
        position=0,
        title=book.title,
        author="",
        category="",
        price_cents=book.price_cents,
        list_cents=book.list_price_cents,
        low_365=bool(book.lowest_label),
        url=book.url,
        picked=True,
        store=store,
        coupon=book.coupon or "",
    )


def _livro_json(book: CatalogBook) -> dict:
    """Mesmo formato de `livros` da prévia do CSV, para o aplicar reconstruir o livro."""
    return {
        "asin": book.asin,
        "title": book.title,
        "author": book.author,
        "price_cents": book.price_cents,
        "list_cents": book.list_cents,
        "low_365": book.low_365,
        "url": book.url,
        "store": book.store,
        "image_url": book.image_url,
        "coupon": book.coupon,
    }


def _salvar_desfazer(board, catalog, day: str) -> None:
    posts = []
    for post in board.posts_for(day):
        posts.append(
            {
                "clock": post.clock,
                "caption": post.caption,
                "image_path": post.image_path,
                "books": [
                    {
                        "title": book.title,
                        "blurb": book.blurb,
                        "price_cents": book.price_cents,
                        "list_price_cents": book.list_price_cents,
                        "discount_pct": book.discount_pct,
                        "lowest_label": book.lowest_label,
                        "url": book.url,
                        "coupon": book.coupon,
                        "alt_url": book.alt_url,
                        "alt_price_cents": book.alt_price_cents,
                        "product_id": book.product_id,
                    }
                    for book in post.books
                ],
            }
        )
    board.put_setting(
        "queue_undo",
        json.dumps({"at": time.time(), "day": day, "picks": catalog.dump_picks(), "posts": posts}),
    )


def _com_bloqueados(escolhidos: list, todos: list, enviados: dict[str, tuple[str, ...]]) -> list:
    """Quem já saiu continua na prévia como bloqueado, sem voltar para a fila."""
    ids = {book.asin for book in escolhidos}
    extra = [
        book
        for book in todos
        if book.asin in enviados and book.asin not in ids and book.pick_state == "enviado"
    ]
    return [*escolhidos, *extra]


def amanha(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()
