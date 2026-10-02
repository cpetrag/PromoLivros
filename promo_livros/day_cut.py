"""Corte da vitrine da Amazon e o encaixe dos posts do dia."""
from __future__ import annotations

import csv
from pathlib import Path

DEALS_URL = (
    "https://www.amazon.com.br/s?k=livro&i=todays-deals"
    "&bbn=21167071011&rh=n:21167071011,p_85:19171728011&s=review-rank"
)
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
TARGET_PASSERS = 66
MAX_ASINS = 400
MAX_BOOKS = 60
MAX_POSTS = 60
KEEPA_BATCH = 20
INFANTIL_SHARE = 0.10


def load_vitrine(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    ordered = sorted(rows, key=lambda row: (_int(row, "lote"), _int(row, "posicao")))
    chosen = []
    for row in ordered:
        if _int(row, "patrocinado") != 0:
            continue
        if (_num(row, "n_avaliacoes") or 0) < 500:
            continue
        if (_num(row, "nota") or 0) < 4.5:
            continue
        if (_num(row, "desconto_pct") or 0) < 30:
            continue
        chosen.append(row)
    return chosen


def from_keepa(row: dict, product: dict, place: int) -> dict:
    stats = product.get("stats") if isinstance(product.get("stats"), dict) else {}
    current = _stat_price(stats, "current", 0)
    avg90 = _stat_price(stats, "avg90", 0)
    min120 = _stat_price(stats, "minInInterval", 0)
    rank = _stat_price(stats, "current", 3)
    drop = None
    if current and avg90 and avg90 > current:
        drop = round((avg90 - current) * 100 / avg90, 1)
    return {
        "asin": row.get("asin") or product.get("asin") or "",
        "titulo": row.get("titulo") or "",
        "lugar_vitrine": place,
        "preco": round(current / 100, 2) if current else _num(row, "preco"),
        "preco_de": _num(row, "preco_de"),
        "off_pagina": _num(row, "desconto_pct"),
        "no_menor_120": bool(current and min120 and current <= min120),
        "queda_vs_media": drop,
        "rank": rank,
        "url": row.get("url") or "",
        "categoria": category_path(product),
    }


def passes(item: dict) -> bool:
    rank = item.get("rank")
    drop = item.get("queda_vs_media")
    title = (item.get("titulo") or "").casefold()
    if any(word in title for word in JUNK):
        return False
    if not item.get("no_menor_120"):
        return False
    if not isinstance(drop, (int, float)) or drop < 10:
        return False
    return isinstance(rank, int) and 0 < rank <= 5000


def category_path(product: dict) -> str:
    tree = product.get("categoryTree")
    if not isinstance(tree, list):
        return ""
    names = []
    for node in tree:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "").strip()
        if name and name.casefold() != "livros":
            names.append(name)
    return " / ".join(names)


def is_infantil(item: dict) -> bool:
    text = (item.get("categoria") or "").casefold()
    return "infantil" in text or "infantojuvenil" in text


def take_with_infantil_cap(ranked: list[dict], slots: int, *, spare: int = 0) -> list[dict]:
    """Enche a grade e deixa infantil em no máximo 10% dos posts do dia."""
    if slots <= 0:
        return []
    allowed = int(slots * INFANTIL_SHARE)
    limit = slots + max(spare, 0)
    picked: list[dict] = []
    kids = 0
    for item in ranked:
        if len(picked) >= limit:
            break
        if is_infantil(item):
            if kids >= allowed:
                continue
            kids += 1
        picked.append(item)
    return picked


def rank_passers(items: list[dict]) -> list[dict]:
    ok = [item for item in items if passes(item)]
    by_drop = sorted(ok, key=lambda item: float(item["queda_vs_media"]), reverse=True)
    drop_place = {item["asin"]: index for index, item in enumerate(by_drop, start=1)}
    scored = []
    for item in ok:
        score = 1 / (60 + int(item["lugar_vitrine"])) + 1 / (60 + drop_place[item["asin"]])
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in scored]


def post_sizes(book_count: int, *, max_posts: int = MAX_POSTS) -> list[int]:
    count = min(book_count, max_posts, MAX_POSTS)
    return [1] * max(count, 0)


def clocks(count: int) -> list[str]:
    from promo_livros.send_schedule import plan_day_clocks

    return plan_day_clocks("08:00", count)


def _stat_price(stats: dict, field: str, index: int) -> int | None:
    values = stats.get(field)
    if not isinstance(values, list) or index >= len(values):
        return None
    entry = values[index]
    if isinstance(entry, list) and len(entry) >= 2:
        entry = entry[1]
    if isinstance(entry, int) and entry > 0:
        return entry
    return None


def _int(row: dict, key: str) -> int:
    try:
        return int(float(row.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _num(row: dict, key: str) -> float | None:
    raw = row.get(key)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
