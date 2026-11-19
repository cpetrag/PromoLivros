"""Publica a fila nova no WhatsApp. Não liga whatsapp.enabled e não usa a fila antiga."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from random import Random
from typing import TYPE_CHECKING, Protocol

from promo_livros import campaign_images
from promo_livros.board_store import POST_KIND_CAMPAIGN, BoardPost, BoardStore
from promo_livros.models import AppConfig
from promo_livros.send_gap import gap_open, latest_stamp
from promo_livros.waha import WahaError

if TYPE_CHECKING:
    from promo_livros.campaign_store import CampaignStore

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
    quiet_since: str | None = None,
    campaigns: CampaignStore | None = None,
    rng: Random | None = None,
) -> str:
    """Manda o próximo post vencido para um grupo. O intervalo entre grupos segura o seguinte."""
    if not store.sending_enabled():
        return "off"
    groups = config.whatsapp_groups
    if not groups:
        return "no_groups"
    schedule = store.send_schedule()
    day = now.date().isoformat()
    post = store.next_due_post(day, _clock(now), store.send_end_for(day, schedule.end))
    if post is None:
        return "idle"
    is_campaign = post.post_kind == POST_KIND_CAMPAIGN
    if is_campaign and (post.campaign_id is None or not post.image_path):
        # Post de campanha sem conteúdo nunca vai ter o que enviar; sair da fila evita travar os seguintes.
        store.skip(post.day, post.id)
        logger.warning("Post de campanha das %s está sem campanha ou imagem. Foi pulado.", post.clock)
        return "skipped"
    if sender.connection_state() != "connected":
        return "disconnected"
    if is_campaign:
        replacement = _campaign_image_or_repick(store, campaigns, post, root, rng or Random())
        if replacement is None:
            # Foto e campanha podem ser apagadas no painel sem olhar a fila; travar aqui segura o dia todo.
            store.skip(post.day, post.id)
            logger.warning(
                "O post de campanha das %s ficou sem foto legível. Foi pulado para não travar a fila.", post.clock
            )
            return "skipped"
        post, image = replacement
    else:
        image = card_bytes(root, post.image_path)
    if image is None:
        logger.error("A imagem do post das %s não está em data/cards. Nada foi enviado.", post.clock)
        return "broken"
    done = store.sent_group_ids(post.id)
    pending = [group for group in groups if group.chat_id not in done]
    if not pending:
        store.mark_sent(post.id)
        return "sent"
    last_sent = latest_stamp((store.last_group_sent_at(), quiet_since), now)
    if not gap_open(last_sent, now, schedule.group_gap_seconds):
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


def _read_campaign_image(root: Path, path: str) -> bytes | None:
    try:
        return campaign_images.read_image(root, path)
    except OSError as exc:
        logger.warning("Não deu para ler a foto %s da campanha: %s", path, type(exc).__name__)
        return None


def _campaign_image_or_repick(
    store: BoardStore,
    campaigns: CampaignStore | None,
    post: BoardPost,
    root: Path,
    rng: Random,
) -> tuple[BoardPost, bytes] | None:
    """Foto do post de campanha. Sumiu: sorteia outra da mesma campanha e atualiza o post.

    None quando a campanha não tem mais foto legível; quem chama pula o post.
    """
    image = _read_campaign_image(root, post.image_path)
    if image is not None:
        return post, image
    if campaigns is None or post.campaign_id is None:
        return None
    candidates = [item for item in campaigns.images(post.campaign_id) if item.id != post.image_id]
    while candidates:
        chosen = candidates.pop(rng.randrange(len(candidates)))
        data = _read_campaign_image(root, chosen.path)
        if data is None:
            continue
        store.set_campaign_content(
            post.id, post.campaign_id, chosen.id, post.text_id, post.caption, chosen.path, post.campaign_locked_at
        )
        logger.warning("A foto do post de campanha das %s sumiu. Foi trocada por outra da campanha.", post.clock)
        return replace(post, image_id=chosen.id, image_path=chosen.path), data
    return None


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


def _clock(now: datetime) -> str:
    return f"{now.hour:02d}:{now.minute:02d}"
