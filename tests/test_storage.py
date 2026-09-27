import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from promo_livros.storage import Storage


class StorageTests(unittest.TestCase):
    def test_last_post_and_category_cache(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            storage = Storage(Path(folder) / "promo.sqlite")
            now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
            self.assertIsNone(storage.last_post("B00TEST123"))
            storage.record_post("B00TEST123", "Título", 2_000, now)
            storage.record_post("B00TEST123", "Título", 1_500, now + timedelta(days=1))

            last = storage.last_post("B00TEST123")
            assert last is not None
            self.assertEqual(last.price_cents, 1_500)
            self.assertEqual(last.posted_at, now + timedelta(days=1))

            self.assertIsNone(storage.cached_category(12, "Livros"))
            storage.save_category(12, "Livros", 20, now)
            self.assertEqual(storage.cached_category(12, "livros"), 20)
            storage.close()


if __name__ == "__main__":
    unittest.main()
