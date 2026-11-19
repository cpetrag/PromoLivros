import tempfile
import unittest
from pathlib import Path

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.campaign_rules import RotationEntry
from promo_livros.campaign_store import CampaignStore

DAY = "2026-11-19"


def _book() -> BoardBook:
    return BoardBook(
        title="Livro",
        blurb="",
        price_cents=1000,
        list_price_cents=2000,
        discount_pct=50.0,
        lowest_label="",
        url="https://example.com/b",
        coupon="",
    )


class BoardCampaignPostTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.path = Path(self._folder.name) / "board.sqlite"
        self.board = BoardStore(self.path)
        self.addCleanup(self.board.close)
        self.campaigns = CampaignStore(self.path)
        self.addCleanup(self.campaigns.close)

    def test_add_campaign_post_without_books(self) -> None:
        post_id = self.board.add_campaign_post(
            day=DAY,
            clock="11:00",
            campaign_id=1,
            image_id=2,
            text_id=3,
            caption="hook",
            image_path="data/campaigns/1/x.jpg",
            locked_at="2026-11-19T10:00:00",
        )
        post = self.board.post_by_id(post_id)
        self.assertEqual(post.post_kind, "campaign")
        self.assertEqual(post.books, ())
        self.assertEqual((post.campaign_id, post.image_id, post.text_id), (1, 2, 3))
        self.assertEqual(post.campaign_locked_at, "2026-11-19T10:00:00")
        self.assertEqual(self.board.posts_for(DAY)[0].id, post_id)

    def test_book_posts_default_to_book_kind_and_still_need_books(self) -> None:
        post_id = self.board.add_post(day=DAY, clock="10:00", caption="c", image_path="", books=[_book()])
        post = self.board.post_by_id(post_id)
        self.assertEqual(post.post_kind, "book")
        self.assertIsNone(post.campaign_id)
        with self.assertRaises(ValueError):
            self.board.add_post(day=DAY, clock="10:00", caption="c", image_path="", books=[])

    def test_set_campaign_content_updates_fields(self) -> None:
        post_id = self.board.add_campaign_post(day=DAY, clock="11:00")
        self.board.set_campaign_content(post_id, 4, 5, 6, "novo", "img.jpg", "2026-11-19T10:30:00")
        post = self.board.post_by_id(post_id)
        self.assertEqual((post.campaign_id, post.image_id, post.text_id), (4, 5, 6))
        self.assertEqual((post.caption, post.image_path), ("novo", "img.jpg"))
        self.assertEqual(post.campaign_locked_at, "2026-11-19T10:30:00")

    def test_migrates_existing_board_database(self) -> None:
        self.board.close()
        reopened = BoardStore(self.path)
        self.addCleanup(reopened.close)
        post_id = reopened.add_campaign_post(day=DAY, clock="11:00")
        self.assertEqual(reopened.post_by_id(post_id).post_kind, "campaign")

    def test_last_used_rotating_picks_newer_board_lock_over_older_run(self) -> None:
        old = self.campaigns.create("Antiga")
        new = self.campaigns.create("Nova")
        run = self.campaigns.run_for(DAY, "last")
        self.campaigns.lock_content(run.id, old, 1, 1, "2026-11-19T09:00:00")
        self.board.add_campaign_post(
            day=DAY, clock="11:00", campaign_id=new, image_id=1, text_id=1, locked_at="2026-11-19T10:00:00"
        )
        self.assertEqual(self.campaigns.last_used_rotating(), RotationEntry(new, 2))

    def test_last_used_rotating_picks_newer_run_over_older_board_lock(self) -> None:
        old = self.campaigns.create("Antiga")
        new = self.campaigns.create("Nova")
        self.board.add_campaign_post(
            day=DAY, clock="11:00", campaign_id=old, image_id=1, text_id=1, locked_at="2026-11-19T09:00:00"
        )
        run = self.campaigns.run_for(DAY, "last")
        self.campaigns.lock_content(run.id, new, 1, 1, "2026-11-19T22:00:00")
        self.assertEqual(self.campaigns.last_used_rotating(), RotationEntry(new, 2))

    def test_last_used_rotating_ignores_fixed_clock_campaigns_on_board(self) -> None:
        fixed = self.campaigns.create("Fixa")
        self.campaigns.set_schedule(fixed, "11:00", None)
        self.board.add_campaign_post(
            day=DAY, clock="11:00", campaign_id=fixed, image_id=1, text_id=1, locked_at="2026-11-19T10:00:00"
        )
        self.assertIsNone(self.campaigns.last_used_rotating())

    def test_last_used_rotating_ignores_unlocked_and_book_posts(self) -> None:
        rotating = self.campaigns.create("Rotativa")
        self.board.add_campaign_post(day=DAY, clock="11:00", campaign_id=rotating)
        self.board.add_post(day=DAY, clock="12:00", caption="c", image_path="", books=[_book()])
        self.assertIsNone(self.campaigns.last_used_rotating())

    def test_last_used_rotating_ignores_replaced_and_cancelled_board_posts(self) -> None:
        rotating = self.campaigns.create("Rotativa")
        for clock in ("11:00", "12:00"):
            self.board.add_campaign_post(
                day=DAY, clock=clock, campaign_id=rotating, image_id=1, text_id=1, locked_at="2026-11-19T10:00:00"
            )
        self.board.replace_scheduled(DAY)
        self.assertIsNone(self.campaigns.last_used_rotating())
        self.assertEqual(self.campaigns.last_content(rotating), (None, None))

    def test_last_content_uses_newest_of_runs_and_board_posts(self) -> None:
        campaign = self.campaigns.create("Rotativa")
        run = self.campaigns.run_for(DAY, "last")
        self.campaigns.lock_content(run.id, campaign, 1, 1, "2026-11-19T09:00:00")
        self.assertEqual(self.campaigns.last_content(campaign), (1, 1))
        self.board.add_campaign_post(
            day=DAY, clock="11:00", campaign_id=campaign, image_id=7, text_id=8, locked_at="2026-11-19T10:00:00"
        )
        self.assertEqual(self.campaigns.last_content(campaign), (7, 8))

    def test_last_used_rotating_works_when_board_table_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            alone = CampaignStore(Path(folder) / "only_campaigns.sqlite")
            try:
                self.assertIsNone(alone.last_used_rotating())
            finally:
                alone.close()


if __name__ == "__main__":
    unittest.main()
