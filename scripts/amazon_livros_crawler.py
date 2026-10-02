#!/usr/bin/env python3
"""
Crawler de busca da Amazon.com.br (livros) -> SQLite + CSV.

A busca atual da Amazon não tem mais "página 2, 3...": no fim da lista há o botão
"Mostrar mais resultados", que adiciona itens por clique. O crawler clica nele
até o botão sumir (ou até --max-itens), extraindo só os ASINs novos a cada rodada.
Se a Amazon mostrar a paginação clássica (link "Próximo"), ele segue esse link.

Para passar do limite de resultados que a Amazon exibe por busca, use --faixas:
a mesma busca é repetida por faixa de preço (low-price/high-price) e tudo é
deduplicado por ASIN.

Uso:
  python scripts/amazon_livros_crawler.py --busca "livro"
  python scripts/amazon_livros_crawler.py --url "https://www.amazon.com.br/s?k=livro&i=todays-deals&..." --max-itens 48
  python scripts/amazon_livros_crawler.py --busca "livro" --faixas "0-15,15-30,30-50,50-80,80-150,150-"
"""
import argparse
import csv
import os
import random
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.sync_api import sync_playwright

BADGE_TXT = "Menor preço em 365 dias"
CARD = 'div[data-component-type="s-search-result"][data-asin]'
BTN_MAIS = '[class*="template=PAGINATION"] input.a-button-input'
LINK_PROX = "a.s-pagination-next:not(.s-pagination-disabled)"
ROOT = Path(__file__).resolve().parents[1]

EXTRACT_JS = r"""
([badgeTxt, vistos]) => {
  const seen = new Set(vistos);
  const out = [];
  let vazios = 0;
  document.querySelectorAll('%s').forEach((c, idx) => {
    const asin = c.dataset.asin;
    if (!c.querySelector('h2')) { vazios++; return; }
    const patro = /Patrocinado/.test(c.innerText);
    const key = asin + '|' + (patro ? 1 : 0);
    if (!asin || seen.has(key)) return;
    seen.add(key);
    const q = s => c.querySelector(s);
    const badges = [...c.querySelectorAll('.a-badge-text')].map(b => b.textContent.trim());
    const star = q('i[class*="a-icon-star"] .a-icon-alt, span.a-icon-alt');
    const rev = c.innerText.match(/estrelas\s*\(([\d.,]+\s*(mil)?)\)/i);
    const preco = (q('[data-cy="price-recipe"] .a-price:not(.a-text-price) .a-offscreen')
                || q('.a-price:not(.a-text-price) .a-offscreen'))?.textContent || null;
    const de = (q('[data-cy="price-recipe"] .a-price.a-text-price .a-offscreen')
             || q('.a-price.a-text-price .a-offscreen'))?.textContent || null;
    out.push({
      key, asin, posicao: idx + 1,
      titulo: (q('h2')?.textContent || '').trim(),
      preco, preco_de: de,
      menor_preco_365: badges.some(t => t.includes(badgeTxt)),
      outros_badges: badges.filter(t => !t.includes(badgeTxt)).join(' | '),
      patrocinado: patro,
      nota: star ? star.textContent.split(' ')[0] : null,
      n_avaliacoes: rev ? rev[1] : null,
    });
  });
  return {itens: out, vazios};
}
""" % CARD


def brl(txt):
    """'R$ 1.234,56' -> 1234.56. Zero vira None (preço Kindle Unlimited)."""
    if not txt:
        return None
    n = re.sub(r"[^\d,]", "", txt).replace(",", ".")
    try:
        v = float(n)
    except ValueError:
        return None
    return v or None


def n_aval(txt):
    if not txt:
        return None
    v = float(re.sub(r"[^\d,]", "", txt).replace(",", ".") or 0)
    return int(v * 1000) if "mil" in txt else int(v)


def affiliate_tag():
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    return os.environ.get("AMAZON_AFFILIATE_TAG", "").strip()


def product_url(asin, tag):
    url = f"https://www.amazon.com.br/dp/{asin}"
    return f"{url}?tag={tag}" if tag else url


def set_params(base, **params):
    u = urlparse(base)
    qs = parse_qs(u.query)
    for k, v in params.items():
        if v is None:
            qs.pop(k, None)
        else:
            qs[k] = [str(v)]
    return urlunparse(u._replace(query=urlencode(qs, doseq=True)))


def parse_faixas(s):
    """'0-15,15-30,150-' -> [(0,15),(15,30),(150,None)]"""
    out = []
    for parte in s.split(","):
        lo, _, hi = parte.strip().partition("-")
        out.append((int(lo) if lo else None, int(hi) if hi else None))
    return out


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS snapshots (
      asin TEXT, coletado_em TEXT, busca TEXT, faixa TEXT, lote INT, posicao INT,
      titulo TEXT, preco REAL, preco_de REAL, desconto_pct REAL,
      menor_preco_365 INT, outros_badges TEXT, patrocinado INT,
      nota REAL, n_avaliacoes INT, url TEXT,
      PRIMARY KEY (asin, coletado_em, patrocinado)
    );
    CREATE INDEX IF NOT EXISTS ix_snap_asin ON snapshots(asin);
    """)
    return db


def captcha(pg):
    return "captcha" in pg.url.lower() or pg.query_selector("form[action*='validateCaptcha']")


def rolar_fim(pg):
    for _ in range(3):
        pg.mouse.wheel(0, 4000)
        time.sleep(0.4)


def coletar_url(pg, url, faixa_lbl, vistos, args, agora, busca_lbl, tag):
    """Percorre os resultados de uma URL de busca. Retorna linhas novas e se parou no captcha."""
    linhas = []
    pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    lote = 1
    sem_novos = 0
    while True:
        if captcha(pg):
            print("[!] CAPTCHA na página. Rode de novo sem --headless e resolva no navegador.")
            return linhas, True
        try:
            pg.wait_for_selector(CARD, timeout=15000)
        except Exception:
            print(f"  [fim] sem resultados ({faixa_lbl}) url={pg.url}")
            break
        rolar_fim(pg)

        res = pg.evaluate(EXTRACT_JS, [BADGE_TXT, list(vistos)])
        novos = res["itens"]
        for it in novos:
            vistos.add(it["key"])
            preco, de = brl(it["preco"]), brl(it["preco_de"])
            linhas.append({
                "asin": it["asin"],
                "coletado_em": agora,
                "busca": busca_lbl,
                "faixa": faixa_lbl,
                "lote": lote,
                "posicao": it["posicao"],
                "titulo": it["titulo"],
                "preco": preco,
                "preco_de": de,
                "desconto_pct": round((1 - preco / de) * 100, 1) if preco and de and de > preco else None,
                "menor_preco_365": int(it["menor_preco_365"]),
                "outros_badges": it["outros_badges"],
                "patrocinado": int(it["patrocinado"]),
                "nota": brl(it["nota"]),
                "n_avaliacoes": n_aval(it["n_avaliacoes"]),
                "url": product_url(it["asin"], tag),
            })
        badges = sum(1 for x in novos if x["menor_preco_365"])
        print(f"  [{faixa_lbl} lote {lote}] +{len(novos)} novos ({badges} com badge) | total {len(vistos)}")

        sem_novos = sem_novos + 1 if not novos else 0
        if sem_novos >= 3:
            print("  [fim] 3 rodadas sem itens novos")
            break
        if args.max_itens and len(vistos) >= args.max_itens:
            print(f"  [fim] atingiu --max-itens {args.max_itens}")
            break

        time.sleep(random.uniform(args.espera_min, args.espera_max))
        btn = pg.query_selector(BTN_MAIS)
        prox = pg.query_selector(LINK_PROX)
        if btn:
            antes = pg.locator(CARD).count()
            btn.scroll_into_view_if_needed()
            btn.click()
            try:
                pg.wait_for_function(
                    f"document.querySelectorAll('{CARD}').length > {antes}",
                    timeout=20000,
                )
            except Exception:
                pass
        elif prox:
            prox.click()
            pg.wait_for_load_state("domcontentloaded")
        else:
            print("  [fim] não há mais resultados")
            break
        lote += 1
    return linhas, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--busca", default="livro")
    ap.add_argument("--url", help="URL de busca completa (sobrepõe --busca)")
    ap.add_argument("--faixas", help='faixas de preço em R$, ex: "0-15,15-30,30-60,60-"')
    ap.add_argument("--max-itens", type=int, default=0, help="0 = sem limite")
    ap.add_argument("--espera-min", type=float, default=2.5)
    ap.add_argument("--espera-max", type=float, default=6.0)
    ap.add_argument("--db", default=str(ROOT / "data" / "amazon_livros.db"))
    ap.add_argument("--csv", default=str(ROOT / "data" / "amazon_livros.csv"))
    ap.add_argument("--so-badge", action="store_true", help="CSV só com Menor preço em 365 dias")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--exec", help="executable_path do Chromium")
    ap.add_argument("--perfil", default=str(ROOT / "data" / "perfil_amazon"))
    args = ap.parse_args()

    base = args.url or "https://www.amazon.com.br/s?" + urlencode({"k": args.busca, "i": "stripbooks"})
    busca_lbl = args.url or args.busca
    faixas = parse_faixas(args.faixas) if args.faixas else [(None, None)]
    agora = datetime.now().isoformat(timespec="seconds")
    tag = affiliate_tag()
    db = init_db(args.db)
    vistos, linhas = set(), []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.perfil,
            headless=args.headless,
            executable_path=args.exec,
            locale="pt-BR",
            viewport={"width": 1366, "height": 900},
        )
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        for lo, hi in faixas:
            lbl = "tudo" if lo is None and hi is None else f"R${lo or 0}-{hi or '+'}"
            url = set_params(base, **{"low-price": lo, "high-price": hi, "page": None})
            print(f"\n== {lbl} ==")
            novas, parou = coletar_url(pg, url, lbl, vistos, args, agora, busca_lbl, tag)
            linhas += novas
            if parou or (args.max_itens and len(vistos) >= args.max_itens):
                break
            time.sleep(random.uniform(args.espera_min, args.espera_max))
        ctx.close()

    if not linhas:
        print("Nada coletado.")
        return
    cols = list(linhas[0].keys())
    db.executemany(
        f"INSERT OR REPLACE INTO snapshots ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r[c] for c in cols) for r in linhas],
    )
    db.commit()
    saida = [r for r in linhas if r["menor_preco_365"]] if args.so_badge else linhas
    saida.sort(key=lambda r: (-r["menor_preco_365"], -(r["desconto_pct"] or 0)))
    csv_path = Path(args.csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
        w.writeheader()
        w.writerows(saida)
    total_b = sum(r["menor_preco_365"] for r in linhas)
    print(f"\nTotal: {len(linhas)} itens, {total_b} com 'Menor preço em 365 dias' -> {args.db} / {args.csv}")


if __name__ == "__main__":
    main()
