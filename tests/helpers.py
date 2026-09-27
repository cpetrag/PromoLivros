from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from promo_livros.config import load_config
from promo_livros.keepa_time import keepa_minutes
from promo_livros.models import (
    PRICE_AMAZON,
    PRICE_BUY_BOX_SHIPPING,
    PRICE_COUNT_REVIEWS,
    PRICE_RATING,
    PRICE_SALES,
    AppConfig,
    FilterSettings,
)

NOW = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)

SAMPLE_YAML = """
keepa:
  domain_id: 12
  category_name: "Livros"
  product_type: 0
  single_variation: false
  max_asins_per_run: 50
  stats_days: 180
  min_tokens_reserve: 20
  request_timeout_seconds: 45
  max_retries: 3
sales:
  current_rank_lte: 20000
  avg30_rank_lte: 30000
  sales_rank_drops30_gte: 10
rating:
  current_rating_gte: 45
  current_review_count_gte: 100
price:
  historic_low_tolerance_percent: 0
  min_discount_vs_avg90_percent: 20
  min_tracking_days: 180
schedule:
  timezone: "America/Sao_Paulo"
  search_time: "06:00"
  publish_start: "20:00"
  publish_end: "22:00"
  posts_per_hour: 3
  per_niche: 2
  reserves_per_niche: 2
niches:
  - key: ficcao
    label: "Ficção"
    category_id: 7872687011
  - key: nao_ficcao
    label: "Não ficção"
    category_id: 7843068011
  - key: biografia
    label: "Biografia"
    category_id: 7841731011
openai:
  model: "gpt-4.1-mini"
  max_chars: 180
storage:
  sqlite_path: "data/promo_livros.sqlite"
  repost_window_days: 30
logging:
  file: "logs/promo_livros.log"
whatsapp:
  enabled: false
website:
  enabled: false
"""


def write_config(directory: Path, yaml_text: str = SAMPLE_YAML) -> Path:
    path = directory / "config.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


def load_sample(directory: Path, **env: str) -> AppConfig:
    environ = {
        "KEEPA_API_KEY": "test-key",
        "AMAZON_AFFILIATE_TAG": "loja-20",
    }
    environ.update(env)
    return load_config(write_config(directory), environ)


def filter_settings(**overrides: int) -> FilterSettings:
    values = dict(
        current_rank_lte=20_000,
        avg30_rank_lte=30_000,
        sales_rank_drops30_gte=10,
        current_rating_gte=45,
        current_review_count_gte=100,
        historic_low_tolerance_percent=0,
        min_discount_vs_avg90_percent=20,
        min_tracking_days=180,
        repost_window_days=30,
    )
    values.update(overrides)
    return FilterSettings(**values)


def _series(values: dict[int, int]) -> list[int]:
    row = [-1] * 19
    for index, value in values.items():
        row[index] = value
    return row


def _mins(values: dict[int, int]) -> list:
    row: list = [None] * 19
    for index, value in values.items():
        row[index] = [1_000, value]
    return row


def make_product(**overrides) -> dict:
    tracked_since = keepa_minutes(NOW - timedelta(days=200))
    product = {
        "asin": "B00TEST123",
        "title": "O Nome do Vento",
        "productType": 0,
        "availabilityAmazon": 0,
        "trackingSince": tracked_since,
        "contributors": [["author", "Patrick Rothfuss"]],
        "images": [{"l": "capa.jpg", "variant": "MAIN"}],
        "csv": None,
        "stats": {
            "current": _series(
                {
                    PRICE_AMAZON: 2_000,
                    PRICE_SALES: 1_000,
                    PRICE_RATING: 47,
                    PRICE_COUNT_REVIEWS: 1_500,
                    PRICE_BUY_BOX_SHIPPING: -1,
                }
            ),
            "avg30": _series({PRICE_SALES: 5_000}),
            "avg90": _series({PRICE_AMAZON: 4_000, PRICE_BUY_BOX_SHIPPING: -1}),
            "min": _mins({PRICE_AMAZON: 2_000}),
            "salesRankDrops30": 12,
        },
    }
    product.update(overrides)
    return product
