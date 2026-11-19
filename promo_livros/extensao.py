"""Caixa da extensão. A fila do dia só muda quando a prévia é aplicada."""
from __future__ import annotations

import re
import secrets
from urllib.parse import urlparse

from promo_livros.catalog import CatalogError
from promo_livros.fila_aplicar import aplicar, previa_caixa

_TOKEN_KEY = "extension_token"
_PRICE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?")


def token_da_extensao(board) -> str:
    current = (board.setting(_TOKEN_KEY) or "").strip()
    if current:
        return current
    created = secrets.token_urlsafe(24)
    board.put_setting(_TOKEN_KEY, created)
    return created


def atender(
    method: str,
    path: str,
    query: dict[str, list[str]],
    body: dict,
    authorization: str,
    *,
    catalog,
    board,
    day: str,
    agora: str,
    memoria,
    cards_dir,
    resolve_urls,
    resolve_ml,
    thumbnail,
    describe,
) -> tuple[int, dict]:
    expected = token_da_extensao(board)
    if not _token_ok(authorization, expected):
        return 401, {"error": "Token da extensão recusado."}
    try:
        if method == "GET" and path == "/extensao/caixa":
            return 200, _lista(catalog, board, day, agora, memoria)
        if method == "GET" and path == "/extensao/estado":
            return 200, _estado(catalog, _first(query, "id"))
        if method == "POST" and path == "/extensao/livro":
            book = catalog.guardar_na_caixa(
                product_id=_text(body, "id"),
                title=_text(body, "title"),
                price_cents=_cents(body.get("price_cents"), body.get("price")),
                list_cents=_cents(body.get("list_cents"), body.get("list_price"), required=False),
                url=_url_da_loja(_text(body, "url"), _text(body, "id")),
                image_url=_imagem(_text(body, "image")),
                author=_text(body, "author"),
                category=_text(body, "category"),
                day=day,
            )
            plan = previa_caixa(catalog, board, day, agora, _ordem(board, body), memoria)
            return 200, {"ok": True, "book": _livro(book), "place": _lugar(book.asin, plan), "plan": plan}
        if method == "POST" and path == "/extensao/previa":
            chosen = _ordem(board, body)
            board.put_setting("curation_order", chosen)
            return 200, previa_caixa(catalog, board, day, agora, chosen, memoria)
        if method == "POST" and path == "/extensao/aplicar":
            notice = aplicar(
                catalog,
                board,
                day,
                _text(body, "previa_id"),
                memoria,
                cards_dir,
                resolve_urls=resolve_urls,
                resolve_ml=resolve_ml,
                thumbnail=thumbnail,
                describe=describe,
                replace_after=agora,
            )
            return 200, {"ok": True, "message": notice, "plan": previa_caixa(catalog, board, day, agora, _ordem(board, body), memoria)}
        if method == "POST" and path == "/extensao/soltar":
            ids = body.get("ids")
            keys = {str(item).upper() for item in ids} if isinstance(ids, list) else None
            count = catalog.soltar_caixa(keys)
            return 200, {"ok": True, "count": count, "plan": previa_caixa(catalog, board, day, agora, _ordem(board, {}), memoria)}
        if method == "POST" and path == "/extensao/tirar":
            catalog.soltar_caixa({_text(body, "id")})
            return 200, {"ok": True, "plan": previa_caixa(catalog, board, day, agora, _ordem(board, body), memoria)}
        if method == "POST" and path == "/extensao/ordem":
            catalog.mover_caixa(_text(body, "id"), int(body.get("passo") or 0))
            return 200, previa_caixa(catalog, board, day, agora, _ordem(board, body), memoria)
    except CatalogError as exc:
        return 400, {"error": str(exc)}
    except (TypeError, ValueError):
        return 400, {"error": "Não entendi esse pedido."}
    return 404, {"error": "Não achei esse caminho."}


def _lista(catalog, board, day: str, agora: str, memoria) -> dict:
    amazon, mercado = catalog.caixa()
    ordem = board.setting("curation_order") or "mine"
    return {
        "ordem": ordem,
        "books": [_livro(book) for book in (*amazon, *mercado)],
        "plan": previa_caixa(catalog, board, day, agora, ordem, memoria),
    }


def _estado(catalog, product_id: str) -> dict:
    book = catalog.find_book(product_id)
    if book is None:
        return {"id": product_id.upper(), "state": "", "title": ""}
    return {"id": book.asin, "state": book.pick_state, "title": book.title, "store": book.store}


def _lugar(product_id: str, plan: dict) -> dict:
    key = product_id.upper()
    for slot in plan.get("slots") or []:
        for side in ("amazon", "ml"):
            item = slot.get(side) or {}
            if str(item.get("id") or "").upper() == key:
                return {"kind": "fila", "clock": slot.get("clock") or ""}
    for item in plan.get("amanha") or []:
        if str(item.get("id") or "").upper() == key:
            return {"kind": "amanha", "clock": ""}
    for item in plan.get("bloqueados") or []:
        if str(item.get("id") or "").upper() == key:
            clocks = item.get("clocks") or []
            return {"kind": "bloqueado", "clock": clocks[0] if clocks else ""}
    return {"kind": "caixa", "clock": ""}


def _livro(book) -> dict:
    discount = 0
    if book.price_cents and book.list_cents and book.list_cents > book.price_cents:
        discount = round((book.list_cents - book.price_cents) * 100 / book.list_cents)
    return {
        "id": book.asin,
        "store": book.store,
        "title": book.title,
        "price_cents": book.price_cents,
        "discount": discount,
        "state": book.pick_state,
        "image": book.image_url,
    }


def _ordem(board, body: dict) -> str:
    chosen = str(body.get("ordem") or board.setting("curation_order") or "mine")
    return chosen if chosen in {"mine", "desc", "mix"} else "mine"


def _token_ok(authorization: str, expected: str) -> bool:
    raw = (authorization or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if not raw or not expected:
        return False
    return secrets.compare_digest(raw, expected)


def _text(body: dict, key: str) -> str:
    return str(body.get(key) or "").strip()


def _first(query: dict[str, list[str]], key: str) -> str:
    return (query.get(key) or [""])[0].strip()


def _cents(numeric, raw, *, required: bool = True) -> int | None:
    if isinstance(numeric, int) and not isinstance(numeric, bool):
        return numeric if numeric > 0 or not required else numeric
    if isinstance(numeric, float):
        return int(round(numeric))
    text = str(raw or numeric or "").strip()
    if not text:
        return None if not required else 0
    match = _PRICE.search(text.replace(" ", ""))
    if match is None:
        return None if not required else 0
    whole = match.group(1).replace(".", "")
    fraction = (match.group(2) or "0").ljust(2, "0")[:2]
    return int(whole) * 100 + int(fraction)


def _url_da_loja(url: str, product_id: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in {
        "www.amazon.com.br",
        "amazon.com.br",
        "www.mercadolivre.com.br",
        "mercadolivre.com.br",
        "produto.mercadolivre.com.br",
    }:
        raise CatalogError("Use a página do produto na Amazon ou no Mercado Livre.")
    key = product_id.strip().upper()
    if key.startswith("MLB") and "amazon." in host:
        raise CatalogError("O anúncio não bate com a loja.")
    if not key.startswith("MLB") and "mercadolivre" in host:
        raise CatalogError("O anúncio não bate com a loja.")
    return url.split("#", 1)[0][:500]


def _imagem(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    return url.split("#", 1)[0][:500]
