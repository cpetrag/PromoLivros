from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from promo_livros.models import AppConfig
from promo_livros.schedule_plan import local_now
from promo_livros.storage import Storage
from promo_livros.waha import WahaError, WhatsAppSender

logger = logging.getLogger("promo_livros")

_STALE_SENDING = timedelta(minutes=2)


def enqueue_dispatches(
    config: AppConfig,
    storage: Storage,
    *,
    day: str,
    niche_key: str,
    position: int,
    asin: str,
    title: str,
    price_cents: int,
    caption: str,
    image_url: str | None,
    now: datetime,
) -> int:
    """Uma linha por grupo. Repetir o horário não duplica o disparo."""
    created = 0
    for group in config.whatsapp_groups:
        if storage.enqueue_dispatch(
            day=day,
            niche_key=niche_key,
            position=position,
            asin=asin,
            title=title,
            price_cents=price_cents,
            chat_id=group.chat_id,
            group_name=group.name,
            caption=caption,
            image_url=image_url,
            now=now,
        ):
            created += 1
    return created


def drain_dispatches(
    config: AppConfig,
    storage: Storage,
    sender: WhatsAppSender,
    now: datetime,
) -> str:
    """Envia o próximo da fila, se a janela e o intervalo entre grupos permitirem.

    Fora da janela o que sobrou expira e o livro não entra nos 30 dias.
    WhatsApp desconectado deixa a linha na fila para o minuto seguinte.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    storage.release_stale_sends(now - _STALE_SENDING)

    if not _in_window(config, now):
        if _after_window(config, now):
            expired = storage.expire_dispatches(service_day_of(config, now))
            if expired:
                logger.info("Janela encerrada. %s disparos não enviados foram expirados.", expired)
            return "expired"
        return "idle"

    pending = storage.next_dispatch()
    if pending is None:
        return "idle"

    last_sent = storage.last_dispatch_sent_at()
    if last_sent is not None and now - last_sent < timedelta(seconds=config.whatsapp_gap_seconds):
        return "waiting"

    state = sender.connection_state()
    if state != "connected":
        logger.info("WhatsApp %s. O disparo de %s fica na fila.", _state_label(state), pending.group_name)
        return "waiting"

    if not storage.claim_dispatch(pending.id):
        return "idle"
    try:
        message_id = sender.send(pending.chat_id, pending.caption, pending.image_url)
    except WahaError as exc:
        if exc.session_down:
            storage.release_dispatch(pending.id)
            logger.warning("Envio para %s adiado: %s", pending.group_name, exc)
            return "waiting"
        storage.fail_dispatch(pending.id, str(exc))
        logger.warning("Envio para %s falhou: %s", pending.group_name, exc)
        return "failed"

    storage.mark_dispatch_sent(pending.id, message_id, now)
    if not storage.queue_position_posted(pending.day, pending.niche_key, pending.position):
        storage.record_post(pending.asin, pending.title, pending.price_cents, now)
        storage.mark_queue(pending.day, pending.niche_key, pending.position, "posted")
    logger.info("Enviado para %s: %s (%s).", pending.group_name, pending.asin, message_id)
    return "sent"


def slot_was_sent(storage: Storage, day: str, niche_key: str, position: int) -> bool:
    return storage.dispatch_was_sent(day, niche_key, position)


def _in_window(config: AppConfig, now: datetime) -> bool:
    current = _minute_of_day(config, now)
    start = config.schedule.publish_start_hour * 60 + config.schedule.publish_start_minute
    end = config.schedule.publish_end_hour * 60 + config.schedule.publish_end_minute
    return start <= current < end


def _after_window(config: AppConfig, now: datetime) -> bool:
    current = _minute_of_day(config, now)
    end = config.schedule.publish_end_hour * 60 + config.schedule.publish_end_minute
    return current >= end


def _minute_of_day(config: AppConfig, now: datetime) -> int:
    local = local_now(now, config.schedule.timezone)
    return local.hour * 60 + local.minute


def service_day_of(config: AppConfig, now: datetime) -> str:
    return local_now(now, config.schedule.timezone).date().isoformat()


def _state_label(state: str) -> str:
    if state == "qr":
        return "aguardando QR"
    return "desconectado"
