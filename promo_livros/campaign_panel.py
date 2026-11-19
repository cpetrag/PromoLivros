"""Telas de campanha e cartão de convites, no mesmo processo do painel."""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from random import Random
from typing import TypedDict

from promo_livros.board_store import POST_KIND_CAMPAIGN, BoardStore
from promo_livros.campaign_copy import clamp_text_count, generate_campaign_texts
from promo_livros.campaign_images import ImageUploadError, read_image, remove_campaign_dir, remove_image, save_upload
from promo_livros.campaign_pages import (
    InviteCard,
    QueuePostCard,
    render_campaign_detail,
    render_campaign_list,
    render_invite_cards,
    render_queue_post_form,
)
from promo_livros.campaign_rules import (
    INVITE_FIXED,
    INVITE_LAST,
    InviteSettings,
    RotationEntry,
    fixed_invite_missed,
    parse_last_offset,
    pick_avoiding,
    rotation_order,
)
from promo_livros.campaign_send import last_invite_clock_for, read_invite_settings
from promo_livros.campaign_store import (
    Campaign,
    CampaignError,
    CampaignImage,
    CampaignRun,
    CampaignStore,
    CampaignText,
)
from promo_livros.form_fields import first_field, raw_field
from promo_livros.models import AppConfig

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
    generate: Callable[[dict[str, list[str]]], str]
    swap_post: Callable[[dict[str, list[str]]], str]
    post_forms: Callable[[], dict[int, str]]


def campaign_callbacks(
    config: AppConfig,
    board: BoardStore,
    campaigns: CampaignStore,
    *,
    root: Path,
    current_day: Callable[[], str],
    now: Callable[[], datetime],
    generate_texts: Callable[..., list[str]] = generate_campaign_texts,
    rng: Random | None = None,
) -> CampaignCallbacks:
    picker = rng or Random()
    holder: dict[str, str | None] = {"notice": None}

    def take_notice() -> str | None:
        notice = holder["notice"]
        holder["notice"] = None
        return notice

    def page() -> str:
        return render_campaign_list(
            campaigns.campaigns(), read_invite_settings(board), notice=take_notice(), day=current_day()
        )

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
            day=current_day(),
            can_generate=bool(config.openai_api_key.strip()),
        )

    def save_settings(form: dict[str, list[str]]) -> str:
        try:
            offset = parse_last_offset(first_field(form, "final"))
        except ValueError as exc:
            holder["notice"] = str(exc)
            return "/campanhas"
        board.put_setting("invite_last_offset_minutes", str(offset))
        holder["notice"] = "Horário do convite final salvo."
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
        if kind == "agenda":
            campaigns.set_schedule(campaign_id, raw_field(form, "fixed_clock"), raw_field(form, "valid_until"))
            return "Agenda salva."
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
        ready = campaigns.ready_rotating(day)
        total = len(config.whatsapp_groups)
        cards = _fixed_cards(day, now_clock, total)
        cards.append(_last_card(day, settings, ready, total))
        return render_invite_cards(cards, ready, _queue_post_cards(day, ready))

    def post_forms() -> dict[int, str]:
        """Formulário de troca de cada post de campanha na fila, para a linha dele na grade da /hoje."""
        day = current_day()
        ready = campaigns.ready_rotating(day)
        return {card.post_id: render_queue_post_form(card, ready) for card in _queue_post_cards(day, ready)}

    def _fixed_cards(day: str, now_clock: str, total: int) -> list[InviteCard]:
        """Uma campanha fixa sai sozinha no próprio horário: o card só mostra o andamento do dia."""
        cards: list[InviteCard] = []
        for campaign in sorted(campaigns.ready_fixed(day), key=lambda item: (item.fixed_clock or "", item.id)):
            clock = campaign.fixed_clock or ""
            run = campaigns.peek_clock_run(day, campaign.id)
            if run is not None and run.status != "pending":
                label = _run_label(run, campaigns, total)
            elif fixed_invite_missed(clock, now_clock):
                label = "Não saiu hoje"
            else:
                label = "Aguardando"
            cards.append(InviteCard(INVITE_FIXED, f"{campaign.name} às {clock}", label, None, campaign.name, False))
        return cards

    def _last_card(day: str, settings: InviteSettings, ready: list[Campaign], total: int) -> InviteCard:
        title = f"Convite final ≈ {last_invite_clock_for(board, day, settings)}"
        names = {item.id: item.name for item in campaigns.campaigns()}
        run = campaigns.peek_run(day, INVITE_LAST)
        if run is not None and run.status != "pending":
            return InviteCard(INVITE_LAST, title, _run_label(run, campaigns, total), None, names.get(run.campaign_id), False)
        entries = {item.id: RotationEntry(item.id, item.position) for item in ready}
        order = rotation_order(list(entries.values()), campaigns.last_used_rotating())
        chosen = run.campaign_id if run is not None and run.manual and run.campaign_id in entries else None
        predicted = chosen if chosen is not None else (order[0] if order else None)
        return InviteCard(INVITE_LAST, title, "Aguardando", chosen, names.get(predicted), True)

    def _queue_post_cards(day: str, ready: list[Campaign]) -> tuple[QueuePostCard, ...]:
        ready_ids = {item.id for item in ready}
        cards: list[QueuePostCard] = []
        for post in board.posts_for(day):
            if post.post_kind != POST_KIND_CAMPAIGN:
                continue
            # Campanha que saiu do ar (vencida ou desativada) deixa a escolha em branco, sem listar o conteúdo dela.
            listed = post.campaign_id if post.campaign_id in ready_ids else None
            cards.append(
                QueuePostCard(
                    post_id=post.id,
                    clock=post.clock,
                    campaign_id=listed,
                    image_id=post.image_id if listed is not None else None,
                    text_id=post.text_id if listed is not None else None,
                    images=tuple(campaigns.images(listed)) if listed is not None else (),
                    texts=tuple(campaigns.texts(listed)) if listed is not None else (),
                )
            )
        return tuple(cards)

    def choose(form: dict[str, list[str]]) -> str:
        # Só o convite final tem escolha manual: campanhas fixas saem no horário delas.
        if first_field(form, "tipo") != INVITE_LAST:
            return "Convite desconhecido."
        raw = first_field(form, "campanha")
        campaign_id: int | None = None
        if raw:
            campaign_id = _parse_id(raw)
            if campaign_id is None or campaign_id not in {item.id for item in campaigns.ready_rotating(current_day())}:
                return "Essa campanha não está pronta."
        if not campaigns.set_manual_campaign(current_day(), INVITE_LAST, campaign_id):
            return "Esse convite já saiu."
        return "Campanha do convite trocada." if campaign_id is not None else "O convite volta para o rodízio."

    def generate(form: dict[str, list[str]]) -> str:
        campaign_id = _parse_id(first_field(form, "id"))
        campaign = campaigns.campaign(campaign_id) if campaign_id is not None else None
        if campaign is None:
            holder["notice"] = "Campanha não encontrada."
            return "/campanhas"
        target = f"/campanhas/{campaign.id}"
        api_key = config.openai_api_key.strip()
        if not api_key:
            holder["notice"] = "Configure a chave da OpenAI (OPENAI_API_KEY) para gerar textos."
            return target
        count = _parse_count(first_field(form, "count"))
        if count is None:
            holder["notice"] = "Informe quantos textos gerar."
            return target
        try:
            texts = generate_texts(
                api_key=api_key,
                model=config.openai_model,
                campaign_name=campaign.name,
                count=clamp_text_count(count),
            )
            for body in texts:
                campaigns.add_text(campaign.id, body)
        except CampaignError as exc:
            holder["notice"] = str(exc)
            return target
        holder["notice"] = f"{len(texts)} textos gerados. Revise antes de usar."
        return target

    def swap_post(form: dict[str, list[str]]) -> str:
        post_id = _parse_id(first_field(form, "post_id"))
        post = next(
            (item for item in board.posts_for(current_day()) if item.id == post_id and item.post_kind == POST_KIND_CAMPAIGN),
            None,
        )
        if post is None:
            return "Esse post não está mais na fila."
        campaign_id = _parse_id(first_field(form, "campaign_id"))
        if campaign_id is None or campaign_id not in {item.id for item in campaigns.ready_rotating(current_day())}:
            return "Essa campanha não está pronta."
        same_campaign = campaign_id == post.campaign_id
        image = _pick_member(campaigns.images(campaign_id), first_field(form, "image_id"), post.image_id if same_campaign else None, picker)
        text = _pick_member(campaigns.texts(campaign_id), first_field(form, "text_id"), post.text_id if same_campaign else None, picker)
        if image is None or text is None:
            return "Essa foto ou esse texto não é da campanha escolhida."
        locked_at = post.campaign_locked_at or now().isoformat(timespec="seconds")
        board.set_campaign_content(post.id, campaign_id, image.id, text.id, text.body, image.path, locked_at)
        return "Post de campanha trocado."

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
        "generate": generate,
        "swap_post": swap_post,
        "post_forms": post_forms,
    }


def _run_label(run: CampaignRun, campaigns: CampaignStore, total: int) -> str:
    if run.status == "sent":
        return "Enviado"
    if run.status == "skipped":
        return "Não saiu hoje" if run.kind == "clock" else "Pulado: nenhuma campanha pronta"
    return f"Enviando {len(campaigns.sent_chat_ids(run.id))}/{total}"


def _pick_member[T: (CampaignImage, CampaignText)](
    items: list[T], raw: str, current_id: int | None, rng: Random
) -> T | None:
    """Item escolhido no select. Vazio sorteia, evitando repetir o atual; id de fora da campanha vira None."""
    if not raw:
        if not items:
            return None
        chosen_id = pick_avoiding([item.id for item in items], current_id, rng)
        return next(item for item in items if item.id == chosen_id)
    item_id = _parse_id(raw)
    return next((item for item in items if item.id == item_id), None)


def _parse_count(raw: str) -> int | None:
    if not raw or len(raw) > 3 or not (raw.isascii() and raw.isdigit()):
        return None
    return int(raw)


def _parse_id(raw: str) -> int | None:
    """Só dígitos ASCII: isdigit() aceita '²', que quebraria o int()."""
    if not raw or len(raw) > _MAX_ID_DIGITS or not (raw.isascii() and raw.isdigit()):
        return None
    value = int(raw)
    return value if _valid_id(value) else None


def _valid_id(value: int) -> bool:
    """O SQLite estoura (OverflowError) com inteiro acima de 64 bits."""
    return 0 < value <= _MAX_SQLITE_INTEGER
