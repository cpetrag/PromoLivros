"""Converte o link da Shopee no short link de afiliado da conta."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

logger = logging.getLogger("promo_livros.shopee_links")

_ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
_SHOPEE_HOSTS = ("shopee.com.br", "s.shopee.com.br", "shope.ee", "shp.ee")
SHOPEE_ID = re.compile(r"^\d{5,12}\.\d{5,14}$")


class ShopeeLinkError(Exception):
    """A API de afiliados da Shopee não devolveu o short link."""


def is_shopee_url(url: str) -> bool:
    host = (urlsplit(url or "").hostname or "").lower().removeprefix("www.")
    return host in _SHOPEE_HOSTS or host.endswith(".shopee.com.br")


def is_shopee_product(product_id: str, url: str = "") -> bool:
    """O id shopid.itemid ou o link dizem que o livro do post é da Shopee."""
    return bool(SHOPEE_ID.fullmatch((product_id or "").strip())) or is_shopee_url(url)


def signature(app_id: str, timestamp: str, payload: str, secret: str) -> str:
    """SHA256(AppId + Timestamp + Payload + Secret), como na documentação da Shopee Brasil."""
    raw = f"{app_id}{timestamp}{payload}{secret}".encode()
    return hashlib.sha256(raw).hexdigest()


def links_de_afiliado(
    urls: list[str],
    app_id: str,
    secret: str,
    sub_id: str = "promolivros",
    *,
    opener=urlopen,
) -> list[str]:
    if not (app_id or "").strip() or not (secret or "").strip():
        raise ShopeeLinkError("Faltam SHOPEE_APP_ID e SHOPEE_SECRET no .env.")
    label = (sub_id or "").strip() or "promolivros"
    return [
        affiliate_url(url, app_id=app_id, secret=secret, sub_id=label, opener=opener)
        for url in urls
    ]


def affiliate_url(
    url: str,
    *,
    app_id: str,
    secret: str,
    sub_id: str = "promolivros",
    opener=urlopen,
    now: int | None = None,
) -> str:
    origin = (url or "").strip()
    if not origin:
        raise ShopeeLinkError("Falta o link da Shopee.")
    timestamp = str(int(now if now is not None else time.time()))
    query = (
        "mutation { generateShortLink(input: {"
        f"originUrl: {json.dumps(origin)}, subIds: [{json.dumps(sub_id)}]"
        "}) { shortLink } }"
    )
    payload = json.dumps({"query": query}, separators=(",", ":"), ensure_ascii=True)
    sign = signature(app_id, timestamp, payload, secret)
    request = Request(
        _ENDPOINT,
        data=payload.encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": (
                f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={sign}"
            ),
        },
        method="POST",
    )
    try:
        with opener(request, timeout=20) as response:
            body = json.loads(response.read().decode())
    except HTTPError as exc:
        raise ShopeeLinkError(f"A Shopee recusou o link ({exc.code}).") from exc
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise ShopeeLinkError("A Shopee não gerou o link de afiliado.") from exc
    errors = body.get("errors") if isinstance(body, dict) else None
    if errors:
        message = " ".join(str(item.get("message") or "") for item in errors if isinstance(item, dict))
        raise ShopeeLinkError(message.strip() or "A Shopee não gerou o link de afiliado.")
    data = body.get("data") if isinstance(body, dict) else None
    short = ""
    if isinstance(data, dict):
        result = data.get("generateShortLink") or {}
        if isinstance(result, dict):
            short = str(result.get("shortLink") or "").strip()
    if not short.startswith("https://"):
        raise ShopeeLinkError("A Shopee não gerou o link de afiliado.")
    return short
