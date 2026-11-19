"""De qual loja é um livro já gravado num post."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from promo_livros.magalu_links import is_magalu_url
from promo_livros.ml_links import is_ml_url
from promo_livros.shopee_links import is_shopee_product

STORE_ORDER = {"amazon": 0, "ml": 1, "shopee": 2, "magalu": 3}

_ASIN = re.compile(r"^[A-Z0-9]{10}$")
# O Aqui só encurta links da Magazine Luiza; depois de aplicada a fila, o post guarda o link curto.
_AQUI_HOSTS = ("aqui.descontos.ai",)
_AMAZON_HOSTS = ("amazon.", "amzn.")


def store_of(book) -> str:
    product_id = (getattr(book, "product_id", "") or "").strip()
    url = getattr(book, "url", "") or ""
    host = (urlsplit(url).hostname or "").lower()
    if is_magalu_url(url) or host in _AQUI_HOSTS:
        return "magalu"
    if is_shopee_product(product_id, url):
        return "shopee"
    if product_id.upper().startswith("MLB") or is_ml_url(url):
        return "ml"
    if product_id and not _ASIN.fullmatch(product_id.upper()) and not _is_amazon_host(host):
        return "magalu"
    return "amazon"


def _is_amazon_host(host: str) -> bool:
    return any(marker in host for marker in _AMAZON_HOSTS)
