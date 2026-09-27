from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from promo_livros.models import WhatsAppGroup

_GROUP_ID_RE = re.compile(r"^[0-9-]+@g\.us$")


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
    with path.open(encoding="utf-8", newline="") as handle:
        updated = replace_groups_block(handle.read(), groups)
    temporary = path.with_suffix(".yaml.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    temporary.replace(path)


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
    end = start + 1
    while end < len(lines):
        if _is_yaml_key_boundary(lines[end]):
            break
        end += 1
    while end > start + 1 and _is_blank_or_comment_only(lines[end - 1]):
        end -= 1
    return start, end


def _is_blank_or_comment_only(line: str) -> bool:
    return line.split("#", 1)[0].strip() == ""


def _is_yaml_key_boundary(line: str) -> bool:
    code = line.split("#", 1)[0]
    if not code.strip():
        return False
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return False
    indent = len(line) - len(stripped)
    return indent in (0, 2)


def _yaml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
