"""Teste: vitrine do crawler + queda real no Keepa. Não mexe na fila."""
import csv
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CSV_IN = ROOT / "data" / "amazon_ofertas_full.csv"
OUT_JSON = ROOT / "data" / "mix_keepa_120.json"
OUT_CSV = ROOT / "data" / "mix_keepa_top50.csv"
AMAZON = 0
SALES = 3
CAP = 120
BATCH = 20


def num(row, key):
    raw = row.get(key) or ""
    try:
        return float(raw)
    except ValueError:
        return None


def reais(cents):
    if cents is None or cents <= 0:
        return None
    return round(cents / 100, 2)


def stat_price(stats, field, index):
    values = stats.get(field)
    if not isinstance(values, list) or index >= len(values):
        return None
    entry = values[index]
    if isinstance(entry, list) and len(entry) >= 2:
        entry = entry[1]
    if isinstance(entry, int) and entry > 0:
        return entry
    return None


def select_rows():
    rows = list(csv.DictReader(CSV_IN.open(encoding="utf-8-sig"), delimiter=";"))
    chosen = []
    for row in sorted(rows, key=lambda r: (int(r["lote"]), int(r["posicao"]))):
        if (row.get("patrocinado") or "0") != "0":
            continue
        reviews = num(row, "n_avaliacoes") or 0
        rating = num(row, "nota") or 0
        off = num(row, "desconto_pct") or 0
        if reviews >= 500 and rating >= 4.5 and off >= 30:
            chosen.append(row)
    return chosen[:CAP], len(chosen)


def fetch_batch(session, key, asins):
    response = session.get(
        "https://api.keepa.com/product",
        params={
            "key": key,
            "domain": 12,
            "asin": ",".join(asins),
            "stats": 120,
            "history": 0,
        },
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    products = payload.get("products") or []
    left = payload.get("tokensLeft")
    print(
        f"  lote {len(asins)} asin -> {len(products)} produtos, tokens {left}",
        flush=True,
    )
    return products if isinstance(products, list) else [], left


def category_name(product):
    tree = product.get("categoryTree")
    if not isinstance(tree, list) or not tree:
        return ""
    names = [node.get("name", "") for node in tree if isinstance(node, dict)]
    names = [name for name in names if name and name != "Livros"]
    return names[-1] if names else ""


def enrich(row, product):
    stats = product.get("stats") if isinstance(product.get("stats"), dict) else {}
    current = stat_price(stats, "current", AMAZON)
    avg90 = stat_price(stats, "avg90", AMAZON)
    min120 = stat_price(stats, "minInInterval", AMAZON)
    min_all = stat_price(stats, "min", AMAZON)
    rank = stat_price(stats, "current", SALES)
    drops = stats.get("salesRankDrops30")
    drop_pct = None
    if current and avg90 and avg90 > current:
        drop_pct = round((avg90 - current) * 100 / avg90, 1)
    at_low = bool(current and min120 and current <= min120)
    return {
        "asin": row["asin"],
        "titulo": row["titulo"],
        "lugar_vitrine": None,
        "preco": reais(current) if current else num(row, "preco"),
        "preco_de": num(row, "preco_de"),
        "off_pagina": num(row, "desconto_pct"),
        "menor_120": reais(min120),
        "no_menor_120": at_low,
        "menor_historico": reais(min_all),
        "media_90": reais(avg90),
        "queda_vs_media": drop_pct,
        "rank": rank,
        "quedas_rank_30": drops if isinstance(drops, int) else None,
        "categoria": category_name(product),
        "nota": num(row, "nota"),
        "avaliacoes": int(num(row, "n_avaliacoes") or 0),
        "badge_365": row.get("menor_preco_365") == "1",
        "url": row["url"],
    }


def main():
    load_dotenv(ROOT / ".env")
    key = os.environ.get("KEEPA_API_KEY", "").strip()
    if not key:
        raise SystemExit("KEEPA_API_KEY ausente")
    picked, eligible = select_rows()
    print(f"elegiveis {eligible}, enviados ao Keepa {len(picked)}", flush=True)
    session = requests.Session()
    by_asin = {}
    for start in range(0, len(picked), BATCH):
        chunk = [row["asin"] for row in picked[start : start + BATCH]]
        products, left = [], None
        for attempt in range(6):
            products, left = fetch_batch(session, key, chunk)
            if products:
                break
            print("  sem produtos, esperando tokens", flush=True)
            time.sleep(70)
        for product in products:
            if isinstance(product, dict) and product.get("asin"):
                by_asin[product["asin"]] = product
        if isinstance(left, int) and left < 25 and start + BATCH < len(picked):
            wait = int((30 - min(left, 30)) / 5 * 60) + 5
            print(f"  saldo {left}, pausa {wait}s", flush=True)
            time.sleep(wait)

    items = []
    for place, row in enumerate(picked, start=1):
        product = by_asin.get(row["asin"])
        if not product:
            continue
        item = enrich(row, product)
        item["lugar_vitrine"] = place
        items.append(item)

    ranked = sorted(
        [item for item in items if item["queda_vs_media"] is not None],
        key=lambda item: item["queda_vs_media"],
        reverse=True,
    )
    drop_place = {item["asin"]: index for index, item in enumerate(ranked, start=1)}
    missing = len(items) + 1
    for item in items:
        drop_index = drop_place.get(item["asin"], missing)
        item["lugar_queda"] = drop_index
        item["nota_mista"] = round(
            1 / (60 + item["lugar_vitrine"]) + 1 / (60 + drop_index),
            6,
        )
    items.sort(key=lambda item: item["nota_mista"], reverse=True)
    OUT_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    top = items[:50]
    if top:
        with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(top[0].keys()), delimiter=";")
            writer.writeheader()
            writer.writerows(top)
    lows = sum(1 for item in items if item["no_menor_120"])
    print(f"com dados {len(items)}, no menor de 120 dias {lows}, top {len(top)}", flush=True)


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
FILA_JSON = ROOT / "data" / "mix_keepa_fila.json"


def passes(item):
    rank = item.get("rank") or 10**9
    drop = item.get("queda_vs_media") or -1
    title = (item.get("titulo") or "").casefold()
    if any(word in title for word in JUNK):
        return False
    return bool(item.get("no_menor_120")) and drop >= 10 and rank <= 5000


def continuar():
    """Segue a vitrine depois dos 120 já lidos, até ter folga para uma fila de ~30."""
    load_dotenv(ROOT / ".env")
    key = os.environ.get("KEEPA_API_KEY", "").strip()
    if not key:
        raise SystemExit("KEEPA_API_KEY ausente")
    all_rows, eligible = select_rows()
    # select_rows corta em CAP. Aqui a fila olha o restante do mesmo corte.
    rows = list(csv.DictReader(CSV_IN.open(encoding="utf-8-sig"), delimiter=";"))
    ordered = []
    for row in sorted(rows, key=lambda r: (int(r["lote"]), int(r["posicao"]))):
        if (row.get("patrocinado") or "0") != "0":
            continue
        reviews = num(row, "n_avaliacoes") or 0
        rating = num(row, "nota") or 0
        off = num(row, "desconto_pct") or 0
        if reviews >= 500 and rating >= 4.5 and off >= 30:
            ordered.append(row)
    seen = {}
    if OUT_JSON.exists():
        for item in json.loads(OUT_JSON.read_text(encoding="utf-8")):
            seen[item["asin"]] = item
    pending = [(place, row) for place, row in enumerate(ordered, start=1) if row["asin"] not in seen]
    print(f"elegiveis {len(ordered)} (antes {eligible}/{len(all_rows)}), ja lidos {len(seen)}, faltam {len(pending)}", flush=True)
    session = requests.Session()
    target = 36
    fetched = 0
    for start in range(0, len(pending), BATCH):
        if sum(1 for item in seen.values() if passes(item)) >= target:
            break
        chunk_rows = pending[start : start + BATCH]
        chunk = [row["asin"] for _, row in chunk_rows]
        products, left = [], None
        for _attempt in range(6):
            products, left = fetch_batch(session, key, chunk)
            if products:
                break
            print("  sem produtos, esperando tokens", flush=True)
            time.sleep(70)
        by_asin = {}
        for product in products:
            if isinstance(product, dict) and product.get("asin"):
                by_asin[product["asin"]] = product
        for place, row in chunk_rows:
            product = by_asin.get(row["asin"])
            if not product:
                continue
            item = enrich(row, product)
            item["lugar_vitrine"] = place
            seen[row["asin"]] = item
        fetched += len(chunk)
        ready = sum(1 for item in seen.values() if passes(item))
        print(f"  lidos agora {fetched}, passam no corte {ready}", flush=True)
        if isinstance(left, int) and left < 25:
            wait = int((30 - min(left, 30)) / 5 * 60) + 5
            print(f"  saldo {left}, pausa {wait}s", flush=True)
            time.sleep(max(wait, 1))
        if fetched >= 200 and ready >= 30:
            break

    items = list(seen.values())
    FILA_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    ready_items = [item for item in items if passes(item)]
    ready_items.sort(key=lambda item: (item["lugar_vitrine"], -(item["queda_vs_media"] or 0)))
    print(f"corte final {len(ready_items)} de {len(items)} lidos", flush=True)


if __name__ == "__main__":
    continuar()
