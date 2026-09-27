import unittest

from promo_livros.dashboard_pages import login_page, render_groups, render_today, render_whatsapp
from promo_livros.day_view import BookLine, DayView, GroupLine
from promo_livros.groups_file import GroupChoice


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
        self.assertIn('/whatsapp/qr', qr)
        self.assertNotIn("/whatsapp/qr", down)
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


if __name__ == "__main__":
    unittest.main()
