"""De qual loja é um livro já gravado num post."""
from __future__ import annotations

from promo_livros.magalu_links import is_magalu_url
from promo_livros.ml_links import is_ml_url
from promo_livros.shopee_links import is_shopee_product

STORE_ORDER = {"amazon": 0, "ml": 1, "shopee": 2, "magalu": 3}


def store_of(book) -> str:
    product_id = (getattr(book, "product_id", "") or "").strip()
    url = getattr(book, "url", "") or ""
    if is_magalu_url(url):
        return "magalu"
    if is_shopee_product(product_id, url):
        return "shopee"
    if product_id.upper().startswith("MLB") or is_ml_url(url):
        return "ml"
    return "amazon"
