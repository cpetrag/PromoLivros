"""Reescreve URLs da Magazine Luiza com parâmetros de afiliado (sem API Magalu)."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_MAGALU_HOST_MARKERS = (
    "magazineluiza",
    "magazinevoce",
    "divulgador.magalu",
    "influenciadormagalu",
    "magalu.com",
)


@dataclass(frozen=True)
class MagaluConvertResult:
    link_convertido: str
    tipo: str  # produto | divulgador | generico | redirect_resolvido
    ok: bool
    erro: str = ""


def is_magalu_url(url: str) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    return any(marker in host for marker in _MAGALU_HOST_MARKERS)


def magalu_product_id(url: str) -> str:
    segments = [part for part in urlsplit(url or "").path.split("/") if part]
    for index, segment in enumerate(segments):
        if segment == "p" and index + 1 < len(segments):
            return segments[index + 1]
    return ""


def convert_magalu(
    url: str,
    *,
    promoter_id: str,
    partner_id: str,
    opener=urlopen,
) -> MagaluConvertResult:
    original = (url or "").strip()
    parts = urlsplit(original)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return MagaluConvertResult(original, "", False, "URL inválida")

    working = original
    redirect = False
    host = (parts.hostname or "").lower()
    if "divulgador.magalu" in host:
        try:
            request = Request(
                working,
                method="GET",
                headers={"User-Agent": _BROWSER},
            )
            with opener(request, timeout=30) as response:
                working = (response.geturl() or "").strip() or working
            redirect = True
        except (URLError, OSError, ValueError) as exc:
            return MagaluConvertResult(original, "", False, str(exc) or "redirect falhou")

    if not is_magalu_url(working):
        return MagaluConvertResult(original, "", False, "não é Magalu")

    converted, tipo = _rewrite_magalu_url(working, promoter_id=promoter_id, partner_id=partner_id)
    if redirect:
        tipo = "redirect_resolvido"
    return MagaluConvertResult(converted, tipo, True, "")


def _rewrite_magalu_url(url: str, *, promoter_id: str, partner_id: str) -> tuple[str, str]:
    parts = urlsplit(url)
    path = parts.path or "/"

    if _has_product_p_segment(path):
        new_path = _p_to_divulgador_path(path)
        converted = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                new_path,
                _affiliate_query(parts.query, promoter_id, partner_id),
                parts.fragment,
            )
        )
        return converted, "produto"

    if "divulgador" in path.split("/"):
        new_path = _normalize_divulgador_path(path)
        converted = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                new_path,
                _affiliate_query(parts.query, promoter_id, partner_id),
                parts.fragment,
            )
        )
        return converted, "divulgador"

    converted = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            path,
            _affiliate_query(parts.query, promoter_id, partner_id),
            parts.fragment,
        )
    )
    return converted, "generico"


def _has_product_p_segment(path: str) -> bool:
    return any(segment == "p" for segment in path.split("/") if segment)


def _normalize_divulgador_path(path: str) -> str:
    trailing = path.endswith("/")
    segments = [part for part in path.split("/") if part]
    out: list[str] = []
    for index, segment in enumerate(segments):
        out.append(segment)
        if segment == "divulgador":
            next_segment = segments[index + 1] if index + 1 < len(segments) else ""
            if next_segment != "oferta":
                out.append("oferta")
    rebuilt = "/" + "/".join(out)
    if trailing and not rebuilt.endswith("/"):
        rebuilt += "/"
    return rebuilt


def _p_to_divulgador_path(path: str) -> str:
    trailing = path.endswith("/")
    segments = [part for part in path.split("/") if part]
    out: list[str] = []
    for segment in segments:
        if segment == "p":
            out.extend(["divulgador", "oferta"])
            continue
        out.append(segment)
    rebuilt = "/" + "/".join(out)
    if trailing and not rebuilt.endswith("/"):
        rebuilt += "/"
    return rebuilt


def _affiliate_query(query: str, promoter_id: str, partner_id: str) -> str:
    parsed = parse_qs(query, keep_blank_values=True)
    params: dict[str, list[str]] = {}
    if "seller_id" in parsed:
        params["seller_id"] = parsed["seller_id"]
    params["promoter_id"] = [promoter_id]
    params["partner_id"] = [partner_id]
    return urlencode(params, doseq=True)