from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from promo_livros.blurb import OpenAIBlurb
from promo_livros.config import load_config
from promo_livros.curation import deliver_pending, due_slots, prepare_day, publish_slot, should_prepare_today
from promo_livros.keepa_client import KeepaClient
from promo_livros.models import AppConfig, ConfigError
from promo_livros.schedule_plan import service_day, zone
from promo_livros.storage import Storage
from promo_livros.waha import WahaClient, WahaError

logger = logging.getLogger("promo_livros")

_PUBLISH_GRACE_MINUTES = 10


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        _run(argv)
    except ConfigError as exc:
        print(f"Configuração: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _run(argv: list[str] | None) -> None:
    args = _parse_args(argv)
    config = load_config(Path(args.config))
    _configure_logging(config.log_path)

    if config.website_enabled:
        raise ConfigError(
            "O site ainda não está ligado. Deixe website.enabled em false."
        )
    if args.groups:
        _print_groups(config)
        return
    if config.whatsapp_enabled and not args.dry_run:
        logger.info(
            "WhatsApp ligado na sessão %s (%s), %s grupos, %s s entre um grupo e outro.",
            config.waha_session,
            config.waha_url,
            len(config.whatsapp_groups),
            config.whatsapp_gap_seconds,
        )
    elif not args.dry_run:
        logger.warning(
            "O WhatsApp ainda está desligado. No horário da noite a mensagem vai para o log "
            "e o livro fica marcado como usado por 30 dias."
        )
    if not config.affiliate_tag:
        logger.warning("AMAZON_AFFILIATE_TAG está vazio. Os links saem sem a tag de afiliado.")
    if not config.openai_api_key:
        logger.warning("OPENAI_API_KEY está vazia. As mensagens saem sem a frase sobre o livro.")

    if args.once:
        _execute(config, args.dry_run, lambda client, storage, blurb: prepare_day(
            config,
            client,
            storage,
            blurb,
            datetime.now(zone(config.schedule.timezone)),
            dry_run=args.dry_run,
            refresh_category=args.refresh_category,
            replace=True,
        ))
        return

    if args.publish:
        _execute(config, args.dry_run, lambda client, storage, blurb: _publish_next_due(
            config, client, storage, dry_run=args.dry_run
        ))
        return

    scheduler = BlockingScheduler(timezone=zone(config.schedule.timezone))
    scheduler.add_job(
        lambda: _safe_job(config, args, prepare=True),
        CronTrigger(
            hour=config.schedule.search_hour,
            minute=config.schedule.search_minute,
            timezone=zone(config.schedule.timezone),
        ),
        id="morning-search",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=2 * 60 * 60,
    )
    for slot in config.slots:
        scheduler.add_job(
            lambda niche_key=slot.niche_key, rank=slot.rank: _safe_job(
                config, args, prepare=False, niche_key=niche_key, rank=rank
            ),
            CronTrigger(
                hour=slot.hour,
                minute=slot.minute,
                timezone=zone(config.schedule.timezone),
            ),
            id=f"publish-{slot.niche_key}-{slot.rank}-{slot.hour:02d}{slot.minute:02d}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=_PUBLISH_GRACE_MINUTES * 60,
        )
    if config.whatsapp_enabled and not args.dry_run:
        scheduler.add_job(
            lambda: _safe_drain(config),
            CronTrigger(minute="*", timezone=zone(config.schedule.timezone)),
            id="dispatch-drain",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=30,
        )

    clocks = ", ".join(f"{slot.hour:02d}:{slot.minute:02d}" for slot in config.slots)
    logger.info(
        "Busca às %02d:%02d. Publicações: %s. Fuso %s. Ctrl+C encerra.",
        config.schedule.search_hour,
        config.schedule.search_minute,
        clocks,
        config.schedule.timezone,
    )
    _catch_up(config, args)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot encerrado.")


def _catch_up(config: AppConfig, args: argparse.Namespace) -> None:
    now = datetime.now(zone(config.schedule.timezone))

    def opener(client, storage, blurb) -> None:
        day = service_day(now, config.schedule.timezone)
        if should_prepare_today(config, now, storage.has_queue(day)):
            logger.info("Ainda não há fila hoje e já passou das %02d:%02d. Montando agora.", config.schedule.search_hour, config.schedule.search_minute)
            prepare_day(config, client, storage, blurb, now, dry_run=args.dry_run, refresh_category=False)
        for slot in due_slots(config, now, grace_minutes=_PUBLISH_GRACE_MINUTES):
            publish_slot(config, client, storage, slot.niche_key, slot.rank, now, dry_run=args.dry_run)

    try:
        _execute(config, args.dry_run, opener)
    except Exception:
        logger.exception("A recuperação da fila de hoje falhou. O agendador segue.")


def _safe_job(
    config: AppConfig,
    args: argparse.Namespace,
    *,
    prepare: bool,
    niche_key: str = "",
    rank: int = 0,
) -> None:
    now = datetime.now(zone(config.schedule.timezone))

    def opener(client, storage, blurb) -> None:
        if prepare:
            prepare_day(config, client, storage, blurb, now, dry_run=args.dry_run, refresh_category=False)
        else:
            publish_slot(config, client, storage, niche_key, rank, now, dry_run=args.dry_run)

    try:
        _execute(config, args.dry_run, opener)
    except Exception:
        logger.exception("A tarefa falhou. A próxima segue no horário, sem derrubar o processo.")


def _safe_drain(config: AppConfig) -> None:
    now = datetime.now(zone(config.schedule.timezone))
    storage = Storage(config.sqlite_path)
    try:
        deliver_pending(config, storage, now)
    except Exception:
        logger.exception("A fila de disparo falhou. O próximo minuto tenta de novo.")
    finally:
        storage.close()


def _print_groups(config: AppConfig) -> None:
    client = WahaClient.from_config(config)
    try:
        groups = client.list_groups()
    except WahaError as exc:
        print(f"WhatsApp: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        client.close()
    if not groups:
        print(
            f"Nenhum grupo. A sessão {config.waha_session} precisa estar WORKING em {config.waha_url}.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    for group in groups:
        print(f"{group.name}\t{group.chat_id}")


def _publish_next_due(config: AppConfig, client: KeepaClient, storage: Storage, *, dry_run: bool) -> str:
    now = datetime.now(zone(config.schedule.timezone))
    for slot in due_slots(config, now, grace_minutes=None):
        outcome = publish_slot(config, client, storage, slot.niche_key, slot.rank, now, dry_run=dry_run)
        if outcome in {"posted", "queued", "dry_run"}:
            return outcome
    logger.info("Nenhum horário da noite já passou com livro pronto.")
    return "empty"


def _execute(config: AppConfig, dry_run: bool, action) -> None:
    del dry_run
    storage = Storage(config.sqlite_path)
    client = KeepaClient(config)
    blurb = OpenAIBlurb(config.openai_api_key, config.openai_model, config.openai_max_chars)
    try:
        action(client, storage, blurb)
    finally:
        client.close()
        storage.close()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Curadoria de promoções de livros da Amazon Brasil via Keepa.")
    parser.add_argument("--once", action="store_true", help="Monta a fila do dia e encerra.")
    parser.add_argument(
        "--groups",
        action="store_true",
        help="Lista os grupos da sessão WAHA e encerra.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publica o próximo horário de hoje que já passou e ainda tem livro pronto.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra a curadoria no log, sem gravar a fila nem marcar o livro como usado.",
    )
    parser.add_argument("--config", default="config.yaml", help="Caminho do config.yaml.")
    parser.add_argument(
        "--refresh-category",
        action="store_true",
        help="Ignora o ID de categoria em cache e consulta de novo a API do Keepa.",
    )
    return parser.parse_args(argv)


def _configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
