"""Histórico de preço por loja, produto e dia. Mercado Livre grava a cada CSV; Shopee entra por arquivo."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

STORES = ("ml", "shopee", "magalu")
WINDOW_DAYS = 365
# Com menos dias que isso, "menor preço" seria só "o preço de ontem" e enganaria quem escolhe.
MIN_HISTORY_DAYS = 7
KEEP_DAYS = 400
HISTORY_COLUMNS = ("loja", "id", "data", "preco", "preco_de")
_MAX_ROWS = 200_000
_IDS = {
    "ml": re.compile(r"^MLB\d{6,14}$"),
    "shopee": re.compile(r"^\d{5,12}\.\d{5,14}$"),
    "magalu": re.compile(r"^[a-z0-9][a-z0-9-]{3,31}$"),
}
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMEZONE = "America/Sao_Paulo"


@dataclass(frozen=True)
class PricePoint:
    store: str
    product_id: str
    day: str
    price_cents: int
    list_cents: int | None = None


@dataclass(frozen=True)
class PriceLow:
    """`days` de histórico (até 365); `lowest` diz se o preço de hoje empata ou bate todos eles."""

    days: int
    previous_min_cents: int
    lowest: bool


def today_iso(timezone: str = _TIMEZONE) -> str:
    return datetime.now(ZoneInfo(timezone)).date().isoformat()


def window_start(today: str, days: int = WINDOW_DAYS) -> str:
    return (date.fromisoformat(today) - timedelta(days=days)).isoformat()


def lowest_since(
    current_cents: int | None,
    previous_min_cents: int | None,
    first_day: str | None,
    today: str,
    previous_max_cents: int | None = None,
) -> PriceLow | None:
    """None quando ainda não há dias suficientes para comparar."""
    if not current_cents or current_cents <= 0 or previous_min_cents is None or not first_day:
        return None
    covered = (date.fromisoformat(today) - date.fromisoformat(first_day)).days
    if covered < MIN_HISTORY_DAYS:
        return None
    # Preço que nunca mudou empata com o mínimo todo dia; sem ter custado mais, não é promoção.
    moved = previous_max_cents is None or current_cents < previous_max_cents
    return PriceLow(min(covered, WINDOW_DAYS), previous_min_cents, current_cents <= previous_min_cents and moved)


def valid_product_id(store: str, product_id: str) -> bool:
    pattern = _IDS.get(store)
    return bool(pattern and pattern.fullmatch(product_id))


def parse_history_csv(text: str) -> list[PricePoint]:
    """Arquivo loja;id;data;preco;preco_de. Linha inválida derruba o arquivo, com o número da linha."""
    from promo_livros.catalog import CatalogError, _cents

    sample = text.lstrip("\ufeff").strip()
    if not sample:
        raise CatalogError("O arquivo de histórico está vazio.")
    reader = csv.DictReader(io.StringIO(sample), delimiter=";")
    header = {(name or "").strip().casefold() for name in reader.fieldnames or []}
    missing = [name for name in HISTORY_COLUMNS if name not in header]
    if missing:
        raise CatalogError("Faltam colunas no histórico: " + ", ".join(missing) + ".")
    points: list[PricePoint] = []
    errors: list[str] = []
    for index, raw in enumerate(reader, start=2):
        row = {(key or "").strip().casefold(): (value or "").strip() for key, value in raw.items() if key}
        store = row.get("loja", "").casefold()
        if store == "ml":
            product_id = row.get("id", "").upper()
        elif store == "magalu":
            product_id = row.get("id", "").lower()
        else:
            product_id = row.get("id", "").replace(" ", "")
        day = row.get("data", "")
        price = _cents(row.get("preco"))
        listed = _cents(row.get("preco_de")) if row.get("preco_de") else None
        if store not in STORES:
            errors.append(f"Linha {index}: loja precisa ser ml, shopee ou magalu.")
        elif not valid_product_id(store, product_id):
            errors.append(f"Linha {index}: id {product_id or '(vazio)'} não é da loja {store}.")
        elif not _valid_day(day):
            errors.append(f"Linha {index}: data {day or '(vazia)'} precisa ser AAAA-MM-DD.")
        elif price is None or price <= 0:
            errors.append(f"Linha {index}: preço inválido.")
        else:
            points.append(PricePoint(store, product_id, day, price, listed if listed and listed > 0 else None))
        if len(points) > _MAX_ROWS:
            raise CatalogError(f"O histórico aceita no máximo {_MAX_ROWS} linhas por arquivo.")
    if errors:
        raise CatalogError(" ".join(errors[:8]))
    return points


def _valid_day(value: str) -> bool:
    if not _DAY.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """python -m promo_livros.price_log arquivo.csv — grava o histórico no banco do painel."""
    import sys
    from pathlib import Path

    from promo_livros.catalog import CatalogError, CatalogStore
    from promo_livros.config import load_config

    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Uso: python -m promo_livros.price_log historico.csv", file=sys.stderr)
        return 2
    try:
        points = parse_history_csv(Path(args[0]).read_text(encoding="utf-8-sig"))
        config = load_config(Path("config.yaml"))
        store = CatalogStore(config.sqlite_path)
        try:
            saved = store.record_price_points(points)
        finally:
            store.close()
    except (CatalogError, OSError, ValueError) as exc:
        print(f"Histórico não gravado: {exc}", file=sys.stderr)
        return 1
    print(f"{saved} preços gravados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
