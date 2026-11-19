import unittest
from random import Random

from promo_livros.campaign_rules import (
    DEFAULT_LAST_OFFSET_MINUTES,
    InviteSettings,
    RotationEntry,
    campaign_valid_on,
    fixed_invite_due,
    fixed_invite_missed,
    invite_settings,
    is_rotating,
    last_invite_clock,
    last_invite_due,
    parse_campaign_clock,
    parse_fixed_clock,
    parse_last_offset,
    parse_valid_until,
    pick_avoiding,
    rotation_order,
)


class CampaignModeTests(unittest.TestCase):
    def test_empty_clock_means_rotating(self) -> None:
        self.assertIsNone(parse_campaign_clock("  "))
        self.assertTrue(is_rotating(None))
        self.assertFalse(is_rotating("10:00"))

    def test_campaign_clock_allows_queue_overlap(self) -> None:
        self.assertEqual(parse_campaign_clock(" 10:00 "), "10:00")

    def test_bad_campaign_clock_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_campaign_clock("25:00")

    def test_valid_until_empty_or_iso(self) -> None:
        self.assertIsNone(parse_valid_until(""))
        self.assertEqual(parse_valid_until("2026-12-01"), "2026-12-01")
        with self.assertRaises(ValueError):
            parse_valid_until("01/12/2026")

    def test_validity_includes_the_end_day(self) -> None:
        self.assertTrue(campaign_valid_on(None, "2026-11-19"))
        self.assertTrue(campaign_valid_on("2026-11-19", "2026-11-19"))
        self.assertFalse(campaign_valid_on("2026-11-18", "2026-11-19"))


class FixedClockTests(unittest.TestCase):
    def test_empty_turns_the_invite_off(self) -> None:
        self.assertIsNone(parse_fixed_clock("  ", {"10:00"}))

    def test_a_queue_clock_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            parse_fixed_clock("10:00", {"10:00"})
        self.assertIn("horário da fila", str(caught.exception))

    def test_bad_format_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_fixed_clock("25:00", set())

    def test_free_clock_is_kept(self) -> None:
        self.assertEqual(parse_fixed_clock(" 13:15 ", {"13:00"}), "13:15")

    def test_due_only_inside_the_grace_window(self) -> None:
        self.assertFalse(fixed_invite_due("13:15", "13:14"))
        self.assertTrue(fixed_invite_due("13:15", "13:15"))
        self.assertTrue(fixed_invite_due("13:15", "14:14"))
        self.assertFalse(fixed_invite_due("13:15", "14:15"))
        self.assertFalse(fixed_invite_due(None, "13:15"))

    def test_missed_after_the_grace_window(self) -> None:
        self.assertFalse(fixed_invite_missed("13:15", "14:14"))
        self.assertTrue(fixed_invite_missed("13:15", "14:15"))
        self.assertFalse(fixed_invite_missed(None, "23:00"))

    def test_late_clock_window_does_not_cross_midnight(self) -> None:
        self.assertTrue(fixed_invite_due("23:30", "23:59"))
        self.assertFalse(fixed_invite_missed("23:30", "23:59"))


class LastInviteTests(unittest.TestCase):
    def test_offset_after_the_last_queue_post(self) -> None:
        self.assertEqual(last_invite_clock("21:20", "22:00", 10), "21:30")

    def test_without_queue_the_window_end_is_the_reference(self) -> None:
        self.assertEqual(last_invite_clock(None, "22:00", 10), "22:10")

    def test_never_passes_the_end_of_the_day(self) -> None:
        self.assertEqual(last_invite_clock("23:55", "22:00", 10), "23:59")

    def test_waits_for_pending_queue_posts(self) -> None:
        self.assertFalse(last_invite_due("21:40", "21:30", queue_pending=True))
        self.assertTrue(last_invite_due("21:40", "21:30", queue_pending=False))
        self.assertFalse(last_invite_due("21:29", "21:30", queue_pending=False))

    def test_offset_limits(self) -> None:
        self.assertEqual(parse_last_offset(" 15 "), 15)
        self.assertEqual(parse_last_offset("1"), 1)
        self.assertEqual(parse_last_offset("120"), 120)
        for raw in ("0", "121", "x", ""):
            with self.assertRaises(ValueError):
                parse_last_offset(raw)


class SettingsTests(unittest.TestCase):
    def test_broken_saved_values_fall_back(self) -> None:
        settings = invite_settings("99:99", "abc")
        self.assertIsNone(settings.fixed_clock)
        self.assertEqual(settings.last_offset_minutes, DEFAULT_LAST_OFFSET_MINUTES)

    def test_out_of_range_saved_offset_falls_back(self) -> None:
        settings = invite_settings("13:15", "500")
        self.assertEqual(settings.last_offset_minutes, DEFAULT_LAST_OFFSET_MINUTES)

    def test_saved_values_are_read(self) -> None:
        self.assertEqual(invite_settings("13:15", "20"), InviteSettings("13:15", 20))
        self.assertEqual(invite_settings(None, None), InviteSettings(None, DEFAULT_LAST_OFFSET_MINUTES))


class RotationTests(unittest.TestCase):
    def test_first_use_starts_at_the_top(self) -> None:
        self.assertEqual(rotation_order([RotationEntry(2, 2), RotationEntry(1, 1)], None), [1, 2])

    def test_goes_to_the_next_after_the_last_used(self) -> None:
        ready = [RotationEntry(1, 1), RotationEntry(2, 2), RotationEntry(3, 3)]
        self.assertEqual(rotation_order(ready, RotationEntry(1, 1)), [2, 3, 1])

    def test_wraps_after_the_last(self) -> None:
        ready = [RotationEntry(1, 1), RotationEntry(2, 2), RotationEntry(3, 3)]
        self.assertEqual(rotation_order(ready, RotationEntry(3, 3)), [1, 2, 3])

    def test_a_campaign_that_left_keeps_its_place(self) -> None:
        ready = [RotationEntry(1, 1), RotationEntry(3, 3)]
        self.assertEqual(rotation_order(ready, RotationEntry(2, 2)), [3, 1])

    def test_tied_positions_order_by_campaign_id(self) -> None:
        self.assertEqual(rotation_order([RotationEntry(5, 1), RotationEntry(4, 1)], None), [4, 5])

    def test_nothing_ready(self) -> None:
        self.assertEqual(rotation_order([], RotationEntry(1, 1)), [])


class PickTests(unittest.TestCase):
    def test_avoids_the_last_used_when_there_is_another(self) -> None:
        for seed in range(20):
            self.assertEqual(pick_avoiding([1, 2], 1, Random(seed)), 2)

    def test_single_item_repeats(self) -> None:
        self.assertEqual(pick_avoiding([5], 5, Random(0)), 5)

    def test_empty_list_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            pick_avoiding([], None, Random(0))
