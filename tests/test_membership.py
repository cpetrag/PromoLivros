import tempfile
import unittest
from pathlib import Path

from promo_livros.membership import MembershipStore


class MembershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.store = MembershipStore(Path(self._dir.name) / "membros.sqlite")

    def tearDown(self) -> None:
        self.store.close()
        self._dir.cleanup()

    def test_first_reading_is_a_baseline(self) -> None:
        people = [("a@c.us", "participant"), ("b@c.us", "admin"), ("c@c.us", "superadmin")]
        row = self.store.observe("2026-09-29", "1@g.us", "Black Livros 01", people)
        self.assertEqual(row.liquid, 1)
        self.assertEqual(row.joined, 0)
        self.assertEqual(row.left, 0)

    def test_later_reading_counts_join_and_leave(self) -> None:
        chat = "1@g.us"
        self.store.observe("2026-09-29", chat, "Um", [("a@c.us", "participant"), ("b@c.us", "participant")])
        row = self.store.observe(
            "2026-09-29",
            chat,
            "Um",
            [("b@c.us", "admin"), ("c@c.us", "participant")],
        )
        self.assertEqual(row.liquid, 1)
        self.assertEqual(row.joined, 1)
        self.assertEqual(row.left, 1)
        self.assertEqual(row.net, 0)
        again = self.store.observe(
            "2026-09-29",
            chat,
            "Um",
            [("b@c.us", "admin"), ("c@c.us", "participant")],
        )
        self.assertEqual((again.joined, again.left), (1, 1))

    def test_empty_list_does_not_erase_the_roster(self) -> None:
        chat = "1@g.us"
        self.store.observe("2026-09-29", chat, "Um", [("a@c.us", "participant")])
        with self.assertRaises(ValueError):
            self.store.observe("2026-09-29", chat, "Um", [])
        row = self.store.observe("2026-09-29", chat, "Um", [("a@c.us", "participant")])
        self.assertEqual((row.joined, row.left), (0, 0))

    def test_days_do_not_share_the_flow(self) -> None:
        chat = "1@g.us"
        self.store.observe("2026-09-29", chat, "Um", [("a@c.us", "participant")])
        today = self.store.observe("2026-09-30", chat, "Um", [("a@c.us", "participant"), ("b@c.us", "participant")])
        self.assertEqual(today.joined, 1)
        self.assertEqual(today.left, 0)


if __name__ == "__main__":
    unittest.main()
