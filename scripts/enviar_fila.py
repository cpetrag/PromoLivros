"""Fica no ar e publica a fila nova. Não altera whatsapp.enabled."""
from __future__ import annotations

import logging
import sys
import time
from contextlib import ExitStack, closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promo_livros.amz_links import AmzLinkClient, AmzLinkError
from promo_livros.board_store import BoardStore
from promo_livros.campaign_store import CampaignStore
from promo_livros.config import load_config
from promo_livros.polls import PollStore
from promo_livros.refresh_links import has_pending_links, refresh_unsent_links
from promo_livros.schedule_plan import zone
from promo_livros.send_cycle import CycleResult, run_send_cycle
from promo_livros.waha import WahaClient

LINK_REFRESH_SECONDS = 60


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("promo_livros.board_send")
    logger.info("Envio da fila nova no ar.")
    previous = CycleResult(invite="", queue="", poll="")
    last_refresh = 0.0
    while True:
        try:
            config = load_config(ROOT / "config.yaml")
            result, last_refresh = _send_once(config, logger, last_refresh)
        except Exception:
            logger.exception("O ciclo de envio falhou.")
            time.sleep(15)
            continue
        if result.queue != previous.queue:
            logger.info("Situação: %s.", result.queue)
        if result.invite != previous.invite:
            logger.info("Convites: %s.", result.invite)
        if result.poll != previous.poll:
            logger.info("Enquetes: %s.", result.poll)
        previous = result
        time.sleep(30 if result.failed else 5)


def _send_once(config, logger: logging.Logger, last_refresh: float) -> tuple[CycleResult, float]:
    """Abre tudo numa ExitStack: se abrir um falhar, os já abertos fecham."""
    with ExitStack() as stack:
        store = stack.enter_context(closing(BoardStore(config.sqlite_path)))
        polls = stack.enter_context(closing(PollStore(config.sqlite_path)))
        campaigns = stack.enter_context(closing(CampaignStore(config.sqlite_path)))
        client = stack.enter_context(closing(WahaClient.from_config(config)))
        last_refresh = _refresh_links(config, store, logger, last_refresh)
        moment = datetime.now(zone(config.schedule.timezone))
        result = run_send_cycle(config, store, polls, campaigns, client, root=ROOT, now=moment)
    return result, last_refresh


def _refresh_links(config, store: BoardStore, logger: logging.Logger, last_refresh: float) -> float:
    if not config.amz_link_api_token or not config.affiliate_tag:
        return last_refresh
    if not has_pending_links(store):
        return last_refresh
    now = time.monotonic()
    if now - last_refresh < LINK_REFRESH_SECONDS:
        return last_refresh
    link_client = AmzLinkClient(config.amz_link_api_url, config.amz_link_api_token)
    try:
        changed = refresh_unsent_links(store, link_client, config.affiliate_tag)
    except AmzLinkError:
        logger.warning("Não consegui refazer os links de afiliado neste ciclo.")
        return now
    if changed:
        logger.info("Links de %s posts ainda não enviados foram refeitos.", changed)
    return now


if __name__ == "__main__":
    raise SystemExit(main())
