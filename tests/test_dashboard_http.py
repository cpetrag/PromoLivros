import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from promo_livros.dashboard import DashboardApp, DashboardHandler, persist_group_selection
from promo_livros.groups_file import GroupsFileError, GroupChoice
from promo_livros.dashboard_auth import SessionStore
from promo_livros.dashboard_pages import login_page, render_groups, render_today, render_whatsapp
from promo_livros.day_view import BookLine, DayView, GroupLine
class PageTests(unittest.TestCase):
    def test_login_page_has_no_queue(self) -> None:
        html = login_page(failed=True)
        self.assertIn("Entrar", html)
        self.assertNotIn("Black Livros", html)
        self.assertIn("Usuário ou senha incorretos", html)

    def test_today_without_queue_says_so(self) -> None:
        html = render_today(day="2026-09-27", view=None, error=None)
        self.assertIn("A fila de hoje ainda não existe", html)
        self.assertIn('href="/whatsapp"', html)

    def test_today_shows_group_status_and_escapes_title(self) -> None:
        view = DayView(
            day="2026-09-27",
            books=(
                BookLine(
                    clock="20:00",
                    niche_label="Ficção",
                    title="<script>",
                    price_label="R$ 34,90",
                    book_status="pronto",
                    caption="linha",
                    groups=(GroupLine("Black Livros 01", "1@g.us", "enviada"),),
                    reserve=False,
                ),
            ),
        )
        html = render_today(day="2026-09-27", view=view, error=None)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn("enviada", html)

    def test_whatsapp_qr_only_when_requested(self) -> None:
        qr = render_whatsapp(state="qr", message=None)
        down = render_whatsapp(state="down", message="O WAHA não respondeu.")
        offline = render_whatsapp(state="disconnected", message=None)
        online = render_whatsapp(state="connected", message=None)
        self.assertIn("/whatsapp/qr", qr)
        self.assertNotIn("/whatsapp/qr", down)
        self.assertNotIn("/whatsapp/qr", offline)
        self.assertNotIn("/whatsapp/qr", online)
        self.assertIn("Conectado", online)
        self.assertIn("O WAHA não respondeu.", down)

    def test_groups_form_marks_missing_and_hides_save_when_offline(self) -> None:
        choices = [
            GroupChoice("Black Livros 01", "120363430990609445@g.us", True, False),
            GroupChoice("Black Livros 03", "120363412365496470@g.us", True, True),
        ]
        online = render_groups(choices, connected=True, notice=None)
        offline = render_groups(choices, connected=False, notice=None)
        self.assertIn("fora da sessão", online)
        self.assertIn("Salvar", online)
        self.assertIn("Conecte o WhatsApp", offline)
        self.assertNotIn(">Salvar<", offline)


class ServerTests(unittest.TestCase):
    def test_hoje_without_cookie_is_the_login_form(self) -> None:
        body = _get(self.server, "/hoje")
        self.assertIn("Entrar", body)
        self.assertNotIn("Sapiens", body)

    def test_hoje_with_cookie_shows_the_book(self) -> None:
        token = self.app.sessions.login("ana", "certa", "ana", "certa")
        body = _get(self.server, "/hoje", cookie=token)
        self.assertIn("Sapiens", body)
        self.assertNotIn('src="/whatsapp/qr"', body)

    def test_qr_route_without_cookie_is_not_an_image(self) -> None:
        status, content_type, _payload = _get_raw(self.server, "/whatsapp/qr")
        self.assertEqual(status, 200)
        self.assertNotIn("image/png", content_type)

    def test_login_rejects_non_integer_content_length(self) -> None:
        status, _content_type, _payload = _post_raw(
            self.server,
            "/login",
            headers={"Content-Length": "abc"},
        )
        self.assertEqual(status, 400)

    def test_login_rejects_huge_content_length_without_reading_body(self) -> None:
        status, _content_type, _payload = _post_raw(
            self.server,
            "/login",
            headers={"Content-Length": str(65537)},
        )
        self.assertEqual(status, 400)

    def test_get_hoje_works_after_bad_post(self) -> None:
        _post_raw(self.server, "/login", headers={"Content-Length": "abc"})
        body = _get(self.server, "/hoje")
        self.assertIn("Entrar", body)

    def setUp(self) -> None:
        book = BookLine(
            clock="20:00",
            niche_label="Ficção",
            title="Sapiens",
            price_label="R$ 34,90",
            book_status="pronto",
            caption="linha",
            groups=(),
            reserve=False,
        )
        app = DashboardApp(
            username="ana",
            password="certa",
            sessions=SessionStore(),
            today=lambda: (None, DayView(day="2026-09-27", books=(book,))),
            whatsapp=lambda: ("connected", None),
            qr_png=lambda: b"\x89PNG",
            group_form=lambda: ([], True, None),
            save_groups=lambda _ids: None,
        )
        self.app = app
        DashboardHandler.app = app
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class SaveGroupsTests(unittest.TestCase):
    def test_empty_selection_refuses_when_whatsapp_enabled_in_file(self) -> None:
        yaml_text = """whatsapp:
  enabled: true
  gap_seconds: 45
  groups:
    - name: "Black Livros 01"
      id: "120363430990609445@g.us"
website:
  enabled: false
"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.yaml"
            path.write_text(yaml_text, encoding="utf-8")
            original = path.read_bytes()
            choices = [GroupChoice("Black Livros 01", "120363430990609445@g.us", True, False)]
            with self.assertRaises(GroupsFileError) as caught:
                persist_group_selection(path, [], choices)
            self.assertIn("lista de grupos ficou vazia", str(caught.exception))
            self.assertEqual(path.read_bytes(), original)


def _post_raw(
    server: ThreadingHTTPServer,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes = b"",
) -> tuple[int, str, bytes]:
    host, port = server.server_address[:2]
    request_headers = dict(headers or {})
    request = Request(
        f"http://{host}:{port}{path}",
        data=data,
        headers=request_headers,
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, response.headers.get("content-type", ""), response.read()
    except HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read()


def _get(server: ThreadingHTTPServer, path: str, cookie: str | None = None) -> str:
    _status, _content_type, payload = _get_raw(server, path, cookie)
    return payload.decode("utf-8")


def _get_raw(
    server: ThreadingHTTPServer,
    path: str,
    cookie: str | None = None,
) -> tuple[int, str, bytes]:
    host, port = server.server_address[:2]
    headers = {}
    if cookie:
        headers["Cookie"] = f"promo_livros_session={cookie}"
    request = Request(f"http://{host}:{port}{path}", headers=headers)
    with urlopen(request) as response:
        return response.status, response.headers.get("content-type", ""), response.read()


if __name__ == "__main__":
    unittest.main()