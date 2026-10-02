"""Refaz agora os links Amazon dos posts que ainda não foram para os grupos."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promo_livros.amz_links import AmzLinkClient, AmzLinkError
from promo_livros.board_store import BoardStore
from promo_livros.config import load_config
from promo_livros.models import ConfigError
from promo_livros.refresh_links import refresh_unsent_links


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config(ROOT / "config.yaml")
    except ConfigError as exc:
        print(f"Configuração: {exc}", file=sys.stderr)
        return 1
    if not config.amz_link_api_token:
        print("AMZ_TOKEN vazio no .env.", file=sys.stderr)
        return 1
    if not config.affiliate_tag:
        print("AMAZON_AFFILIATE_TAG vazia no .env.", file=sys.stderr)
        return 1
    store = BoardStore(config.sqlite_path)
    client = AmzLinkClient(config.amz_link_api_url, config.amz_link_api_token)
    try:
        changed = refresh_unsent_links(store, client, config.affiliate_tag)
    except AmzLinkError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        store.close()
    print(f"{changed} posts atualizados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
