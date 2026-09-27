from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from promo_livros.config import load_config
from promo_livros.dashboard_auth import SessionStore
from promo_livros.dashboard_pages import login_page, render_groups, render_today, render_whatsapp
from promo_livros.day_view import DayView
from promo_livros.groups_file import GroupChoice, GroupsFileError, group_choices, selected_groups, write_groups
from promo_livros.models import ConfigError

HOST = "127.0.0.1"
PORT = 8787
COOKIE = "promo_livros_session"


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


class DashboardHandler(BaseHTTPRequestHandler):
    app: DashboardApp

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/whatsapp/qr":
            self._qr()
            return
        if not self._logged_in():
            self._html(login_page(failed=False))
            return
        if path == "/whatsapp":
            state, message = self.app.whatsapp()
            self._html(render_whatsapp(state=state, message=message))
            return
        if path == "/grupos":
            choices, connected, notice = self.app.group_form()
            self._html(render_groups(choices, connected=connected, notice=notice))
            return
        error, view = self.app.today()
        day = view.day if view is not None else ""
        self._html(render_today(day=day, view=view, error=error))

    def do_POST(self) -> None:
        if not _same_origin(self):
            self.send_error(403)
            return
        path = urlparse(self.path).path
        form = _form(self)
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
        if path == "/logout":
            self.app.sessions.forget(self._token())
            self._redirect("/", None)
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

    def _logged_in(self) -> bool:
        return self.app.sessions.valid(self._token())

    def _token(self) -> str | None:
        header = self.headers.get("Cookie", "")
        for part in header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and value:
                return value
        return None

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
        if token:
            self.send_header("Set-Cookie", f"{COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/")
        else:
            self.send_header("Set-Cookie", f"{COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.end_headers()


def _same_origin(handler: BaseHTTPRequestHandler) -> bool:
    origin = handler.headers.get("Origin")
    if not origin:
        return True
    return urlparse(origin).netloc == handler.headers.get("Host", "")


def _form(handler: BaseHTTPRequestHandler) -> dict[str, list[str]]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length).decode("utf-8", errors="replace")
    return parse_qs(raw, keep_blank_values=False)


def _field(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name, [])
    return values[0] if values else ""


def serve(app: DashboardApp) -> None:
    DashboardHandler.app = app
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
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


def build_app(config, username: str, password: str) -> DashboardApp:
    from datetime import datetime

    from promo_livros.day_view import build_day_view, captions_for, load_day_rows
    from promo_livros.groups_file import group_choices
    from promo_livros.models import WhatsAppGroup
    from promo_livros.schedule_plan import service_day, zone
    from promo_livros.storage import DayReadError
    from promo_livros.waha import WahaClient, WahaError

    sessions = SessionStore()
    holder = {"groups": config.whatsapp_groups, "enabled": config.whatsapp_enabled}

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
        groups = selected_groups(posted_ids, choices)
        write_groups(Path("config.yaml"), groups, enabled=holder["enabled"])
        holder["groups"] = tuple(WhatsAppGroup(name, chat_id) for name, chat_id in groups)

    return DashboardApp(username, password, sessions, today, whatsapp, qr_png, group_form, save)


if __name__ == "__main__":
    main()
