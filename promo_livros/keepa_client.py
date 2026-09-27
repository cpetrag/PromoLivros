from __future__ import annotations

import logging
import math
import re
import time
from typing import Any

import requests

from promo_livros.keepa_time import tracking_since_lte
from promo_livros.models import (
    AppConfig,
    FinderQuery,
    KeepaError,
    KeepaRetryableError,
    KeepaTokenError,
)

logger = logging.getLogger("promo_livros")

_API_ROOT = "https://api.keepa.com"
_KEY_RE = re.compile(r"(key=)[^&\s]+", re.IGNORECASE)
_TOKEN_WAITS_LIMIT = 5


class KeepaClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"
        self._session.headers["User-Agent"] = "promo-livros/1.0"
        self.tokens_left: int | None = None
        self.refill_in_ms: int | None = None
        self.refill_rate: int | None = None
        self._tokens_updated_at: float | None = None

    def close(self) -> None:
        self._session.close()

    def balance_is_fresh(self) -> bool:
        # Tokens não usados expiram em 60 minutos, então um saldo velho não serve para decidir a espera.
        if self.tokens_left is None or self._tokens_updated_at is None:
            return False
        return (time.monotonic() - self._tokens_updated_at) < 120

    def lookup_category_name(self, category_id: int) -> str | None:
        payload = self._request(
            "GET",
            "/category",
            params={"category": category_id, "parents": 0},
            estimated_tokens=1,
        )
        categories = payload.get("categories")
        if not isinstance(categories, dict):
            return None
        node = categories.get(str(category_id))
        if not isinstance(node, dict):
            return None
        name = node.get("name")
        return name if isinstance(name, str) and name.strip() else None

    def subcategory_ids(self, category_id: int) -> list[int]:
        payload = self._request(
            "GET",
            "/category",
            params={"category": category_id, "parents": 0},
            estimated_tokens=1,
        )
        categories = payload.get("categories")
        if not isinstance(categories, dict):
            return []
        node = categories.get(str(category_id))
        if not isinstance(node, dict):
            return []
        children = node.get("children") or []
        if not isinstance(children, list):
            return []
        ids: list[int] = []
        for child in children:
            if isinstance(child, bool):
                continue
            if isinstance(child, int):
                ids.append(child)
            elif isinstance(child, str) and child.isdigit():
                ids.append(int(child))
        return ids

    def root_categories(self) -> dict[str, dict]:
        payload = self._request(
            "GET",
            "/category",
            params={"category": 0, "parents": 0},
            estimated_tokens=1,
        )
        categories = payload.get("categories")
        if not isinstance(categories, dict) or not categories:
            raise KeepaError("A API de categorias não devolveu a lista de raízes.")
        return categories

    def finder(self, selection: dict) -> tuple[list[str], int]:
        per_page = int(selection.get("perPage") or 50)
        estimated = 10 + math.ceil(per_page / 100)
        payload = self._request(
            "POST",
            "/query",
            params={},
            json_body=selection,
            estimated_tokens=estimated,
        )
        raw_asins = payload.get("asinList") or []
        if not isinstance(raw_asins, list):
            raise KeepaError("Resposta do Product Finder sem asinList.")
        asins = [asin for asin in raw_asins if isinstance(asin, str) and asin]
        total = payload.get("totalResults")
        total_results = total if isinstance(total, int) else len(asins)
        return asins, total_results

    def products(self, asins: list[str]) -> list[dict]:
        found: list[dict] = []
        # O histórico csv vem ligado por omissão. history=0 é que o desliga.
        for start in range(0, len(asins), 100):
            chunk = asins[start : start + 100]
            payload = self._request(
                "GET",
                "/product",
                params={
                    "asin": ",".join(chunk),
                    "stats": self._config.stats_days,
                    # Sem isto, stats.current da nota e das avaliações volta -1,
                    # mesmo com o finder tendo filtrado current_RATING.
                    "rating": 1,
                },
                # rating=1 pode cobrar mais 1 token por ASIN quando o dado tem menos de 14 dias.
                estimated_tokens=len(chunk) * 2,
            )
            products = payload.get("products") or []
            if not isinstance(products, list):
                raise KeepaError("Resposta de /product sem a lista products.")
            for product in products:
                if isinstance(product, dict):
                    found.append(product)
        return found

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict,
        estimated_tokens: int,
        json_body: dict | None = None,
        skip_wait: bool = False,
    ) -> dict:
        query = {"key": self._config.keepa_api_key, "domain": self._config.domain_id, **params}
        token_waits = 0
        attempt = 0
        last_error: Exception | None = None

        while True:
            if not skip_wait:
                self._wait_until_affordable(estimated_tokens)
            try:
                response = self._session.request(
                    method,
                    f"{_API_ROOT}{path}",
                    params=query,
                    json=json_body,
                    timeout=self._config.request_timeout_seconds,
                )
            except requests.RequestException as exc:
                attempt += 1
                last_error = exc
                if attempt >= self._config.max_retries:
                    raise KeepaError(f"Falha de rede em {path} após {attempt} tentativas.") from exc
                self._backoff(attempt, exc)
                continue

            payload = _json_or_empty(response)
            self._remember_tokens(payload)

            if _is_token_exhausted(response.status_code, payload):
                token_waits += 1
                refill = _refill_ms(payload) or self.refill_in_ms or 60_000
                last_error = KeepaTokenError("tokens do Keepa esgotados", refill_in_ms=refill)
                if token_waits > _TOKEN_WAITS_LIMIT:
                    raise last_error
                self._sleep_for_tokens(refill, reason="a API recusou a chamada por falta de tokens")
                self.tokens_left = 0
                continue

            if response.status_code >= 500:
                attempt += 1
                last_error = KeepaRetryableError(f"Keepa respondeu HTTP {response.status_code} em {path}.")
                if attempt >= self._config.max_retries:
                    raise last_error
                self._backoff(attempt, last_error)
                continue

            message = _error_message(payload)
            if _result_present(path, payload) and response.status_code < 400:
                # Lote pode trazer produtos e, ainda assim, um aviso. Isso não invalida o que veio.
                if message:
                    logger.warning("Keepa avisou em %s: %s", path, message)
                return payload

            if response.status_code >= 400 or message:
                reason = message or f"HTTP {response.status_code}"
                raise KeepaError(f"Keepa recusou {path}: {reason}")

            return payload

    def _wait_until_affordable(self, needed: int) -> None:
        if self.tokens_left is None:
            return
        target = needed + self._config.min_tokens_reserve
        if self.tokens_left >= target:
            return
        missing = target - max(self.tokens_left, 0)
        rate = self.refill_rate if self.refill_rate and self.refill_rate > 0 else 1
        cycles = math.ceil(missing / rate)
        first_wait_ms = self.refill_in_ms if self.refill_in_ms and self.refill_in_ms > 0 else 60_000
        wait_ms = first_wait_ms + max(cycles - 1, 0) * 60_000
        self._sleep_for_tokens(wait_ms, reason=f"saldo {self.tokens_left}, precisa de {target}")
        # A resposta seguinte substitui este número. Sem isso, um retry de rede da mesma chamada esperaria de novo.
        self.tokens_left = target

    def _sleep_for_tokens(self, wait_ms: int, *, reason: str) -> None:
        remaining = max(wait_ms / 1000, 1) + 2
        logger.warning("Tokens do Keepa baixos (%s). Aguardando %.0f s.", reason, remaining)
        while remaining > 0:
            step = min(60, remaining)
            time.sleep(step)
            remaining -= step
            if remaining > 0:
                logger.info("Ainda aguardando tokens do Keepa, faltam cerca de %.0f s.", remaining)

    def _backoff(self, attempt: int, exc: Exception) -> None:
        delay = min(2 ** (attempt - 1), 30)
        logger.warning(
            "Falha ao falar com o Keepa (tentativa %s/%s): %s. Nova tentativa em %s s.",
            attempt,
            self._config.max_retries,
            _sanitize(str(exc)),
            delay,
        )
        time.sleep(delay)

    def _remember_tokens(self, payload: dict) -> None:
        left = payload.get("tokensLeft")
        if isinstance(left, int):
            self.tokens_left = left
        refill_in = payload.get("refillIn")
        if isinstance(refill_in, int):
            self.refill_in_ms = refill_in
        rate = payload.get("refillRate")
        if isinstance(rate, int):
            self.refill_rate = rate
        consumed = payload.get("tokensConsumed")
        if isinstance(left, int):
            self._tokens_updated_at = time.monotonic()
            logger.info(
                "Keepa tokens restantes: %s (consumidos nesta chamada: %s).",
                left,
                consumed if isinstance(consumed, int) else "?",
            )


def merge_asins(groups: list[list[str]], limit: int) -> tuple[list[str], int]:
    """A primeira lista tem prioridade (oferta da Amazon). Devolve (selecionados, descartados)."""
    ordered: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for asin in group:
            if asin in seen:
                continue
            seen.add(asin)
            ordered.append(asin)
    if len(ordered) <= limit:
        return ordered, 0
    return ordered[:limit], len(ordered) - limit


def category_include_ids(parent_id: int, children: list[int], limit: int = 50) -> list[int]:
    """O finder aceita no máximo 50 ids. O nicho vem primeiro para não ser cortado."""
    ordered: list[int] = []
    seen: set[int] = set()
    for value in (parent_id, *children):
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
        if len(ordered) == limit:
            break
    return ordered


def build_finder_queries(
    config: AppConfig,
    category_id: int,
    now,
    category_ids: list[int] | None = None,
) -> list[FinderQuery]:
    """Duas buscas porque o Product Finder junta filtros com AND e a oferta é Amazon OU Buy Box."""
    filters = config.filters
    per_page = max(50, min(config.max_asins_per_run, 10_000))
    shared: dict[str, Any] = {
        "rootCategory": [category_id],
        "productType": config.product_type,
        "current_SALES_gte": 1,
        "current_SALES_lte": filters.current_rank_lte,
        "avg30_SALES_gte": 1,
        "avg30_SALES_lte": filters.avg30_rank_lte,
        "salesRankDrops30_gte": filters.sales_rank_drops30_gte,
        "current_RATING_gte": filters.current_rating_gte,
        "current_COUNT_REVIEWS_gte": filters.current_review_count_gte,
        "trackingSince_lte": tracking_since_lte(now, filters.min_tracking_days),
        "sort": [["current_SALES", "asc"]],
        "page": 0,
        "perPage": per_page,
    }
    if config.single_variation:
        shared["singleVariation"] = True
    if category_ids:
        shared["categories_include"] = category_ids[:50]

    amazon = {
        **shared,
        "current_AMAZON_gte": 1,
        "availabilityAmazon": [0],
        "deltaPercent90_AMAZON_gte": filters.min_discount_vs_avg90_percent,
    }
    buy_box = {
        **shared,
        "current_BUY_BOX_SHIPPING_gte": 1,
        "deltaPercent90_BUY_BOX_SHIPPING_gte": filters.min_discount_vs_avg90_percent,
    }
    # isLowest só existe como igualdade com o mínimo histórico. Com tolerância, o corte fica no Python.
    if filters.historic_low_tolerance_percent == 0:
        amazon["isLowest_AMAZON"] = True
        buy_box["isLowest_BUY_BOX_SHIPPING"] = True

    return [FinderQuery("amazon", amazon), FinderQuery("buy_box", buy_box)]


def find_root_category(categories: dict, name: str) -> int:
    target = name.casefold().strip()
    exact_roots: list[int] = []
    exact_any: list[int] = []
    for key, category in categories.items():
        if not isinstance(category, dict):
            continue
        category_name = str(category.get("name", "")).casefold().strip()
        if category_name != target:
            continue
        category_id = category.get("catId", key)
        try:
            parsed = int(category_id)
        except (TypeError, ValueError):
            continue
        exact_any.append(parsed)
        if category.get("parent") in (0, None):
            exact_roots.append(parsed)

    chosen = exact_roots or exact_any
    unique = list(dict.fromkeys(chosen))
    if len(unique) == 1:
        return unique[0]

    available = sorted(
        {
            str(category.get("name"))
            for category in categories.values()
            if isinstance(category, dict) and category.get("name")
        }
    )
    if len(unique) > 1:
        raise KeepaError(
            f"Há mais de uma categoria raiz chamada '{name}': {unique}. "
            "Ajuste category_name no config.yaml."
        )
    preview = ", ".join(available[:30]) or "(nenhuma)"
    raise KeepaError(
        f"Não achei a categoria raiz '{name}' na Amazon Brasil. "
        f"Nomes devolvidos pela API: {preview}."
    )


def _json_or_empty(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_token_exhausted(status_code: int, payload: dict) -> bool:
    if status_code == 429:
        return True
    message = _error_message(payload).casefold()
    return "token" in message


def _result_present(path: str, payload: dict) -> bool:
    if path == "/query":
        return isinstance(payload.get("asinList"), list)
    if path == "/product":
        return isinstance(payload.get("products"), list)
    if path == "/category":
        return isinstance(payload.get("categories"), dict)
    return False


def _error_message(payload: dict) -> str:
    error = payload.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        for key in ("message", "details", "type"):
            value = error.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _refill_ms(payload: dict) -> int | None:
    value = payload.get("refillIn")
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _sanitize(text: str) -> str:
    return _KEY_RE.sub(r"\1***", text)
