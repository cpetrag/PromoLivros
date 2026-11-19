from __future__ import annotations

import json
import os
from collections.abc import Callable
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import yaml

from promo_livros.config import load_config
from promo_livros.dashboard_auth import SessionStore
from promo_livros.dashboard_pages import (
    login_page,
    render_board,
    render_groups,
    render_sent,
    render_settings,
    render_signatures,
    render_today,
    render_whatsapp,
)
from promo_livros.day_view import DayView
from promo_livros.groups_file import GroupChoice, GroupsFileError, group_choices, selected_groups, write_groups
from promo_livros.models import ConfigError
from promo_livros.multipart_form import MEDIA_TYPE as MULTIPART_MEDIA_TYPE
from promo_livros.multipart_form import parse_multipart

if TYPE_CHECKING:
    from promo_livros.campaign_panel import CampaignCallbacks

HOST = "127.0.0.1"
PORT = 8787
COOKIE = "promo_livros_session"
MAX_POST_BODY = 65536
MAX_SETTINGS_BODY = 512_000
MAX_CSV_BODY = 2_000_000
MAX_WEBHOOK_BODY = 4_000_000
MAX_CAMPAIGN_UPLOAD_BODY = 40 * 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CAMPAIGN_ID = r"([0-9]{1,12})"


@dataclass
class DashboardApp:
    username: str
    password: str
    sessions: SessionStore
    today: Callable[[], tuple[str | None, DayView | None]]
    whatsapp: Callable[[], tuple[str, str | None]]
    qr_png: Callable[[], bytes]
    group_form: Callable[[], tuple[list[GroupChoice], bool, str | None]]
    save_groups: Callable[[list[str]], None]
    board: Callable[[], tuple[str, list, str | None, bool] | None] = None
    sent: Callable[[], list[tuple[str, str, str]]] | None = None
    move_post: Callable[[int, int], None] | None = None
    cancel_post: Callable[[int], None] | None = None
    add_post: Callable[[dict[str, list[str]]], str | None] | None = None
    read_link: Callable[[str], dict] | None = None
    card_file: Callable[[int], Path | None] | None = None
    sending: Callable[[], bool] | None = None
    set_sending: Callable[[bool], None] | None = None
    pair: Callable[[], None] | None = None
    schedule_now: Callable[[], object] | None = None
    save_schedule: Callable[[dict[str, list[str]]], None] | None = None
    repack_remaining: Callable[[], None] | None = None
    reorder_posts: Callable[[list[int]], None] | None = None
    queue_action: Callable[[str, dict[str, list[str]]], dict] | None = None
    swap_book: Callable[[dict[str, list[str]]], dict] | None = None
    save_draft_order: Callable[[list[str], list[str]], dict] | None = None
    rush_post: Callable[[int], None] | None = None
    skip_post: Callable[[int], None] | None = None
    duplicate_post: Callable[[int], None] | None = None
    restore_post: Callable[[int], None] | None = None
    apply_price: Callable[[int], None] | None = None
    pause_for: Callable[[dict[str, list[str]]], None] | None = None
    revise_post: Callable[[dict[str, list[str]]], str | None] | None = None
    kick_check: Callable[[], None] | None = None
    clear_queue: Callable[[], None] | None = None
    signatures_text: Callable[[], str] | None = None
    save_signatures: Callable[[dict[str, list[str]]], None] | None = None
    settings_page: Callable[[], str] | None = None
    save_settings: Callable[[dict[str, list[str]]], None] | None = None
    curation_page: Callable[..., str] | None = None
    import_catalog_text: Callable[[str], str] | None = None
    import_catalog_folder: Callable[[], str] | None = None
    import_fila_csv: Callable[[str], dict] | None = None
    import_fila_passo: Callable[[str], dict] | None = None
    import_fila_resolver: Callable[[str], dict] | None = None
    toggle_pick: Callable[..., dict] | None = None
    move_pick: Callable[..., dict] | None = None
    apply_picks: Callable[..., str] | None = None
    preview_picks: Callable[..., dict] | None = None
    undo_queue: Callable[[], str] | None = None
    fill_picks: Callable[[], dict] | None = None
    clear_picks: Callable[[], dict] | None = None
    undo_clear: Callable[[], dict] | None = None
    undo_fill: Callable[[], dict] | None = None
    save_order: Callable[[str], dict] | None = None
    move_tomorrow: Callable[[int], None] | None = None
    catalog_cover: Callable[[str], bytes] | None = None
    save_interval: Callable[[str], dict] | None = None
    extension_call: Callable[..., tuple[int, dict]] | None = None
    extension_token: Callable[[], str] | None = None
    polls_page: Callable[[dict[str, list[str]]], str] | None = None
    poll_detail: Callable[[int], str | None] | None = None
    poll_csv: Callable[[int], str | None] | None = None
    poll_save: Callable[[dict[str, list[str]]], str] | None = None
    poll_action: Callable[[int, str], str] | None = None
    poll_webhook: Callable[[dict, str], int] | None = None
    campaigns: CampaignCallbacks | None = None


class DashboardHandler(BaseHTTPRequestHandler):
    app: DashboardApp
    # Um cliente lento ou parado (upload de 40 MB pela metade) não pode prender uma thread para sempre.
    timeout = 60

    def do_OPTIONS(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/extensao/"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            return
        self.send_error(404)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/extensao/"):
            self._extensao(path)
            return
        if path == "/whatsapp/qr":
            self._qr()
            return
        card = re.fullmatch(r"/cards/(\d+)\.jpg", path)
        if card:
            self._card(int(card.group(1)))
            return
        if not self._logged_in():
            self._html(login_page(failed=False))
            return
        store_logo = re.fullmatch(r"/lojas/(amazon|ml|shopee|magalu)\.png", path)
        if store_logo:
            self._store_logo(store_logo.group(1))
            return
        if path == "/whatsapp":
            self._html(_whatsapp_page(self.app))
            return
        if path == "/grupos":
            choices, connected, notice = self.app.group_form()
            self._html(render_groups(choices, connected=connected, notice=notice))
            return
        if path == "/assinaturas" and self.app.signatures_text:
            from promo_livros.signatures import parse_block

            block = self.app.signatures_text()
            saved = "ok" in parse_qs(urlparse(self.path).query)
            self._html(render_signatures(block, saved=saved, count=len(parse_block(block))))
            return
        if path == "/configuracoes" and self.app.settings_page:
            self._html(self.app.settings_page())
            return
        if self.app.campaigns is not None and (path == "/campanhas" or path.startswith("/campanhas/")):
            self._campaign_get(path)
            return
        cover = re.fullmatch(r"/curadoria/capa/([A-Z0-9]{10}|MLB\d{6,14})\.jpg", path)
        if cover and self.app.catalog_cover:
            self._cover(cover.group(1))
            return
        if path == "/curadoria" and self.app.curation_page:
            loja = parse_qs(urlparse(self.path).query).get("loja", ["amazon"])[0]
            self._html(self.app.curation_page(loja))
            return
        if path == "/enviados" and self.app.sent:
            self._html(render_sent(self.app.sent()))
            return
        if path == "/enquetes" and self.app.polls_page is not None:
            self._html(self.app.polls_page(parse_qs(urlparse(self.path).query)))
            return
        csv_match = re.fullmatch(r"/enquetes/(\d+)\.csv", path)
        if csv_match and self.app.poll_csv is not None:
            self._poll_csv(int(csv_match.group(1)))
            return
        detail_match = re.fullmatch(r"/enquetes/(\d+)", path)
        if detail_match and self.app.poll_detail is not None:
            page = self.app.poll_detail(int(detail_match.group(1)))
            if page is None:
                self.send_error(404)
                return
            self._html(page)
            return
        if self.app.board and path in {"/", "/hoje", "/hoje/parcial"}:
            ctx = self._board_context()
            if ctx is None:
                self.send_error(404)
                return
            if path == "/hoje/parcial":
                from promo_livros.dashboard_belt import fragments

                self._json(fragments(
                    ctx["day"],
                    ctx["posts"],
                    sending=ctx["sending"],
                    schedule=ctx["schedule"],
                    groups=ctx["groups"],
                    aba=ctx["aba"],
                    now=ctx["now"],
                    whatsapp=ctx["whatsapp"],
                    paused_until=ctx["paused_until"],
                    members=ctx["members"],
                    repeat_days=ctx["repeat_days"],
                    arquivo=ctx.get("arquivo"),
                    invites=ctx["invites"],
                ))
                return
            self._html(render_board(
                ctx["day"],
                ctx["posts"],
                notice=ctx["notice"],
                sending=ctx["sending"],
                schedule=ctx["schedule"],
                groups=ctx["groups"],
                aba=ctx["aba"],
                now=ctx["now"],
                whatsapp=ctx["whatsapp"],
                paused_until=ctx["paused_until"],
                members=ctx["members"],
                repeat_days=ctx["repeat_days"],
                arquivo=ctx.get("arquivo"),
                invites=ctx["invites"],
            ))
            return
        error, view = self.app.today()
        day = view.day if view is not None else ""
        self._html(render_today(day=day, view=view, error=error))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/extensao/"):
            self._extensao(path)
            return
        if path == "/whatsapp/webhook":
            self._poll_webhook()
            return
        if not _same_origin(self):
            self.send_error(403)
            return
        if path == "/curadoria/csv":
            self._import_csv()
            return
        if path == "/curadoria/fila/csv":
            self._import_fila_csv()
            return
        if self.app.campaigns is not None and re.fullmatch(r"/campanhas/[^/]+/fotos", path):
            self._campaign_upload(path)
            return
        form = _form(self, MAX_SETTINGS_BODY if path == "/configuracoes" else MAX_POST_BODY)
        if form is None:
            return
        if path == "/login":
            token = self.app.sessions.login(
                _field(form, "username"),
                _field(form, "password"),
                self.app.username,
                self.app.password,
            )
            if token is None:
                self._html(login_page(failed=True))
                return
            self._redirect("/hoje", token)
            return
        if not self._logged_in():
            self._html(login_page(failed=False))
            return
        if path == "/enquetes" and self.app.poll_save is not None:
            self._redirect(self.app.poll_save(form), self._token())
            return
        poll_action = re.fullmatch(r"/enquetes/(\d+)/(encerrar|parcial|fixar|desafixar|duplicar)", path)
        if poll_action and self.app.poll_action is not None:
            self._redirect(
                self.app.poll_action(int(poll_action.group(1)), poll_action.group(2)),
                self._token(),
            )
            return
        if self.app.campaigns is not None:
            if path == "/campanhas/config":
                self._redirect(self.app.campaigns["save_settings"](form), self._token())
                return
            if path == "/campanhas/acao":
                self._redirect(self.app.campaigns["action"](form), self._token())
                return
            if path == "/hoje/convite":
                self.app.campaigns["choose"](form)
                self._redirect("/hoje", self._token())
                return
        if path == "/logout":
            self.app.sessions.forget(self._token())
            self._redirect("/", None)
            return
        if path == "/curadoria/intervalo" and self.app.save_interval:
            try:
                self._json(self.app.save_interval(_field(form, "interval")))
            except ValueError as exc:
                self._json({"error": str(exc)})
            return
        if path == "/curadoria/marcar" and self.app.toggle_pick:
            try:
                self._json(
                    self.app.toggle_pick(
                        _field(form, "asin"),
                        _field(form, "on") == "1",
                        _field(form, "loja") or "amazon",
                    )
                )
            except ValueError as exc:
                self._json({"error": str(exc)})
            return
        if path == "/curadoria/ordem" and self.app.move_pick:
            try:
                self._json(
                    self.app.move_pick(
                        _field(form, "asin"),
                        _field(form, "loja") or "amazon",
                        1 if _field(form, "passo") == "1" else -1,
                    )
                )
            except ValueError as exc:
                self._json({"error": str(exc)})
            return
        if path == "/curadoria/pasta" and self.app.import_catalog_folder:
            self.app.import_catalog_folder()
            self._redirect("/curadoria", self._token())
            return
        if path == "/curadoria/fila/csv/passo" and self.app.import_fila_passo:
            try:
                self._json(self.app.import_fila_passo(_field(form, "job")))
            except ValueError as exc:
                self._json({"error": str(exc)})
            return
        if path == "/curadoria/fila/csv/resolver" and self.app.import_fila_resolver:
            try:
                self._json(self.app.import_fila_resolver(_field(form, "job")))
            except ValueError as exc:
                self._json({"error": str(exc)})
            return
        if path == "/curadoria/fila/previa" and self.app.preview_picks:
            try:
                self._json(self.app.preview_picks(_field(form, "ordem")))
            except Exception as exc:
                self._json({"error": str(exc)})
            return
        if path == "/curadoria/fila" and self.app.apply_picks:
            notice = self.app.apply_picks(_field(form, "previa_id"))
            if not notice:
                self._json({"error": "A prévia não vale mais. Revise a fila de novo."})
                return
            if _field(form, "resposta") == "json":
                self._json({"ok": True, "message": notice})
                return
            self._redirect("/hoje", self._token())
            return
        if path == "/curadoria/desfazer" and self.app.undo_queue:
            try:
                self._json({"ok": True, "message": self.app.undo_queue()})
            except Exception as exc:
                self._json({"error": str(exc)})
            return
        if path == "/curadoria/preencher" and self.app.fill_picks:
            try:
                self._json(self.app.fill_picks())
            except Exception as exc:
                self._json({"error": str(exc)})
            return
        if path == "/curadoria/desmarcar" and self.app.clear_picks:
            self._json(self.app.clear_picks())
            return
        if path == "/curadoria/desmarcar/desfazer" and self.app.undo_clear:
            self._json(self.app.undo_clear())
            return
        if path == "/curadoria/preencher/desfazer" and self.app.undo_fill:
            self._json(self.app.undo_fill())
            return
        if path == "/curadoria/fila/ordem" and self.app.save_draft_order:
            try:
                self._json(self.app.save_draft_order(form.get("amazon", []), form.get("segunda", [])))
            except Exception as exc:
                self._json({"error": str(exc)})
            return
        if path == "/curadoria/preferencia" and self.app.save_order:
            self._json(self.app.save_order(_field(form, "ordem")))
            return
        if path == "/assinaturas" and self.app.save_signatures:
            self.app.save_signatures(form)
            self._redirect("/assinaturas?ok=1", self._token())
            return
        if path == "/configuracoes" and self.app.save_settings:
            self.app.save_settings(form)
            mark = "teste=1" if _field(form, "acao") == "testar" else "ok=1"
            self._redirect(f"/configuracoes?{mark}", self._token())
            return
        if path == "/grupos":
            try:
                self.app.save_groups(form.get("chat_id", []))
            except GroupsFileError as exc:
                choices, connected, _notice = self.app.group_form()
                self._html(render_groups(choices, connected=connected, notice=str(exc)))
                return
            self._redirect("/grupos", self._token())
            return
        if path == "/hoje/mover" and self.app.move_post:
            self.app.move_post(_int_field(form, "id"), _int_field(form, "direcao"))
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/amanha" and self.app.move_tomorrow:
            self.app.move_tomorrow(_int_field(form, "id"))
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/apagar" and self.app.cancel_post:
            self.app.cancel_post(_int_field(form, "id"))
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/manual" and self.app.add_post:
            self.app.add_post(form)
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/link" and self.app.read_link:
            self._json(self.app.read_link(_field(form, "url")))
            return
        if path == "/whatsapp/envio" and self.app.set_sending:
            self.app.set_sending(_field(form, "enabled") == "1")
            target = _field(form, "next")
            if target not in {"/hoje", "/whatsapp"}:
                target = "/whatsapp"
            self._redirect(target, self._token())
            return
        if path == "/whatsapp/parear" and self.app.pair:
            try:
                self.app.pair()
            except Exception:
                self._html(render_whatsapp(state="down", message="Não foi possível abrir o QR."))
                return
            self._redirect("/whatsapp", self._token())
            return
        if path == "/envio/regras" and self.app.save_schedule:
            self.app.save_schedule(form)
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/limpar" and self.app.clear_queue:
            self.app.clear_queue()
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/reorganizar" and self.app.repack_remaining:
            self.app.repack_remaining()
            self._redirect("/hoje", self._token())
            return
        queue_action = re.fullmatch(r"/hoje/(trocar|antes|horario|empurrar|reespacar|horarios/desfazer)", path)
        if queue_action and self.app.queue_action:
            self._json(self.app.queue_action(queue_action.group(1).replace("horarios/", ""), form))
            return
        if path == "/hoje/trocar-livro" and self.app.swap_book:
            self._json(self.app.swap_book(form))
            return
        if path == "/hoje/reordenar" and self.app.reorder_posts:
            ids: list[int] = []
            for raw in form.get("id", []):
                try:
                    ids.append(int(raw))
                except ValueError:
                    continue
            self.app.reorder_posts(ids)
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/agora" and self.app.rush_post:
            self.app.rush_post(_int_field(form, "id"))
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/pular" and self.app.skip_post:
            self.app.skip_post(_int_field(form, "id"))
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/duplicar" and self.app.duplicate_post:
            self.app.duplicate_post(_int_field(form, "id"))
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/desfazer" and self.app.restore_post:
            self.app.restore_post(_int_field(form, "id"))
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/preco" and self.app.apply_price:
            self.app.apply_price(_int_field(form, "id"))
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/pausar" and self.app.pause_for:
            self.app.pause_for(form)
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/editar" and self.app.revise_post:
            self.app.revise_post(form)
            self._redirect("/hoje", self._token())
            return
        if path == "/hoje/checar":
            if self.app.kick_check:
                self.app.kick_check()
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _qr(self) -> None:
        if not self._logged_in():
            self._html(login_page(failed=False))
            return
        state, message = self.app.whatsapp()
        if state != "qr" or message:
            self._html(render_whatsapp(state=state, message=message or "Não há QR."))
            return
        try:
            payload = self.app.qr_png()
        except Exception:
            self._html(render_whatsapp(state="down", message="WAHA não devolveu o QR."))
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _cover(self, asin: str) -> None:
        if not self._logged_in() or self.app.catalog_cover is None:
            self._html(login_page(failed=False))
            return
        try:
            payload = self.app.catalog_cover(asin)
        except Exception:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "private, max-age=86400")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _import_csv(self) -> None:
        if not _same_origin(self):
            self.send_error(403)
            return
        if not self._logged_in() or self.app.import_catalog_text is None:
            self._html(login_page(failed=False))
            return
        length = _content_length(self, MAX_CSV_BODY)
        if length is None:
            return
        text = self.rfile.read(length).decode("utf-8-sig", errors="replace")
        try:
            message = self.app.import_catalog_text(text)
        except ValueError as exc:
            self._json({"error": str(exc)})
            return
        self._json({"ok": True, "message": message})

    def _import_fila_csv(self) -> None:
        if not _same_origin(self):
            self.send_error(403)
            return
        if not self._logged_in() or self.app.import_fila_csv is None:
            self._html(login_page(failed=False))
            return
        length = _content_length(self, MAX_CSV_BODY)
        if length is None:
            return
        text = self.rfile.read(length).decode("utf-8-sig", errors="replace")
        try:
            payload = self.app.import_fila_csv(text)
        except ValueError as exc:
            self._json({"error": str(exc)})
            return
        self._json(payload)

    def _card(self, post_id: int) -> None:
        if not self._logged_in() or self.app.card_file is None:
            self._html(login_page(failed=False))
            return
        path = self.app.card_file(post_id)
        if path is None:
            self.send_error(404)
            return
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _store_logo(self, store: str) -> None:
        from promo_livros.post_card import store_logo_png

        payload = store_logo_png(store)
        if payload is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "private, max-age=86400")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _campaign_get(self, path: str) -> None:
        campaigns = self.app.campaigns
        if path == "/campanhas":
            self._html(campaigns["page"]())
            return
        detail = re.fullmatch(rf"/campanhas/{_CAMPAIGN_ID}", path)
        if detail:
            page = campaigns["detail"](int(detail.group(1)))
            if page is None:
                self.send_error(404)
                return
            self._html(page)
            return
        photo = re.fullmatch(rf"/campanhas/foto/{_CAMPAIGN_ID}\.jpg", path)
        payload = campaigns["image"](int(photo.group(1))) if photo else None
        if payload is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "private, max-age=86400")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _campaign_upload(self, path: str) -> None:
        """Lê o corpo aqui, e não em _form, porque as fotos passam do limite dos formulários comuns."""
        # O corpo não é lido nas recusas abaixo; a conexão fecha para não sobrar lixo nela.
        self.close_connection = True
        if not self._logged_in():
            self._html(login_page(failed=False))
            return
        match = re.fullmatch(rf"/campanhas/{_CAMPAIGN_ID}/fotos", path)
        if match is None:
            self.send_error(404)
            return
        campaign_id = int(match.group(1))
        back = f"/campanhas/{campaign_id}"
        media_type = self.headers.get("Content-Type", "").partition(";")[0].strip().lower()
        if media_type != MULTIPART_MEDIA_TYPE:
            self._refuse_upload(back, "Envie as fotos pelo formulário da campanha.")
            return
        raw_length = (self.headers.get("Content-Length") or "").strip()
        if not (raw_length.isascii() and raw_length.isdigit()):
            self.send_error(411)
            return
        length = int(raw_length)
        if length > MAX_CAMPAIGN_UPLOAD_BODY:
            limit_mb = MAX_CAMPAIGN_UPLOAD_BODY // (1024 * 1024)
            self._refuse_upload(back, f"O envio passa de {limit_mb} MB. Mande menos fotos de cada vez.")
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self.send_error(400)
            return
        try:
            _fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
        except ValueError as exc:
            self._refuse_upload(back, str(exc))
            return
        self._redirect(self.app.campaigns["upload"](campaign_id, files.get("fotos", [])), self._token())

    def _refuse_upload(self, location: str, message: str) -> None:
        self.app.campaigns["notify"](message)
        self._redirect(location, self._token())

    def _logged_in(self) -> bool:
        return self.app.sessions.valid(self._token())

    def _token(self) -> str | None:
        header = self.headers.get("Cookie", "")
        for part in header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and value:
                return value
        return None

    def _board_context(self) -> dict | None:
        if self.app.board is None:
            return None
        board = self.app.board()
        if board is None:
            return None
        day, posts, notice, sending, schedule = board[:5]
        groups: tuple[str, ...] = board[5] if len(board) > 5 else ()
        extra = board[6] if len(board) > 6 and isinstance(board[6], dict) else {}
        aba = parse_qs(urlparse(self.path).query).get("aba", ["todas"])[0]
        if self.app.kick_check:
            self.app.kick_check()
        return {
            "day": day,
            "posts": posts,
            "notice": notice,
            "sending": sending,
            "schedule": schedule,
            "groups": groups,
            "aba": aba,
            "now": extra.get("now"),
            "whatsapp": extra.get("whatsapp") or "unknown",
            "paused_until": extra.get("paused_until") or "",
            "members": extra.get("members"),
            "repeat_days": extra.get("repeat_days") or 1,
            "arquivo": extra.get("arquivo"),
            "invites": extra.get("invites") or "",
        }

    def _extensao(self, path: str) -> None:
        if self.app.extension_call is None:
            self._ext_json({"error": "A extensão não está ligada."}, status=404)
            return
        body: dict = {}
        if self.command == "POST":
            length = _content_length(self, MAX_POST_BODY)
            if length is None:
                return
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
            if raw:
                try:
                    loaded = json.loads(raw)
                except json.JSONDecodeError:
                    self._ext_json({"error": "Não entendi esse pedido."}, status=400)
                    return
                if not isinstance(loaded, dict):
                    self._ext_json({"error": "Não entendi esse pedido."}, status=400)
                    return
                body = loaded
        status, payload = self.app.extension_call(
            self.command,
            path,
            parse_qs(urlparse(self.path).query),
            body,
            self.headers.get("Authorization", ""),
        )
        self._ext_json(payload, status=status)

    def _ext_json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, payload: dict) -> None:
        self._status_json(payload, 200)

    def _status_json(self, payload: dict, status: int) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _poll_webhook(self) -> None:
        if self.app.poll_webhook is None:
            self.send_error(404)
            return
        length = _content_length(self, MAX_WEBHOOK_BODY)
        if length is None:
            return
        raw = self.rfile.read(length) if length else b""
        try:
            loaded = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            self._status_json({"ok": False}, 400)
            return
        if not isinstance(loaded, dict):
            self._status_json({"ok": False}, 400)
            return
        status = self.app.poll_webhook(loaded, self.headers.get("X-Api-Key", ""))
        self._status_json({"ok": status == 200}, status)

    def _poll_csv(self, poll_id: int) -> None:
        if self.app.poll_csv is None:
            self.send_error(404)
            return
        body = self.app.poll_csv(poll_id)
        if body is None:
            self.send_error(404)
            return
        payload = body.encode("utf-8-sig")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="enquete-{poll_id}.csv"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str, token: str | None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Set-Cookie", _session_cookie(token, _request_is_https(self)))
        self.end_headers()


def _request_is_https(handler: BaseHTTPRequestHandler) -> bool:
    forwarded = (handler.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    if forwarded == "https":
        return True
    visitor = (handler.headers.get("Cf-Visitor") or "").lower()
    return '"scheme":"https"' in visitor.replace(" ", "")


def _session_cookie(token: str | None, secure: bool) -> str:
    if token:
        value = f"{COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/"
    else:
        value = f"{COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
    if secure:
        value += "; Secure"
    return value


def _whatsapp_page(app: DashboardApp) -> str:
    state, message = app.whatsapp()
    sending = app.sending() if app.sending else False
    schedule = app.schedule_now() if app.schedule_now else None
    if state == "qr" and not message:
        try:
            app.qr_png()
        except Exception:
            return render_whatsapp(
                state="qr",
                message="WAHA não devolveu o QR.",
                sending=sending,
                schedule=schedule,
            )
    return render_whatsapp(state=state, message=message, sending=sending, schedule=schedule)


def _same_origin(handler: BaseHTTPRequestHandler) -> bool:
    origin = handler.headers.get("Origin")
    if not origin:
        return True
    return urlparse(origin).netloc == handler.headers.get("Host", "")


def _form(handler: BaseHTTPRequestHandler, limit: int = MAX_POST_BODY) -> dict[str, list[str]] | None:
    length = _content_length(handler, limit)
    if length is None:
        return None
    raw = handler.rfile.read(length).decode("utf-8", errors="replace")
    return parse_qs(raw, keep_blank_values=False)


def _content_length(handler: BaseHTTPRequestHandler, limit: int = MAX_POST_BODY) -> int | None:
    raw = handler.headers.get("Content-Length", "0") or "0"
    try:
        length = int(raw)
    except ValueError:
        handler.send_error(400)
        return None
    if length < 0 or length > limit:
        handler.send_error(400)
        return None
    return length


def whatsapp_enabled_in_file(config_path: Path) -> bool:
    try:
        with config_path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except OSError as exc:
        raise GroupsFileError("Não foi possível ler config.yaml.") from exc
    except yaml.YAMLError as exc:
        raise GroupsFileError("config.yaml não pôde ser lido.") from exc
    if not isinstance(raw, dict):
        raise GroupsFileError("config.yaml não pôde ser lido.")
    whatsapp = raw.get("whatsapp")
    if not isinstance(whatsapp, dict):
        raise GroupsFileError("config.yaml não tem whatsapp.")
    enabled = whatsapp.get("enabled")
    if not isinstance(enabled, bool):
        raise GroupsFileError("whatsapp.enabled precisa ser true ou false.")
    return enabled


def persist_group_selection(
    config_path: Path,
    posted_ids: list[str],
    choices: list[GroupChoice],
) -> list[tuple[str, str]]:
    groups = selected_groups(posted_ids, choices)
    write_groups(config_path, groups, enabled=whatsapp_enabled_in_file(config_path))
    return groups


def _field(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name, [])
    return values[0] if values else ""


def _int_field(form: dict[str, list[str]], name: str) -> int:
    try:
        return int(_field(form, name))
    except ValueError:
        return 0


class DashboardServer(ThreadingHTTPServer):
    # A Curadoria pede dezenas de capas de uma vez; com a fila padrão (5) o túnel leva timeout e devolve 502.
    request_queue_size = 128
    daemon_threads = True


def serve(app: DashboardApp) -> None:
    DashboardHandler.app = app
    server = DashboardServer((HOST, PORT), DashboardHandler)
    server.serve_forever()


def main() -> None:
    try:
        config = load_config(Path("config.yaml"))
    except ConfigError as exc:
        raise SystemExit(f"Configuração: {exc}") from exc
    username = os.environ.get("DASHBOARD_USERNAME", "").strip()
    password = os.environ.get("DASHBOARD_PASSWORD", "").strip()
    if not username or not password:
        raise SystemExit("Defina DASHBOARD_USERNAME e DASHBOARD_PASSWORD no .env.")
    app = build_app(config, username, password)
    serve(app)


def apply_interval_save(store, day: str, schedule) -> str:
    """Grava a janela. Não mexe no relógio dos posts que já estão na fila."""
    from promo_livros.send_schedule import slot_clocks

    store.save_send_schedule(schedule)
    clocks = slot_clocks(schedule)
    span = f"{clocks[0]} a {clocks[-1]}" if clocks else "nenhum horário"
    pending = store.posts_for(day)
    if pending:
        return (
            f"Intervalos salvos. Os {len(pending)} posts de hoje continuam nos horários atuais. "
            f"A grade nova cabe {len(clocks)} posts, de {span}. "
            "Para encaixar o que falta, use Reorganizar o que resta."
        )
    return f"Intervalos salvos. A fila das 5h cabe {len(clocks)} posts, de {span}."


def build_app(config, username: str, password: str) -> DashboardApp:
    import logging
    import threading
    import time
    from datetime import datetime

    from promo_livros.day_view import build_day_view, captions_for, load_day_rows
    from promo_livros.groups_file import group_choices
    from promo_livros.models import WhatsAppGroup
    from promo_livros.schedule_plan import service_day, zone
    from promo_livros.storage import DayReadError
    from promo_livros.waha import WahaClient, WahaError

    from promo_livros.amz_links import affiliate_resolver
    from promo_livros.board_actions import revise_manual, schedule_manual
    from promo_livros.board_store import BoardStore

    sessions = SessionStore()
    holder = {"groups": config.whatsapp_groups, "notice": None}
    board_store = BoardStore(config.sqlite_path)
    member_cache: dict[str, object] = {"at": 0.0, "day": "", "view": None}
    member_lock = threading.Lock()
    cards_dir = Path("data") / "cards"
    resolve_urls = affiliate_resolver(config)

    def current_day() -> str:
        return service_day(datetime.now(zone(config.schedule.timezone)), config.schedule.timezone)

    def today() -> tuple[str | None, DayView | None]:
        day = service_day(datetime.now(zone(config.schedule.timezone)), config.schedule.timezone)
        try:
            queue, dispatches = load_day_rows(config.sqlite_path, day)
        except DayReadError as exc:
            return str(exc), None
        view = build_day_view(
            day=day,
            slots=config.slots,
            niches=config.niches,
            per_niche=config.schedule.per_niche,
            queue=tuple(queue),
            dispatches=tuple(dispatches),
            saved_groups=holder["groups"],
            captions=captions_for(dispatches, queue, config.affiliate_tag),
        )
        return None, view

    def whatsapp() -> tuple[str, str | None]:
        client = WahaClient.from_config(config)
        try:
            return client.probe_session(), None
        except WahaError as exc:
            return "down", str(exc)
        finally:
            client.close()

    def qr_png() -> bytes:
        client = WahaClient.from_config(config)
        try:
            return client.fetch_qr_png()
        finally:
            client.close()

    def pair() -> None:
        client = WahaClient.from_config(config)
        try:
            client.begin_pairing()
        finally:
            client.close()

    def group_form() -> tuple[list[GroupChoice], bool, str | None]:
        state, message = whatsapp()
        if state != "connected":
            return group_choices((), holder["groups"]), False, message
        client = WahaClient.from_config(config)
        try:
            live = client.list_groups()
        except WahaError as exc:
            return group_choices((), holder["groups"]), False, str(exc)
        finally:
            client.close()
        return group_choices(live, holder["groups"]), True, None

    def save(posted_ids: list[str]) -> None:
        choices, connected, message = group_form()
        if not connected:
            raise GroupsFileError(message or "Conecte o WhatsApp para ver a lista.")
        groups = persist_group_selection(Path("config.yaml"), posted_ids, choices)
        holder["groups"] = tuple(WhatsAppGroup(name, chat_id) for name, chat_id in groups)

    def queue_day() -> str:
        today = current_day()
        cleared = board_store.close_past_days(today)
        if cleared and not holder.get("notice"):
            holder["notice"] = f"A fila de ontem saiu ({cleared} posts). Ela vale só para a data e a hora."
        return today

    probe_cache = {"at": 0.0, "state": "unknown"}
    checking = {"on": False}

    def cached_whatsapp() -> str:
        import threading
        import time

        if probe_cache.get("running"):
            return str(probe_cache["state"])
        if probe_cache["at"] and time.monotonic() - probe_cache["at"] < 25:
            return str(probe_cache["state"])
        probe_cache["running"] = True

        def run() -> None:
            try:
                state, _message = whatsapp()
            except Exception:
                state = "unknown"
            probe_cache["at"] = time.monotonic()
            probe_cache["state"] = state
            probe_cache["running"] = False

        threading.Thread(target=run, daemon=True).start()
        return str(probe_cache["state"])

    def kick_check() -> None:
        import threading

        if checking["on"]:
            return
        checking["on"] = True

        def run() -> None:
            try:
                from promo_livros.keepa_client import KeepaClient
                from promo_livros.offer_check import check_scheduled

                def factory():
                    if not getattr(config, "keepa_api_key", ""):
                        return None
                    return KeepaClient(config)

                check_scheduled(board_store, queue_day(), client_factory=factory)
            except Exception:
                return
            finally:
                checking["on"] = False

        threading.Thread(target=run, daemon=True).start()

    def read_members(day: str):
        """Lê os três grupos no máximo a cada 20s. Uma lista vazia não apaga a base."""
        from promo_livros.membership import MembershipStore, MembershipView
        from promo_livros.waha import WahaError

        with member_lock:
            cached = member_cache["view"]
            cached_at = float(member_cache["at"])  # type: ignore[arg-type]
            if (
                cached is not None
                and member_cache["day"] == day
                and time.monotonic() - cached_at < 20
            ):
                return cached
            groups = tuple(holder["groups"])
            store = MembershipStore(config.sqlite_path)
            client = WahaClient.from_config(config)
            try:
                rows = []
                for group in groups:
                    people = client.group_participants(group.chat_id)
                    rows.append(store.observe(day, group.chat_id, group.name, people))
                view = MembershipView(available=True, groups=tuple(rows))
            except (WahaError, ValueError):
                logging.getLogger("promo_livros").warning("Não foi possível ler os membros dos grupos.")
                same_day = member_cache["day"] == day and cached is not None
                view = cached if same_day else MembershipView(available=False)
            finally:
                client.close()
                store.close()
            member_cache["view"] = view
            member_cache["day"] = day
            member_cache["at"] = time.monotonic()
            return view

    def board():
        day = queue_day()
        notice = holder["notice"]
        holder["notice"] = None
        names = tuple(group.name for group in holder["groups"])
        effective = board_store.sending_enabled()
        paused = board_store.setting("paused_until") or ""
        now = datetime.now(zone(config.schedule.timezone))
        return (
            day,
            board_store.day_feed(day),
            notice,
            effective,
            board_store.send_schedule(),
            names,
            {
                "now": now,
                "whatsapp": cached_whatsapp(),
                "paused_until": paused,
                "members": read_members(day),
                "repeat_days": board_store.repeat_days(),
                "arquivo": board_store.sent_feed(),
                "invites": invites_html(),
            },
        )

    def invites_html() -> str:
        try:
            return campaign_panel["invites"]()
        except Exception as exc:
            # O cartão de convites é acessório: um erro nele não pode derrubar a /hoje.
            logging.getLogger("promo_livros").error(
                "Não consegui montar os convites da /hoje: %s", type(exc).__name__
            )
            return ""

    def sent():
        queue_day()
        return [(line.when, line.title, line.detail) for line in board_store.sent_lines()]

    def move_post(post_id: int, direction: int) -> None:
        if direction not in (-1, 1):
            return
        board_store.shift(queue_day(), post_id, direction)

    def cancel_post(post_id: int) -> None:
        board_store.cancel(queue_day(), post_id)

    def queue_action(acao: str, form: dict[str, list[str]]) -> dict:
        from promo_livros.fila_acoes import executar

        now = datetime.now(zone(config.schedule.timezone))
        try:
            return executar(board_store, queue_day(), now.strftime("%H:%M"), acao, form)
        except Exception:
            logging.getLogger("promo_livros").exception("A ação %s da grade falhou.", acao)
            return {"ok": False, "error": "Não mudei os horários. Tente de novo."}

    def swap_book(form: dict[str, list[str]]) -> dict:
        from promo_livros.troca_livro import trocar_livro

        try:
            post_id = int(_field(form, "id"))
            com_id = int(_field(form, "com"))
        except ValueError:
            return {"ok": False, "error": "Pedido incompleto. Atualize a página."}
        try:
            return trocar_livro(
                board_store, cards_dir, queue_day(), post_id, com_id, _field(form, "lado"), fetch_cover=catalog_cover
            )
        except Exception:
            logging.getLogger("promo_livros").exception("A troca de livro entre %s e %s falhou.", post_id, com_id)
            return {"ok": False, "error": "Não troquei o livro. Tente de novo."}

    def read_link(url: str) -> dict:
        """Lê a oferta de um link avulso para o compositor preencher os campos."""
        from promo_livros.link_offer import LinkOfferError, offer_from_catalog, read_offer
        from promo_livros.ml_links import session_from_export

        known = offer_from_catalog(url, catalog.find_book)
        if known is not None:
            return known
        cookie, _csrf = session_from_export(board_store.setting("ml_cookies") or "")
        try:
            return read_offer(url, ml_cookie=cookie).as_dict()
        except LinkOfferError as exc:
            return {"error": str(exc)}

    def add_post(form: dict[str, list[str]]) -> str | None:
        notice = schedule_manual(
            board_store, queue_day(), form, cards_dir, resolve_urls=resolve_urls
        )
        holder["notice"] = notice
        return notice

    def save_rules(form: dict[str, list[str]]) -> None:
        from promo_livros.send_schedule import parse_schedule, write_group_gap

        try:
            parsed = parse_schedule(
                _field(form, "start"),
                _field(form, "end"),
                _field(form, "interval"),
                _field(form, "gap"),
            )
            repeat = _field(form, "repeat") or board_store.setting("janela_repeticao_dias") or "1"
            try:
                days = min(30, max(1, int(repeat)))
            except ValueError:
                holder["notice"] = "Os dias sem repetir precisam ser um número de 1 a 30."
                return
            board_store.put_setting("janela_repeticao_dias", str(days))
        except ValueError as exc:
            holder["notice"] = str(exc)
            return
        yaml_note = ""
        try:
            write_group_gap(Path("config.yaml"), parsed.group_gap_seconds)
        except OSError:
            yaml_note = " O config.yaml não foi alterado."
        notice = apply_interval_save(board_store, queue_day(), parsed)
        if yaml_note:
            notice = notice.replace("Intervalos salvos.", f"Intervalos salvos.{yaml_note}", 1)
        holder["notice"] = notice

    def save_signatures(form: dict[str, list[str]]) -> None:
        board_store.put_setting("signatures", _field(form, "bloco"))

    def clear_queue() -> None:
        day = queue_day()
        waiting = len(board_store.posts_for(day))
        board_store.cancel_day(day)
        if waiting == 0:
            holder["notice"] = "A fila já estava vazia."
            return
        word = "post saiu" if waiting == 1 else "posts saíram"
        holder["notice"] = f"{waiting} {word} da fila. O que já foi enviado continua na lista."

    def repack_remaining() -> None:
        from promo_livros.fila_aplicar import reorganizar

        now = datetime.now(zone(config.schedule.timezone))
        holder["notice"] = reorganizar(
            catalog,
            board_store,
            queue_day(),
            now.strftime("%H:%M"),
            cards_dir,
            resolve_urls=resolve_urls,
            resolve_ml=resolve_ml,
            thumbnail=lambda item: thumbnail_url(
                item,
                cookie=session_from_export(board_store.setting("ml_cookies") or "")[0],
            ),
            describe=book_line,
        )

    def reorder_posts(ids: list[int]) -> None:
        if board_store.reorder(queue_day(), ids):
            holder["notice"] = "Fila reordenada e horários recalculados."
        else:
            holder["notice"] = "A ordem não foi salva."

    def rush_post(post_id: int) -> None:
        now = datetime.now(zone(config.schedule.timezone))
        clock = f"{now.hour:02d}:{now.minute:02d}"
        if board_store.rush(queue_day(), post_id, clock):
            holder["notice"] = f"O post entra no próximo ciclo do envio, às {clock}."
        else:
            holder["notice"] = "Só dá para enviar agora um post que está na fila."

    def skip_post(post_id: int) -> None:
        if board_store.skip(queue_day(), post_id):
            holder["notice"] = "Post pulado. O próximo da fila segue."
        else:
            holder["notice"] = "Só dá para pular um post que está na fila."

    def duplicate_post(post_id: int) -> None:
        from promo_livros.send_schedule import slot_clocks, upcoming_clocks

        post = board_store.post_by_id(post_id)
        if post is None or not post.books:
            holder["notice"] = "Não encontrei o post para duplicar."
            return
        day = queue_day()
        schedule = board_store.send_schedule()
        now = datetime.now(zone(config.schedule.timezone))
        now_clock = f"{now.hour:02d}:{now.minute:02d}"
        used = {item.clock for item in board_store.posts_for(day)}
        clock = ""
        for candidate in [*upcoming_clocks(schedule, now_clock), *slot_clocks(schedule)]:
            if candidate not in used:
                clock = candidate
                break
        if not clock:
            holder["notice"] = "Não há horário livre para duplicar."
            return
        board_store.add_post(
            day=day,
            clock=clock,
            caption=post.caption,
            image_path=post.image_path,
            books=list(post.books),
        )
        holder["notice"] = f"Post duplicado às {clock}."

    def restore_post(post_id: int) -> None:
        if board_store.restore(queue_day(), post_id):
            holder["notice"] = "Post de volta na fila."
        else:
            holder["notice"] = "Não deu para desfazer."

    def apply_price(post_id: int) -> None:
        notice = board_store.apply_live_price(queue_day(), post_id)
        holder["notice"] = notice or "Preço atualizado no texto."

    def pause_for(form: dict[str, list[str]]) -> None:
        from datetime import timedelta

        choice = _field(form, "minutos")
        now = datetime.now(zone(config.schedule.timezone))
        schedule = board_store.send_schedule()
        if choice == "30":
            when = now + timedelta(minutes=30)
        elif choice == "60":
            when = now + timedelta(hours=1)
        elif choice == "amanha":
            hour, minute = schedule.start.split(":")
            tomorrow = now.date() + timedelta(days=1)
            when = datetime(
                tomorrow.year,
                tomorrow.month,
                tomorrow.day,
                int(hour),
                int(minute),
                tzinfo=now.tzinfo,
            )
        else:
            holder["notice"] = "Escolha 30 min, 1 h ou até amanhã."
            return
        board_store.pause_until(when)
        holder["notice"] = f"Envios pausados até {when.strftime('%H:%M')}."

    def revise_post(form: dict[str, list[str]]) -> str | None:
        notice = revise_manual(
            board_store,
            queue_day(),
            _int_field(form, "id"),
            form,
            cards_dir,
            resolve_urls=resolve_urls,
        )
        holder["notice"] = notice
        return notice

    from promo_livros.blurb import BlurbCache, OpenAIAuthError, OpenAIBlurb
    from promo_livros.book_match import TitleIndex
    from promo_livros.catalog import (
        CatalogError,
        CatalogStore,
        cached_cover,
        cached_ml_cover,
        catalog_kind,
        capture_clock,
        cover_url,
        file_stamp,
        latest_csv,
        load_csv_file,
        mercado_livre_csv,
        parse_csv,
        publish_selection,
        shopee_csv,
        magalu_csv,
        split_store_posts,
        fill_blurbs,
    )
    from promo_livros.dashboard_curation import render_curation
    from promo_livros.formatter import format_brl
    from promo_livros.ml_links import (
        DEFAULT_TAG,
        apply_ml_links,
        is_ml_url,
        session_from_export,
        session_ready,
        thumbnail_url,
    )

    catalog = CatalogStore(config.sqlite_path)
    from promo_livros.fila_aplicar import MemoriaPrevia

    previas = MemoriaPrevia()
    fila_jobs: dict = {}
    catalog_folder = Path("CSV Atualizado")
    cover_cache = Path("data") / "covers"
    board_store.put_setting("curation", "manual")

    def _load_quiet(loader, path: Path) -> str | None:
        try:
            count = loader(parse_csv(load_csv_file(path)), path.name)
        except (CatalogError, OSError) as exc:
            return str(exc)
        return f"Importei {path.name}: {count} livros."

    def _sync_catalogs() -> list[str]:
        now = datetime.now(zone(config.schedule.timezone))
        day = service_day(now, config.schedule.timezone)
        notes = []
        cleared = catalog.begin_day(day)
        if cleared:
            notes.append(f"As {cleared} marcações de ontem saíram.")
        found = latest_csv(catalog_folder)
        mercado = mercado_livre_csv(catalog_folder)
        notes.extend(_reload_catalog(found, catalog.replace, "source_stamp", lambda: len(catalog.picked())))
        notes.extend(
            _reload_catalog(mercado, catalog.replace_ml, "ml_source_stamp", lambda: _second_marks("ml"))
        )
        notes.extend(
            _reload_catalog(
                shopee_csv(catalog_folder), catalog.replace_shopee, "shopee_source_stamp", lambda: _second_marks("shopee")
            )
        )
        notes.extend(
            _reload_catalog(
                magalu_csv(catalog_folder), catalog.replace_magalu, "magalu_source_stamp", lambda: _second_marks("magalu")
            )
        )
        _tag_kids(found, "amazon", "kids_stamp_v3")
        _tag_kids(mercado, "ml", "ml_kids_stamp_v3")
        return notes

    def _second_marks(store: str) -> int:
        return sum(1 for book in catalog.ml_picked() if book.store == store)

    def _tag_kids(path: Path | None, kind: str, stamp_key: str) -> None:
        if path is None:
            return
        stamp = file_stamp(path)
        if not stamp or stamp == catalog.stored_stamp(stamp_key):
            return
        try:
            catalog.annotate_kids(parse_csv(load_csv_file(path)), kind)
        except (CatalogError, OSError):
            return
        catalog.save_stamp(stamp_key, stamp)

    def _reload_catalog(path: Path | None, loader, stamp_key: str, current_marks) -> list[str]:
        if path is None:
            return []
        stamp = file_stamp(path)
        if not stamp or stamp == catalog.stored_stamp(stamp_key):
            return []
        marked = current_marks()
        note = _load_quiet(loader, path)
        if note is None or not note.startswith("Importei "):
            return [note] if note else []
        catalog.save_stamp(stamp_key, stamp)
        if marked:
            note = f"{note} As {marked} marcações saíram."
        return [note]

    def _loaded_note(prefix: str, count: int, marked: int) -> str:
        note = f"{prefix}: {count} livros."
        if marked:
            note = f"{note} As {marked} marcações saíram."
        return note

    def _import_folder_file(path: Path, loader, stamp_key: str, current_marks) -> str:
        marked = current_marks()
        note = _load_quiet(loader, path) or ""
        if not note.startswith("Importei "):
            return note
        catalog.save_stamp(stamp_key, file_stamp(path))
        if marked:
            note = f"{note} As {marked} marcações saíram."
        return note

    def curation_page(loja: str = "amazon") -> str:
        notice = holder.get("curation_notice")
        holder["curation_notice"] = None
        loaded = _sync_catalogs()
        if loaded:
            notice = " ".join(part for part in [notice, *loaded] if part)
        found = latest_csv(catalog_folder)
        mercado = mercado_livre_csv(catalog_folder)
        shopee_file = shopee_csv(catalog_folder)
        magalu_file = magalu_csv(catalog_folder)
        from promo_livros.fila import horarios_livres
        from promo_livros.fila_aplicar import previa

        now = datetime.now(zone(config.schedule.timezone))
        schedule = board_store.send_schedule()
        agora = now.strftime("%H:%M")
        clocks = horarios_livres(schedule.start, schedule.end, schedule.post_interval_minutes, agora)
        ordem = board_store.setting("curation_order") or "mine"
        store = {"mercadolivre": "ml", "shopee": "shopee", "magalu": "magalu", "magazineluiza": "magalu"}.get(
            loja, "amazon"
        )
        amazon_books = catalog.books()
        second_books = catalog.ml_books()
        ml_books = [book for book in second_books if book.store == "ml"]
        shopee_books = [book for book in second_books if book.store == "shopee"]
        magalu_books = [book for book in second_books if book.store == "magalu"]
        books = {"ml": ml_books, "shopee": shopee_books, "magalu": magalu_books}.get(store, amazon_books)
        index = TitleIndex(amazon_books, second_books)
        store_names = {"ml": "no Mercado Livre", "shopee": "na Shopee", "magalu": "na Magazine Luiza"}
        peers = {}
        covers = {}
        for book in books:
            peer = index.ml_for(book) if store == "amazon" else index.amazon_for(book)
            if peer is None:
                continue
            price = f" · {format_brl(peer.price_cents)}" if peer.price_cents is not None else ""
            where = store_names.get(peer.store, "na Amazon")
            peers[book.asin] = f"Existe {where}{price}"
            if store == "ml":
                covers[book.asin] = cover_url(peer.asin)
        active_file = {"ml": mercado, "shopee": shopee_file, "magalu": magalu_file}.get(store, found)
        sources = {"ml": catalog.ml_source_name, "shopee": catalog.shopee_source_name, "magalu": catalog.magalu_source_name}
        return render_curation(
            books,
            source=sources.get(store, catalog.source_name)(),
            folder_file=active_file.name if active_file else "",
            captured=capture_clock(active_file, config.schedule.timezone) if active_file else "",
            notice=notice if isinstance(notice, str) else None,
            clocks=clocks,
            interval=schedule.post_interval_minutes,
            store=store,
            peers=peers,
            covers=covers,
            marked=catalog.picked_total(),
            photos_ready=session_ready(board_store.setting("ml_cookies") or ""),
            amazon_marked=len(catalog.picked()),
            ml_marked=len(catalog.ml_picked()),
            plan=previa(catalog, board_store, current_day(), agora, ordem, previas),
            amazon_books=amazon_books,
            ml_books=ml_books,
            shopee_books=shopee_books,
            magalu_books=magalu_books,
            reviews=catalog.reviews(),
            ml_lows={
                **catalog.price_lows("ml", {book.asin: book.price_cents for book in ml_books}),
                **catalog.price_lows("shopee", {book.asin: book.price_cents for book in shopee_books}),
                **catalog.price_lows("magalu", {book.asin: book.price_cents for book in magalu_books}),
            },
            shopee_file=shopee_file.name if shopee_file else "",
            shopee_captured=capture_clock(shopee_file, config.schedule.timezone) if shopee_file else "",
            magalu_file=magalu_file.name if magalu_file else "",
            magalu_captured=capture_clock(magalu_file, config.schedule.timezone) if magalu_file else "",
            agora=agora,
            inicio=schedule.start,
            fim=schedule.end,
            ordem=ordem,
            amazon_file=found.name if found else "",
            ml_file=mercado.name if mercado else "",
            amazon_captured=capture_clock(found, config.schedule.timezone) if found else "",
            ml_captured=capture_clock(mercado, config.schedule.timezone) if mercado else "",
            extension_token=extension_token(),
        )

    def _pick_plan(clocks: list[str] | None = None) -> list[dict]:
        from promo_livros.fila import horarios_livres
        from promo_livros.pick_plan import plan_rows

        if clocks is None:
            now = datetime.now(zone(config.schedule.timezone))
            schedule = board_store.send_schedule()
            clocks = horarios_livres(
                schedule.start, schedule.end, schedule.post_interval_minutes, now.strftime("%H:%M")
            )
        amazon, mercado = catalog.queue_for(current_day())
        return plan_rows(amazon, mercado, clocks)

    def import_catalog_text(text: str) -> str:
        rows = parse_csv(text)
        kind = catalog_kind(rows)
        if kind == "ml":
            marked = _second_marks("ml")
            count = catalog.replace_ml(rows, "arquivo do computador")
            holder["curation_notice"] = _loaded_note("CSV do Mercado Livre carregado", count, marked)
        elif kind == "shopee":
            marked = _second_marks("shopee")
            count = catalog.replace_shopee(rows, "arquivo do computador")
            holder["curation_notice"] = _loaded_note("CSV da Shopee carregado", count, marked)
        elif kind == "magalu":
            marked = _second_marks("magalu")
            count = catalog.replace_magalu(rows, "arquivo do computador")
            holder["curation_notice"] = _loaded_note("CSV da Magazine Luiza carregado", count, marked)
        else:
            marked = len(catalog.picked())
            count = catalog.replace(rows, "arquivo do computador")
            holder["curation_notice"] = _loaded_note("CSV carregado", count, marked)
        return str(holder["curation_notice"])

    def import_catalog_folder() -> str:
        notes = []
        found = latest_csv(catalog_folder)
        mercado = mercado_livre_csv(catalog_folder)
        shopee = shopee_csv(catalog_folder)
        magalu = magalu_csv(catalog_folder)
        if found is None and mercado is None and shopee is None and magalu is None:
            holder["curation_notice"] = "Não achei os CSVs na pasta CSV Atualizado."
            return str(holder["curation_notice"])
        if found is not None:
            notes.append(_import_folder_file(found, catalog.replace, "source_stamp", lambda: len(catalog.picked())))
        if mercado is not None:
            notes.append(
                _import_folder_file(mercado, catalog.replace_ml, "ml_source_stamp", lambda: _second_marks("ml"))
            )
        if shopee is not None:
            notes.append(
                _import_folder_file(shopee, catalog.replace_shopee, "shopee_source_stamp", lambda: _second_marks("shopee"))
            )
        if magalu is not None:
            notes.append(
                _import_folder_file(magalu, catalog.replace_magalu, "magalu_source_stamp", lambda: _second_marks("magalu"))
            )
        holder["curation_notice"] = " ".join(note for note in notes if note)
        return str(holder["curation_notice"])

    def import_fila_csv(text: str) -> dict:
        from promo_livros.fila_csv import ImportacaoFila, previa_do_csv

        now = datetime.now(zone(config.schedule.timezone))
        schedule = board_store.send_schedule()
        payload = previa_do_csv(
            catalog,
            board_store,
            current_day(),
            now.strftime("%H:%M"),
            schedule.end,
            text,
            previas,
        )
        job = ImportacaoFila(payload)
        fila_jobs[job.id] = job
        if len(fila_jobs) > 4:
            for key in list(fila_jobs)[:-4]:
                del fila_jobs[key]
        return job.visao()

    def import_fila_passo(job_id: str) -> dict:
        from promo_livros.catalog import publish_selection
        from promo_livros.fila_csv import avancar, livros_da_previa
        from promo_livros.ml_links import session_from_export, thumbnail_url

        job = fila_jobs.get(job_id or "")
        if job is None:
            raise CatalogError("Essa importação não está mais aqui. Envie o arquivo de novo.")

        def gravar(atual) -> str:
            finais = {
                book.get("url_chave") or book.get("url") or "": book.get("url_final") or book.get("url_chave") or book.get("url") or ""
                for book in atual.livros.values()
            }

            def describe(title: str, author: str = "") -> str:
                for book in atual.livros.values():
                    if book["title"] == title:
                        return book.get("blurb") or ""
                return ""

            def cached(urls: list[str]) -> list[str]:
                return [finais.get(url, url) for url in urls]

            return publish_selection(
                catalog,
                board_store,
                current_day(),
                "00:00",
                cards_dir,
                slots_fixos=atual.slots_ids,
                livros_extra=livros_da_previa({"livros": list(atual.livros.values())}),
                resolve_urls=cached,
                resolve_ml=cached,
                resolve_shopee=cached,
                thumbnail=lambda item: thumbnail_url(
                    item,
                    cookie=session_from_export(board_store.setting("ml_cookies") or "")[0],
                ),
                describe=describe,
            )

        return avancar(
            job,
            resolve_amazon=resolve_urls,
            resolve_ml=resolve_ml_estrito,
            resolve_shopee=resolve_shopee_estrito,
            resolve_magalu=resolve_magalu_estrito,
            describe=book_line,
            gravar=gravar,
        )

    def import_fila_resolver(job_id: str) -> dict:
        from promo_livros.fila_csv import resolver_links

        job = fila_jobs.get(job_id or "")
        if job is None:
            raise CatalogError("Essa importação não está mais aqui. Envie o arquivo de novo.")
        return resolver_links(
            job,
            resolve_amazon=resolve_urls,
            resolve_ml=resolve_ml_estrito,
            resolve_shopee=resolve_shopee_estrito,
            resolve_magalu=resolve_magalu_estrito,
        )

    def resolve_ml_estrito(urls: list[str]) -> list[str]:
        from promo_livros.ml_links import links_de_afiliado

        export = board_store.setting("ml_cookies") or ""
        tag = board_store.setting("ml_tag") or DEFAULT_TAG
        return links_de_afiliado(urls, export, tag)

    def resolve_shopee_estrito(urls: list[str]) -> list[str]:
        from promo_livros.shopee_links import links_de_afiliado as links_shopee

        return links_shopee(
            urls,
            config.shopee_app_id,
            config.shopee_secret,
            config.shopee_sub_id,
        )

    def resolve_magalu_estrito(urls: list[str]) -> list[str]:
        from promo_livros.aqui_links import AquiLinkError, create_short_link
        from promo_livros.fila_csv import LinkQuebrado
        from promo_livros.magalu_links import convert_magalu

        if not config.magalu_promoter_id or not config.magalu_partner_id:
            raise LinkQuebrado("Faltam credenciais da Magazine Luiza.")
        if not config.aqui_api_key:
            raise LinkQuebrado("Falta a chave da API do Aqui.")
        out: list[str] = []
        for url in urls:
            converted = convert_magalu(
                url,
                promoter_id=config.magalu_promoter_id,
                partner_id=config.magalu_partner_id,
            )
            if not converted.ok or not converted.link_convertido:
                texto = " ".join((converted.erro or "").split())
                raise LinkQuebrado(
                    texto[:180] or "A Magazine Luiza não gerou o link de afiliado."
                )
            try:
                short = create_short_link(
                    converted.link_convertido,
                    api_key=config.aqui_api_key,
                    base_url=config.aqui_base_url,
                )
            except AquiLinkError as exc:
                texto = " ".join(str(exc).split())
                raise LinkQuebrado(texto[:180] or "O Aqui não encurtou o link.") from exc
            out.append(short)
        return out

    def toggle_pick(asin: str, picked: bool, loja: str = "amazon") -> dict:
        day = current_day()
        if loja in {"ml", "shopee", "magalu"}:
            total = catalog.set_ml_picked(asin, picked, day)
        else:
            total = catalog.set_picked(asin, picked, day)
        return {"picked": total, "plan": _pick_plan()}

    def move_pick(asin: str, loja: str, step: int) -> dict:
        catalog.move_pick(asin, loja if loja in {"ml", "shopee", "magalu"} else "amazon", step)
        return {"picked": catalog.picked_total(), "plan": _pick_plan()}

    def resolve_ml(urls: list[str]) -> list[str]:
        export = board_store.setting("ml_cookies") or ""
        tag = board_store.setting("ml_tag") or DEFAULT_TAG
        return apply_ml_links(urls, export, tag)

    def apply_picks(previa_id: str = "") -> str:
        from promo_livros.fila_aplicar import aplicar

        if not previa_id:
            holder["curation_notice"] = "Revise a fila antes de aplicar."
            return ""
        _sync_catalogs()
        try:
            notice = aplicar(
                catalog,
                board_store,
                current_day(),
                previa_id,
                previas,
                cards_dir,
                resolve_urls=resolve_urls,
                resolve_ml=resolve_ml,
                thumbnail=lambda item: thumbnail_url(
                    item,
                    cookie=session_from_export(board_store.setting("ml_cookies") or "")[0],
                ),
                describe=book_line,
            )
        except CatalogError as exc:
            holder["curation_notice"] = str(exc)
            return ""
        holder["notice"] = notice
        return notice

    def extension_token() -> str:
        from promo_livros.extensao import token_da_extensao

        return token_da_extensao(board_store)

    def extension_call(method: str, path: str, query: dict, body: dict, authorization: str) -> tuple[int, dict]:
        from promo_livros.extensao import atender

        now = datetime.now(zone(config.schedule.timezone))
        return atender(
            method,
            path,
            query,
            body,
            authorization,
            catalog=catalog,
            board=board_store,
            day=current_day(),
            agora=now.strftime("%H:%M"),
            memoria=previas,
            cards_dir=cards_dir,
            resolve_urls=resolve_urls,
            resolve_ml=resolve_ml,
            thumbnail=lambda item: thumbnail_url(
                item,
                cookie=session_from_export(board_store.setting("ml_cookies") or "")[0],
            ),
            describe=book_line,
        )

    def preview_picks(ordem: str = "") -> dict:
        from promo_livros.fila_aplicar import previa

        now = datetime.now(zone(config.schedule.timezone))
        chosen = ordem if ordem in {"mine", "desc", "mix"} else (board_store.setting("curation_order") or "mine")
        return previa(catalog, board_store, current_day(), now.strftime("%H:%M"), chosen, previas)

    def undo_queue() -> str:
        from promo_livros.fila_aplicar import desfazer

        notice = desfazer(catalog, board_store, current_day())
        holder["notice"] = notice
        return notice

    def save_order(ordem: str) -> dict:
        from promo_livros.fila_aplicar import limpar_ordem_manual

        chosen = ordem if ordem in {"mine", "desc", "mix"} else "mine"
        board_store.put_setting("curation_order", chosen)
        limpar_ordem_manual(board_store)
        return preview_picks(chosen)

    def save_draft_order(amazon: list[str], segunda: list[str]) -> dict:
        from promo_livros.catalog import CatalogError
        from promo_livros.fila_aplicar import salvar_ordem_manual

        try:
            salvar_ordem_manual(board_store, current_day(), amazon, segunda)
        except CatalogError as exc:
            return {"error": str(exc)}
        board_store.put_setting("curation_order", "mine")
        return preview_picks("mine")

    def clear_picks() -> dict:
        previous = catalog.clear_marks()
        holder["pick_undo"] = previous
        return {"ok": True, "message": "Marcações tiradas.", "picked": catalog.picked_total()}

    def fill_picks() -> dict:
        from promo_livros.dashboard_curation import discount_percent
        from promo_livros.fila import pode_preencher

        day = current_day()
        enviados = set(board_store.sent_product_clocks(day))
        added: list[tuple[str, str]] = []
        plan = preview_picks(board_store.setting("curation_order") or "mine")
        clocks = plan.get("clocks") or []
        amazon_count = sum(1 for slot in plan["slots"] if slot.get("amazon"))
        ml_count = sum(
            1 for slot in plan["slots"] if slot.get("ml") or slot.get("shopee") or slot.get("magalu")
        )
        gaps = {
            "amazon": max(0, len(clocks) - amazon_count),
            "ml": max(0, len(clocks) - ml_count),
        }
        pools = {
            "amazon": sorted(
                (book for book in catalog.books() if pode_preencher(book, loja="amazon", enviados=enviados)),
                key=lambda book: (-discount_percent(book), book.title.casefold()),
            ),
            "ml": sorted(
                (book for book in catalog.ml_books() if pode_preencher(book, loja="ml", enviados=enviados)),
                key=lambda book: (-discount_percent(book), book.title.casefold()),
            ),
        }
        for store, need in gaps.items():
            for book in pools[store][:need]:
                if store == "ml":
                    catalog.set_ml_picked(book.asin, True, day)
                else:
                    catalog.set_picked(book.asin, True, day)
                added.append((store, book.asin))
        holder["fill_undo"] = added
        fresh = preview_picks(board_store.setting("curation_order") or "mine")
        fresh["added"] = [{"store": store, "asin": asin} for store, asin in added]
        fresh["message"] = f"Marquei {len(added)} livros para completar a fila."
        return fresh

    def undo_clear() -> dict:
        rows = holder.get("pick_undo") or []
        catalog.restore_rows(rows)
        holder["pick_undo"] = []
        return {"ok": True, "message": "Marcações de volta.", "picked": catalog.picked_total()}

    def undo_fill() -> dict:
        added = holder.get("fill_undo") or []
        day = current_day()
        for store, asin in added:
            if store == "ml":
                catalog.set_ml_picked(asin, False, day)
            else:
                catalog.set_picked(asin, False, day)
        holder["fill_undo"] = []
        return {"ok": True, "message": "Desfiz o preenchimento.", "picked": catalog.picked_total()}

    def move_tomorrow(post_id: int) -> None:
        from promo_livros.fila_aplicar import amanha
        from promo_livros.send_schedule import slot_clocks

        post = board_store.post_by_id(post_id)
        if post is None:
            holder["notice"] = "Não encontrei o post."
            return
        tomorrow = amanha(queue_day())
        schedule = board_store.send_schedule()
        used = {item.clock for item in board_store.posts_for(tomorrow)}
        clock = ""
        for candidate in slot_clocks(schedule):
            if candidate not in used:
                clock = candidate
                break
        if not clock:
            holder["notice"] = "Amanhã não tem horário livre."
            return
        if board_store.move_to_day(post_id, tomorrow, clock):
            holder["notice"] = f"O post foi para amanhã às {clock}."
        else:
            holder["notice"] = "Só dá para mover um post que ainda está na fila."

    def catalog_cover(asin: str) -> bytes:
        if asin.startswith("MLB"):
            cookie, _csrf = session_from_export(board_store.setting("ml_cookies") or "")
            return cached_ml_cover(cover_cache, asin, cookie=cookie, image_url=catalog.ml_image(asin))
        return cached_cover(cover_cache, asin)

    def settings_page() -> str:
        from promo_livros.blurb import research_prompt

        cookies = board_store.setting("ml_cookies") or ""
        tag = board_store.setting("ml_tag") or DEFAULT_TAG
        prompt = board_store.setting("resenha_prompt") or research_prompt()
        notice = holder.get("settings_notice")
        holder["settings_notice"] = None
        saved = bool(holder.pop("settings_saved", False))
        draft = holder.pop("settings_draft", None)
        titulo = ""
        autor = ""
        resultado = ""
        if isinstance(draft, dict):
            cookies = str(draft.get("cookies") or cookies)
            tag = str(draft.get("tag") or tag)
            prompt = str(draft.get("prompt") or prompt)
            titulo = str(draft.get("titulo") or "")
            autor = str(draft.get("autor") or "")
            resultado = str(draft.get("resultado") or "")
        return render_settings(
            cookies,
            tag,
            saved=saved,
            ready=session_ready(cookies),
            notice=notice if isinstance(notice, str) else None,
            prompt=prompt,
            titulo=titulo,
            autor=autor,
            resultado=resultado,
        )

    def save_settings(form: dict[str, list[str]]) -> None:
        from promo_livros.blurb import research_prompt

        tag = _field(form, "tag") or DEFAULT_TAG
        prompt = _field(form, "prompt").strip() or research_prompt()
        titulo = _field(form, "titulo")
        autor = _field(form, "autor")
        if len(prompt) > 4000:
            holder["settings_notice"] = "O prompt passa de 4000 caracteres."
            holder["settings_draft"] = {
                "cookies": _field(form, "cookies"),
                "tag": tag,
                "prompt": prompt[:4000],
                "titulo": titulo,
                "autor": autor,
            }
            return
        if _field(form, "acao") == "testar":
            holder["settings_draft"] = {
                "cookies": _field(form, "cookies"),
                "tag": tag,
                "prompt": prompt,
                "titulo": titulo,
                "autor": autor,
                "resultado": _test_prompt(prompt, titulo, autor),
            }
            return
        if re.fullmatch(r"[A-Za-z0-9_-]{3,40}", tag) is None:
            holder["settings_notice"] = "A tag só pode ter letras, números, _ e hífen."
            holder["settings_draft"] = {
                "cookies": _field(form, "cookies"),
                "tag": tag,
                "prompt": prompt,
                "titulo": titulo,
                "autor": autor,
            }
            return
        board_store.put_setting("ml_cookies", _field(form, "cookies"))
        board_store.put_setting("ml_tag", tag)
        board_store.put_setting("resenha_prompt", prompt)
        holder["settings_saved"] = True
        _convert_queued_links()

    def _test_prompt(prompt: str, title: str, author: str) -> str:
        name = " ".join(title.split())
        if not name:
            return "Escreva o título do livro para testar."
        if review_writer is None:
            return "A chave da OpenAI não está configurada."
        try:
            line = review_writer.research(title=name, author=author.strip(), prompt=prompt) or ""
        except OpenAIAuthError:
            return "A chave da OpenAI foi recusada."
        except Exception:
            logging.getLogger("promo_livros").warning("O teste do prompt falhou.", exc_info=True)
            return "Não consegui gerar a resenha."
        return line or "A resenha veio vazia."

    def _convert_queued_links() -> None:
        export = board_store.setting("ml_cookies") or ""
        tag = board_store.setting("ml_tag") or DEFAULT_TAG
        if not session_ready(export):
            return
        for post in board_store.unsent_posts():
            urls = [book.url for book in post.books]
            if not any(is_ml_url(url) for url in urls):
                continue
            converted = apply_ml_links(urls, export, tag)
            if converted != urls:
                board_store.replace_urls_if_unsent(post.id, converted)

    def save_interval(raw: str) -> dict:
        from promo_livros.send_schedule import parse_schedule, repack_clocks

        current = board_store.send_schedule()
        parsed = parse_schedule(current.start, current.end, raw, str(current.group_gap_seconds))
        board_store.save_send_schedule(parsed)
        now = datetime.now(zone(config.schedule.timezone))
        clocks, _late = repack_clocks(parsed, now.strftime("%H:%M"), 60)
        return {"clocks": clocks, "plan": _pick_plan(clocks)}

    def card_file(post_id: int) -> Path | None:
        raw = board_store.image_path_for(post_id)
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        resolved = path.resolve()
        cards = (Path.cwd() / cards_dir).resolve()
        if resolved.parent != cards or not resolved.is_file():
            return None
        return resolved

    review_cache = BlurbCache(Path("data") / "blurb_cache.json")
    review_writer = (
        OpenAIBlurb(config.openai_api_key, config.openai_model, config.openai_max_chars)
        if config.openai_api_key
        else None
    )
    reviews_stopped = {"value": False}
    review_lock = threading.Lock()

    def book_line(title: str, author: str = "") -> str:
        if review_writer is None or reviews_stopped["value"]:
            return ""
        with review_lock:
            if reviews_stopped["value"]:
                return ""
            cached = review_cache.get(title)
            if cached:
                return cached
            try:
                prompt = board_store.setting("resenha_prompt") or ""
                line = review_writer.research(title=title, author=author, prompt=prompt) or ""
            except OpenAIAuthError:
                reviews_stopped["value"] = True
                logging.getLogger("promo_livros").warning(
                    "A chave da OpenAI foi recusada. Os posts seguem sem resenha."
                )
                return ""
            if line:
                review_cache.put(title, line)
            return line

    def _fill_reviews() -> None:
        try:
            filled = fill_blurbs(board_store, book_line)
        except Exception:
            logging.getLogger("promo_livros").warning("Não preenchi as resenhas da fila.", exc_info=True)
            return
        if filled:
            logging.getLogger("promo_livros").info("Completei a resenha de %s posts.", filled)

    opened = board_store.close_past_days(current_day())
    if opened:
        holder["notice"] = f"A fila de ontem saiu ({opened} posts). Ela vale só para a data e a hora."
    catalog.migrate_pick_states(set(board_store.sent_product_clocks(current_day())), current_day())
    from promo_livros.poll_panel import poll_callbacks
    from promo_livros.polls import PollStore

    polls = poll_callbacks(config, PollStore(config.sqlite_path))
    from promo_livros.campaign_panel import campaign_callbacks
    from promo_livros.campaign_store import CampaignStore

    campaign_panel = campaign_callbacks(
        config,
        board_store,
        CampaignStore(config.sqlite_path),
        root=PROJECT_ROOT,
        current_day=current_day,
        now=lambda: datetime.now(zone(config.schedule.timezone)),
    )

    def choose_invite(form: dict[str, list[str]]) -> str:
        notice = campaign_panel["choose"](form)
        holder["notice"] = notice
        return notice

    campaign_routes: CampaignCallbacks = {**campaign_panel, "choose": choose_invite}
    started = _sync_catalogs()
    if started:
        holder["curation_notice"] = " ".join(started)
    split_store_posts(catalog, board_store)
    threading.Thread(target=_convert_queued_links, name="links-ml", daemon=True).start()
    if review_writer is not None:
        threading.Thread(target=_fill_reviews, name="resenhas", daemon=True).start()
    else:
        logging.getLogger("promo_livros").warning("OPENAI_API_KEY está vazia. Os posts saem sem resenha.")

    return DashboardApp(
        username,
        password,
        sessions,
        today,
        whatsapp,
        qr_png,
        group_form,
        save,
        board=board,
        sent=sent,
        move_post=move_post,
        cancel_post=cancel_post,
        add_post=add_post,
        read_link=read_link,
        card_file=card_file,
        sending=board_store.sending_enabled,
        set_sending=board_store.set_sending,
        pair=pair,
        schedule_now=board_store.send_schedule,
        save_schedule=save_rules,
        repack_remaining=repack_remaining,
        reorder_posts=reorder_posts,
        queue_action=queue_action,
        swap_book=swap_book,
        save_draft_order=save_draft_order,
        rush_post=rush_post,
        skip_post=skip_post,
        duplicate_post=duplicate_post,
        restore_post=restore_post,
        apply_price=apply_price,
        pause_for=pause_for,
        revise_post=revise_post,
        kick_check=kick_check,
        clear_queue=clear_queue,
        signatures_text=lambda: board_store.setting("signatures") or "",
        save_signatures=save_signatures,
        settings_page=settings_page,
        save_settings=save_settings,
        curation_page=curation_page,
        import_catalog_text=import_catalog_text,
        import_catalog_folder=import_catalog_folder,
        import_fila_csv=import_fila_csv,
        import_fila_passo=import_fila_passo,
        import_fila_resolver=import_fila_resolver,
        toggle_pick=toggle_pick,
        move_pick=move_pick,
        apply_picks=apply_picks,
        preview_picks=preview_picks,
        undo_queue=undo_queue,
        fill_picks=fill_picks,
        clear_picks=clear_picks,
        undo_clear=undo_clear,
        undo_fill=undo_fill,
        save_order=save_order,
        move_tomorrow=move_tomorrow,
        catalog_cover=catalog_cover,
        save_interval=save_interval,
        extension_call=extension_call,
        extension_token=extension_token,
        polls_page=polls["page"],
        poll_detail=polls["detail"],
        poll_csv=polls["csv"],
        poll_save=polls["save"],
        poll_action=polls["action"],
        poll_webhook=polls["webhook"],
        campaigns=campaign_routes,
    )


if __name__ == "__main__":
    main()
