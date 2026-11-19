"""Telas de campanha e cartão de convites, no mesmo processo do painel."""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from promo_livros.board_store import BoardStore
from promo_livros.campaign_images import ImageUploadError, read_image, remove_campaign_dir, remove_image, save_upload
from promo_livros.campaign_pages import InviteCard, render_campaign_detail, render_campaign_list, render_invite_cards
from promo_livros.campaign_rules import (
    INVITE_FIXED,
    INVITE_KINDS,
    InviteSettings,
    RotationEntry,
    fixed_invite_missed,
    parse_fixed_clock,
    parse_last_offset,
    rotation_order,
)
from promo_livros.campaign_send import last_invite_clock_for, read_invite_settings
from promo_livros.campaign_store import CampaignError, CampaignRun, CampaignStore
from promo_livros.form_fields import first_field, raw_field
from promo_livros.models import AppConfig
from promo_livros.send_schedule import slot_clocks

logger = logging.getLogger("promo_livros.campaigns")

_MAX_ID_DIGITS = 12
_MAX_SQLITE_INTEGER = 2**63 - 1


class CampaignCallbacks(TypedDict):
    notify: Callable[[str], None]
    page: Callable[[], str]
    detail: Callable[[int], str | None]
    save_settings: Callable[[dict[str, list[str]]], str]
    action: Callable[[dict[str, list[str]]], str]
    upload: Callable[[int, list[bytes]], str]
    image: Callable[[int], bytes | None]
    invites: Callable[[], str]
    choose: Callable[[dict[str, list[str]]], str]


def campaign_callbacks(
    config: AppConfig,
    board: BoardStore,
    campaigns: CampaignStore,
    *,
    root: Path,
    current_day: Callable[[], str],
    now: Callable[[], datetime],
) -> CampaignCallbacks:
    holder: dict[str, str | None] = {"notice": None}

    def take_notice() -> str | None:
        notice = holder["notice"]
        holder["notice"] = None
        return notice

    def page() -> str:
        return render_campaign_list(campaigns.campaigns(), read_invite_settings(board), notice=take_notice())

    def detail(campaign_id: int) -> str | None:
        if not _valid_id(campaign_id):
            return None
        campaign = campaigns.campaign(campaign_id)
        if campaign is None:
            return None
        return render_campaign_detail(
            campaign,
            campaigns.images(campaign_id),
            campaigns.texts(campaign_id),
            notice=take_notice(),
        )

    def save_settings(form: dict[str, list[str]]) -> str:
        taken = set(slot_clocks(board.send_schedule())) | {post.clock for post in board.posts_for(current_day())}
        try:
            fixed = parse_fixed_clock(first_field(form, "fixo"), taken)
            offset = parse_last_offset(first_field(form, "final"))
        except ValueError as exc:
            holder["notice"] = str(exc)
            return "/campanhas"
        board.put_setting("invite_fixed_clock", fixed or "")
        board.put_setting("invite_last_offset_minutes", str(offset))
        holder["notice"] = "Horários dos convites salvos."
        return "/campanhas"

    def action(form: dict[str, list[str]]) -> str:
        kind = first_field(form, "acao")
        if kind == "criar":
            try:
                new_id = campaigns.create(raw_field(form, "nome"))
            except CampaignError as exc:
                holder["notice"] = str(exc)
                return "/campanhas"
            holder["notice"] = "Campanha criada. Agora mande as fotos e escreva os textos."
            return f"/campanhas/{new_id}"
        campaign_id = _parse_id(first_field(form, "id"))
        if campaign_id is None or campaigns.campaign(campaign_id) is None:
            holder["notice"] = "Campanha não encontrada."
            return "/campanhas"
        try:
            if kind in {"subir", "descer"}:
                campaigns.move(campaign_id, -1 if kind == "subir" else 1)
                return "/campanhas"
            if kind == "apagar":
                campaigns.delete(campaign_id)
                _remove_folder(campaign_id)
                holder["notice"] = "Campanha apagada."
                return "/campanhas"
            holder["notice"] = _edit(campaign_id, kind, form)
        except CampaignError as exc:
            holder["notice"] = str(exc)
        return f"/campanhas/{campaign_id}"

    def _remove_folder(campaign_id: int) -> None:
        try:
            remove_campaign_dir(root, campaign_id)
        except OSError as exc:
            logger.warning("A pasta da campanha %s ficou no disco: %s", campaign_id, type(exc).__name__)

    def _edit(campaign_id: int, kind: str, form: dict[str, list[str]]) -> str:
        if kind == "renomear":
            campaigns.rename(campaign_id, raw_field(form, "nome"))
            return "Nome salvo."
        if kind in {"ativar", "desativar"}:
            campaigns.set_active(campaign_id, kind == "ativar")
            return "Campanha ativada." if kind == "ativar" else "Campanha desativada. Ela sai do rodízio."
        if kind == "texto_novo":
            campaigns.add_text(campaign_id, raw_field(form, "corpo"))
            return "Texto adicionado."
        if kind in {"texto_editar", "texto_apagar"}:
            return _edit_text(campaign_id, kind, form)
        if kind == "foto_apagar":
            return _remove_photo(campaign_id, form)
        return "Ação desconhecida."

    def _edit_text(campaign_id: int, kind: str, form: dict[str, list[str]]) -> str:
        text_id = _parse_id(first_field(form, "texto"))
        text = campaigns.text(text_id) if text_id is not None else None
        if text is None or text.campaign_id != campaign_id:
            return "Texto não encontrado."
        if kind == "texto_editar":
            campaigns.update_text(text.id, raw_field(form, "corpo"))
            return "Texto salvo."
        campaigns.delete_text(text.id)
        return "Texto removido."

    def _remove_photo(campaign_id: int, form: dict[str, list[str]]) -> str:
        image_id = _parse_id(first_field(form, "foto"))
        image = campaigns.image(image_id) if image_id is not None else None
        if image is None or image.campaign_id != campaign_id:
            return "Foto não encontrada."
        removed_path = campaigns.delete_image(image.id)
        if removed_path is not None:
            _drop_file(removed_path, campaign_id)
        return "Foto removida."

    def _drop_file(relative_path: str, campaign_id: int) -> None:
        try:
            remove_image(root, relative_path)
        except OSError as exc:
            logger.warning("Uma foto da campanha %s ficou no disco: %s", campaign_id, type(exc).__name__)

    def upload(campaign_id: int, files: list[bytes]) -> str:
        if not _valid_id(campaign_id) or campaigns.campaign(campaign_id) is None:
            holder["notice"] = "Campanha não encontrada."
            return "/campanhas"
        if not files:
            holder["notice"] = "Escolha ao menos uma foto."
            return f"/campanhas/{campaign_id}"
        saved = 0
        refused: list[str] = []
        for index, payload in enumerate(files, start=1):
            try:
                path = save_upload(root, campaign_id, payload)
            except ImageUploadError as exc:
                refused.append(f"Arquivo {index}: {exc}")
                continue
            except OSError as exc:
                logger.warning("Não deu para gravar uma foto da campanha %s: %s", campaign_id, type(exc).__name__)
                refused.append(f"Arquivo {index}: não deu para salvar agora. Tente de novo.")
                continue
            try:
                campaigns.add_image(campaign_id, path)
            except CampaignError:
                # A campanha foi apagada no meio do envio: a foto já gravada não pode ficar órfã.
                _remove_folder(campaign_id)
                holder["notice"] = "Campanha não encontrada."
                return "/campanhas"
            except sqlite3.Error as exc:
                logger.warning("Uma foto da campanha %s não entrou no banco: %s", campaign_id, type(exc).__name__)
                _drop_file(path, campaign_id)
                refused.append(f"Arquivo {index}: não deu para salvar agora. Tente de novo.")
                continue
            saved += 1
        summary = "1 foto salva." if saved == 1 else f"{saved} fotos salvas."
        holder["notice"] = " ".join([summary, *refused])
        return f"/campanhas/{campaign_id}"

    def image(image_id: int) -> bytes | None:
        if not _valid_id(image_id):
            return None
        found = campaigns.image(image_id)
        if found is None:
            return None
        try:
            return read_image(root, found.path)
        except OSError as exc:
            logger.warning("A foto %s da campanha %s não abriu: %s", image_id, found.campaign_id, type(exc).__name__)
            return None

    def invites() -> str:
        day = current_day()
        moment = now()
        now_clock = f"{moment.hour:02d}:{moment.minute:02d}"
        settings = read_invite_settings(board)
        ready = campaigns.ready_campaigns()
        entries = {item.id: RotationEntry(item.id, item.position) for item in ready}
        names = {item.id: item.name for item in campaigns.campaigns()}
        last_used = campaigns.last_used_campaign()
        total = len(config.whatsapp_groups)
        cards: list[InviteCard] = []
        for kind in INVITE_KINDS:
            run = campaigns.peek_run(day, kind)
            title = _invite_title(kind, settings, day)
            if run is not None and run.status != "pending":
                label = _run_label(run, campaigns, total)
                cards.append(InviteCard(kind, title, label, None, names.get(run.campaign_id), False))
                continue
            if kind == INVITE_FIXED and settings.fixed_clock is None:
                cards.append(InviteCard(kind, title, "Desligado", None, None, False))
                continue
            if kind == INVITE_FIXED and fixed_invite_missed(settings.fixed_clock, now_clock):
                cards.append(InviteCard(kind, title, "Não saiu hoje", None, None, False))
                continue
            # Simula o rodízio: o convite final prevê a campanha seguinte à que o do horário vai usar.
            order = rotation_order(list(entries.values()), last_used)
            chosen = run.campaign_id if run is not None and run.manual and run.campaign_id in entries else None
            predicted = chosen if chosen is not None else (order[0] if order else None)
            if predicted is not None:
                last_used = entries[predicted]
            cards.append(InviteCard(kind, title, "Aguardando", chosen, names.get(predicted), True))
        return render_invite_cards(cards, ready)

    def _invite_title(kind: str, settings: InviteSettings, day: str) -> str:
        if kind == INVITE_FIXED:
            return f"Convite das {settings.fixed_clock}" if settings.fixed_clock else "Convite no horário"
        return f"Convite final ≈ {last_invite_clock_for(board, day, settings)}"

    def choose(form: dict[str, list[str]]) -> str:
        kind = first_field(form, "tipo")
        if kind not in INVITE_KINDS:
            return "Convite desconhecido."
        raw = first_field(form, "campanha")
        campaign_id: int | None = None
        if raw:
            campaign_id = _parse_id(raw)
            if campaign_id is None or campaign_id not in {item.id for item in campaigns.ready_campaigns()}:
                return "Essa campanha não está pronta."
        if not campaigns.set_manual_campaign(current_day(), kind, campaign_id):
            return "Esse convite já saiu."
        return "Campanha do convite trocada." if campaign_id is not None else "O convite volta para o rodízio."

    def notify(message: str) -> None:
        holder["notice"] = message

    return {
        "notify": notify,
        "page": page,
        "detail": detail,
        "save_settings": save_settings,
        "action": action,
        "upload": upload,
        "image": image,
        "invites": invites,
        "choose": choose,
    }


def _run_label(run: CampaignRun, campaigns: CampaignStore, total: int) -> str:
    if run.status == "sent":
        return "Enviado"
    if run.status == "skipped":
        return "Pulado: nenhuma campanha pronta"
    return f"Enviando {len(campaigns.sent_chat_ids(run.id))}/{total}"


def _parse_id(raw: str) -> int | None:
    """Só dígitos ASCII: isdigit() aceita '²', que quebraria o int()."""
    if not raw or len(raw) > _MAX_ID_DIGITS or not (raw.isascii() and raw.isdigit()):
        return None
    value = int(raw)
    return value if _valid_id(value) else None


def _valid_id(value: int) -> bool:
    """O SQLite estoura (OverflowError) com inteiro acima de 64 bits."""
    return 0 < value <= _MAX_SQLITE_INTEGER
