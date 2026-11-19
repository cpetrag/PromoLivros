"""Telas e webhook de enquete, no mesmo processo do painel."""
from __future__ import annotations

import hmac
import logging
import time
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from promo_livros.dashboard_pages import render_poll_detail, render_poll_list
from promo_livros.form_fields import first_field
from promo_livros.models import AppConfig
from promo_livros.polls import PollError, PollStore, handle_webhook, person_is_admin
from promo_livros.schedule_plan import zone
from promo_livros.waha import WahaClient, WahaError

logger = logging.getLogger("promo_livros.polls")
_LINK_TTL_SECONDS = 60


def poll_callbacks(config: AppConfig, store: PollStore) -> dict:
    names = {group.chat_id: group.name for group in config.whatsapp_groups}
    allowed = set(names)
    clock = zone(config.schedule.timezone)
    holder: dict[str, str | None] = {"notice": None}
    cache: dict[str, object] = {"at": 0.0, "links": {}}

    def now() -> datetime:
        return datetime.now(clock)

    def links() -> dict[str, str]:
        cached = cache["links"]
        if isinstance(cached, dict) and time.monotonic() - float(cache["at"]) < _LINK_TTL_SECONDS:
            return cached
        client = WahaClient.from_config(config)
        try:
            found = client.lid_links()
        except WahaError:
            logger.warning("Não consegui ler o mapa de @lid.")
            return cached if isinstance(cached, dict) else {}
        finally:
            client.close()
        cache["links"] = found
        cache["at"] = time.monotonic()
        return found

    def is_admin(chat_id: str, participant: str) -> bool:
        client = WahaClient.from_config(config)
        try:
            people = client.group_participants(chat_id)
        except WahaError:
            logger.warning("Não consegui conferir os admins de %s.", chat_id)
            return False
        finally:
            client.close()
        return person_is_admin(people, participant, links())

    def members(chat_id: str) -> int | None:
        client = WahaClient.from_config(config)
        try:
            people = client.group_participants(chat_id)
        except WahaError:
            return None
        finally:
            client.close()
        return sum(1 for _member_id, role in people if role != "left")

    def page(query: dict[str, list[str]]) -> str:
        chat_id = first_field(query, "grupo")
        status = first_field(query, "status")
        if chat_id not in allowed:
            chat_id = ""
        if status not in {"agendada", "ativa", "encerrada"}:
            status = ""
        notice = holder["notice"]
        holder["notice"] = None
        return render_poll_list(
            store.list_polls(chat_id=chat_id or None, status=status or None),
            [(name, chat_id) for chat_id, name in names.items()],
            notice=notice,
            chat_id=chat_id,
            status=status,
        )

    def detail(poll_id: int) -> str | None:
        try:
            poll = store.combined(poll_id)
            chats = store.batch_chat_ids(poll_id)
        except PollError:
            return None
        notice = holder["notice"]
        holder["notice"] = None
        return render_poll_detail(
            poll,
            members=_member_total(chats, members),
            notice=notice,
            zone_name=config.schedule.timezone,
        )

    def csv_text(poll_id: int) -> str | None:
        try:
            store.detail(poll_id)
        except PollError:
            return None
        return store.votes_csv(poll_id)

    def save(form: dict[str, list[str]]) -> str:
        chat_id = first_field(form, "chat_id")
        send_at = _local_moment(first_field(form, "enviar"), clock) or now()
        closes_at = _local_moment(first_field(form, "encerrar"), clock)
        if closes_at is not None and closes_at <= send_at:
            holder["notice"] = "O encerramento precisa ser depois do envio."
            return "/enquetes"
        pin = first_field(form, "fixar") or None
        question = first_field(form, "pergunta")
        options = [line.strip() for line in first_field(form, "opcoes").splitlines()]
        multiple = first_field(form, "multipla") == "1"
        try:
            if chat_id == "todos":
                poll_id = store.create_for_groups(
                    [(item, names[item]) for item in names],
                    question=question,
                    options=options,
                    multiple=multiple,
                    pin=pin,
                    send_at=send_at,
                    closes_at=closes_at,
                )
            elif chat_id in names:
                poll_id = store.create(
                    chat_id=chat_id,
                    group_name=names[chat_id],
                    question=question,
                    options=options,
                    multiple=multiple,
                    pin=pin,
                    send_at=send_at,
                    closes_at=closes_at,
                )
            else:
                holder["notice"] = "Escolha um grupo da lista."
                return "/enquetes"
        except PollError as exc:
            holder["notice"] = str(exc)
            return "/enquetes"
        if chat_id == "todos":
            holder["notice"] = (
                "Enquete agendada em todos os grupos. O envio espera entre um grupo e outro, "
                "e o resultado soma os votos."
            )
        else:
            holder["notice"] = "Enquete agendada. O envio sai no próximo ciclo, respeitando a espera entre mensagens."
        return f"/enquetes/{poll_id}"

    def action(poll_id: int, kind: str) -> str:
        moment = now()
        try:
            ids = store.batch_ids(poll_id)
        except PollError:
            holder["notice"] = "Enquete não encontrada."
            return "/enquetes"
        if kind == "duplicar":
            copy_id = store.duplicate(poll_id, moment)
            holder["notice"] = "Cópia agendada para agora."
            return f"/enquetes/{copy_id}"
        if kind == "encerrar":
            holder["notice"] = _close_batch(store, ids, moment)
        elif kind == "parcial":
            holder["notice"] = _queue_each(store, ids, moment, "partial", "A parcial só sai com a enquete ativa.", "publicar a parcial")
        elif kind == "fixar":
            holder["notice"] = _pin_each(store, ids, moment)
        elif kind == "desafixar":
            holder["notice"] = _unpin_each(store, ids, moment)
        return f"/enquetes/{poll_id}"

    def webhook(body: dict, api_key: str) -> int:
        if not _same_secret(api_key, config.waha_api_key):
            return 401
        handle_webhook(
            store,
            body,
            session=config.waha_session,
            links=links(),
            is_admin=is_admin,
            allowed_groups=allowed,
            group_names=names,
            now=now(),
        )
        return 200

    return {
        "page": page,
        "detail": detail,
        "csv": csv_text,
        "save": save,
        "action": action,
        "webhook": webhook,
    }


def _member_total(chats: list[str], members: Callable[[str], int | None]) -> int | None:
    total = 0
    for chat_id in chats:
        count = members(chat_id)
        if count is None:
            return None
        total += count
    return total


def _close_batch(store: PollStore, ids: list[int], moment: datetime) -> str:
    closed = False
    abandoned = False
    for item in ids:
        if store.close_now(item, moment):
            closed = True
        elif store.abandon(item, moment):
            abandoned = True
    if closed and abandoned:
        return "Vou publicar o resultado nos grupos que já receberam a enquete. As que ainda não saíram foram canceladas."
    if closed and len(ids) > 1:
        return "Vou publicar o resultado em cada grupo, com a espera entre um e outro."
    if closed:
        return "Vou publicar o resultado no próximo envio."
    if abandoned:
        return "Enquete agendada cancelada."
    return "Essa enquete já está encerrada."


def _queue_each(store: PollStore, ids: list[int], moment: datetime, kind: str, empty: str, verb: str) -> str:
    queued = 0
    for item in ids:
        poll = store.detail(item)
        if poll.status == "ativa" and poll.message_id:
            store.enqueue(item, kind, "", moment)
            queued += 1
    if queued == 0:
        return empty
    if queued > 1:
        return f"Vou {verb} em cada grupo, com a espera entre um e outro."
    return f"Vou {verb} no próximo envio."


def _pin_each(store: PollStore, ids: list[int], moment: datetime) -> str:
    queued = 0
    for item in ids:
        poll = store.detail(item)
        if poll.status != "ativa" or not poll.message_id:
            continue
        if not poll.pin:
            store.choose_pin(item, "7d")
        store.enqueue(item, "pin", "", moment)
        queued += 1
    if queued == 0:
        return "A enquete precisa já estar no grupo para ser fixada."
    if queued > 1:
        return "Vou tentar fixar em cada grupo, com a espera entre um e outro."
    return "Vou tentar fixar no próximo envio."


def _unpin_each(store: PollStore, ids: list[int], moment: datetime) -> str:
    queued = 0
    for item in ids:
        poll = store.detail(item)
        if poll.pin_ok and poll.message_id:
            store.enqueue(item, "unpin", "", moment)
            queued += 1
    if queued == 0:
        return "Essa enquete não está fixada."
    if queued > 1:
        return "Vou tentar desafixar em cada grupo, com a espera entre um e outro."
    return "Vou tentar desafixar no próximo envio."


def _local_moment(value: str, clock: ZoneInfo) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=clock)
    return parsed.astimezone(clock)


def _same_secret(given: str, expected: str) -> bool:
    if not given or not expected:
        return False
    return hmac.compare_digest(given, expected)
