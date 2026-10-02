"""Confere link e preço de um post sem participar do envio."""
from __future__ import annotations

import re

import requests

from promo_livros.ml_links import is_ml_url
from promo_livros.models import PRICE_AMAZON, PRICE_BUY_BOX_SHIPPING

_ASIN = re.compile(r"(?:/dp/|/gp/product/|/gp/aw/d/|[?&]asin=)([A-Z0-9]{10})", re.I)
_UA = {"User-Agent": "promo-livros/1.0"}


def asin_in(url: str) -> str | None:
    match = _ASIN.search(url or "")
    if match is None:
        return None
    return match.group(1).upper()


def resolve_asin(url: str) -> tuple[str | None, str]:
    """Devolve o ASIN e um estado: ok, broken ou unknown.

    unknown significa que a rede não respondeu. Isso não marca o post como falha.
    """
    found = asin_in(url)
    if found:
        return found, "ok"
    if not (url or "").startswith("http"):
        return None, "broken"
    try:
        response = requests.get(url, allow_redirects=True, timeout=6, headers=_UA)
    except requests.RequestException:
        return None, "unknown"
    if response.status_code >= 400:
        return None, "broken"
    found = asin_in(str(response.url))
    if found:
        return found, "ok"
    return None, "unknown"


def live_cents(product: dict) -> int | None:
    stats = product.get("stats") if isinstance(product.get("stats"), dict) else {}
    for index in (PRICE_AMAZON, PRICE_BUY_BOX_SHIPPING):
        cents = _positive(stats, index)
        if cents is not None:
            return cents
    return None


def judge(product: dict | None, stored_cents: int) -> tuple[str, int | None]:
    """ok, price, broken ou unavailable, e o preço atual em centavos quando existe."""
    if not isinstance(product, dict) or not product.get("asin"):
        return "broken", None
    cents = live_cents(product)
    if cents is None:
        if product.get("availabilityAmazon") == 0:
            return "ok", None
        return "unavailable", None
    if stored_cents and cents != stored_cents:
        return "price", cents
    return "ok", cents


def check_scheduled(store, day: str, *, client_factory) -> None:
    """Atualiza o cache dos posts ainda não enviados. No máximo oito por vez."""
    pending = []
    for post in store.posts_for(day):
        if store.check_is_fresh(post.id):
            continue
        if not post.books:
            continue
        pending.append(post)
        if len(pending) >= 8:
            break
    if not pending:
        return
    resolved: list[tuple[object, str | None, str]] = []
    asins: list[str] = []
    for post in pending:
        url = next((book.url for book in post.books if book.url and not is_ml_url(book.url)), "")
        if not url:
            alt = post.books[0].alt_url
            if alt and not is_ml_url(alt):
                url = alt
        if not url or is_ml_url(url):
            store.save_check(post.id, "unknown", None)
            continue
        asin, link_state = resolve_asin(url)
        resolved.append((post, asin, link_state))
        if link_state == "ok" and asin:
            asins.append(asin)
    products: dict[str, dict] = {}
    priced = False
    if asins and client_factory is not None:
        client = client_factory()
        if client is not None:
            try:
                for product in client.deal_stats(asins):
                    key = str(product.get("asin") or "").upper()
                    if key:
                        products[key] = product
                priced = True
            except Exception:
                priced = False
            finally:
                close = getattr(client, "close", None)
                if close is not None:
                    close()
    for post, asin, link_state in resolved:
        stored = post.books[0].price_cents
        if link_state == "broken":
            _remember(store, day, post.id, "broken", None)
            continue
        if link_state != "ok" or not asin:
            store.save_check(post.id, "unknown", None)
            continue
        if not priced:
            store.save_check(post.id, "unknown", None)
            continue
        state, cents = judge(products.get(asin), stored)
        _remember(store, day, post.id, state, cents)


def _remember(store, day: str, post_id: int, state: str, cents: int | None) -> None:
    store.save_check(post_id, state, cents)
    if state in {"broken", "unavailable"}:
        store.fail_if_unsent(day, post_id)


def _positive(stats: dict, index: int) -> int | None:
    values = stats.get("current")
    if not isinstance(values, list) or index >= len(values):
        return None
    entry = values[index]
    if isinstance(entry, list) and len(entry) >= 2:
        entry = entry[1]
    if isinstance(entry, bool) or not isinstance(entry, int) or entry <= 0:
        return None
    return entry
