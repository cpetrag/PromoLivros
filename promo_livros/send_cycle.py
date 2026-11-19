"""Uma volta do loop de envio: convite, fila e enquetes, com a mesma espera entre todos."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from promo_livros.board_send import publish_due
from promo_livros.board_store import BoardStore
from promo_livros.campaign_send import publish_due_invite
from promo_livros.campaign_store import CampaignStore
from promo_livros.models import AppConfig
from promo_livros.polls import PollStore, advance_polls
from promo_livros.send_gap import latest_stamp
from promo_livros.waha import WahaClient

logger = logging.getLogger("promo_livros.send_cycle")

FAILED = "failed"


@dataclass(frozen=True)
class CycleResult:
    invite: str
    queue: str
    poll: str

    @property
    def failed(self) -> bool:
        return FAILED in {self.invite, self.queue, self.poll}


def run_send_cycle(
    config: AppConfig,
    board: BoardStore,
    polls: PollStore,
    campaigns: CampaignStore,
    client: WahaClient,
    *,
    root: Path,
    now: datetime,
) -> CycleResult:
    """Cada passo relê os carimbos depois do anterior, porque o anterior pode ter acabado de mandar."""
    invite = _guarded(
        "O ciclo do convite falhou.",
        lambda: publish_due_invite(
            config,
            board,
            campaigns,
            client,
            root=root,
            now=now,
            quiet_since=polls.last_outbound_at(),
        ),
    )
    queue = _guarded(
        "O ciclo da fila falhou.",
        lambda: publish_due(
            config,
            board,
            client,
            root=root,
            now=now,
            quiet_since=latest_stamp((polls.last_outbound_at(), campaigns.last_sent_at()), now),
        ),
    )
    poll = _guarded(
        "O ciclo da enquete falhou.",
        lambda: advance_polls(
            polls,
            client,
            now,
            gap_seconds=board.send_schedule().group_gap_seconds,
            other_sent_at=latest_stamp((board.last_group_sent_at(), campaigns.last_sent_at()), now),
        ),
    )
    return CycleResult(invite=invite, queue=queue, poll=poll)


def _guarded(message: str, step: Callable[[], str]) -> str:
    """Um passo quebrado não pode segurar os outros: o loop segue e tenta de novo na próxima volta."""
    try:
        return step()
    except Exception:
        logger.exception(message)
        return FAILED
