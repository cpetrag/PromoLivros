"""Publica a fila nova no WhatsApp. Não liga whatsapp.enabled e não usa a fila antiga."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from promo_livros.board_store import BoardStore
from promo_livros.models import AppConfig
from promo_livros.waha import WahaError

logger = logging.getLogger("promo_livros.board_send")


class CardSender(Protocol):
    def connection_state(self) -> str:
        """connected quando a sessão pode mandar mensagem."""

    def send_jpeg(self, chat_id: str, caption: str, image: bytes) -> str:
        """Envia o card e devolve o id da mensagem."""


def publish_due(
    config: AppConfig,
    store: BoardStore,
    sender: CardSender,
    *,
    root: Path,
    now: datetime,
) -> str:
    """Manda o próximo post vencido para um grupo. O intervalo entre grupos segura o seguinte."""
    if not store.sending_enabled():
        return "off"
    groups = config.whatsapp_groups
    if not groups:
        return "no_groups"
    schedule = store.send_schedule()
    post = store.next_due_post(now.date().isoformat(), _clock(now), schedule.end)
    if post is None:
        return "idle"
    if sender.connection_state() != "connected":
        return "disconnected"
    image = card_bytes(root, post.image_path)
    if image is None:
        logger.error("O card do post das %s não está em data/cards. Nada foi enviado.", post.clock)
        return "broken"
    done = store.sent_group_ids(post.id)
    pending = [group for group in groups if group.chat_id not in done]
    if not pending:
        store.mark_sent(post.id)
        return "sent"
    if not _gap_open(store.last_group_sent_at(), now, schedule.group_gap_seconds):
        return "waiting"
    group = pending[0]
    stamp = now.isoformat(timespec="seconds")
    if store.claim_group_send(post.id, group.chat_id, group.name, stamp) != "send":
        return "waiting"
    caption = _caption_for_send(store, post, already_sent=bool(done))
    try:
        message_id = sender.send_jpeg(group.chat_id, caption, image)
    except WahaError as exc:
        store.release_group_send(post.id, group.chat_id)
        if exc.session_down:
            logger.warning("Envio para %s adiado: %s", group.name, exc)
            return "waiting"
        logger.warning("Envio para %s falhou: %s", group.name, exc)
        return "failed"
    store.finish_group_send(post.id, group.chat_id, message_id, stamp)
    logger.info("Post das %s enviado para %s.", post.clock, group.name)
    if {item.chat_id for item in groups} <= store.sent_group_ids(post.id):
        store.mark_sent(post.id)
        logger.info("Post das %s saiu para os %s grupos.", post.clock, len(groups))
    return "sent"


def _caption_for_send(store: BoardStore, post, *, already_sent: bool) -> str:
    """No primeiro grupo do post, troca a assinatura pela próxima da lista."""
    if already_sent:
        return post.caption
    signature = store.take_signature()
    if not signature:
        return post.caption
    from promo_livros.signatures import apply_signature

    caption = apply_signature(post.caption, signature)
    store.rewrite_caption(post.id, caption)
    return caption


def card_bytes(root: Path, image_path: str) -> bytes | None:
    path = Path(image_path)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    cards = (root / "data" / "cards").resolve()
    if resolved.parent != cards or not resolved.is_file():
        return None
    return resolved.read_bytes()


def _gap_open(last_sent: str | None, now: datetime, gap_seconds: int) -> bool:
    if not last_sent:
        return True
    previous = datetime.fromisoformat(last_sent)
    if previous.tzinfo is None and now.tzinfo is not None:
        previous = previous.replace(tzinfo=now.tzinfo)
    return now - previous >= timedelta(seconds=gap_seconds)


def _clock(now: datetime) -> str:
    return f"{now.hour:02d}:{now.minute:02d}"
