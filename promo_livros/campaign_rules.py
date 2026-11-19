"""Regras dos convites: horários, rodízio e sorteio. Sem banco e sem rede."""
from __future__ import annotations

from dataclasses import dataclass
from random import Random

from promo_livros.send_schedule import clock_minutes, format_clock

INVITE_FIXED = "fixed"
INVITE_LAST = "last"
INVITE_KINDS = (INVITE_FIXED, INVITE_LAST)
DEFAULT_LAST_OFFSET_MINUTES = 10
MIN_LAST_OFFSET_MINUTES = 1
MAX_LAST_OFFSET_MINUTES = 120
FIXED_GRACE_MINUTES = 60
_LAST_MINUTE_OF_DAY = 23 * 60 + 59


@dataclass(frozen=True)
class InviteSettings:
    fixed_clock: str | None
    last_offset_minutes: int


@dataclass(frozen=True)
class RotationEntry:
    campaign_id: int
    position: int


def invite_settings(raw_fixed: str | None, raw_offset: str | None) -> InviteSettings:
    """Lê o que está salvo. Valor estragado volta ao padrão para não travar o envio."""
    fixed = (raw_fixed or "").strip() or None
    if fixed is not None:
        try:
            clock_minutes(fixed)
        except ValueError:
            fixed = None
    try:
        offset = parse_last_offset(raw_offset or "")
    except ValueError:
        offset = DEFAULT_LAST_OFFSET_MINUTES
    return InviteSettings(fixed, offset)


def parse_fixed_clock(raw: str, taken_clocks: set[str]) -> str | None:
    value = raw.strip()
    if not value:
        return None
    clock_minutes(value, "Convite no horário")
    if value in taken_clocks:
        raise ValueError(f"{value} já é horário da fila. Escolha outro para o convite.")
    return value


def parse_last_offset(raw: str) -> int:
    try:
        minutes = int(raw.strip())
    except ValueError as exc:
        raise ValueError("Os minutos do convite final precisam ser um número.") from exc
    if not MIN_LAST_OFFSET_MINUTES <= minutes <= MAX_LAST_OFFSET_MINUTES:
        raise ValueError(
            f"Os minutos do convite final ficam entre {MIN_LAST_OFFSET_MINUTES} e {MAX_LAST_OFFSET_MINUTES}."
        )
    return minutes


def fixed_invite_due(fixed_clock: str | None, now_clock: str) -> bool:
    """Só dentro da janela de tolerância: um horário salvo depois de passar não dispara na hora."""
    if fixed_clock is None:
        return False
    start = clock_minutes(fixed_clock)
    return start <= clock_minutes(now_clock) < start + FIXED_GRACE_MINUTES


def fixed_invite_missed(fixed_clock: str | None, now_clock: str) -> bool:
    if fixed_clock is None:
        return False
    return clock_minutes(now_clock) >= clock_minutes(fixed_clock) + FIXED_GRACE_MINUTES


def last_invite_clock(last_queue_clock: str | None, send_end: str, offset_minutes: int) -> str:
    reference = clock_minutes(last_queue_clock or send_end)
    return format_clock(min(reference + offset_minutes, _LAST_MINUTE_OF_DAY))


def last_invite_due(now_clock: str, invite_clock: str, *, queue_pending: bool) -> bool:
    return not queue_pending and clock_minutes(now_clock) >= clock_minutes(invite_clock)


def rotation_order(ready: list[RotationEntry], last_used: RotationEntry | None) -> list[int]:
    """Campanhas prontas a partir da seguinte à última usada, dando a volta."""
    ordered = sorted(ready, key=lambda entry: (entry.position, entry.campaign_id))
    if last_used is None:
        return [entry.campaign_id for entry in ordered]
    marker = (last_used.position, last_used.campaign_id)
    split = next(
        (index for index, entry in enumerate(ordered) if (entry.position, entry.campaign_id) > marker),
        0,
    )
    return [entry.campaign_id for entry in ordered[split:] + ordered[:split]]


def pick_avoiding(item_ids: list[int], last_used_id: int | None, rng: Random) -> int:
    if not item_ids:
        raise ValueError("Não há opção para sortear.")
    options = [item for item in item_ids if item != last_used_id] or list(item_ids)
    return rng.choice(options)
