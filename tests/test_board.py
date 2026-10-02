import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.post_card import render_card
from promo_livros.post_copy import blurb_for, product_coupon, render_caption


class CopyTests(unittest.TestCase):
    def test_rejects_a_synopsis_about_another_book(self) -> None:
        text = "Os fãs de Junji Ito em Fragmentos do Horror pediram mais."
        self.assertEqual(blurb_for("A Menina do Outro Lado", text), "")

    def test_keeps_the_first_long_sentence_of_this_book(self) -> None:
        text = (
            "Caixa rígida com coleção com os sete livros em capa dura, da mágica série Harry Potter. "
            "A vida segue."
        )
        self.assertIn("Harry Potter", blurb_for("Box Harry Potter", text))

    def test_ignores_the_first_purchase_banner(self) -> None:
        self.assertIsNone(product_coupon(["cupom 20% : 20LEITURA. Válido na sua primeira compra"]))

    def test_caption_uses_emojis_discount_and_a_twelve_word_subject(self) -> None:
        caption = render_caption(
            [
                {
                    "title": "Gildo",
                    "blurb": "Um livro sobre o Gildo.",
                    "price_cents": 3479,
                    "list_price_cents": 6490,
                    "discount_pct": 46.4,
                    "lowest_label": "Menor preço em 120 dias.",
                    "coupon": "Cupom: GILDO10",
                    "url": "https://www.amazon.com.br/dp/857412320X?tag=souleitor-20",
                }
            ]
        )
        self.assertEqual(
            caption,
            "\n".join(
                [
                    "📖 *Gildo*",
                    "ℹ️ _Um livro sobre o Gildo._",
                    "💲 R$ 34,79, (46%) menor preço dos últimos 120 dias",
                    "",
                    "Cupom: GILDO10",
                    "",
                    "🔗 https://www.amazon.com.br/dp/857412320X?tag=souleitor-20",
                    "",
                    "ℹ️ Livros com até 60% de desconto: https://link.amazon/B01bzXpmN",
                ]
            ),
        )

    def test_caption_cuts_the_subject_at_twelve_words(self) -> None:
        caption = render_caption(
            [
                {
                    "title": "Gildo",
                    "blurb": "um dois três quatro cinco seis sete oito nove dez onze doze treze",
                    "price_cents": 1990,
                    "list_price_cents": None,
                    "discount_pct": None,
                    "lowest_label": "",
                    "coupon": "",
                    "url": "https://example.com/gildo",
                }
            ]
        )
        self.assertIn("ℹ️ _um dois três quatro cinco seis sete oito nove dez onze doze._", caption)
        self.assertNotIn("treze", caption)
        self.assertIn("💲 R$ 19,90", caption)
        self.assertNotIn("De R$", caption)
        self.assertIn("https://link.amazon/B01bzXpmN", caption)

    def test_each_post_varies_the_signature_and_keeps_the_link(self) -> None:
        from promo_livros.post_copy import sign_line

        first = sign_line(0)
        second = sign_line(1)
        third = sign_line(2)
        self.assertIn("https://link.amazon/B01bzXpmN", first)
        self.assertIn("https://link.amazon/A0g7KCGdE", second)
        self.assertIn("https://link.amazon/B01bzXpmN", third)
        self.assertNotEqual(first, third)
        self.assertNotIn("https://link.amazon/A0g7KCGdE", first)


class BoardTests(unittest.TestCase):
    def test_shift_exchanges_clocks_and_cancel_hides_the_post(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = BoardStore(Path(folder) / "board.sqlite")
            first = _add(store, "08:00", "Um")
            second = _add(store, "08:40", "Dois")
            store.shift("2026-09-28", first, 1)
            posts = store.posts_for("2026-09-28")
            by_title = {post.books[0].title: post.clock for post in posts}
            self.assertEqual(by_title["Um"], "08:40")
            self.assertEqual(by_title["Dois"], "08:00")
            store.cancel("2026-09-28", second)
            self.assertEqual(len(store.posts_for("2026-09-28")), 1)
            store.close()

    def test_reorder_keeps_the_clocks_and_moves_the_books(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = BoardStore(Path(folder) / "board.sqlite")
            first = _add(store, "08:00", "Um")
            second = _add(store, "08:40", "Dois")
            self.assertTrue(store.reorder("2026-09-28", [second, first]))
            by_title = {post.books[0].title: post.clock for post in store.posts_for("2026-09-28")}
            self.assertEqual(by_title["Dois"], "08:00")
            self.assertEqual(by_title["Um"], "08:40")
            store.close()

    def test_rush_is_the_next_post_even_when_another_is_already_due(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = BoardStore(Path(folder) / "board.sqlite")
            _add(store, "10:00", "Cedo")
            late = _add(store, "11:00", "Tarde")
            self.assertTrue(store.rush("2026-09-28", late, "10:30"))
            found = store.next_due_post("2026-09-28", "10:30", "22:00")
            self.assertIsNotNone(found)
            assert found is not None
            self.assertEqual(found.books[0].title, "Tarde")
            store.close()

    def test_skip_leaves_the_queue_and_restore_brings_a_cancel_back(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = BoardStore(Path(folder) / "board.sqlite")
            first = _add(store, "08:00", "Um")
            self.assertTrue(store.skip("2026-09-28", first))
            self.assertEqual(store.posts_for("2026-09-28"), [])
            second = _add(store, "08:40", "Dois")
            store.cancel("2026-09-28", second)
            self.assertTrue(store.restore("2026-09-28", second))
            self.assertEqual(store.posts_for("2026-09-28")[0].books[0].title, "Dois")
            store.close()

    def test_a_new_day_drops_yesterdays_queue_and_keeps_what_already_went_out(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = BoardStore(Path(folder) / "board.sqlite")
            try:
                yesterday = _add_on(store, "2026-09-29", "08:00", "Ontem")
                sent = _add_on(store, "2026-09-29", "09:00", "Já saiu")
                store.mark_sent(sent)
                today = _add_on(store, "2026-09-30", "08:00", "Hoje")
                self.assertEqual(store.close_past_days("2026-09-30"), 1)
                self.assertEqual(store.posts_for("2026-09-29"), [])
                self.assertEqual([post.id for post in store.posts_for("2026-09-30")], [today])
                gone = {post.id: post.status for post in store.day_feed("2026-09-29")}
                self.assertEqual(gone[yesterday], "cancelled")
                self.assertEqual(gone[sent], "sent")
                self.assertEqual(store.close_past_days("2026-09-30"), 0)
                due = store.next_due_post("2026-09-30", "08:00", "22:00")
                self.assertIsNotNone(due)
                assert due is not None
                self.assertEqual(due.books[0].title, "Hoje")
            finally:
                store.close()

    def test_pause_until_blocks_sending_and_then_releases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = BoardStore(Path(folder) / "board.sqlite")
            store.set_sending(True)
            store.pause_until(datetime.now(timezone.utc) + timedelta(minutes=30))
            self.assertFalse(store.sending_enabled())
            store.pause_until(datetime.now(timezone.utc) - timedelta(minutes=1))
            self.assertTrue(store.sending_enabled())
            self.assertIsNone(store.setting("paused_until"))
            store.close()

    def test_card_keeps_three_covers_and_writes_a_jpeg(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            logo = Path(folder) / "logo.png"
            Image.new("RGB", (40, 40), "white").save(logo)
            covers = [Image.new("RGB", (30, 50), color) for color in ("red", "green", "blue")]
            destination = Path(folder) / "card.jpg"
            render_card(covers, destination, logo_path=logo)
            self.assertTrue(destination.is_file())
            with Image.open(destination) as image:
                self.assertEqual(image.format, "JPEG")


def _add(store: BoardStore, clock: str, title: str) -> int:
    return _add_on(store, "2026-09-28", clock, title)


def _add_on(store: BoardStore, day: str, clock: str, title: str) -> int:
    return store.add_post(
        day=day,
        clock=clock,
        caption=title,
        image_path="",
        books=[
            BoardBook(title, "", 1000, None, None, "", "https://www.amazon.com.br/dp/857412320X", "")
        ],
    )


if __name__ == "__main__":
    unittest.main()
