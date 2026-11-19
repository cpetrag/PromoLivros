"""Leitura dos campos de formulário já decodificados por parse_qs."""
from __future__ import annotations


def first_field(form: dict[str, list[str]], name: str) -> str:
    return raw_field(form, name).strip()


def raw_field(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name, [])
    return values[0] if values else ""
