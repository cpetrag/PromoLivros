"""Janela e intervalos de envio. Os números vêm do painel."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_CLOCK = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
MAX_SLOTS = 60


@dataclass(frozen=True)
class SendSchedule:
    start: str
    end: str
    post_interval_minutes: int
    group_gap_seconds: int


def default_schedule() -> SendSchedule:
    return SendSchedule("08:00", "22:00", 40, 45)


def parse_schedule(start: str, end: str, interval: str, gap: str) -> SendSchedule:
    start_minutes = _clock_minutes(start, "Primeiro post")
    end_minutes = _clock_minutes(end, "Parar antes de")
    if end_minutes <= start_minutes:
        raise ValueError("O fim da janela precisa ser depois do primeiro post.")
    try:
        step = int(str(interval).strip())
        seconds = int(str(gap).strip())
    except ValueError as exc:
        raise ValueError("Intervalo e espera entre grupos precisam ser números.") from exc
    if not 5 <= step <= 180:
        raise ValueError("O intervalo entre posts fica entre 5 e 180 minutos.")
    if not 5 <= seconds <= 600:
        raise ValueError("A espera entre grupos fica entre 5 e 600 segundos.")
    schedule = SendSchedule(f"{start.strip()}", f"{end.strip()}", step, seconds)
    slots = slot_clocks(schedule)
    if len(slots) > MAX_SLOTS:
        raise ValueError(
            f"Essa janela gera {len(slots)} posts. O limite é {MAX_SLOTS}. Aumente o intervalo ou encurte o período."
        )
    return schedule


MAX_DAY_POSTS = 60
MAX_POSTS_PER_HOUR = 5
DAY_SPAN_MINUTES = 12 * 60


def plan_day_clocks(start: str, book_count: int) -> list[str]:
    """Um livro por horário. No máximo 5 por hora e 60 no dia, espalhados em 12 horas.

    36 livros viram um a cada 20 minutos (3 por hora). 60 livros, um a cada 12 minutos.
    """
    count = min(book_count, MAX_DAY_POSTS)
    if count <= 0:
        return []
    start_minutes = _clock_minutes(start, "Primeiro post")
    step = max(60 // MAX_POSTS_PER_HOUR, DAY_SPAN_MINUTES // count)
    clocks: list[str] = []
    for index in range(count):
        minute = start_minutes + index * step
        if minute >= 24 * 60:
            break
        clocks.append(_format_clock(minute))
    return clocks


def plan_span_clocks(start: str, end: str, count: int) -> list[str]:
    """Reparte `count` horários de `start` até antes de `end`."""
    if count <= 0:
        return []
    start_minutes = _clock_minutes(start, "Primeiro post")
    end_minutes = _clock_minutes(end, "Parar antes de")
    if end_minutes <= start_minutes:
        return []
    step = max(1, (end_minutes - start_minutes) // count)
    clocks: list[str] = []
    for index in range(count):
        minute = start_minutes + index * step
        if minute >= end_minutes or minute >= 24 * 60:
            break
        clocks.append(_format_clock(minute))
    return clocks


def _format_clock(minute: int) -> str:
    hour, mins = divmod(minute, 60)
    return f"{hour:02d}:{mins:02d}"


def clock_minutes(value: str, label: str = "Horário") -> int:
    return _clock_minutes(value, label)


def format_clock(minute: int) -> str:
    return _format_clock(minute)


def slot_clocks(schedule: SendSchedule) -> list[str]:
    minute = _clock_minutes(schedule.start, "Primeiro post")
    end = _clock_minutes(schedule.end, "Parar antes de")
    clocks: list[str] = []
    while minute < end and len(clocks) <= MAX_SLOTS:
        hour, mins = divmod(minute, 60)
        clocks.append(f"{hour:02d}:{mins:02d}")
        minute += schedule.post_interval_minutes
    return clocks


def upcoming_clocks(schedule: SendSchedule, now_clock: str) -> list[str]:
    """Horários da grade que ainda não passaram."""
    now_minutes = _clock_minutes(now_clock, "Agora")
    return [clock for clock in slot_clocks(schedule) if _clock_minutes(clock, "Horário") > now_minutes]


def repack_clocks(schedule: SendSchedule, now_clock: str, count: int) -> tuple[list[str], int]:
    """Recoloca `count` posts nos horários que ainda cabem. Os que passam do fim continuam o intervalo.

    O segundo número é quantos ficaram depois do horário de parar.
    """
    if count <= 0:
        return [], 0
    end = _clock_minutes(schedule.end, "Parar antes de")
    now_minutes = _clock_minutes(now_clock, "Agora")
    if now_minutes >= end:
        return [], count
    clocks = upcoming_clocks(schedule, now_clock)
    if len(clocks) >= count:
        chosen = clocks[:count]
        return chosen, 0
    minute = _clock_minutes(clocks[-1], "Horário") + schedule.post_interval_minutes if clocks else now_minutes + 1
    while len(clocks) < count and minute < 24 * 60 and len(clocks) < MAX_SLOTS:
        hour, mins = divmod(minute, 60)
        clocks.append(f"{hour:02d}:{mins:02d}")
        minute += schedule.post_interval_minutes
    late = sum(1 for clock in clocks if _clock_minutes(clock, "Horário") >= end)
    return clocks, late


def write_group_gap(path: Path, seconds: int) -> None:
    """Troca só gap_seconds. Não mexe em whatsapp.enabled."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"^  gap_seconds: \d+[ \t]*$", re.MULTILINE)
    if len(pattern.findall(text)) != 1:
        raise OSError("config.yaml não tem um único gap_seconds.")
    updated = pattern.sub(f"  gap_seconds: {int(seconds)}", text, count=1)
    old_enabled = [line for line in text.splitlines() if "enabled:" in line]
    new_enabled = [line for line in updated.splitlines() if "enabled:" in line]
    if old_enabled != new_enabled:
        raise OSError("A gravação mexeria no enabled.")
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(updated, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _clock_minutes(value: str, label: str) -> int:
    match = _CLOCK.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"{label} precisa ser um horário, como 08:00.")
    return int(match.group(1)) * 60 + int(match.group(2))
