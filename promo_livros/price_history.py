from __future__ import annotations

from promo_livros.filters import _as_int

_MINUTES_PER_DAY = 24 * 60


def price_points(csv, index: int, *, with_shipping: bool) -> list[tuple[int, int]]:
    """Pares (minuto Keepa, preço em centavos). Preço ausente ou zero não entra."""
    if not isinstance(csv, list) or index >= len(csv):
        return []
    history = csv[index]
    if not isinstance(history, list):
        return []
    step = 3 if with_shipping else 2
    points: list[tuple[int, int]] = []
    for offset in range(0, len(history) - step + 1, step):
        moment = _as_int(history[offset])
        price = _as_int(history[offset + 1])
        if moment is None or price is None or price <= 0:
            continue
        landing = price
        if with_shipping:
            shipping = _as_int(history[offset + 2])
            if shipping is None or shipping < 0:
                shipping = 0
            landing = price + shipping
        points.append((moment, landing))
    return points


def days_as_lowest(points: list[tuple[int, int]], current_cents: int, now_minutes: int) -> int | None:
    """Há quantos dias o preço atual é o menor. None quando não há histórico."""
    if current_cents <= 0 or not points:
        return None
    cheaper = [moment for moment, price in points if price < current_cents]
    if not cheaper:
        start = points[0][0]
    else:
        last_cheaper = max(cheaper)
        later = [moment for moment, _price in points if moment > last_cheaper]
        if not later:
            return 0
        start = later[0]
    elapsed = now_minutes - start
    if elapsed < 0:
        return 0
    return elapsed // _MINUTES_PER_DAY
