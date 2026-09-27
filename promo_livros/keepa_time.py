from __future__ import annotations

from datetime import datetime, timedelta, timezone

from promo_livros.models import KEEPA_TIME_OFFSET_MINUTES


def keepa_minutes(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp()) // 60 - KEEPA_TIME_OFFSET_MINUTES


def tracking_since_lte(now: datetime, min_days: int) -> int:
    """Produtos com trackingSince menor ou igual a este valor já eram rastreados há `min_days`."""
    cutoff = now - timedelta(days=min_days)
    return keepa_minutes(cutoff)


def minimum_positive_price(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value
