from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


# Índices do csv / stats do Keepa. Fonte: Product Object, tabela "The csv History Array".
PRICE_AMAZON = 0
PRICE_SALES = 3
PRICE_RATING = 16
PRICE_COUNT_REVIEWS = 17
PRICE_BUY_BOX_SHIPPING = 18

# Minutos entre a época Keepa e o Unix epoch. Fonte: Keepa Time Minutes.
KEEPA_TIME_OFFSET_MINUTES = 21_564_000


class ConfigError(Exception):
    """Configuração ausente ou incoerente. Não adianta tentar de novo sem editar o arquivo."""


class KeepaError(Exception):
    """Falha da API Keepa que não deve derrubar o processo agendado."""


class KeepaTokenError(KeepaError):
    def __init__(self, message: str, *, refill_in_ms: int | None) -> None:
        super().__init__(message)
        self.refill_in_ms = refill_in_ms


class KeepaRetryableError(KeepaError):
    """Rede instável ou erro 5xx. Vale tentar de novo com espera."""


@dataclass(frozen=True)
class FilterSettings:
    current_rank_lte: int
    avg30_rank_lte: int
    sales_rank_drops30_gte: int
    current_rating_gte: int
    current_review_count_gte: int
    historic_low_tolerance_percent: int
    min_discount_vs_avg90_percent: int
    min_tracking_days: int
    repost_window_days: int


@dataclass(frozen=True)
class ScheduleSettings:
    timezone: str
    search_hour: int
    search_minute: int
    publish_start_hour: int
    publish_start_minute: int
    publish_end_hour: int
    publish_end_minute: int
    posts_per_hour: int
    per_niche: int
    reserves_per_niche: int


@dataclass(frozen=True)
class NicheConfig:
    key: str
    label: str
    category_id: int


@dataclass(frozen=True)
class PublishSlot:
    hour: int
    minute: int
    niche_key: str
    rank: int


@dataclass(frozen=True)
class AppConfig:
    keepa_api_key: str
    affiliate_tag: str
    domain_id: int
    category_name: str
    product_type: int
    single_variation: bool
    max_asins_per_run: int
    stats_days: int
    min_tokens_reserve: int
    request_timeout_seconds: float
    max_retries: int
    filters: FilterSettings
    schedule: ScheduleSettings
    niches: tuple[NicheConfig, ...]
    slots: tuple[PublishSlot, ...]
    openai_api_key: str
    openai_model: str
    openai_max_chars: int
    sqlite_path: Path
    log_path: Path
    whatsapp_enabled: bool
    whatsapp_gap_seconds: int
    whatsapp_groups: tuple[WhatsAppGroup, ...]
    waha_url: str
    waha_api_key: str
    waha_session: str
    website_enabled: bool
    amz_link_api_url: str
    amz_link_api_token: str
    shopee_app_id: str
    shopee_secret: str
    shopee_sub_id: str
    magalu_promoter_id: str
    magalu_partner_id: str
    aqui_api_key: str
    aqui_base_url: str


@dataclass(frozen=True)
class WhatsAppGroup:
    name: str
    chat_id: str


@dataclass(frozen=True)
class Dispatch:
    id: int
    day: str
    niche_key: str
    position: int
    asin: str
    title: str
    price_cents: int
    chat_id: str
    group_name: str
    caption: str
    image_url: str | None
    status: str
    queued_at: datetime


@dataclass(frozen=True)
class LastPost:
    asin: str
    title: str
    price_cents: int
    posted_at: datetime


@dataclass(frozen=True)
class Deal:
    asin: str
    title: str
    author: str
    price_cents: int
    avg90_cents: int
    historic_min_cents: int
    rating: int
    review_count: int
    image_url: str | None
    price_source: str
    synopsis: str = ""
    lowest_for_days: int | None = None
    niche_label: str = ""
    blurb: str = ""


@dataclass(frozen=True)
class QueuedPost:
    day: str
    niche_key: str
    position: int
    asin: str
    title: str
    author: str
    niche_label: str
    price_cents: int
    avg90_cents: int
    historic_min_cents: int
    rating: int
    review_count: int
    image_url: str | None
    price_source: str
    synopsis: str
    lowest_for_days: int | None
    blurb: str
    status: str


@dataclass(frozen=True)
class Evaluation:
    accepted: bool
    reason: str | None
    detail: str
    deal: Deal | None = None
    is_repost: bool = False


@dataclass(frozen=True)
class RenderedMessage:
    caption: str
    image_url: str | None
    price_cents: int


class DealPoster(Protocol):
    def send_deal(self, caption: str, image_url: str | None) -> None:
        """Publica a oferta. WhatsApp e o site usam este mesmo método."""


@dataclass(frozen=True)
class FinderQuery:
    name: str
    selection: dict
