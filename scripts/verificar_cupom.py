"""Abre a página de cada livro da fila e lê capa, sinopse e cupom. Não envia nada."""
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "mix_keepa_fila.json"
OUT = ROOT / "data" / "fila_paginas.json"
JUNK = (
    "colorir",
    "colorindo",
    "fisher-price",
    "fisher price",
    "banho",
    "tapete",
    "atividade",
    "bebê",
    "bebe",
    "baby",
    "contraste",
    "tummy",
    "montessori",
)
EXTRACT = r"""
() => {
  const title = document.querySelector('#productTitle')?.innerText?.trim() || '';
  const img = document.querySelector('#landingImage, #imgBlkFront, #ebooksImgBlkFront')?.src || '';
  const descNode = document.querySelector('#bookDescription_feature_div, #productDescription, #editorialReviews_feature_div');
  const desc = (descNode?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 500);
  const cupomNodes = [...document.querySelectorAll('[id*="coupon" i], [class*="coupon" i], #promoPriceBlockMessage_feature_div, #dealBadge_feature_div')];
  const cupom = cupomNodes.map(n => n.innerText.replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 4);
  return {title, img, desc, cupom};
}
"""


def passes(item):
    rank = item.get("rank") or 10**9
    drop = item.get("queda_vs_media") or -1
    title = (item.get("titulo") or "").casefold()
    if any(word in title for word in JUNK):
        return False
    return bool(item.get("no_menor_120")) and drop >= 10 and rank <= 5000


def ranked():
    items = json.loads(SRC.read_text(encoding="utf-8"))
    ok = [item for item in items if passes(item)]
    drop_order = sorted(ok, key=lambda item: item["queda_vs_media"], reverse=True)
    drop_place = {item["asin"]: index for index, item in enumerate(drop_order, start=1)}
    for item in ok:
        item["nota_mista"] = 1 / (60 + item["lugar_vitrine"]) + 1 / (60 + drop_place[item["asin"]])
    ok.sort(key=lambda item: item["nota_mista"], reverse=True)
    return ok[:30]


def main():
    books = ranked()
    found = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="pt-BR", viewport={"width": 1280, "height": 900})
        for index, book in enumerate(books, start=1):
            url = book["url"].split("?")[0]
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if "captcha" in page.url.lower():
                print(f"[{index}] captcha em {book['asin']}", flush=True)
                found.append({**book, "pagina_titulo": "", "capa": "", "sinopse": "", "cupom": [], "erro": "captcha"})
                break
            try:
                page.wait_for_selector("#productTitle", timeout=12000)
            except Exception:
                print(f"[{index}] sem título {book['asin']}", flush=True)
            data = page.evaluate(EXTRACT)
            body = page.inner_text("body")
            extra = re.findall(r"(?i)cupom[^\n]{0,90}", body)
            coupons = data.get("cupom") or []
            for line in extra:
                clean = " ".join(line.split())
                if clean not in coupons:
                    coupons.append(clean)
            row = {
                "asin": book["asin"],
                "titulo": book["titulo"],
                "preco": book["preco"],
                "preco_de": book.get("preco_de"),
                "off_pagina": book.get("off_pagina"),
                "queda_vs_media": book.get("queda_vs_media"),
                "url": book["url"],
                "pagina_titulo": data.get("title") or "",
                "capa": data.get("img") or "",
                "sinopse": data.get("desc") or "",
                "cupom": coupons[:4],
            }
            found.append(row)
            print(f"[{index}] {book['asin']} cupom={len(coupons)} capa={'sim' if row['capa'] else 'não'}", flush=True)
            time.sleep(1.2)
        browser.close()
    OUT.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"salvos {len(found)}", flush=True)


if __name__ == "__main__":
    main()
