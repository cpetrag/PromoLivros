import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from promo_livros.send_gap import gap_open, latest_stamp
from promo_livros.send_schedule import clock_minutes, format_clock

ZONE = ZoneInfo("America/Sao_Paulo")


class SendGapTests(unittest.TestCase):
    def test_latest_stamp_ignores_empty_values(self) -> None:
        now = datetime(2026, 11, 3, 13, 0, tzinfo=ZONE)
        early = (now - timedelta(minutes=5)).isoformat(timespec="seconds")
        late = (now - timedelta(seconds=10)).isoformat(timespec="seconds")
        self.assertEqual(latest_stamp((early, None, late, ""), now), late)
        self.assertIsNone(latest_stamp((None, ""), now))

    def test_naive_stamp_takes_the_zone_of_now(self) -> None:
        now = datetime(2026, 11, 3, 13, 0, tzinfo=ZONE)
        self.assertFalse(gap_open("2026-11-03T12:59:30", now, 45))
        self.assertTrue(gap_open("2026-11-03T12:59:00", now, 45))

    def test_no_previous_send_is_open(self) -> None:
        self.assertTrue(gap_open(None, datetime(2026, 11, 3, 13, 0, tzinfo=ZONE), 45))


class ClockHelpersTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        self.assertEqual(clock_minutes("13:15"), 13 * 60 + 15)
        self.assertEqual(format_clock(13 * 60 + 15), "13:15")

    def test_bad_clock_names_the_field(self) -> None:
        with self.assertRaises(ValueError) as caught:
            clock_minutes("25:00", "Convite no horário")
        self.assertIn("Convite no horário", str(caught.exception))

    def test_only_ascii_digits_are_a_clock(self) -> None:
        for value in ("1٣:15", "١٣:١٥", "１３:１５"):
            with self.assertRaises(ValueError):
                clock_minutes(value)
