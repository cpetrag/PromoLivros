import tempfile
import unittest
from pathlib import Path

from PIL import Image

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.post_card import extract_covers, render_card
from promo_livros.troca_livro import trocar_livro

DAY = "2026-11-03"
RED, BLUE, GREEN, ORANGE = (200, 30, 30), (30, 60, 200), (20, 150, 60), (240, 120, 20)


def _book(title, product_id, url):
    return BoardBook(
        title=title, blurb=f"Sobre {title}", price_cents=2990, list_price_cents=4990, discount_pct=40.0,
        lowest_label="", url=url, coupon="", product_id=product_id,
    )


AZ1 = _book("Duna", "B0AAAAAAA1", "https://link.amazon/a1")
AZ2 = _book("Sapiens", "B0AAAAAAA2", "https://link.amazon/a2")
SHOPEE = _book("Torto Arado", "123456.7890123", "https://s.shopee.com.br/x")
ML = _book("Tudo é rio", "MLB1234567", "https://meli.la/x")


def _cover(color, size=(196, 280)):
    return Image.new("RGB", size, color)


def _main_color(image):
    return image.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))


def _close(color, expected, tolerance=30):
    return all(abs(a - b) <= tolerance for a, b in zip(color, expected))


class ExtractCoversTests(unittest.TestCase):
    def test_roundtrip_keeps_each_cover_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "1.jpg"
            render_card([_cover(RED), _cover(BLUE, (180, 260))], card)
            covers = extract_covers(card, 2)
            self.assertIsNotNone(covers)
            self.assertTrue(_close(_main_color(covers[0]), RED))
            self.assertTrue(_close(_main_color(covers[1]), BLUE))

    def test_wrong_count_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "1.jpg"
            render_card([_cover(RED)], card)
            self.assertIsNone(extract_covers(card, 2))
            self.assertIsNone(extract_covers(Path(tmp) / "missing.jpg", 1))


class TrocarLivroTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cards = root / "cards"
        self.board = BoardStore(root / "board.db")
        self.first = self._post("10:00", [AZ1, SHOPEE], [RED, ORANGE], "ℹ️ Assinatura A: https://link.amazon/s1")
        self.second = self._post("10:40", [AZ2, ML], [BLUE, GREEN], "ℹ️ Assinatura B: https://link.amazon/s2")

    def tearDown(self):
        self.board.close() if hasattr(self.board, "close") else None
        self.tmp.cleanup()

    def _post(self, clock, books, colors, signature):
        post_id = self.board.add_post(day=DAY, clock=clock, caption=f"texto\n\n{signature}", image_path="", books=books)
        render_card([_cover(color) for color in colors], self.cards / f"{post_id}.jpg")
        self.board.set_image(post_id, f"data/cards/{post_id}.jpg")
        return post_id

    def _posts(self):
        return {post.id: post for post in self.board.posts_for(DAY)}

    def test_swaps_second_store_books_and_rebuilds_card_and_caption(self):
        result = trocar_livro(self.board, self.cards, DAY, self.first, self.second, "segunda")
        self.assertTrue(result["ok"], result)
        posts = self._posts()
        self.assertEqual([book.title for book in posts[self.first].books], ["Duna", "Tudo é rio"])
        self.assertEqual([book.title for book in posts[self.second].books], ["Sapiens", "Torto Arado"])
        self.assertIn("Tudo é rio", posts[self.first].caption)
        self.assertNotIn("Torto Arado", posts[self.first].caption)
        self.assertTrue(posts[self.first].caption.endswith("ℹ️ Assinatura A: https://link.amazon/s1"))
        self.assertEqual(posts[self.first].clock, "10:00")
        first_covers = extract_covers(self.cards / f"{self.first}.jpg", 2)
        second_covers = extract_covers(self.cards / f"{self.second}.jpg", 2)
        self.assertTrue(_close(_main_color(first_covers[1]), GREEN))
        self.assertTrue(_close(_main_color(second_covers[1]), ORANGE))
        self.assertFalse(list(self.cards.glob("*.novo")))

    def test_undo_is_the_same_swap_again(self):
        params = trocar_livro(self.board, self.cards, DAY, self.first, self.second, "amazon")["undo"]
        trocar_livro(self.board, self.cards, DAY, params["id"], params["com"], params["lado"])
        posts = self._posts()
        self.assertEqual([book.title for book in posts[self.first].books], ["Duna", "Torto Arado"])

    def test_refuses_to_leave_a_post_empty(self):
        lonely = self._post("11:20", [ML], [GREEN], "ℹ️ C: https://link.amazon/s3")
        result = trocar_livro(self.board, self.cards, DAY, lonely, self.first, "amazon")
        self.assertTrue(result["ok"])
        back = trocar_livro(self.board, self.cards, DAY, self.second, lonely, "segunda")
        self.assertTrue(back["ok"])
        empty = self._post("12:00", [AZ2], [BLUE], "ℹ️ D: https://link.amazon/s4")
        refused = trocar_livro(self.board, self.cards, DAY, empty, self.first, "amazon")
        self.assertFalse(refused["ok"])
        self.assertIn("ficaria sem livro", refused["error"])

    def test_sent_post_is_left_alone(self):
        with self.board._lock, self.board._connection:
            self.board._connection.execute("UPDATE scheduled_posts SET status = 'sent' WHERE id = ?", (self.second,))
        result = trocar_livro(self.board, self.cards, DAY, self.first, self.second, "segunda")
        self.assertFalse(result["ok"])
        self.assertEqual([book.title for book in self._posts()[self.first].books], ["Duna", "Torto Arado"])

    def test_swaps_only_the_second_amazon(self):
        left = self._post("13:00", [AZ1, AZ2], [RED, BLUE], "ℹ️ E: https://link.amazon/s5")
        other = self._post(
            "14:20",
            [_book("Duna 2", "B0AAAAAAA3", "https://link.amazon/a3"), _book("Sapiens 2", "B0AAAAAAA4", "https://link.amazon/a4")],
            [ORANGE, GREEN],
            "ℹ️ G: https://link.amazon/s7",
        )
        result = trocar_livro(self.board, self.cards, DAY, left, other, "segunda")
        self.assertTrue(result["ok"], result)
        posts = self._posts()
        self.assertEqual([book.title for book in posts[left].books], ["Duna", "Sapiens 2"])
        self.assertEqual([book.title for book in posts[other].books], ["Duna 2", "Sapiens"])

    def test_bad_side_is_refused(self):
        self.assertFalse(trocar_livro(self.board, self.cards, DAY, self.first, self.second, "x")["ok"])

    def test_replace_post_books_rejects_stale_snapshot(self):
        posts = self._posts()
        error = self.board.replace_post_books(DAY, {self.first: ((AZ2,), [AZ2], "x")})
        self.assertIn("mudou", error)
        self.assertEqual(self._posts()[self.first].books, posts[self.first].books)


if __name__ == "__main__":
    unittest.main()
