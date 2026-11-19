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

    def test_board_shows_the_invite_card_and_the_campaigns_link(self) -> None:
        from promo_livros.dashboard_pages import render_board
        from promo_livros.send_schedule import default_schedule

        html = render_board(
            "2026-11-03",
            [],
            notice=None,
            sending=True,
            schedule=default_schedule(),
            invites='<section id="convites">Convites aqui</section>',
        )
        self.assertIn("Convites aqui", html)
        self.assertIn('href="/campanhas">Campanhas</a>', html)
        self.assertLess(html.index('id="convites"'), html.index('id="regras"'))
        self.assertIn("#convites .invite", html)

    def test_board_is_the_belt(self) -> None:
        from promo_livros.board_store import FeedPost, FeedSend
        from promo_livros.dashboard_pages import render_board
        from promo_livros.send_schedule import default_schedule

        post = FeedPost(
            id=7,
            clock="20:37",
            status="scheduled",
            title="Demon Slayer <x>",
            price_cents=1990,
            discount_pct=40,
            url="https://link.amazon/B0abc",
            sends=(FeedSend("Black Livros 01", "sent", "20:13"),),
        )
        html = render_board(
            "2026-09-28",
            [post],
            notice=None,
            sending=True,
            schedule=default_schedule(),
            groups=("Black Livros 01",),
        )
        self.assertIn("Promo Livros", html)
        self.assertIn("Programação do dia", html)
        self.assertIn("28 de setembro de 2026", html)
        self.assertIn("Demon Slayer &lt;x&gt;", html)
        self.assertNotIn("Demon Slayer <x>", html)
        self.assertIn("Black Livros 01", html)
        self.assertIn("Pausar envios", html)
        self.assertIn('width="64"', html)
        self.assertIn('height="90"', html)
        self.assertIn('id="lightbox"', html)
        self.assertIn('action="/hoje/manual"', html)
        self.assertIn('action="/hoje/reorganizar"', html)
        self.assertIn('action="/hoje/limpar"', html)
        self.assertIn("Programar post", html)
        self.assertIn('href="/enquetes">Enquetes</a>', html)

    def test_board_grade_row_of_a_campaign_post_has_the_swap_form(self) -> None:
        from promo_livros.board_store import POST_KIND_CAMPAIGN, FeedPost
        from promo_livros.dashboard_pages import render_board
        from promo_livros.send_schedule import default_schedule

        campaign_post = FeedPost(
            11, "11:00", "scheduled", "Entre no grupo", 0, None, "", (),
            caption="Entre no grupo", post_kind=POST_KIND_CAMPAIGN, campaign_id=2, image_id=3, text_id=4,
        )
        book_post = FeedPost(12, "12:00", "scheduled", "Um livro", 1000, None, "https://www.amazon.com.br/dp/B000000001", ())
        form = '<form class="campaign-swap" method="post" action="/hoje/campanha-post"><input name="post_id" value="11"></form>'
        html = render_board(
            "2026-10-03",
            [campaign_post, book_post],
            notice=None,
            sending=True,
            schedule=default_schedule(),
            campaign_forms={11: form},
        )
        row = html[html.index('data-id="11"'):html.index('data-id="12"')]
        self.assertIn('action="/hoje/campanha-post"', row)
        self.assertIn('data-kind="campaign"', row)
        self.assertEqual(html.count('class="campaign-swap"'), 1)

    def test_sent_posts_stay_on_the_sent_tab(self) -> None:
        from promo_livros.board_store import FeedPost
        from promo_livros.dashboard_pages import render_board, render_settings
        from promo_livros.send_schedule import default_schedule

        waiting = FeedPost(1, "16:00", "scheduled", "Ainda na fila", 1000, None, "https://www.amazon.com.br/dp/B000000001", ())
        gone = FeedPost(2, "11:00", "sent", "Já saiu", 1000, None, "https://www.amazon.com.br/dp/B000000002", (), day="2026-10-02")
        html = render_board("2026-10-03", [waiting, gone], notice=None, sending=True, schedule=default_schedule(), arquivo=[gone])
        self.assertIn("Ainda na fila", html)
        self.assertNotIn("Já saiu", html)
        sent = render_board(
            "2026-10-03",
            [waiting, gone],
            notice=None,
            sending=True,
            schedule=default_schedule(),
            aba="enviadas",
            arquivo=[gone],
        )
        self.assertIn("Já saiu", sent)
        self.assertIn("02/10 11:00", sent)
        self.assertNotIn("Últimos 5 dias", sent)
        settings = render_settings("", "tag", saved=False, ready=False, notice=None, prompt="Fale do livro.")
        self.assertIn("Prompt da resenha", settings)
        self.assertIn("Testar resenha", settings)
        self.assertIn("Fale do livro.", settings)

    def test_board_shows_liquid_members(self) -> None:
        from promo_livros.dashboard_pages import render_board
        from promo_livros.membership import GroupMembers, MembershipView
        from promo_livros.send_schedule import default_schedule

        view = MembershipView(
            available=True,
            groups=(GroupMembers(name="Black Livros 01", liquid=53, joined=2, left=1),),
        )
        html = render_board(
            "2026-09-29",
            [],
            notice=None,
            sending=False,
            schedule=default_schedule(),
            members=view,
        )
        self.assertIn("Membros líquidos", html)
        self.assertIn(">53<", html)
        self.assertIn("Entradas do dia", html)
        self.assertIn(">2<", html)
        self.assertIn("Saídas", html)
        self.assertIn("Líquido do dia", html)
        self.assertIn("+1", html)
        self.assertLess(html.index('id="members"'), html.index('id="rows"'))

    def test_a_late_unsent_post_is_marked_as_missed(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from promo_livros.board_store import FeedPost
        from promo_livros.dashboard_pages import render_board
        from promo_livros.send_schedule import default_schedule

        post = FeedPost(
            id=4,
            clock="14:05",
            status="scheduled",
            title="Box Rubem Fonseca",
            price_cents=2899,
            discount_pct=40,
            url="https://www.amazon.com.br/dp/8503012345",
            sends=(),
        )
        html = render_board(
            "2026-09-30",
            [post],
            notice=None,
            sending=True,
            schedule=default_schedule(),
            now=datetime(2026, 9, 30, 14, 30, tzinfo=ZoneInfo("America/Sao_Paulo")),
            whatsapp="disconnected",
        )
        self.assertIn("não saiu · WhatsApp desconectado", html)
        self.assertIn("1 post passou do horário e não saiu.", html)
        self.assertIn("O WhatsApp está desconectado.", html)

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
        self.assertIn("<h2>&lt;script&gt;</h2>", html)
        self.assertNotIn("<h2><script>", html)
        self.assertIn("enviada", html)

    def test_whatsapp_qr_only_when_requested(self) -> None:
        qr = render_whatsapp(state="qr", message=None)
        down = render_whatsapp(state="down", message="O WAHA não respondeu.")
        offline = render_whatsapp(state="disconnected", message=None)
        online = render_whatsapp(state="connected", message=None)
        self.assertIn("/whatsapp/qr", qr)
        self.assertIn('http-equiv="refresh"', qr)
        self.assertNotIn("/whatsapp/qr", down)
        self.assertNotIn("/whatsapp/qr", offline)
        self.assertIn("Gerar QR", offline)
        self.assertNotIn("Gerar QR", online)
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

    def test_logged_in_hoje_sends_the_board_page(self) -> None:
        from promo_livros.send_schedule import default_schedule

        self.app.board = lambda: ("2026-10-02", [], None, False, default_schedule(), (), {})
        token = self.app.sessions.login("ana", "certa", "ana", "certa")
        body = _get(self.server, "/hoje", cookie=token)
        self.assertIn("Programação do dia", body)

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

    def test_poll_webhook_accepts_json_without_login(self) -> None:
        seen: dict[str, object] = {}

        def webhook(body: dict, key: str) -> int:
            seen["body"] = body
            seen["key"] = key
            return 200 if key == "segredo" else 401

        self.app.poll_webhook = webhook
        status, content_type, payload = _post_raw(
            self.server,
            "/whatsapp/webhook",
            data=b'{"event":"poll.vote"}',
            headers={"X-Api-Key": "segredo", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        self.assertNotIn("Entrar", payload.decode("utf-8"))
        self.assertEqual(seen["key"], "segredo")
        denied, _, _ = _post_raw(
            self.server,
            "/whatsapp/webhook",
            data=b"{}",
            headers={"X-Api-Key": "errada"},
        )
        self.assertEqual(denied, 401)

    def test_poll_webhook_accepts_large_waha_events(self) -> None:
        self.app.poll_webhook = lambda _body, _key: 200
        big = b'{"event":"message","payload":{"body":"' + b"x" * 200_000 + b'"}}'
        status, _content_type, _payload = _post_raw(
            self.server,
            "/whatsapp/webhook",
            data=big,
            headers={"X-Api-Key": "segredo", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)

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


class WhatsappQrPageTests(unittest.TestCase):
    def test_whatsapp_page_shows_error_when_qr_fetch_fails(self) -> None:
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

        def failing_qr() -> bytes:
            raise RuntimeError("WAHA down")

        app = DashboardApp(
            username="ana",
            password="certa",
            sessions=SessionStore(),
            today=lambda: (None, DayView(day="2026-09-27", books=(book,))),
            whatsapp=lambda: ("qr", None),
            qr_png=failing_qr,
            group_form=lambda: ([], True, None),
            save_groups=lambda _ids: None,
        )
        DashboardHandler.app = app
        server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            token = app.sessions.login("ana", "certa", "ana", "certa")
            body = _get(server, "/whatsapp", cookie=token)
            self.assertIn("WAHA não devolveu o QR.", body)
            self.assertNotIn("/whatsapp/qr", body)
        finally:
            server.shutdown()
            server.server_close()


class ComposerTests(unittest.TestCase):
    def test_the_composer_has_a_block_per_store_with_a_button_to_read_the_link(self) -> None:
        from promo_livros.dashboard_pages import render_board
        from promo_livros.send_schedule import default_schedule

        html = render_board(
            "2026-09-28",
            [],
            notice=None,
            sending=True,
            schedule=default_schedule(),
        )
        self.assertIn("Primeira oferta", html)
        self.assertIn("Segunda oferta", html)
        self.assertIn('name="url"', html)
        self.assertIn('name="url2"', html)
        self.assertIn('id="field-url-1"', html)
        self.assertIn('id="field-url-2"', html)
        self.assertIn('data-alvo="-1"', html)
        self.assertIn('data-alvo="-2"', html)
        self.assertEqual(html.count(">Puxar dados</button>"), 2)
        self.assertIn("Deixe vazio para o post sair com uma loja só.", html)


class LinkRouteTests(unittest.TestCase):
    def test_the_route_answers_with_the_fields_the_composer_fills(self) -> None:
        import json

        asked = []

        def read_link(url: str) -> dict:
            asked.append(url)
            return {
                "store": "ml",
                "title": "Livro Dom Casmurro",
                "price": "19,00",
                "list_price": "39,00",
                "cover": "https://http2.mlstatic.com/D_NQ_NP_1.jpg",
                "url": url,
            }

        app = DashboardApp(
            username="ana",
            password="certa",
            sessions=SessionStore(),
            today=lambda: (None, None),
            whatsapp=lambda: ("connected", None),
            qr_png=lambda: b"",
            group_form=lambda: ([], True, None),
            save_groups=lambda _ids: None,
            read_link=read_link,
        )
        DashboardHandler.app = app
        server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            token = app.sessions.login("ana", "certa", "ana", "certa")
            body = b"url=https%3A%2F%2Fprodutos.mercadolivre.com.br%2FMLB-1"
            status, content_type, payload = _post_raw(
                server,
                "/hoje/link",
                headers={
                    "Cookie": f"promo_livros_session={token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Content-Length": str(len(body)),
                },
                data=body,
            )
            self.assertEqual(status, 200)
            self.assertIn("application/json", content_type)
            self.assertEqual(json.loads(payload)["title"], "Livro Dom Casmurro")
            self.assertEqual(asked, ["https://produtos.mercadolivre.com.br/MLB-1"])
        finally:
            server.shutdown()
            server.server_close()


class QueueActionRouteTests(unittest.TestCase):
    def test_route_passes_the_action_and_answers_json(self) -> None:
        import json

        asked = []

        def queue_action(acao: str, form: dict[str, list[str]]) -> dict:
            asked.append((acao, form.get("id")))
            return {"ok": True, "message": "1 post mudou de horário."}

        app = DashboardApp(
            username="ana",
            password="certa",
            sessions=SessionStore(),
            today=lambda: (None, None),
            whatsapp=lambda: ("connected", None),
            qr_png=lambda: b"",
            group_form=lambda: ([], True, None),
            save_groups=lambda _ids: None,
            queue_action=queue_action,
        )
        DashboardHandler.app = app
        server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = b"id=7&minutos=20"
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
            }
            _status, _type, payload = _post_raw(server, "/hoje/empurrar", headers=headers, data=body)
            self.assertIn(b"Entrar", payload)
            self.assertEqual(asked, [])
            token = app.sessions.login("ana", "certa", "ana", "certa")
            headers["Cookie"] = f"promo_livros_session={token}"
            status, content_type, payload = _post_raw(server, "/hoje/empurrar", headers=headers, data=body)
            self.assertEqual(status, 200)
            self.assertIn("application/json", content_type)
            self.assertTrue(json.loads(payload)["ok"])
            _post_raw(server, "/hoje/horarios/desfazer", headers={**headers, "Content-Length": "0"}, data=b"")
            self.assertEqual(asked, [("empurrar", ["7"]), ("desfazer", None)])
        finally:
            server.shutdown()
            server.server_close()


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


CAMPAIGN_FORM_PATHS = (
    "/campanhas/config",
    "/campanhas/acao",
    "/campanhas/gerar",
    "/hoje/convite",
    "/hoje/campanha-post",
)


class CampaignRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple] = []

        def upload(campaign_id: int, files: list[bytes]) -> str:
            self.calls.append(("upload", campaign_id, files))
            return f"/campanhas/{campaign_id}"

        def choose(form: dict[str, list[str]]) -> str:
            self.calls.append(("choose", form.get("tipo")))
            return "ok"

        def image(image_id: int) -> bytes | None:
            self.calls.append(("image", image_id))
            return b"\xff\xd8jpeg" if image_id == 5 else None

        def record(name: str, answer: str):
            def callback(form: dict[str, list[str]]) -> str:
                self.calls.append((name, form))
                return answer

            return callback

        campaigns = {
            "page": lambda: "Lista de campanhas",
            "detail": lambda campaign_id: f"Detalhe {campaign_id}" if campaign_id == 3 else None,
            "save_settings": record("save_settings", "/campanhas"),
            "action": record("action", "/campanhas"),
            "upload": upload,
            "image": image,
            "invites": lambda: "",
            "choose": choose,
            "generate": record("generate", "/campanhas/3"),
            "swap_post": record("swap_post", "ok"),
            "notify": lambda message: self.calls.append(("notify", message)),
        }
        self.app = DashboardApp(
            username="ana",
            password="certa",
            sessions=SessionStore(),
            today=lambda: (None, None),
            whatsapp=lambda: ("connected", None),
            qr_png=lambda: b"",
            group_form=lambda: ([], True, None),
            save_groups=lambda _ids: None,
            campaigns=campaigns,
        )
        DashboardHandler.app = self.app
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.token = self.app.sessions.login("ana", "certa", "ana", "certa")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _form_headers(self, body: bytes, *, logged: bool = True) -> dict[str, str]:
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))}
        if logged:
            headers["Cookie"] = f"promo_livros_session={self.token}"
        return headers

    def _multipart(self, *, logged: bool = True) -> tuple[dict[str, str], bytes]:
        boundary = "----b"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="fotos"; filename="a.png"\r\n\r\n'.encode()
            + b"\x89PNG\r\nbytes"
            + f"\r\n--{boundary}--\r\n".encode()
        )
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))}
        if logged:
            headers["Cookie"] = f"promo_livros_session={self.token}"
        return headers, body

    def test_pages_need_login(self) -> None:
        self.assertIn("Entrar", _get(self.server, "/campanhas"))
        self.assertIn("Entrar", _get(self.server, "/campanhas/3"))
        self.assertIn("Entrar", _get(self.server, "/campanhas/foto/5.jpg"))
        self.assertEqual(self.calls, [])
        self.assertIn("Lista de campanhas", _get(self.server, "/campanhas", cookie=self.token))
        self.assertIn("Detalhe 3", _get(self.server, "/campanhas/3", cookie=self.token))

    def test_missing_and_oversized_ids_are_404(self) -> None:
        for path in (
            "/campanhas/4",
            "/campanhas/9999999999999",
            "/campanhas/99999999999999999999999",
            "/campanhas/abc",
            "/campanhas/foto/99999999999999999999999.jpg",
            "/campanhas/foto/abc.jpg",
        ):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                _get_raw(self.server, path, self.token)
            self.assertEqual(caught.exception.code, 404)

    def test_photo_route_serves_jpeg(self) -> None:
        host, port = self.server.server_address[:2]
        request = Request(
            f"http://{host}:{port}/campanhas/foto/5.jpg",
            headers={"Cookie": f"promo_livros_session={self.token}"},
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "image/jpeg")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertTrue(response.headers["Cache-Control"].startswith("private"))
            self.assertEqual(response.read(), b"\xff\xd8jpeg")
        with self.assertRaises(HTTPError):
            _get_raw(self.server, "/campanhas/foto/6.jpg", self.token)

    def test_upload_reads_the_files_and_goes_back_to_the_campaign(self) -> None:
        headers, body = self._multipart()
        status, _type, payload = _post_raw(self.server, "/campanhas/3/fotos", headers=headers, data=body)
        self.assertEqual(status, 200)
        self.assertIn(b"Detalhe 3", payload)
        self.assertEqual(self.calls, [("upload", 3, [b"\x89PNG\r\nbytes"])])

    def test_upload_without_login_does_nothing(self) -> None:
        headers, body = self._multipart(logged=False)
        _status, _type, payload = _post_raw(self.server, "/campanhas/3/fotos", headers=headers, data=body)
        self.assertIn(b"Entrar", payload)
        self.assertEqual(self.calls, [])

    def test_upload_refuses_a_form_that_is_not_multipart(self) -> None:
        body = b"fotos=x"
        _status, _type, payload = _post_raw(self.server, "/campanhas/3/fotos", headers=self._form_headers(body), data=body)
        self.assertIn(b"Detalhe 3", payload)
        self.assertEqual([call[0] for call in self.calls], ["notify"])

    def test_upload_refuses_a_body_above_the_limit_without_reading_it(self) -> None:
        import http.client

        from promo_livros.dashboard import MAX_CAMPAIGN_UPLOAD_BODY

        host, port = self.server.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=5)
        try:
            connection.putrequest("POST", "/campanhas/3/fotos")
            connection.putheader("Cookie", f"promo_livros_session={self.token}")
            connection.putheader("Content-Type", "multipart/form-data; boundary=b")
            connection.putheader("Content-Length", str(MAX_CAMPAIGN_UPLOAD_BODY + 1))
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 303)
            self.assertEqual(response.getheader("Location"), "/campanhas/3")
        finally:
            connection.close()
        self.assertEqual([call[0] for call in self.calls], ["notify"])
        self.assertIn("40 MB", self.calls[0][1])

    def test_upload_without_length_is_refused(self) -> None:
        import http.client

        host, port = self.server.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=5)
        try:
            connection.putrequest("POST", "/campanhas/3/fotos")
            connection.putheader("Cookie", f"promo_livros_session={self.token}")
            connection.putheader("Content-Type", "multipart/form-data; boundary=b")
            connection.endheaders()
            self.assertEqual(connection.getresponse().status, 411)
        finally:
            connection.close()
        self.assertEqual(self.calls, [])

    def test_upload_to_an_oversized_id_is_404(self) -> None:
        headers, body = self._multipart()
        status, _type, _payload = _post_raw(
            self.server, "/campanhas/99999999999999999999/fotos", headers=headers, data=body
        )
        self.assertEqual(status, 404)
        self.assertEqual(self.calls, [])

    def test_form_routes_need_login(self) -> None:
        body = b"acao=apagar&id=3"
        for path in CAMPAIGN_FORM_PATHS:
            with self.subTest(path=path):
                _status, _type, payload = _post_raw(
                    self.server, path, headers=self._form_headers(body, logged=False), data=body
                )
                self.assertIn(b"Entrar", payload)
        self.assertEqual(self.calls, [])

    def test_cross_origin_posts_are_refused(self) -> None:
        headers, body = self._multipart()
        headers["Origin"] = "http://evil.example"
        status, _type, _payload = _post_raw(self.server, "/campanhas/3/fotos", headers=headers, data=body)
        self.assertEqual(status, 403)
        form_body = b"acao=apagar&id=3"
        form_headers = {**self._form_headers(form_body), "Origin": "http://evil.example"}
        for path in CAMPAIGN_FORM_PATHS:
            with self.subTest(path=path):
                status, _type, _payload = _post_raw(self.server, path, headers=form_headers, data=form_body)
                self.assertEqual(status, 403)
        self.assertEqual(self.calls, [])

    def test_settings_and_action_go_through(self) -> None:
        body = b"acao=apagar&id=3"
        _post_raw(self.server, "/campanhas/acao", headers=self._form_headers(body), data=body)
        body = b"fixo=13%3A15&final=10"
        _post_raw(self.server, "/campanhas/config", headers=self._form_headers(body), data=body)
        self.assertEqual(
            self.calls,
            [
                ("action", {"acao": ["apagar"], "id": ["3"]}),
                ("save_settings", {"fixo": ["13:15"], "final": ["10"]}),
            ],
        )

    def test_partial_refresh_carries_the_invite_card(self) -> None:
        import json

        from promo_livros.send_schedule import default_schedule

        self.app.board = lambda: (
            "2026-11-03",
            [],
            None,
            True,
            default_schedule(),
            (),
            {"invites": '<section id="convites">Enviando 1/3</section>'},
        )
        page = _get(self.server, "/hoje", cookie=self.token)
        self.assertIn('<div id="invites"><section id="convites">Enviando 1/3</section></div>', page)
        self.assertIn('"invites"', page.split("/hoje/parcial", 1)[1])
        partial = json.loads(_get(self.server, "/hoje/parcial", cookie=self.token))
        self.assertEqual(partial["invites"], '<section id="convites">Enviando 1/3</section>')

    def test_idle_connections_time_out(self) -> None:
        self.assertEqual(DashboardHandler.timeout, 60)

    def test_choose_invite_from_today(self) -> None:
        self.app.board = None
        body = b"tipo=last&campanha=2"
        _post_raw(self.server, "/hoje/convite", headers=self._form_headers(body), data=body)
        self.assertEqual(self.calls, [("choose", ["last"])])

    def test_generate_texts_redirects_to_the_campaign(self) -> None:
        body = b"id=3&count=5"
        status, _type, payload = _post_raw(self.server, "/campanhas/gerar", headers=self._form_headers(body), data=body)
        self.assertEqual(status, 200)
        self.assertIn(b"Detalhe 3", payload)
        self.assertEqual(self.calls, [("generate", {"id": ["3"], "count": ["5"]})])

    def test_swap_campaign_post_from_today(self) -> None:
        self.app.board = None
        body = b"post_id=9&campaign_id=2&image_id=&text_id="
        _post_raw(self.server, "/hoje/campanha-post", headers=self._form_headers(body), data=body)
        self.assertEqual(len(self.calls), 1)
        name, form = self.calls[0]
        self.assertEqual((name, form["post_id"], form["campaign_id"]), ("swap_post", ["9"], ["2"]))


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