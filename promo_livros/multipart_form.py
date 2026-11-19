"""Lê multipart/form-data do envio de fotos. O módulo cgi não existe mais no Python 3.13."""
from __future__ import annotations

import re

MEDIA_TYPE = "multipart/form-data"
_BOUNDARY = re.compile(r'(?:^|;)\s*boundary=(?:"([^"]+)"|([^;\s]+))', re.IGNORECASE)
_NAME = re.compile(r'(?:^|;)\s*name="([^"]*)"', re.IGNORECASE)
_FILENAME = re.compile(r'(?:^|;)\s*filename="([^"]*)"', re.IGNORECASE)


def parse_multipart(content_type: str, body: bytes) -> tuple[dict[str, list[str]], dict[str, list[bytes]]]:
    """Campos de texto e arquivos por nome. Arquivo vazio (campo sem seleção) fica de fora."""
    media_type, _, parameters = content_type.partition(";")
    if media_type.strip().lower() != MEDIA_TYPE:
        raise ValueError("O formulário precisa ser multipart/form-data.")
    match = _BOUNDARY.search(parameters)
    if match is None:
        raise ValueError("O formulário não tem boundary.")
    # O delimitador real é CRLF + "--boundary"; o CRLF extra cobre a primeira parte do corpo.
    delimiter = b"\r\n--" + (match.group(1) or match.group(2)).encode("latin-1")
    fields: dict[str, list[str]] = {}
    files: dict[str, list[bytes]] = {}
    for chunk in (b"\r\n" + body).split(delimiter)[1:]:
        if chunk.startswith(b"--"):
            break
        head, separator, data = chunk.partition(b"\r\n\r\n")
        if not separator:
            continue
        disposition = _disposition(head.decode("utf-8", errors="replace"))
        name_match = _NAME.search(disposition)
        if name_match is None:
            continue
        name = name_match.group(1)
        if _FILENAME.search(disposition) is not None:
            if data:
                files.setdefault(name, []).append(data)
        else:
            fields.setdefault(name, []).append(data.decode("utf-8", errors="replace"))
    return fields, files


def _disposition(head: str) -> str:
    for line in head.split("\r\n"):
        key, _, value = line.partition(":")
        if key.strip().lower() == "content-disposition":
            return value.strip()
    return ""
