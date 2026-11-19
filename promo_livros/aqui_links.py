"""Encurta URLs via API do Aqui (aqui.descontos.ai)."""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AquiLinkError(Exception):
    """Falha ao encurtar: credenciais ausentes, HTTP recusado ou shortUrl ausente."""


def create_short_link(
    url: str,
    *,
    api_key: str,
    base_url: str = "https://aqui.descontos.ai",
    title: str = "",
    opener=urlopen,
    timeout: float = 20,
) -> str:
    """POST /api/v1/links; devolve shortUrl."""
    if not (api_key or "").strip():
        raise AquiLinkError("Falta a chave da API do Aqui.")
    origin = (url or "").strip()
    if not origin:
        raise AquiLinkError("Falta a URL para encurtar.")
    endpoint = f"{base_url.rstrip('/')}/api/v1/links"
    payload: dict[str, str] = {"url": origin}
    label = (title or "").strip()
    if label:
        payload["title"] = label
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    request = Request(
        endpoint,
        data=body.encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            code = response.getcode()
            raw = response.read().decode()
    except HTTPError as exc:
        raise AquiLinkError(f"O Aqui recusou o link ({exc.code}).") from exc
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise AquiLinkError("O Aqui não encurtou o link.") from exc
    if code != 201:
        raise AquiLinkError(f"O Aqui recusou o link ({code}).")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AquiLinkError("O Aqui não encurtou o link.") from exc
    short = ""
    if isinstance(data, dict):
        short = str(data.get("shortUrl") or "").strip()
    if not short:
        raise AquiLinkError("O encurtador Aqui não devolveu shortUrl.")
    return short
