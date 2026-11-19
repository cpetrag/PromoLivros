"""Manda os convites das campanhas, fora dos horários da fila."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from random import Random

from promo_livros.board_send import CardSender
from promo_livros.board_store import BoardStore
from promo_livros.campaign_images import read_image
from promo_livros.campaign_rules import (
    INVITE_LAST,
    InviteSettings,
    RotationEntry,
    fixed_invite_due,
    fixed_invite_missed,
    invite_settings,
    last_invite_clock,
    last_invite_due,
    pick_avoiding,
    rotation_order,
)
from promo_livros.campaign_store import CampaignImage, CampaignRun, CampaignStore
from promo_livros.models import AppConfig, WhatsAppGroup
from promo_livros.send_gap import gap_open, latest_stamp
from promo_livros.waha import WahaError

logger = logging.getLogger("promo_livros.campaign_send")

# Convite de uma campanha com horário fixo. O 'fixed' global antigo não é mais enviado.
CLOCK_KIND = "clock"


@dataclass(frozen=True)
class InviteContent:
    image: bytes
    caption: str


class _LockStatus(Enum):
    READY = "ready"
    PHOTO_UNREACHABLE = "photo_unreachable"
    NO_CAMPAIGN = "no_campaign"
    CLOSED = "closed"
    CHANGED = "changed"


@dataclass(frozen=True)
class _LockResult:
    status: _LockStatus
    run: CampaignRun | None = None
    content: InviteContent | None = None


def read_invite_settings(board: BoardStore) -> InviteSettings:
    return invite_settings(board.setting("invite_fixed_clock"), board.setting("invite_last_offset_minutes"))


def last_invite_clock_for(board: BoardStore, day: str, settings: InviteSettings) -> str:
    return _last_invite_clock(board, day, _send_end(board, day), settings)


def publish_due_invite(
    config: AppConfig,
    board: BoardStore,
    campaigns: CampaignStore,
    sender: CardSender,
    *,
    root: Path,
    now: datetime,
    quiet_since: str | None = None,
    rng: Random | None = None,
) -> str:
    """Manda o convite final (só campanhas rotativas) para o próximo grupo, com a mesma espera da fila."""
    if not board.sending_enabled():
        return "off"
    groups = config.whatsapp_groups
    if not groups:
        return "no_groups"
    run = _due_run(board, campaigns, now)
    if run is None:
        return "idle"
    return _send_to_next_group(
        board, campaigns, sender, run, groups, root=root, now=now, quiet_since=quiet_since, rng=rng
    )


def publish_due_fixed_campaigns(
    config: AppConfig,
    board: BoardStore,
    campaigns: CampaignStore,
    sender: CardSender,
    *,
    root: Path,
    now: datetime,
    quiet_since: str | None = None,
    rng: Random | None = None,
) -> str:
    """Manda as campanhas de horário fixo na hora delas, sem depender da fila de livros."""
    if not board.sending_enabled():
        return "off"
    groups = config.whatsapp_groups
    if not groups:
        return "no_groups"
    run = _due_fixed_run(campaigns, now)
    if run is None:
        return "idle"
    return _send_to_next_group(
        board, campaigns, sender, run, groups, root=root, now=now, quiet_since=quiet_since, rng=rng
    )


def _send_to_next_group(
    board: BoardStore,
    campaigns: CampaignStore,
    sender: CardSender,
    run: CampaignRun,
    groups: Sequence[WhatsAppGroup],
    *,
    root: Path,
    now: datetime,
    quiet_since: str | None,
    rng: Random | None,
) -> str:
    if sender.connection_state() != "connected":
        return "disconnected"
    stamp = now.isoformat(timespec="seconds")
    lock = _locked_content(campaigns, root, run, rng or Random(), stamp)
    if lock.status is _LockStatus.PHOTO_UNREACHABLE:
        return "waiting"
    if lock.status is _LockStatus.CHANGED:
        logger.info("Convite %s de %s mudou durante o sorteio. Decido de novo na próxima volta.", run.kind, run.day)
        return "waiting"
    if lock.status is _LockStatus.CLOSED:
        logger.info("Convite %s de %s já tinha sido encerrado por outro envio.", run.kind, run.day)
        return "idle"
    if lock.status is _LockStatus.NO_CAMPAIGN or lock.run is None or lock.content is None:
        return _close_without_content(campaigns, run, stamp)
    run, content = lock.run, lock.content
    done = campaigns.sent_chat_ids(run.id)
    pending = [group for group in groups if group.chat_id not in done]
    if not pending:
        campaigns.mark_run_sent(run.id, stamp)
        return "sent"
    last_sent = latest_stamp((board.last_group_sent_at(), campaigns.last_sent_at(), quiet_since), now)
    if not gap_open(last_sent, now, board.send_schedule().group_gap_seconds):
        return "waiting"
    group = pending[0]
    if not campaigns.claim_group_send(run.id, group.chat_id, stamp):
        return "waiting"
    try:
        message_id = sender.send_jpeg(group.chat_id, content.caption, content.image)
    except WahaError as exc:
        campaigns.release_group_send(run.id, group.chat_id)
        if exc.session_down:
            logger.warning("Convite para %s adiado: %s", group.name, exc)
            return "waiting"
        logger.warning("Convite para %s falhou: %s", group.name, exc)
        return "failed"
    except Exception as exc:
        campaigns.release_group_send(run.id, group.chat_id)
        logger.error("Erro inesperado (%s) no convite para %s. O grupo volta para a fila.", type(exc).__name__, group.name)
        raise
    campaigns.finish_group_send(run.id, group.chat_id, message_id, stamp)
    logger.info("Convite %s enviado para %s.", run.kind, group.name)
    if {item.chat_id for item in groups} <= campaigns.sent_chat_ids(run.id):
        campaigns.mark_run_sent(run.id, stamp)
        logger.info("Convite %s saiu para os %s grupos.", run.kind, len(groups))
    return "sent"


def _close_without_content(campaigns: CampaignStore, run: CampaignRun, stamp: str) -> str:
    """Sem campanha pronta: pula o convite, ou fecha como enviado se algum grupo já recebeu."""
    reached = campaigns.sent_chat_ids(run.id)
    if reached:
        campaigns.mark_run_sent(run.id, stamp)
        logger.warning(
            "Convite %s de %s encerrado em %s grupo(s): o conteúdo sumiu e não há outra campanha pronta.",
            run.kind,
            run.day,
            len(reached),
        )
        return "sent"
    campaigns.skip_run(run.id)
    logger.warning("Convite %s de %s pulado: nenhuma campanha pronta.", run.kind, run.day)
    return "skipped"


def _open_run(campaigns: CampaignStore, now: datetime) -> CampaignRun | None:
    """Convite começado hoje ou ontem vem antes, fora da janela, para terminar os grupos que faltam."""
    oldest_resumable = (now.date() - timedelta(days=1)).isoformat()
    while (started := campaigns.open_sending_run()) is not None:
        if started.day >= oldest_resumable:
            return started
        # Convite parado há dias não pode segurar os de hoje para sempre.
        campaigns.mark_run_sent(started.id, now.isoformat(timespec="seconds"))
        logger.warning("Convite %s de %s ficou parado no meio e foi encerrado.", started.kind, started.day)
    return None


def _due_run(board: BoardStore, campaigns: CampaignStore, now: datetime) -> CampaignRun | None:
    """Convite final vencido. Campanha fixa em andamento é terminada pelo passo das fixas."""
    started = _open_run(campaigns, now)
    if started is not None:
        return None if started.kind == CLOCK_KIND else started
    day = now.date().isoformat()
    now_clock = f"{now.hour:02d}:{now.minute:02d}"
    run = campaigns.run_for(day, INVITE_LAST)
    if run.status == "pending" and _last_is_due(board, day, now_clock, read_invite_settings(board)):
        return run
    return None


def _due_fixed_run(campaigns: CampaignStore, now: datetime) -> CampaignRun | None:
    """Fixa em andamento, ou a primeira cuja hora chegou. Passou da tolerância sem sair, é pulada."""
    started = _open_run(campaigns, now)
    if started is not None:
        return started if started.kind == CLOCK_KIND else None
    day = now.date().isoformat()
    now_clock = f"{now.hour:02d}:{now.minute:02d}"
    for campaign in campaigns.ready_fixed(day):
        clock = campaign.fixed_clock
        if clock is None:
            continue
        if fixed_invite_due(clock, now_clock):
            run = campaigns.run_for_clock(day, campaign.id, clock)
            if run.status == "pending":
                return run
        elif fixed_invite_missed(clock, now_clock):
            run = campaigns.run_for_clock(day, campaign.id, clock)
            if run.status == "pending":
                campaigns.skip_run(run.id)
                logger.warning("Campanha %s das %s pulada: passou da tolerância sem sair.", campaign.name, clock)
    return None


def _last_is_due(board: BoardStore, day: str, now_clock: str, settings: InviteSettings) -> bool:
    end = _send_end(board, day)
    return last_invite_due(
        now_clock,
        _last_invite_clock(board, day, end, settings),
        queue_pending=board.has_pending_posts(day, end),
    )


def _send_end(board: BoardStore, day: str) -> str:
    return board.send_end_for(day, board.send_schedule().end)


def _last_invite_clock(board: BoardStore, day: str, end: str, settings: InviteSettings) -> str:
    return last_invite_clock(board.last_queue_clock(day, end), end, settings.last_offset_minutes)


def _locked_content(
    campaigns: CampaignStore,
    root: Path,
    run: CampaignRun,
    rng: Random,
    stamp: str,
) -> _LockResult:
    """Conteúdo já travado segue igual para os grupos que faltam. Senão, sorteia e trava."""
    if run.status == "sending":
        kept = _stored_content(campaigns, root, run)
        if kept is not None:
            return kept
    for campaign_id in _candidates(campaigns, run):
        picked = _pick_content(campaigns, root, campaign_id, rng)
        if picked is None:
            continue
        image_id, text_id, content = picked
        locked_run = campaigns.lock_content(run.id, campaign_id, image_id, text_id, stamp, expected=run)
        if locked_run is not None:
            return _LockResult(_LockStatus.READY, locked_run, content)
        current = campaigns.run(run.id)
        if current is not None and current.status in {"pending", "sending"}:
            return _LockResult(_LockStatus.CHANGED)
        return _LockResult(_LockStatus.CLOSED)
    return _LockResult(_LockStatus.NO_CAMPAIGN)


def _stored_content(campaigns: CampaignStore, root: Path, run: CampaignRun) -> _LockResult | None:
    """None quando a foto ou o texto travado sumiu de vez e é preciso sortear de novo."""
    image = campaigns.image(run.image_id) if run.image_id else None
    text = campaigns.text(run.text_id) if run.text_id else None
    data: bytes | None = None
    if image is not None and text is not None:
        try:
            data = read_image(root, image.path)
        except OSError as exc:
            # Pasta de rede oscilando: trocar a foto no meio deixaria grupos com convites diferentes.
            logger.warning(
                "A foto do convite %s não abriu agora (%s). Tento de novo depois.", run.kind, type(exc).__name__
            )
            return _LockResult(_LockStatus.PHOTO_UNREACHABLE)
    if data is None or text is None:
        logger.warning("A foto ou o texto do convite %s sumiu no meio do envio. Vou sortear de novo.", run.kind)
        return None
    return _LockResult(_LockStatus.READY, run, InviteContent(data, text.body))


def _candidates(campaigns: CampaignStore, run: CampaignRun) -> list[int]:
    if run.kind == CLOCK_KIND:
        # Campanha fixa só manda o próprio conteúdo, nunca entra no rodízio.
        ready_ids = {item.id for item in campaigns.ready_fixed(run.day)}
        return [run.campaign_id] if run.campaign_id in ready_ids else []
    ready = campaigns.ready_rotating(run.day)
    order = rotation_order(
        [RotationEntry(item.id, item.position) for item in ready],
        campaigns.last_used_rotating(),
    )
    preferred = run.campaign_id if run.status == "sending" or run.manual else None
    if preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)
    return order


def _pick_content(
    campaigns: CampaignStore,
    root: Path,
    campaign_id: int,
    rng: Random,
) -> tuple[int, int, InviteContent] | None:
    texts = campaigns.texts(campaign_id)
    images = {image.id: image for image in campaigns.images(campaign_id)}
    if not texts or not images:
        return None
    last_image_id, last_text_id = campaigns.last_content(campaign_id)
    while images:
        image_id = pick_avoiding(list(images), last_image_id, rng)
        data = _read_photo(root, images[image_id])
        if data is not None:
            text_id = pick_avoiding([text.id for text in texts], last_text_id, rng)
            body = next(text.body for text in texts if text.id == text_id)
            return image_id, text_id, InviteContent(data, body)
        logger.warning("A foto %s da campanha %s não está no disco.", images[image_id].path, campaign_id)
        del images[image_id]
    return None


def _read_photo(root: Path, image: CampaignImage) -> bytes | None:
    """No sorteio, foto que não abre vira ausente: o convite tenta outra em vez de derrubar o loop."""
    try:
        return read_image(root, image.path)
    except OSError as exc:
        logger.warning("Não deu para ler a foto %s da campanha: %s", image.path, type(exc).__name__)
        return None
