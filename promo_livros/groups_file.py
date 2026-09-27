from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from promo_livros.models import WhatsAppGroup

_GROUP_ID_RE = re.compile(r"^[0-9-]+@g\.us$")
_ALLOWED_CONTROL = frozenset("\n\r\t")


class GroupsFileError(Exception):
    """A lista não pode ser gravada."""


@dataclass(frozen=True)
class GroupChoice:
    name: str
    chat_id: str
    checked: bool
    missing: bool


def validate_groups(groups: list[tuple[str, str]], *, enabled: bool) -> None:
    if enabled and not groups:
        raise GroupsFileError("O disparo está ligado e a lista de grupos ficou vazia.")
    seen: set[str] = set()
    for name, chat_id in groups:
        if not name.strip():
            raise GroupsFileError("Grupo sem nome.")
        for char in name:
            if ord(char) < 32 and char not in _ALLOWED_CONTROL:
                raise GroupsFileError("Nome de grupo com caractere inválido.")
        if _GROUP_ID_RE.fullmatch(chat_id) is None:
            raise GroupsFileError(f"Id de grupo inválido '{chat_id}'.")
        if chat_id in seen:
            raise GroupsFileError(f"Grupo repetido '{chat_id}'.")
        seen.add(chat_id)


def group_choices(
    session: tuple[WhatsAppGroup, ...] | list[WhatsAppGroup],
    saved: tuple[WhatsAppGroup, ...] | list[WhatsAppGroup],
) -> list[GroupChoice]:
    saved_ids = {group.chat_id for group in saved}
    rows: list[GroupChoice] = []
    seen: set[str] = set()
    for group in session:
        seen.add(group.chat_id)
        rows.append(GroupChoice(group.name, group.chat_id, group.chat_id in saved_ids, False))
    for group in saved:
        if group.chat_id in seen:
            continue
        rows.append(GroupChoice(group.name, group.chat_id, True, True))
    return rows


def selected_groups(posted_ids: list[str], choices: list[GroupChoice]) -> list[tuple[str, str]]:
    allowed = {choice.chat_id: choice.name for choice in choices}
    groups: list[tuple[str, str]] = []
    for chat_id in posted_ids:
        name = allowed.get(chat_id)
        if name is None:
            raise GroupsFileError(f"Id de grupo inválido '{chat_id}'.")
        groups.append((name, chat_id))
    return groups


def replace_groups_block(text: str, groups: list[tuple[str, str]]) -> str:
    lines = text.splitlines(keepends=True)
    start, end = _groups_span(lines)
    block = ["  groups:\n"]
    for name, chat_id in groups:
        block.append(f'    - name: "{_yaml_string(name)}"\n')
        block.append(f'      id: "{chat_id}"\n')
    return "".join(lines[:start] + block + lines[end:])


def write_groups(path: Path, groups: list[tuple[str, str]], *, enabled: bool) -> None:
    validate_groups(groups, enabled=enabled)
    temporary: Path | None = None
    try:
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                original_text = handle.read()
        except OSError as exc:
            raise GroupsFileError("Não foi possível ler config.yaml.") from exc
        updated = replace_groups_block(original_text, groups)
        _assert_safe_groups_write(original_text, updated, groups)
        temporary = path.with_suffix(".yaml.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                handle.write(updated)
            try:
                temporary.replace(path)
            except OSError as exc:
                if temporary.is_file():
                    temporary.unlink()
                raise GroupsFileError("Não foi possível gravar config.yaml.") from exc
        except OSError as exc:
            if temporary is not None and temporary.is_file():
                temporary.unlink()
            raise GroupsFileError("Não foi possível gravar config.yaml.") from exc
    except GroupsFileError:
        raise
    except OSError as exc:
        raise GroupsFileError("Não foi possível gravar config.yaml.") from exc


def _assert_safe_groups_write(
    original_text: str,
    updated: str,
    groups: list[tuple[str, str]],
) -> None:
    try:
        original = yaml.safe_load(original_text)
        parsed = yaml.safe_load(updated)
    except yaml.YAMLError as exc:
        raise GroupsFileError("config.yaml ficaria inválido.") from exc
    if not isinstance(original, dict) or not isinstance(parsed, dict):
        raise GroupsFileError("config.yaml ficaria inválido.")
    original_whatsapp = original.get("whatsapp")
    parsed_whatsapp = parsed.get("whatsapp")
    if not isinstance(original_whatsapp, dict) or not isinstance(parsed_whatsapp, dict):
        raise GroupsFileError("config.yaml ficaria inválido.")
    if original_whatsapp.get("enabled") != parsed_whatsapp.get("enabled"):
        raise GroupsFileError("config.yaml mudaria whatsapp.enabled.")
    saved = _group_pairs_from_parsed(parsed_whatsapp.get("groups"))
    if saved != groups:
        raise GroupsFileError("config.yaml não refletiria a lista de grupos gravada.")


def _group_pairs_from_parsed(rows: object) -> list[tuple[str, str]]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise GroupsFileError("config.yaml ficaria inválido.")
    pairs: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise GroupsFileError("config.yaml ficaria inválido.")
        name = row.get("name")
        chat_id = row.get("id")
        if not isinstance(name, str) or not isinstance(chat_id, str):
            raise GroupsFileError("config.yaml ficaria inválido.")
        pairs.append((name, chat_id))
    return pairs


def _groups_span(lines: list[str]) -> tuple[int, int]:
    in_whatsapp = False
    start = None
    for index, line in enumerate(lines):
        code = line.split("#", 1)[0].strip()
        if code == "whatsapp:":
            in_whatsapp = True
            continue
        if in_whatsapp and line[:1].strip() and not line.lstrip().startswith("#"):
            break
        if in_whatsapp and code == "groups:":
            start = index
            break
    if start is None:
        raise GroupsFileError("config.yaml não tem whatsapp.groups.")
    groups_indent = _line_indent(lines[start])
    end = start + 1
    while end < len(lines):
        if _is_yaml_key_boundary(lines[end], groups_indent=groups_indent):
            break
        end += 1
    while end > start + 1 and _is_blank_or_comment_only(lines[end - 1]):
        end -= 1
    return start, end


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_blank_or_comment_only(line: str) -> bool:
    return line.split("#", 1)[0].strip() == ""


def _is_yaml_key_boundary(line: str, *, groups_indent: int) -> bool:
    code = line.split("#", 1)[0]
    if not code.strip():
        return False
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return False
    if stripped.startswith("-"):
        return False
    indent = _line_indent(line)
    return indent <= groups_indent


def _yaml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n")
    escaped = escaped.replace("\r", "\\r")
    escaped = escaped.replace("\t", "\\t")
    return escaped
