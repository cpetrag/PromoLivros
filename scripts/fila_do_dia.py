"""Monta a fila do dia. O cron do Mac chama isto às 5h. Não envia WhatsApp."""
import argparse
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promo_livros.config import load_config
from promo_livros.morning import build_today

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monta a fila de um dia. Sem --day, usa hoje.")
    parser.add_argument("--day", default="", help="Dia no formato AAAA-MM-DD. Vazio significa hoje.")
    args = parser.parse_args(argv)
    if args.day and not _DAY.fullmatch(args.day):
        parser.error("--day precisa ser AAAA-MM-DD")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(ROOT / "config.yaml")
    return build_today(config, ROOT, day=args.day or None)


if __name__ == "__main__":
    raise SystemExit(main())
