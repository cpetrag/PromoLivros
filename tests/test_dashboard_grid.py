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


class ListStoreLogosTests(unittest.TestCase):
    def test_each_post_shows_the_logos_of_its_stores(self):
        from promo_livros.dashboard_belt import _row

        html = _row(_post(7, "13:40", shelf=(AMAZON, MAGALU)), (), [7])
        self.assertIn('src="/lojas/amazon.png"', html)
        self.assertIn('src="/lojas/magalu.png"', html)
        self.assertNotIn('src="/lojas/ml.png"', html)
        self.assertLess(html.index("/cards/7.jpg"), html.index("/lojas/amazon.png"))

    def test_campaign_post_row_shows_swap_form_and_looks_distinct(self):
        from promo_livros.board_store import POST_KIND_CAMPAIGN
        from promo_livros.dashboard_belt import _row

        post = FeedPost(
            id=9, clock="11:00", status="scheduled", title="Entre no grupo", price_cents=0, discount_pct=None,
            url="", sends=(), caption="Entre no grupo", post_kind=POST_KIND_CAMPAIGN, campaign_id=2, image_id=3, text_id=4,
        )
        form = '<form class="campaign-swap" method="post" action="/hoje/campanha-post"></form>'

        html = _row(post, (), [9], campaign_form=form)

        self.assertIn('action="/hoje/campanha-post"', html)
        self.assertIn('data-kind="campaign"', html)
        self.assertIn("post campaign", html)
        self.assertIn("Campanha</span>", html)
        self.assertNotIn("js-edit", html)
        self.assertNotIn("/lojas/", html)

    def test_book_post_row_has_no_campaign_form(self):
        from promo_livros.dashboard_belt import _row

        html = _row(_post(7, "13:40", shelf=(AMAZON,)), (), [7])

        self.assertNotIn("/hoje/campanha-post", html)
        self.assertIn('data-kind="book"', html)
        self.assertIn("js-edit", html)

    def test_summary_counts_posts_still_to_go_per_store(self):
        from promo_livros.dashboard_belt import _stores_summary

        posts = [
            _post(1, "13:40", shelf=(AMAZON, MAGALU)),
            _post(2, "14:00", shelf=(AMAZON, ML)),
            _post(3, "14:30", shelf=(AMAZON,)),
        ]
        html = _stores_summary(posts)
        self.assertIn("3 posts ainda vão sair", html)
        self.assertRegex(html, r'amazon\.png"[^>]*><b>3</b>')
        self.assertRegex(html, r'ml\.png"[^>]*><b>1</b>')
        self.assertRegex(html, r'magalu\.png"[^>]*><b>1</b>')
        self.assertEqual(_stores_summary([]), "")


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
