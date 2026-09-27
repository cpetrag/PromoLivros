from __future__ import annotations

import logging
from datetime import datetime, timezone

from promo_livros.blurb import BlurbWriter
from promo_livros.dispatch import drain_dispatches, enqueue_dispatches
from promo_livros.formatter import render_deal
from promo_livros.keepa_client import (
    KeepaClient,
    build_finder_queries,
    category_include_ids,
    find_root_category,
    merge_asins,
)
from promo_livros.models import AppConfig, Deal, KeepaError, QueuedPost
from promo_livros.schedule_plan import local_now, service_day
from promo_livros.selection import deals_from_products, offer_still_holds
from promo_livros.storage import Storage
from promo_livros.waha import WahaClient, WhatsAppSender

logger = logging.getLogger("promo_livros")

_PRODUCT_BATCH = 10


def prepare_day(
    config: AppConfig,
    client: KeepaClient,
    storage: Storage,
    blurb: BlurbWriter,
    now: datetime,
    *,
    dry_run: bool,
    refresh_category: bool,
    replace: bool = False,
) -> list[QueuedPost]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    day = service_day(now, config.schedule.timezone)
    if not dry_run and storage.has_queue(day) and not replace:
        logger.info("A fila de %s já está pronta.", day)
        return []
    if not dry_run and storage.day_has_posted(day):
        logger.info("A fila de %s já tem livro publicado. A busca da manhã não substitui.", day)
        return []

    root_id = resolve_root_category(client, storage, config, refresh=refresh_category, now=now)
    excluded: set[str] = set()
    rows: list[QueuedPost] = []
    need = config.schedule.per_niche + config.schedule.reserves_per_niche
    for niche in config.niches:
        try:
            deals = _pick_niche(config, client, storage, niche.category_id, root_id, now, excluded, need, refresh_category)
        except KeepaError:
            logger.exception("A busca do nicho %s falhou. Os outros nichos seguem.", niche.label)
            continue
        for position, deal in enumerate(deals):
            text = _blurb_or_blank(blurb, deal, niche.label)
            rows.append(
                QueuedPost(
                    day=day,
                    niche_key=niche.key,
                    position=position,
                    asin=deal.asin,
                    title=deal.title,
                    author=deal.author,
                    niche_label=niche.label,
                    price_cents=deal.price_cents,
                    avg90_cents=deal.avg90_cents,
                    historic_min_cents=deal.historic_min_cents,
                    rating=deal.rating,
                    review_count=deal.review_count,
                    image_url=deal.image_url,
                    price_source=deal.price_source,
                    synopsis=deal.synopsis,
                    lowest_for_days=deal.lowest_for_days,
                    blurb=text,
                    status="ready",
                )
            )
            excluded.add(deal.asin)
        logger.info("%s: %s livros na fila (meta %s, sendo %s reservas).", niche.label, len(deals), need, config.schedule.reserves_per_niche)

    _log_evening_plan(config, rows)
    if not rows and storage.has_queue(day):
        logger.info("A busca não achou livros. A fila já gravada permanece.")
        return []
    if dry_run:
        logger.info("Dry-run: a fila de %s não foi gravada.", day)
        return rows
    if not storage.replace_queue(day, rows):
        logger.info("A fila de %s já tem livro publicado. A busca da manhã não substitui.", day)
        return []
    logger.info("Fila de %s gravada com %s livros.", day, len(rows))
    return rows


def publish_slot(
    config: AppConfig,
    client: KeepaClient,
    storage: Storage,
    niche_key: str,
    rank: int,
    now: datetime,
    *,
    dry_run: bool,
    sender: WhatsAppSender | None = None,
) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    day = service_day(now, config.schedule.timezone)
    niche = next((item for item in config.niches if item.key == niche_key), None)
    label = niche.label if niche is not None else niche_key
    candidates = _candidates(storage.queue_for_niche(day, niche_key), rank, config.schedule.per_niche)
    ready = [row for row in candidates if row.status == "ready"]
    if not ready:
        logger.info("%s sem livro pronto para este horário.", label)
        return "empty"

    for row in ready:
        try:
            products = client.products([row.asin])
        except KeepaError:
            logger.exception("Falha ao conferir o preço de %s. O horário segue para o reserva.", row.asin)
            continue
        product = next((item for item in products if str(item.get("asin")) == row.asin), None)
        fresh = None if product is None else offer_still_holds(
            product,
            row.price_cents,
            config.filters,
            expected_product_type=config.product_type,
            now=now,
        )
        if fresh is None:
            logger.info("%s não segurou o preço da manhã. Pulado.", row.asin)
            if not dry_run:
                storage.mark_queue(day, niche_key, row.position, "skipped")
            continue

        days = fresh.lowest_for_days if fresh.lowest_for_days is not None else row.lowest_for_days
        deal = Deal(
            asin=fresh.asin,
            title=fresh.title,
            author=fresh.author,
            price_cents=fresh.price_cents,
            avg90_cents=fresh.avg90_cents,
            historic_min_cents=fresh.historic_min_cents,
            rating=fresh.rating,
            review_count=fresh.review_count,
            image_url=fresh.image_url or row.image_url,
            price_source=fresh.price_source,
            synopsis=row.synopsis,
            lowest_for_days=days,
            niche_label=row.niche_label,
            blurb=row.blurb,
        )
        rendered = render_deal(deal, config.affiliate_tag)
        logger.info(
            "publicação %s %s\n%s\ncapa: %s",
            label,
            row.asin,
            rendered.caption,
            rendered.image_url or "(sem capa)",
        )
        if dry_run:
            return "dry_run"
        if not config.whatsapp_enabled:
            storage.record_post(deal.asin, deal.title, rendered.price_cents, now)
            storage.mark_queue(day, niche_key, row.position, "posted")
            return "posted"

        enqueue_dispatches(
            config,
            storage,
            day=day,
            niche_key=niche_key,
            position=row.position,
            asin=deal.asin,
            title=deal.title,
            price_cents=rendered.price_cents,
            caption=rendered.caption,
            image_url=rendered.image_url,
            now=now,
        )
        storage.mark_queue(day, niche_key, row.position, "queued")
        _drain(config, storage, sender, now)
        if storage.queue_position_posted(day, niche_key, row.position):
            return "posted"
        return "queued"

    logger.info("Nenhum reserva de %s segurou o preço.", label)
    return "skipped"


def deliver_pending(
    config: AppConfig,
    storage: Storage,
    now: datetime,
    *,
    sender: WhatsAppSender | None = None,
) -> str:
    """Manda o próximo grupo da fila. O horário do livro já enfileirou o texto."""
    return _drain(config, storage, sender, now)


def _drain(
    config: AppConfig,
    storage: Storage,
    sender: WhatsAppSender | None,
    now: datetime,
) -> str:
    owns_sender = sender is None
    client = sender if sender is not None else WahaClient.from_config(config)
    try:
        return drain_dispatches(config, storage, client, now)
    finally:
        if owns_sender:
            client.close()


def should_prepare_today(config: AppConfig, now: datetime, has_queue: bool) -> bool:
    if has_queue:
        return False
    local = local_now(now, config.schedule.timezone)
    current = local.hour * 60 + local.minute
    start = config.schedule.search_hour * 60 + config.schedule.search_minute
    publish = config.schedule.publish_start_hour * 60 + config.schedule.publish_start_minute
    return start <= current < publish


def due_slots(config: AppConfig, now: datetime, *, grace_minutes: int | None) -> list:
    local = local_now(now, config.schedule.timezone)
    due = []
    for slot in config.slots:
        slot_time = local.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
        delta = (local - slot_time).total_seconds()
        if grace_minutes is None:
            if delta >= 0:
                due.append(slot)
        elif 0 <= delta <= grace_minutes * 60:
            due.append(slot)
    return due


def resolve_root_category(
    client: KeepaClient,
    storage: Storage,
    config: AppConfig,
    *,
    refresh: bool,
    now: datetime,
) -> int:
    cached = None if refresh else storage.cached_category(config.domain_id, config.category_name)
    if cached is not None and client.balance_is_fresh():
        logger.info("Categoria raiz em cache: %s (id=%s).", config.category_name, cached)
        return cached

    if cached is not None:
        confirmed_name = client.lookup_category_name(cached)
        if confirmed_name is not None and confirmed_name.casefold() == config.category_name.casefold():
            logger.info("Categoria raiz confirmada: %s (id=%s).", confirmed_name, cached)
            return cached
        logger.warning(
            "O id em cache (%s) não é mais '%s'. Consultando as categorias raiz de novo.",
            cached,
            config.category_name,
        )

    categories = client.root_categories()
    category_id = find_root_category(categories, config.category_name)
    storage.save_category(config.domain_id, config.category_name, category_id, now)
    logger.info("Categoria raiz confirmada pela API: %s (id=%s).", config.category_name, category_id)
    return category_id


def _pick_niche(config, client, storage, category_id, root_id, now, excluded, need, refresh):
    children = _child_ids(client, storage, config, category_id, now, refresh=refresh)
    include = category_include_ids(category_id, children)
    queries = build_finder_queries(config, root_id, now, category_ids=include)
    groups: list[list[str]] = []
    for query in queries:
        asins, total = client.finder(query.selection)
        logger.info("Query %s no nicho %s: %s ASINs, totalResults=%s.", query.name, category_id, len(asins), total)
        groups.append(asins)
    selected, capped = merge_asins(groups, config.max_asins_per_run)
    if capped:
        logger.info("Limite de %s ASINs no nicho %s.", config.max_asins_per_run, category_id)

    collected: list[Deal] = []
    for start in range(0, len(selected), _PRODUCT_BATCH):
        if len(collected) >= need:
            break
        chunk = [asin for asin in selected[start : start + _PRODUCT_BATCH] if asin not in excluded]
        if not chunk:
            continue
        products = client.products(chunk)
        last_posts = {asin: storage.last_post(asin) for asin in chunk}
        collected.extend(
            deals_from_products(
                products,
                config.filters,
                expected_product_type=config.product_type,
                now=now,
                last_posts=last_posts,
                excluded=excluded | {deal.asin for deal in collected},
                limit=need - len(collected),
            )
        )
    return collected


def _child_ids(client, storage, config, category_id, now, *, refresh: bool) -> list[int]:
    if not refresh:
        cached = storage.cached_children(config.domain_id, category_id)
        if cached is not None:
            return cached
    try:
        children = client.subcategory_ids(category_id)
    except KeepaError:
        logger.warning("Não deu para listar as subcategorias de %s. A busca usa só esse id.", category_id)
        return []
    storage.save_children(config.domain_id, category_id, children, now)
    return children


def _blurb_or_blank(blurb: BlurbWriter, deal: Deal, niche_label: str) -> str:
    if not deal.synopsis:
        return ""
    try:
        text = blurb.summarize(
            title=deal.title,
            author=deal.author,
            niche_label=niche_label,
            rating=deal.rating,
            review_count=deal.review_count,
            synopsis=deal.synopsis,
        )
    except Exception:
        logger.exception("Falha ao resumir %s. A mensagem sai sem a frase.", deal.asin)
        return ""
    return text or ""


def _candidates(rows: list[QueuedPost], rank: int, per_niche: int) -> list[QueuedPost]:
    primary = [row for row in rows if row.position == rank]
    reserves = [row for row in rows if row.position >= per_niche]
    return primary + reserves


def _log_evening_plan(config: AppConfig, rows: list[QueuedPost]) -> None:
    for slot in config.slots:
        match = next((row for row in rows if row.niche_key == slot.niche_key and row.position == slot.rank), None)
        clock = f"{slot.hour:02d}:{slot.minute:02d}"
        if match is None:
            logger.info("%s sem livro neste nicho.", clock)
            continue
        rendered = render_deal(_deal_from_row(match), config.affiliate_tag)
        logger.info("%s\n%s\ncapa: %s", clock, rendered.caption, rendered.image_url or "(sem capa)")


def _deal_from_row(row: QueuedPost) -> Deal:
    return Deal(
        asin=row.asin,
        title=row.title,
        author=row.author,
        price_cents=row.price_cents,
        avg90_cents=row.avg90_cents,
        historic_min_cents=row.historic_min_cents,
        rating=row.rating,
        review_count=row.review_count,
        image_url=row.image_url,
        price_source=row.price_source,
        synopsis=row.synopsis,
        lowest_for_days=row.lowest_for_days,
        niche_label=row.niche_label,
        blurb=row.blurb,
    )
