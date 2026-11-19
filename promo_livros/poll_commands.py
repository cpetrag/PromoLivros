"""Comandos de enquete digitados no grupo."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

_COMMAND = re.compile(r"^!(enquete|resultado|encerrar)\b", re.IGNORECASE)
_PIN = re.compile(r"--fixar\s+(24h|7d|30d)\b", re.IGNORECASE)
_MULTI = re.compile(r"--multi\b", re.IGNORECASE)
_CLOSES = re.compile(r"--fecha\s+(\d+)([hdm])\b", re.IGNORECASE)
_FLAG = re.compile(r"--\S+")

_MAX_QUESTION = 255
_MAX_OPTION = 100


class PollCommandError(ValueError):
    """O comando !enquete chegou incompleto ou com uma flag inválida."""


@dataclass(frozen=True)
class NewPoll:
    question: str
    options: tuple[str, ...]
    multiple: bool
    pin: str | None
    closes_after: timedelta | None


def parse_group_command(text: str) -> NewPoll | str | None:
    """None quando a mensagem não é comando. 'resultado', 'encerrar' ou a enquete nova."""
    raw = " ".join(text.strip().split())
    found = _COMMAND.match(raw)
    if found is None:
        return None
    kind = found.group(1).lower()
    if kind == "resultado":
        return "resultado"
    if kind == "encerrar":
        return "encerrar"
    rest = raw[found.end() :].strip()
    pin_match = _PIN.search(rest)
    closes_match = _CLOSES.search(rest)
    multiple = _MULTI.search(rest) is not None
    pin = pin_match.group(1).lower() if pin_match else None
    closes_after = _duration(closes_match) if closes_match else None
    cleaned = _PIN.sub(" ", rest)
    cleaned = _CLOSES.sub(" ", cleaned)
    cleaned = _MULTI.sub(" ", cleaned)
    if _FLAG.search(cleaned):
        raise PollCommandError("Não reconheci uma das flags. Use --fixar 24h, 7d ou 30d, --multi e --fecha 48h.")
    parts = [part.strip() for part in cleaned.split("|")]
    parts = [part for part in parts if part]
    if len(parts) < 3:
        raise PollCommandError("A enquete precisa de uma pergunta e pelo menos duas opções, separadas por |.")
    question, *options = parts
    if len(question) > _MAX_QUESTION:
        raise PollCommandError("A pergunta passa de 255 caracteres.")
    if len(options) > 12:
        raise PollCommandError("A enquete aceita no máximo 12 opções.")
    if any(len(option) > _MAX_OPTION for option in options):
        raise PollCommandError("Cada opção aceita no máximo 100 caracteres.")
    if len(set(option.casefold() for option in options)) != len(options):
        raise PollCommandError("As opções precisam ser diferentes.")
    return NewPoll(
        question=question,
        options=tuple(options),
        multiple=multiple,
        pin=pin,
        closes_after=closes_after,
    )


def _duration(match: re.Match[str]) -> timedelta:
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if amount < 1:
        raise PollCommandError("O prazo precisa ser maior que zero.")
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "d":
        return timedelta(days=amount)
    return timedelta(hours=amount)
