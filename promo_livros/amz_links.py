"""Cliente da API local de links de afiliado. Sem token, o chamador mantém a URL atual."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

logger = logging.getLogger("promo_livros.amz_links")

BATCH_SIZE = 50
_AMAZON_HOSTS = {"amazon.com.br"}
_SHORT_HOSTS = {"amzn.to", "a.co"}
_ALREADY_SHORT = "link.amazon"


class AmzLinkError(Exception):
    """A API não devolveu um lote utilizável. O link antigo continua valendo."""


@dataclass(frozen=True)
class LinkResult:
    url: str | None
    error: str | None


class AmzLinkClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def links(self, pairs: list[tuple[str, str]]) -> list[LinkResult]:
        results: list[LinkResult] = []
        for start in range(0, len(pairs), BATCH_SIZE):
            results.extend(self._post(pairs[start : start + BATCH_SIZE]))
        return results

    def _post(self, pairs: list[tuple[str, str]]) -> list[LinkResult]:
        body = json.dumps(
            {"items": [{"url": url, "tag": tag} for url, tag in pairs]}
        ).encode()
        request = Request(
            f"{self.base_url}/links",
            data=body,
            headers={
                "content-type": "application/json",
                "x-api-key": self.token,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode())
        except HTTPError as exc:
            exc.read()
            raise AmzLinkError(f"A API de links respondeu HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AmzLinkError("A API de links não respondeu.") from exc
        if not isinstance(payload, list) or len(payload) != len(pairs):
            raise AmzLinkError("A API de links devolveu um lote inesperado.")
        return [_result(item) for item in payload]


def needs_affiliate_link(url: str) -> bool:
    """Amazon ainda não encurtada por esta API. link.amazon já está pronto."""
    host = _host(url)
    if host == _ALREADY_SHORT:
        return False
    if host in _SHORT_HOSTS:
        return True
    return host in _AMAZON_HOSTS or host.endswith(".amazon.com.br")


def apply_affiliate_links(urls: list[str], client: AmzLinkClient, tag: str) -> list[str]:
    """Devolve a mesma quantidade de URLs. Item com erro fica com o link original."""
    result = list(urls)
    indexed = [(index, url) for index, url in enumerate(urls) if needs_affiliate_link(url)]
    if not indexed:
        return result
    fetched = client.links([(url, tag) for _index, url in indexed])
    for (index, _original), item in zip(indexed, fetched, strict=True):
        if item.url:
            result[index] = item.url
        elif item.error:
            logger.warning("Link da Amazon mantido (%s).", item.error)
    return result


def affiliate_resolver(config):
    """Função `(urls) -> urls` ou None quando a API não está configurada."""
    if not config.amz_link_api_token or not config.affiliate_tag:
        return None
    client = AmzLinkClient(config.amz_link_api_url, config.amz_link_api_token)
    tag = config.affiliate_tag

    def resolve(urls: list[str]) -> list[str]:
        try:
            return apply_affiliate_links(urls, client, tag)
        except AmzLinkError:
            logger.warning("A API de links não respondeu. Os links atuais foram mantidos.")
            return list(urls)

    return resolve


def _host(url: str) -> str:
    hostname = urlsplit(url.strip()).hostname or ""
    return hostname.lower().removeprefix("www.")


def _result(item: object) -> LinkResult:
    if isinstance(item, dict):
        url = item.get("url")
        if isinstance(url, str) and url.startswith("https://"):
            return LinkResult(url=url, error=None)
        error = item.get("error")
        if isinstance(error, str) and error:
            return LinkResult(url=None, error=error)
    return LinkResult(url=None, error="ERRO_INTERNO")
