from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from promo_livros.models import ConfigError, NicheConfig, PublishSlot, ScheduleSettings


def build_slots(schedule: ScheduleSettings, niches: tuple[NicheConfig, ...] | list[NicheConfig]) -> tuple[PublishSlot, ...]:
    """Três publicações por hora, um nicho por vez, até o horário de silêncio."""
    if not niches:
        raise ConfigError("config.yaml: defina ao menos um nicho.")
    if 60 % schedule.posts_per_hour != 0:
        raise ConfigError("config.yaml: posts_per_hour precisa dividir 60 em minutos inteiros.")

    interval = 60 // schedule.posts_per_hour
    start = schedule.publish_start_hour * 60 + schedule.publish_start_minute
    end = schedule.publish_end_hour * 60 + schedule.publish_end_minute
    if end <= start:
        raise ConfigError("config.yaml: publish_end precisa ser depois de publish_start.")

    slots: list[PublishSlot] = []
    index = 0
    for rank in range(schedule.per_niche):
        for niche in niches:
            minute_of_day = start + index * interval
            if minute_of_day >= end:
                raise ConfigError(
                    "A janela de publicação não cabe os horários. "
                    "Reduza per_niche ou posts_per_hour, ou alargue publish_start e publish_end."
                )
            hour, minute = divmod(minute_of_day, 60)
            slots.append(PublishSlot(hour=hour, minute=minute, niche_key=niche.key, rank=rank))
            index += 1
    return tuple(slots)


def zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception as exc:
        raise ConfigError(f"config.yaml: fuso horário desconhecido '{timezone_name}'.") from exc


def service_day(now: datetime, timezone_name: str) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(zone(timezone_name)).date().isoformat()


def local_now(now: datetime, timezone_name: str) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(zone(timezone_name))
