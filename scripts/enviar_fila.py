"""Fica no ar e publica a fila nova. Não altera whatsapp.enabled."""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promo_livros.amz_links import AmzLinkClient, AmzLinkError
from promo_livros.board_send import publish_due
from promo_livros.board_store import BoardStore
from promo_livros.config import load_config
from promo_livros.refresh_links import has_pending_links, refresh_unsent_links
from promo_livros.schedule_plan import zone
from promo_livros.waha import WahaClient

LINK_REFRESH_SECONDS = 60


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("promo_livros.board_send")
    logger.info("Envio da fila nova no ar.")
    previous = ""
    last_refresh = 0.0
    while True:
        try:
            config = load_config(ROOT / "config.yaml")
            store = BoardStore(config.sqlite_path)
            client = WahaClient.from_config(config)
            try:
                last_refresh = _refresh_links(config, store, logger, last_refresh)
                result = publish_due(
                    config,
                    store,
                    client,
                    root=ROOT,
                    now=datetime.now(zone(config.schedule.timezone)),
                )
            finally:
                client.close()
                store.close()
        except Exception:
            logger.exception("O ciclo de envio falhou.")
            time.sleep(15)
            continue
        if result != previous:
            logger.info("Situação: %s.", result)
            previous = result
        time.sleep(30 if result == "failed" else 5)


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
