from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from dotenv import load_dotenv

from promo_livros.models import (
    AppConfig,
    ConfigError,
    FilterSettings,
    NicheConfig,
    ScheduleSettings,
    WhatsAppGroup,
)
from promo_livros.schedule_plan import build_slots, zone

AMAZON_BR_DOMAIN_ID = 12


def load_config(path: Path, environ: Mapping[str, str] | None = None) -> AppConfig:
    """Lê o YAML e o .env ao lado dele. `environ` existe para os testes não dependerem do shell."""
    config_path = path.resolve()
    if not config_path.is_file():
        raise ConfigError(f"Arquivo de configuração não encontrado: {config_path}")

    if environ is None:
        load_dotenv(config_path.parent / ".env")
        environ = os.environ

    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ConfigError("config.yaml precisa ser um mapa de seções.")

    root = config_path.parent
    return _build(raw, environ, root)


def _build(raw: Mapping, environ: Mapping[str, str], root: Path) -> AppConfig:
    keepa = _section(raw, "keepa")
    sales = _section(raw, "sales")
    rating = _section(raw, "rating")
    price = _section(raw, "price")
    schedule = _section(raw, "schedule")
    storage = _section(raw, "storage")
    logging_section = _section(raw, "logging")
    whatsapp = _section(raw, "whatsapp")
    website = _section(raw, "website")

    domain_id = _as_int(keepa, "domain_id", minimum=1)
    if domain_id != AMAZON_BR_DOMAIN_ID:
        raise ConfigError(
            "Este bot monta links da Amazon.com.br e só aceita keepa.domain_id = 12."
        )

    category_name = _as_str(keepa, "category_name")
    affiliate_tag = environ.get("AMAZON_AFFILIATE_TAG", "").strip()
    if affiliate_tag and not _valid_affiliate_tag(affiliate_tag):
        raise ConfigError(
            "AMAZON_AFFILIATE_TAG só pode ter letras, números e hífen (exemplo: meunome-20)."
        )

    filters = FilterSettings(
        current_rank_lte=_as_int(sales, "current_rank_lte", minimum=1),
        avg30_rank_lte=_as_int(sales, "avg30_rank_lte", minimum=1),
        sales_rank_drops30_gte=_as_int(sales, "sales_rank_drops30_gte", minimum=0),
        current_rating_gte=_as_int(rating, "current_rating_gte", minimum=0, maximum=50),
        current_review_count_gte=_as_int(rating, "current_review_count_gte", minimum=0),
        historic_low_tolerance_percent=_as_int(
            price, "historic_low_tolerance_percent", minimum=0, maximum=100
        ),
        min_discount_vs_avg90_percent=_as_int(
            price, "min_discount_vs_avg90_percent", minimum=0, maximum=100
        ),
        min_tracking_days=_as_int(price, "min_tracking_days", minimum=1),
        repost_window_days=_as_int(storage, "repost_window_days", minimum=1),
    )

    api_key = environ.get("KEEPA_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("Defina KEEPA_API_KEY no arquivo .env.")

    schedule_settings = _schedule(schedule)
    niches = _niches(raw)
    # Valida o fuso na carga, antes do primeiro agendamento.
    zone(schedule_settings.timezone)
    openai = _section(raw, "openai")

    return AppConfig(
        keepa_api_key=api_key,
        affiliate_tag=affiliate_tag,
        domain_id=domain_id,
        category_name=category_name,
        product_type=_as_int(keepa, "product_type", minimum=0),
        single_variation=_as_bool(keepa, "single_variation"),
        max_asins_per_run=_as_int(keepa, "max_asins_per_run", minimum=1, maximum=10_000),
        stats_days=_as_int(keepa, "stats_days", minimum=1),
        min_tokens_reserve=_as_int(keepa, "min_tokens_reserve", minimum=0),
        request_timeout_seconds=float(_as_int(keepa, "request_timeout_seconds", minimum=5)),
        max_retries=_as_int(keepa, "max_retries", minimum=1, maximum=8),
        filters=filters,
        schedule=schedule_settings,
        niches=niches,
        slots=build_slots(schedule_settings, niches),
        openai_api_key=environ.get("OPENAI_API_KEY", "").strip(),
        openai_model=_as_str(openai, "model"),
        openai_max_chars=_as_int(openai, "max_chars", minimum=40, maximum=400),
        sqlite_path=_resolve(root, _as_str(storage, "sqlite_path")),
        log_path=_resolve(root, _as_str(logging_section, "file")),
        whatsapp_enabled=_as_bool(whatsapp, "enabled"),
        whatsapp_gap_seconds=_gap_seconds(whatsapp),
        whatsapp_groups=_whatsapp_groups(whatsapp),
        waha_url=environ.get("WAHA_URL", "http://127.0.0.1:4443").strip() or "http://127.0.0.1:4443",
        waha_api_key=environ.get("WAHA_API_KEY", "").strip(),
        waha_session=environ.get("WAHA_SESSION", "promo-livros").strip() or "promo-livros",
        website_enabled=_as_bool(website, "enabled"),
        amz_link_api_url=_amz_link_api_url(environ),
        amz_link_api_token=environ.get("AMZ_TOKEN", "").strip(),
    )


_GROUP_ID_RE = re.compile(r"^[0-9-]+@g\.us$")


def _amz_link_api_url(environ: Mapping[str, str]) -> str:
    raw = environ.get("AMZ_LINK_API_URL", "").strip() or "http://127.0.0.1:3070"
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError("AMZ_LINK_API_URL precisa ser um endereço http ou https.")
    return raw.rstrip("/")


def _gap_seconds(section: Mapping) -> int:
    if "gap_seconds" not in section:
        return 45
    return _as_int(section, "gap_seconds", minimum=5, maximum=600)


def _whatsapp_groups(section: Mapping) -> tuple[WhatsAppGroup, ...]:
    rows = section.get("groups", [])
    if rows is None:
        return ()
    if not isinstance(rows, list):
        raise ConfigError("config.yaml: whatsapp.groups precisa ser uma lista.")
    groups: list[WhatsAppGroup] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ConfigError("Cada grupo do WhatsApp precisa ter name e id.")
        chat_id = _as_str(row, "id")
        if _GROUP_ID_RE.fullmatch(chat_id) is None:
            raise ConfigError(f"config.yaml: id de grupo inválido '{chat_id}'.")
        if chat_id in seen:
            raise ConfigError(f"config.yaml: grupo repetido '{chat_id}'.")
        seen.add(chat_id)
        groups.append(WhatsAppGroup(name=_as_str(row, "name"), chat_id=chat_id))
    if _as_bool(section, "enabled") and not groups:
        raise ConfigError("whatsapp.enabled está true e whatsapp.groups está vazio.")
    return tuple(groups)


def _schedule(section: Mapping) -> ScheduleSettings:
    search_hour, search_minute = _as_clock(section, "search_time")
    start_hour, start_minute = _as_clock(section, "publish_start")
    end_hour, end_minute = _as_clock(section, "publish_end")
    return ScheduleSettings(
        timezone=_as_str(section, "timezone"),
        search_hour=search_hour,
        search_minute=search_minute,
        publish_start_hour=start_hour,
        publish_start_minute=start_minute,
        publish_end_hour=end_hour,
        publish_end_minute=end_minute,
        posts_per_hour=_as_int(section, "posts_per_hour", minimum=1, maximum=6),
        per_niche=_as_int(section, "per_niche", minimum=1, maximum=24),
        reserves_per_niche=_as_int(section, "reserves_per_niche", minimum=0, maximum=6),
    )


def _niches(raw: Mapping) -> tuple[NicheConfig, ...]:
    rows = raw.get("niches")
    if not isinstance(rows, list) or not rows:
        raise ConfigError("config.yaml: 'niches' precisa ser uma lista com ao menos um nicho.")
    niches: list[NicheConfig] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ConfigError("Cada nicho precisa ter key, label e category_id.")
        key = _as_str(row, "key")
        if not re.fullmatch(r"[a-z0-9_]+", key):
            raise ConfigError(f"config.yaml: a key do nicho '{key}' só pode ter letras minúsculas, números e _.")
        if key in seen:
            raise ConfigError(f"config.yaml: nicho repetido '{key}'.")
        seen.add(key)
        niches.append(
            NicheConfig(
                key=key,
                label=_as_str(row, "label"),
                category_id=_as_int(row, "category_id", minimum=1),
            )
        )
    return tuple(niches)


_CLOCK_RE = re.compile(r"^(\d{2}):(\d{2})$")


def _as_clock(section: Mapping, key: str) -> tuple[int, int]:
    text = _as_str(section, key)
    match = _CLOCK_RE.fullmatch(text)
    if match is None:
        raise ConfigError(f"config.yaml: '{key}' precisa ser um horário HH:MM.")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ConfigError(f"config.yaml: '{key}' não é um horário válido.")
    return hour, minute


def _section(raw: Mapping, name: str) -> Mapping:
    section = raw.get(name)
    if not isinstance(section, dict):
        raise ConfigError(f"A seção '{name}' do config.yaml está ausente ou não é um mapa.")
    return section


def _as_str(section: Mapping, key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"config.yaml: '{key}' precisa ser um texto não vazio.")
    return value.strip()


def _as_bool(section: Mapping, key: str) -> bool:
    value = section.get(key)
    if not isinstance(value, bool):
        raise ConfigError(f"config.yaml: '{key}' precisa ser true ou false.")
    return value


def _as_int(
    section: Mapping,
    key: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"config.yaml: '{key}' precisa ser um número inteiro.")
    if minimum is not None and value < minimum:
        raise ConfigError(f"config.yaml: '{key}' não pode ser menor que {minimum}.")
    if maximum is not None and value > maximum:
        raise ConfigError(f"config.yaml: '{key}' não pode ser maior que {maximum}.")
    return value


def _resolve(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def _valid_affiliate_tag(tag: str) -> bool:
    return all(character.isalnum() or character == "-" for character in tag)
