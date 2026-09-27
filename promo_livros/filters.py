from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from promo_livros.models import (
    PRICE_AMAZON,
    PRICE_BUY_BOX_SHIPPING,
    PRICE_COUNT_REVIEWS,
    PRICE_RATING,
    PRICE_SALES,
    Deal,
    Evaluation,
    FilterSettings,
    LastPost,
)
from promo_livros.keepa_time import keepa_minutes, minimum_positive_price

logger = logging.getLogger("promo_livros")

# Ordem do funil: cada livro conta uma vez, no primeiro motivo que o elimina.
REASON_LABELS = {
    "incomplete": "dados_incompletos",
    "product_type": "tipo_produto",
    "sales_rank": "ranking_atual",
    "sales_avg30": "ranking_media_30d",
    "sales_drops": "quedas_ranking_30d",
    "rating": "nota",
    "reviews": "avaliacoes",
    "tracking": "rastreio_insuficiente",
    "third_party": "so_terceiros",
    "historic_low": "nao_e_menor_preco",
    "discount": "desconto_insuficiente",
    "already_posted": "ja_postado",
}


@dataclass
class FilterReport:
    finder_amazon: int = 0
    finder_buy_box: int = 0
    finder_amazon_total: int = 0
    finder_buy_box_total: int = 0
    capped: int = 0
    fetched: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    accepted: int = 0
    reposted: int = 0
    posted: int = 0
    dry_run: int = 0
    send_failed: int = 0

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1

    def summary(self) -> str:
        parts = [
            f"finder_amazon_pagina={self.finder_amazon}",
            f"finder_amazon_total={self.finder_amazon_total}",
            f"finder_buy_box_pagina={self.finder_buy_box}",
            f"finder_buy_box_total={self.finder_buy_box_total}",
            f"descartados_pelo_limite={self.capped}",
            f"detalhes_baixados={self.fetched}",
        ]
        for reason, label in REASON_LABELS.items():
            parts.append(f"{label}={self.rejected.get(reason, 0)}")
        parts.append(f"aceitos={self.accepted}")
        parts.append(f"repostados_preco_menor={self.reposted}")
        parts.append(f"postados={self.posted}")
        parts.append(f"dry_run={self.dry_run}")
        parts.append(f"falha_envio={self.send_failed}")
        return "resumo: " + " ".join(parts)


def evaluate_product(
    product: dict,
    settings: FilterSettings,
    *,
    expected_product_type: int,
    now: datetime,
    last_post: LastPost | None,
) -> Evaluation:
    """Reaplica os critérios em cima do /product. A query já cortou a maior parte."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    asin = str(product.get("asin") or "").strip()
    title = _clean_text(product.get("title"))
    stats = product.get("stats")
    if not asin or not title or not isinstance(stats, dict):
        return _reject("incomplete", "sem asin, título ou stats")

    product_type = product.get("productType")
    if product_type != expected_product_type:
        return _reject("product_type", f"productType={product_type}")

    current_rank = _stat_int(stats, "current", PRICE_SALES)
    if current_rank is None or current_rank < 1:
        return _reject("incomplete", "ranking atual ausente")
    if current_rank > settings.current_rank_lte:
        return _reject("sales_rank", f"ranking={current_rank} limite={settings.current_rank_lte}")

    avg30_rank = _stat_int(stats, "avg30", PRICE_SALES)
    if avg30_rank is None or avg30_rank < 1:
        return _reject("incomplete", "média de 30 dias do ranking ausente")
    if avg30_rank > settings.avg30_rank_lte:
        return _reject("sales_avg30", f"media30={avg30_rank} limite={settings.avg30_rank_lte}")

    drops = stats.get("salesRankDrops30")
    if not isinstance(drops, int) or isinstance(drops, bool):
        return _reject("incomplete", "salesRankDrops30 ausente")
    if drops < settings.sales_rank_drops30_gte:
        return _reject("sales_drops", f"quedas={drops} minimo={settings.sales_rank_drops30_gte}")

    rating = _stat_int(stats, "current", PRICE_RATING)
    if rating is None or rating < 0:
        return _reject("incomplete", "nota ausente")
    if rating < settings.current_rating_gte or rating > 50:
        return _reject("rating", f"nota={rating} minimo={settings.current_rating_gte}")

    reviews = _stat_int(stats, "current", PRICE_COUNT_REVIEWS)
    if reviews is None or reviews < 0:
        return _reject("incomplete", "avaliações ausentes")
    if reviews < settings.current_review_count_gte:
        return _reject("reviews", f"avaliacoes={reviews} minimo={settings.current_review_count_gte}")

    tracking_since = product.get("trackingSince")
    if not isinstance(tracking_since, int) or isinstance(tracking_since, bool) or tracking_since <= 0:
        return _reject("incomplete", "trackingSince ausente")
    age_days = (keepa_minutes(now) - tracking_since) / (24 * 60)
    if age_days < settings.min_tracking_days:
        return _reject(
            "tracking",
            f"dias_rastreado={age_days:.0f} minimo={settings.min_tracking_days}",
        )

    amazon_ok = product.get("availabilityAmazon") == 0
    chosen, failure = _choose_offer(
        stats,
        product.get("csv"),
        settings,
        amazon_available=amazon_ok,
    )
    if chosen is None:
        return _reject(failure or "third_party", "nenhuma oferta da Amazon ou da Buy Box passou")

    price_cents, avg90_cents, historic_min, source = chosen
    is_repost = False
    if last_post is not None:
        within_window = now - last_post.posted_at <= timedelta(days=settings.repost_window_days)
        if within_window and price_cents >= last_post.price_cents:
            return _reject(
                "already_posted",
                f"ultimo={last_post.price_cents} atual={price_cents}",
            )
        is_repost = within_window and price_cents < last_post.price_cents

    deal = Deal(
        asin=asin,
        title=title,
        author=extract_author(product),
        price_cents=price_cents,
        avg90_cents=avg90_cents,
        historic_min_cents=historic_min,
        rating=rating,
        review_count=reviews,
        image_url=extract_image_url(product),
        price_source=source,
    )
    detail = f"fonte={source} preco={price_cents} media90={avg90_cents} minimo={historic_min}"
    return Evaluation(accepted=True, reason=None, detail=detail, deal=deal, is_repost=is_repost)


def extract_author(product: dict) -> str:
    contributors = product.get("contributors") or []
    names: list[str] = []
    author_roles = {"author", "autor"}
    for entry in contributors:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        left = str(entry[0]).strip()
        right = str(entry[1]).strip()
        if left.casefold() in author_roles and right:
            names.append(right)
        elif right.casefold() in author_roles and left:
            names.append(left)
    if names:
        return ", ".join(names)
    return "Autor desconhecido"


def extract_image_url(product: dict) -> str | None:
    images = product.get("images") or []
    if not isinstance(images, list) or not images:
        return None
    chosen = next(
        (
            image
            for image in images
            if isinstance(image, dict) and str(image.get("variant", "")).upper() == "MAIN"
        ),
        images[0],
    )
    if not isinstance(chosen, dict):
        return None
    filename = chosen.get("l") or chosen.get("m")
    if not isinstance(filename, str) or not filename.strip():
        return None
    return f"https://m.media-amazon.com/images/I/{filename.strip()}"


def _choose_offer(
    stats: dict,
    csv,
    settings: FilterSettings,
    *,
    amazon_available: bool,
) -> tuple[tuple[int, int, int, str] | None, str | None]:
    """Amazon primeiro. Buy Box só entra se a oferta da Amazon não passar nas travas de preço."""
    failure: str | None = None
    saw_offer = False

    if amazon_available:
        outcome = _inspect_offer(stats, csv, PRICE_AMAZON, settings, with_shipping=False)
        if isinstance(outcome, tuple):
            return (*outcome, "amazon"), None
        if outcome != "incomplete":
            saw_offer = True
            failure = outcome

    buy_box = _inspect_offer(
        stats, csv, PRICE_BUY_BOX_SHIPPING, settings, with_shipping=True
    )
    if isinstance(buy_box, tuple):
        return (*buy_box, "buy_box"), None
    if buy_box != "incomplete":
        saw_offer = True
        failure = failure or buy_box

    if not saw_offer:
        if amazon_available:
            return None, "incomplete"
        return None, "third_party"
    return None, failure or "historic_low"


def _inspect_offer(
    stats: dict,
    csv,
    index: int,
    settings: FilterSettings,
    *,
    with_shipping: bool,
) -> tuple[int, int, int] | str:
    current = minimum_positive_price(_stat_int(stats, "current", index))
    avg90 = minimum_positive_price(_stat_int(stats, "avg90", index))
    historic = _historic_min(stats, csv, index, with_shipping=with_shipping)
    if current is None or avg90 is None or historic is None:
        return "incomplete"

    ceiling = (historic * (100 + settings.historic_low_tolerance_percent)) // 100
    if current > ceiling:
        return "historic_low"
    if (avg90 - current) * 100 < settings.min_discount_vs_avg90_percent * avg90:
        return "discount"
    return current, avg90, historic


def _historic_min(stats: dict, csv, index: int, *, with_shipping: bool) -> int | None:
    # `min` é o menor valor já registrado. `minInInterval` só cobre a janela do stats=180.
    entry = _stat_value(stats, "min", index)
    if isinstance(entry, list) and len(entry) >= 2:
        price = minimum_positive_price(_as_int(entry[1]))
        if price is not None:
            return price
    return historic_min_from_csv(csv, index, with_shipping=with_shipping)


def historic_min_from_csv(csv: list | None, index: int, *, with_shipping: bool) -> int | None:
    if not isinstance(csv, list) or index >= len(csv):
        return None
    history = csv[index]
    if not isinstance(history, list):
        return None
    step = 3 if with_shipping else 2
    lowest: int | None = None
    for offset in range(0, len(history) - step + 1, step):
        price = _as_int(history[offset + 1])
        if price is None or price <= 0:
            continue
        landing = price
        if with_shipping:
            shipping = _as_int(history[offset + 2])
            if shipping is None or shipping < 0:
                shipping = 0
            landing = price + shipping
        if lowest is None or landing < lowest:
            lowest = landing
    return lowest


def _stat_int(stats: dict, field_name: str, index: int) -> int | None:
    return _as_int(_stat_value(stats, field_name, index))


def _stat_value(stats: dict, field_name: str, index: int):
    values = stats.get(field_name)
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def _as_int(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _clean_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", " ").split())


def _reject(reason: str, detail: str) -> Evaluation:
    return Evaluation(accepted=False, reason=reason, detail=detail, deal=None)
