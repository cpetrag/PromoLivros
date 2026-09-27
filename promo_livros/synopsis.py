from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_SYNOPSIS_LIMIT = 4_000


def extract_synopsis(product: dict) -> str:
    """Sinopse da Amazon que o Keepa devolve. O texto das resenhas dos leitores não vem na API."""
    parts: list[str] = []
    description = product.get("description")
    if isinstance(description, str) and description.strip():
        parts.append(description)
    if not parts:
        features = product.get("features")
        if isinstance(features, list):
            parts.extend(item for item in features if isinstance(item, str) and item.strip())
    text = html.unescape(_TAG_RE.sub(" ", " ".join(parts)))
    return " ".join(text.split())[:_SYNOPSIS_LIMIT]
