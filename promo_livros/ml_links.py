"""Converte link de produto do Mercado Livre no link de afiliado da conta."""
from __future__ import annotations

import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

logger = logging.getLogger("promo_livros.ml_links")

DEFAULT_TAG = "cpetrag1971"
_ENDPOINT = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
_LINKBUILDER = "https://www.mercadolivre.com.br/afiliados/linkbuilder"
_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_ML_HOSTS = ("mercadolivre.com.br", "mercadolibre.com", "meli.la")


class MlLinkError(Exception):
    """A API de afiliados não devolveu um link. O endereço do produto continua valendo."""


def is_ml_url(url: str) -> bool:
    host = (urlsplit(url or "").hostname or "").lower().removeprefix("www.")
    return host == "meli.la" or any(host == name or host.endswith("." + name) for name in _ML_HOSTS[:2])


def clean_product_url(url: str) -> str:
    """Tira o filtro de vitrine. A API de afiliado recebe o endereço do produto."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return (url or "").strip()
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def session_from_export(raw: str) -> tuple[str, str]:
    """Lê o export do Cookie-Editor e devolve o cabeçalho Cookie e o CSRF."""
    text = (raw or "").strip()
    if not text:
        return "", ""
    pairs = _pairs(text)
    cookie = "; ".join(f"{name}={value}" for name, value in pairs)
    csrf = next((value for name, value in pairs if name == "_csrf" and value), "")
    return cookie, csrf


def session_ready(raw: str) -> bool:
    cookie, csrf = session_from_export(raw)
    return bool(cookie and csrf)


def apply_ml_links(urls: list[str], export: str, tag: str, *, opener=urlopen) -> list[str]:
    """Devolve a mesma quantidade de URLs. Sem sessão ou com erro, o link original fica."""
    result = list(urls)
    cookie, csrf = session_from_export(export)
    label = (tag or DEFAULT_TAG).strip() or DEFAULT_TAG
    if not cookie or not csrf:
        return result
    token = _fresh_csrf(cookie, csrf, opener)
    for index, url in enumerate(urls):
        if not url or not is_ml_url(url):
            continue
        try:
            result[index] = affiliate_url(url, cookie=cookie, csrf=token, tag=label, opener=opener)
        except MlLinkError as exc:
            logger.warning("Link do Mercado Livre mantido: %s", exc)
    return result


def affiliate_url(url: str, *, cookie: str, csrf: str, tag: str, opener=urlopen) -> str:
    product = _affiliate_target(url)
    body = json.dumps({"urls": [product], "tag": tag}).encode()
    request = Request(
        _ENDPOINT,
        data=body,
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/plain, */*",
            "x-csrf-token": csrf,
            "cookie": cookie,
            "origin": "https://www.mercadolivre.com.br",
            "referer": _LINKBUILDER,
            "user-agent": _BROWSER,
        },
        method="POST",
    )
    try:
        with opener(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except HTTPError as exc:
        exc.read()
        raise MlLinkError(f"O Mercado Livre respondeu HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MlLinkError("O Mercado Livre não respondeu.") from exc
    found = _short_url(payload)
    if not found:
        detail = _api_message(payload)
        raise MlLinkError(detail or "O Mercado Livre não devolveu o link.")
    return found


def _fresh_csrf(cookie: str, fallback: str, opener) -> str:
    request = Request(
        _LINKBUILDER,
        headers={"cookie": cookie, "user-agent": _BROWSER, "accept": "text/html"},
    )
    try:
        with opener(request, timeout=8) as response:
            html = response.read().decode("utf-8", "replace")
    except (HTTPError, URLError, TimeoutError, UnicodeError):
        return fallback
    match = re.search(r"name=[\"']csrf-token[\"'][^>]*content=[\"']([^\"']+)", html, re.I)
    if match is None:
        match = re.search(r"content=[\"']([^\"']+)[\"'][^>]*name=[\"']csrf-token[\"']", html, re.I)
    return match.group(1) if match else fallback


_PICTURE = re.compile(r"https?://http2\.mlstatic\.com/D_[^\"'\s<>]+")


def thumbnail_url(item_id: str, *, opener=urlopen, cookie: str = "") -> str | None:
    """Foto do anúncio. A API pública costuma recusar; a sessão do navegador ainda lê a página."""
    found = _picture_at(f"https://api.mercadolibre.com/items/{item_id}", opener, cookie="")
    if found or not cookie:
        return found
    numeric = item_id[3:] if item_id.startswith("MLB") else item_id
    for url in (
        f"https://www.mercadolivre.com.br/p/api/items/{item_id}",
        f"https://produto.mercadolivre.com.br/MLB-{numeric}",
    ):
        found = _picture_at(url, opener, cookie=cookie)
        if found:
            return found
    return None


def _picture_at(url: str, opener, *, cookie: str) -> str | None:
    headers = {"accept": "application/json,text/html", "user-agent": "Mozilla/5.0"}
    if cookie:
        headers["cookie"] = cookie
        headers["referer"] = "https://www.mercadolivre.com.br/"
    request = Request(url, headers=headers)
    try:
        with opener(request, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
    except (HTTPError, URLError, TimeoutError, UnicodeError):
        return None
    return _picture_in(body)


def _picture_in(body: str) -> str | None:
    text = body.replace("\\/", "/")
    if text[:1] == "{":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            found = _picture_from_payload(payload)
            if found:
                return found
    match = _PICTURE.search(text)
    return _http_picture(match.group(0)) if match else None


def _picture_from_payload(payload: dict) -> str | None:
    for key in ("secure_thumbnail", "thumbnail"):
        found = _http_picture(payload.get(key))
        if found:
            return found
    pictures = payload.get("pictures")
    if isinstance(pictures, list):
        for picture in pictures:
            if not isinstance(picture, dict):
                continue
            for key in ("secure_url", "url"):
                found = _http_picture(picture.get(key))
                if found:
                    return found
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _picture_from_payload(nested)
    return None


def _http_picture(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("http"):
        return None
    url = value.replace("http://", "https://", 1).split("?")[0].rstrip("\\")
    if "/D_" not in url or "mlstatic.com" not in url:
        return None
    return url


def _pairs(text: str) -> list[tuple[str, str]]:
    if text[:1] in "[{":
        return _pairs_from_json(text)
    lines = [line for line in text.splitlines() if line.strip()]
    if text.startswith("#") or (lines and "\t" in lines[0]):
        return _pairs_from_netscape(text)
    return _pairs_from_header(text)


def _pairs_from_json(text: str) -> list[tuple[str, str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("cookies")
    if not isinstance(data, list):
        return []
    pairs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        domain = str(item.get("domain") or "").lower()
        if not name or not value:
            continue
        if domain and "mercado" not in domain and "meli" not in domain:
            continue
        pairs.append((name, value))
    return pairs


def _pairs_from_header(text: str) -> list[tuple[str, str]]:
    pairs = []
    for part in text.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name and value:
            pairs.append((name, value))
    return pairs


def _pairs_from_netscape(text: str) -> list[tuple[str, str]]:
    pairs = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain = fields[0].lower()
        name = fields[5].strip()
        value = fields[6].strip()
        if not name or not value:
            continue
        if "mercado" not in domain and "meli" not in domain:
            continue
        pairs.append((name, value))
    return pairs


_PRODUTO_HYPHEN = re.compile(r"https://produto\.mercadolivre\.com\.br/MLB-(\d{6,14})/?$", re.I)
_PRODUTO_PLAIN = re.compile(r"https://produto\.mercadolivre\.com\.br/(MLB\d{6,14})/?$", re.I)


def _affiliate_target(url: str) -> str:
    """A API recusa produto.mercadolivre.com.br. O anúncio público /p/MLB entra no programa."""
    cleaned = clean_product_url(url)
    hyphen = _PRODUTO_HYPHEN.fullmatch(cleaned)
    if hyphen:
        return f"https://www.mercadolivre.com.br/p/MLB{hyphen.group(1)}"
    plain = _PRODUTO_PLAIN.fullmatch(cleaned)
    if plain:
        return f"https://www.mercadolivre.com.br/p/{plain.group(1).upper()}"
    return cleaned


def _api_message(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    urls = payload.get("urls")
    if isinstance(urls, list):
        for item in urls:
            if not isinstance(item, dict):
                continue
            message = item.get("message") or item.get("error")
            if isinstance(message, str) and message.strip():
                return message.strip()
    message = payload.get("message") or payload.get("error")
    if isinstance(message, str):
        return message.strip()
    return ""


def _short_url(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("short_url", "shortUrl", "short_link"):
        found = _https(payload.get(key))
        if found:
            return found
    urls = payload.get("urls")
    if isinstance(urls, list):
        for item in urls:
            found = _short_url(item) if isinstance(item, dict) else _https(item)
            if found:
                return found
    return None


def _https(value: object) -> str | None:
    if isinstance(value, str) and value.startswith("https://"):
        return value
    return None
