from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from promo_livros.filters import evaluate_product
from promo_livros.keepa_time import keepa_minutes
from promo_livros.models import PRICE_AMAZON, PRICE_BUY_BOX_SHIPPING, Deal, FilterSettings, LastPost
from promo_livros.price_history import days_as_lowest, price_points
from promo_livros.synopsis import extract_synopsis


def deals_from_products(
    products: list[dict],
    settings: FilterSettings,
    *,
    expected_product_type: int,
    now: datetime,
    last_posts: dict[str, LastPost | None],
    excluded: set[str],
    limit: int,
) -> list[Deal]:
    """Os primeiros livros que passam na régua, na ordem em que o finder devolveu."""
    chosen: list[Deal] = []
    seen: set[str] = set()
    for product in products:
        if len(chosen) >= limit:
            break
        asin = str(product.get("asin") or "").strip()
        if not asin or asin in seen or asin in excluded:
            continue
        seen.add(asin)
        evaluation = evaluate_product(
            product,
            settings,
            expected_product_type=expected_product_type,
            now=now,
            last_post=last_posts.get(asin),
        )
        if not evaluation.accepted or evaluation.deal is None:
            continue
        chosen.append(enrich_deal(evaluation.deal, product, now))
    return chosen


def enrich_deal(deal: Deal, product: dict, now: datetime) -> Deal:
    index = PRICE_AMAZON if deal.price_source == "amazon" else PRICE_BUY_BOX_SHIPPING
    points = price_points(product.get("csv"), index, with_shipping=deal.price_source != "amazon")
    return replace(
        deal,
        synopsis=extract_synopsis(product),
        lowest_for_days=days_as_lowest(points, deal.price_cents, keepa_minutes(now)),
    )


def offer_still_holds(product: dict, queued_price_cents: int, settings: FilterSettings, *, expected_product_type: int, now: datetime) -> Deal | None:
    """O preço da manhã ainda vale. Subiu, ou deixou de passar na régua, não publica."""
    evaluation = evaluate_product(
        product,
        settings,
        expected_product_type=expected_product_type,
        now=now,
        last_post=None,
    )
    if not evaluation.accepted or evaluation.deal is None:
        return None
    if evaluation.deal.price_cents > queued_price_cents:
        return None
    return enrich_deal(evaluation.deal, product, now)
