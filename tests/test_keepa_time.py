import unittest
from datetime import datetime, timezone

from promo_livros.keepa_time import keepa_minutes
from promo_livros.models import KEEPA_TIME_OFFSET_MINUTES


class KeepaTimeTests(unittest.TestCase):
    def test_roundtrip_matches_the_documented_offset(self) -> None:
        moment = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
        keepa = keepa_minutes(moment)
        unix_seconds = (keepa + KEEPA_TIME_OFFSET_MINUTES) * 60
        self.assertEqual(unix_seconds, int(moment.timestamp()) // 60 * 60)


if __name__ == "__main__":
    unittest.main()
