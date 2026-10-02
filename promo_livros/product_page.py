"""Lê capa, sinopse e cupom na página do produto. Não envia nada."""
from __future__ import annotations

import re
import time

_EXTRACT = r"""
() => {
  const title = document.querySelector('#productTitle')?.innerText?.trim() || '';
  const img = document.querySelector('#landingImage, #imgBlkFront, #ebooksImgBlkFront')?.src || '';
  const descNode = document.querySelector('#bookDescription_feature_div, #productDescription, #editorialReviews_feature_div');
  const desc = (descNode?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 500);
  const cupomNodes = [...document.querySelectorAll('[id*="coupon" i], [class*="coupon" i], #promoPriceBlockMessage_feature_div, #dealBadge_feature_div')];
  const cupom = cupomNodes.map(n => n.innerText.replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 4);
  const crumbs = [...document.querySelectorAll('#wayfinding-breadcrumbs_feature_div a, #wayfinding-breadcrumbs_container a')]
    .map(node => (node.innerText || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean);
  return {title, img, desc, cupom, crumbs};
}
"""


def read_product_pages(books: list[dict]) -> list[dict]:
    from playwright.sync_api import sync_playwright

    found: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="pt-BR", viewport={"width": 1280, "height": 900})
        try:
            for book in books:
                row, blocked = _read_one(page, book)
                found.append(row)
                if blocked:
                    break
                time.sleep(1.2)
        finally:
            browser.close()
    return found


def _read_one(page, book: dict) -> tuple[dict, bool]:
    url = str(book.get("url") or "").split("?")[0]
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    if "captcha" in page.url.lower():
        return _row(book, "", "", "", []), True
    try:
        page.wait_for_selector("#productTitle", timeout=12000)
    except Exception:
        pass
    data = page.evaluate(_EXTRACT)
    coupons = list(data.get("cupom") or [])
    for line in re.findall(r"(?i)cupom[^\n]{0,90}", page.inner_text("body")):
        clean = " ".join(line.split())
        if clean not in coupons:
            coupons.append(clean)
    return (
        _row(
            book,
            data.get("title") or "",
            data.get("img") or "",
            data.get("desc") or "",
            coupons[:4],
            crumbs=list(data.get("crumbs") or []),
        ),
        False,
    )


def _row(
    book: dict,
    title: str,
    cover: str,
    synopsis: str,
    coupons: list[str],
    crumbs: list[str] | None = None,
) -> dict:
    category = " / ".join(crumb for crumb in crumbs or [] if crumb.casefold() != "livros")
    return {
        **book,
        "pagina_titulo": title,
        "capa": cover,
        "sinopse": synopsis,
        "cupom": coupons,
        "categoria": category or book.get("categoria") or "",
    }
