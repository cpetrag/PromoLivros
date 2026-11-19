import unittest

from promo_livros.board_store import FeedBook, FeedPost
from promo_livros.dashboard_grid import render_grid, store_of
from promo_livros.send_schedule import SendSchedule


def _post(post_id, clock, status="scheduled", shelf=()):
    return FeedPost(
        id=post_id, clock=clock, status=status, title=f"Livro {post_id}",
        price_cents=1990, discount_pct=30.0, url="https://amazon.com.br/dp/X", sends=(), shelf=shelf,
    )


AMAZON = FeedBook("Duna <1>", 4990, 40.0, "https://www.amazon.com.br/dp/B0", "B0ABCDEFGH")
SHOPEE = FeedBook("Torto Arado", 2990, 25.0, "https://s.shopee.com.br/abc", "123456.7890123")
ML = FeedBook("Sapiens", 3990, None, "https://www.mercadolivre.com.br/p/MLB1", "MLB12345")
MAGALU = FeedBook(
    "Livro Magalu",
    2990,
    20.0,
    "https://www.magazineluiza.com.br/livro/p/jf7k9gad9/sku/",
    "jf7k9gad9",
)


class StoreOfTests(unittest.TestCase):
    def test_detects_each_store(self):
        self.assertEqual(store_of(AMAZON), "amazon")
        self.assertEqual(store_of(SHOPEE), "shopee")
        self.assertEqual(store_of(ML), "ml")
        self.assertEqual(store_of(MAGALU), "magalu")


class RenderGridTests(unittest.TestCase):
    def setUp(self):
        self.schedule = SendSchedule(start="09:00", end="22:00", post_interval_minutes=40, group_gap_seconds=45)

    def test_row_shows_magalu_tag(self):
        html = render_grid([_post(2, "11:00", shelf=(AMAZON, MAGALU))], self.schedule, "08:00")
        self.assertIn('grid-tag magalu">Magazine Luiza', html)

    def test_row_pairs_amazon_with_second_store_and_escapes(self):
        html = render_grid([_post(1, "10:00", shelf=(AMAZON, SHOPEE))], self.schedule, "08:00")
        self.assertIn('data-id="1"', html)
        self.assertIn("Duna &lt;1&gt;", html)
        self.assertNotIn("Duna <1>", html)
        self.assertIn('grid-tag shopee">Shopee', html)
        self.assertIn("js-grid-menu", html)

    def test_two_offers_from_the_same_store_both_show(self):
        other = FeedBook("Fundação", 1990, 10.0, "https://www.amazon.com.br/dp/B1", "B1ABCDEFGH")
        html = render_grid([_post(1, "10:00", shelf=(AMAZON, other))], self.schedule, "08:00")
        self.assertIn("Duna", html)
        self.assertIn("Fundação", html)
        self.assertIn('grid-tag amazon">Amazon', html)

    def test_free_slots_exclude_taken_clocks(self):
        html = render_grid([_post(1, "09:00")], self.schedule, "08:00")
        self.assertIn('data-free="09:40,', html)

    def test_done_posts_go_to_collapsed_block_without_menu(self):
        html = render_grid([_post(1, "09:00", status="sent")], self.schedule, "10:00")
        self.assertIn("<details class=\"grid-done\">", html)
        self.assertIn("Nenhum post na fila.", html)
        self.assertNotIn("js-grid-menu", html)

    def test_posts_from_other_days_stay_out(self):
        old = FeedPost(2, "11:00", "sent", "Ontem", 1000, None, "u", (), day="2026-11-02")
        html = render_grid([old], self.schedule, "10:00", "2026-11-03")
        self.assertNotIn("Ontem", html)


if __name__ == "__main__":
    unittest.main()
