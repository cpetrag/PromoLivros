"""Espera entre mensagens nos grupos. Vale para fila, convites e enquetes."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta


def latest_stamp(stamps: Iterable[str | None], now: datetime) -> str | None:
    present = [item for item in stamps if item]
    if not present:
        return None
    return max(present, key=lambda value: _moment(value, now))


def gap_open(last_sent: str | None, now: datetime, gap_seconds: int) -> bool:
    if not last_sent:
        return True
    return now - _moment(last_sent, now) >= timedelta(seconds=gap_seconds)


def _moment(value: str, now: datetime) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None and now.tzinfo is not None:
        return parsed.replace(tzinfo=now.tzinfo)
    return parsed
