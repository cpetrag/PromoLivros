import tempfile
import unittest
from pathlib import Path

from promo_livros.board_store import BoardBook, BoardStore

DAY = "2026-11-03"


def _book() -> BoardBook:
    return BoardBook("Livro", "", 1000, 2000, 50, "Menor preço em 120 dias.", "https://example", "")


def _add(store: BoardStore, clock: str) -> int:
    return store.add_post(day=DAY, clock=clock, caption="*Livro*", image_path="data/cards/1.jpg", books=[_book()])


class QueueEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.store = BoardStore(Path(self.folder.name) / "board.sqlite")

    def tearDown(self) -> None:
        self.store.close()
        self.folder.cleanup()

    def test_last_clock_counts_sent_and_scheduled_before_the_end(self) -> None:
        first = _add(self.store, "10:00")
        late = _add(self.store, "21:20")
        _add(self.store, "22:30")
        self.store.mark_sent(first)
        self.assertEqual(self.store.last_queue_clock(DAY, "22:00"), "21:20")
        self.store.cancel(DAY, late)
        self.assertEqual(self.store.last_queue_clock(DAY, "22:00"), "10:00")

    def test_empty_day_has_no_clock(self) -> None:
        self.assertIsNone(self.store.last_queue_clock(DAY, "22:00"))

    def test_pending_ignores_posts_after_the_end(self) -> None:
        _add(self.store, "22:30")
        self.assertFalse(self.store.has_pending_posts(DAY, "22:00"))
        early = _add(self.store, "21:00")
        self.assertTrue(self.store.has_pending_posts(DAY, "22:00"))
        self.store.mark_sent(early)
        self.assertFalse(self.store.has_pending_posts(DAY, "22:00"))

    def test_post_exactly_at_the_end_is_ignored(self) -> None:
        _add(self.store, "22:00")
        self.assertIsNone(self.store.last_queue_clock(DAY, "22:00"))
        self.assertFalse(self.store.has_pending_posts(DAY, "22:00"))
