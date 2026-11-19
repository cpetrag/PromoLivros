import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from random import Random
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.campaign_images import read_image
from promo_livros.campaign_rules import INVITE_FIXED, INVITE_LAST
from promo_livros.campaign_send import publish_due_invite
from promo_livros.campaign_store import CampaignStore
from promo_livros.models import WhatsAppGroup
from promo_livros.send_schedule import parse_schedule
from promo_livros.waha import WahaError

ZONE = ZoneInfo("America/Sao_Paulo")
DAY = "2026-11-03"
GROUPS = (
    WhatsAppGroup("Black Livros 01", "120363430990609445@g.us"),
    WhatsAppGroup("Black Livros 02", "120363410393297284@g.us"),
)


class _Sender:
    def __init__(self, state: str = "connected", fail: WahaError | None = None) -> None:
        self.state = state
        self.fail = fail
        self.sent: list[tuple[str, str, bytes]] = []

    def connection_state(self) -> str:
        return self.state

    def send_jpeg(self, chat_id: str, caption: str, image: bytes) -> str:
        if self.fail is not None:
            raise self.fail
        self.sent.append((chat_id, caption, image))
        return f"msg-{len(self.sent)}"


def _at(hour: int, minute: int, day: int = 3) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=ZONE)


class InviteSendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.board = BoardStore(self.root / "board.sqlite")
        self.board.set_sending(True)
        self.board.save_send_schedule(parse_schedule("08:00", "22:00", "40", "45"))
        self.board.put_setting("invite_fixed_clock", "13:15")
        self.campaigns = CampaignStore(self.root / "board.sqlite")

    def tearDown(self) -> None:
        self.campaigns.close()
        self.board.close()
        self.folder.cleanup()

    def _campaign(self, name: str, *, images: int = 1, text: str | None = None) -> int:
        campaign_id = self.campaigns.create(name)
        for index in range(images):
            relative = f"data/campaigns/{campaign_id}/{index}.jpg"
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"jpeg-{campaign_id}-{index}".encode())
            self.campaigns.add_image(campaign_id, relative)
        self.campaigns.add_text(campaign_id, text or f"Entre no {name}!")
        return campaign_id

    def _invite(self, sender: _Sender, now: datetime, quiet_since: str | None = None) -> str:
        config = SimpleNamespace(whatsapp_groups=GROUPS)
        return publish_due_invite(
            config,
            self.board,
            self.campaigns,
            sender,
            root=self.root,
            now=now,
            quiet_since=quiet_since,
            rng=Random(0),
        )

    def test_fixed_invite_goes_to_each_group_with_the_same_content(self) -> None:
        self._campaign("A")
        sender = _Sender()
        now = _at(13, 15)
        self.assertEqual(self._invite(sender, now), "sent")
        self.assertEqual(self._invite(sender, now + timedelta(seconds=10)), "waiting")
        self.assertEqual(self._invite(sender, now + timedelta(seconds=45)), "sent")
        self.assertEqual([chat for chat, _caption, _image in sender.sent], [group.chat_id for group in GROUPS])
        self.assertEqual(sender.sent[0][1:], sender.sent[1][1:])
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "sent")
        self.assertEqual(self._invite(sender, now + timedelta(minutes=5)), "idle")

    def test_fixed_invite_waits_for_its_clock_and_gives_up_after_the_window(self) -> None:
        self._campaign("A")
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(13, 14)), "idle")
        self.assertEqual(self._invite(sender, _at(14, 15)), "idle")
        self.assertEqual(sender.sent, [])
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "pending")

    def test_sending_off_does_nothing(self) -> None:
        self._campaign("A")
        self.board.set_sending(False)
        self.assertEqual(self._invite(_Sender(), _at(13, 15)), "off")

    def test_rotation_alternates_between_the_two_invites(self) -> None:
        self._campaign("A", text="Texto A")
        self._campaign("B", text="Texto B")
        sender = _Sender()
        self._invite(sender, _at(13, 15))
        self._invite(sender, _at(13, 16))
        self.assertEqual(self._invite(sender, _at(22, 9)), "idle")
        self._invite(sender, _at(22, 10))
        self.assertEqual([caption for _chat, caption, _image in sender.sent], ["Texto A", "Texto A", "Texto B"])

    def test_last_invite_waits_for_the_queue(self) -> None:
        self._campaign("A")
        book = BoardBook("Livro", "", 1000, 2000, 50, "Menor preço.", "https://example", "")
        post_id = self.board.add_post(day=DAY, clock="21:20", caption="*Livro*", image_path="data/cards/1.jpg", books=[book])
        self.board.put_setting("invite_fixed_clock", "")
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(21, 35)), "idle")
        self.board.mark_sent(post_id)
        self.assertEqual(self._invite(sender, _at(21, 35)), "sent")
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_LAST).status, "sending")

    def test_manual_choice_wins_over_rotation(self) -> None:
        self._campaign("A", text="Texto A")
        chosen = self._campaign("B", text="Texto B")
        self.campaigns.set_manual_campaign(DAY, INVITE_FIXED, chosen)
        sender = _Sender()
        self._invite(sender, _at(13, 15))
        self.assertEqual(sender.sent[0][1], "Texto B")

    def test_no_ready_campaign_skips_the_invite(self) -> None:
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(13, 15)), "skipped")
        self.assertEqual(self._invite(sender, _at(13, 16)), "idle")
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "skipped")

    def test_missing_photo_moves_to_the_next_campaign(self) -> None:
        broken = self._campaign("A", text="Texto A")
        self._campaign("B", text="Texto B")
        (self.root / f"data/campaigns/{broken}/0.jpg").unlink()
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(13, 15)), "sent")
        self.assertEqual(sender.sent[0][1], "Texto B")

    def test_a_recent_message_holds_the_invite(self) -> None:
        self._campaign("A")
        sender = _Sender()
        now = _at(13, 15)
        quiet = (now - timedelta(seconds=10)).isoformat(timespec="seconds")
        self.assertEqual(self._invite(sender, now, quiet_since=quiet), "waiting")
        self.assertEqual(sender.sent, [])

    def test_disconnected_session_keeps_the_invite_pending(self) -> None:
        self._campaign("A")
        self.assertEqual(self._invite(_Sender(state="disconnected"), _at(13, 15)), "disconnected")
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "pending")

    def test_session_down_retries_the_same_group(self) -> None:
        self._campaign("A")
        down = _Sender(fail=WahaError("sem sessão", session_down=True))
        self.assertEqual(self._invite(down, _at(13, 15)), "waiting")
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(13, 16)), "sent")
        self.assertEqual(sender.sent[0][0], GROUPS[0].chat_id)

    def test_next_day_avoids_the_last_photo(self) -> None:
        self._campaign("A", images=2)
        sender = _Sender()
        self._invite(sender, _at(13, 15))
        self._invite(sender, _at(13, 16))
        self._invite(sender, _at(13, 15, day=4))
        self.assertNotEqual(sender.sent[0][2], sender.sent[2][2])

    def test_run_finished_elsewhere_is_not_skipped_or_sent(self) -> None:
        self._campaign("A")
        run = self.campaigns.run_for(DAY, INVITE_FIXED)
        original_lock = self.campaigns.lock_content

        def lock_after_someone_finished(*args, **kwargs):
            self.campaigns.mark_run_sent(run.id, "2026-11-03T13:15:00-03:00")
            return original_lock(*args, **kwargs)

        sender = _Sender()
        with patch.object(self.campaigns, "lock_content", side_effect=lock_after_someone_finished):
            self.assertEqual(self._invite(sender, _at(13, 15)), "idle")
        self.assertEqual(sender.sent, [])
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "sent")

    def test_manual_choice_made_during_the_draw_is_kept(self) -> None:
        self._campaign("A", text="Texto A")
        chosen = self._campaign("B", text="Texto B")
        original_lock = self.campaigns.lock_content

        def lock_after_a_manual_choice(*args, **kwargs):
            self.campaigns.set_manual_campaign(DAY, INVITE_FIXED, chosen)
            return original_lock(*args, **kwargs)

        sender = _Sender()
        with patch.object(self.campaigns, "lock_content", side_effect=lock_after_a_manual_choice):
            self.assertEqual(self._invite(sender, _at(13, 15)), "waiting")
        self.assertEqual(sender.sent, [])
        run = self.campaigns.run_for(DAY, INVITE_FIXED)
        self.assertEqual((run.status, run.campaign_id, run.manual), ("pending", chosen, True))
        self.assertEqual(self._invite(sender, _at(13, 16)), "sent")
        self.assertEqual(sender.sent[0][1], "Texto B")

    def test_unreadable_photo_is_logged_and_the_next_campaign_is_used(self) -> None:
        broken = self._campaign("A", text="Texto A")
        self._campaign("B", text="Texto B")
        sender = _Sender()

        def flaky_read(root: Path, relative_path: str) -> bytes | None:
            if relative_path.startswith(f"data/campaigns/{broken}/"):
                raise OSError("share offline")
            return read_image(root, relative_path)

        with patch("promo_livros.campaign_send.read_image", side_effect=flaky_read):
            with self.assertLogs("promo_livros.campaign_send", level="WARNING"):
                self.assertEqual(self._invite(sender, _at(13, 15)), "sent")
        self.assertEqual(sender.sent[0][1], "Texto B")

    def test_no_groups_configured(self) -> None:
        self._campaign("A")
        config = SimpleNamespace(whatsapp_groups=())
        result = publish_due_invite(
            config, self.board, self.campaigns, _Sender(), root=self.root, now=_at(13, 15), rng=Random(0)
        )
        self.assertEqual(result, "no_groups")

    def test_last_invite_started_before_midnight_finishes_the_next_day(self) -> None:
        self._campaign("A")
        self.board.put_setting("invite_fixed_clock", "")
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(23, 59)), "sent")
        self.assertEqual(self._invite(sender, _at(0, 1, day=4)), "sent")
        self.assertEqual([chat for chat, _caption, _image in sender.sent], [group.chat_id for group in GROUPS])
        self.assertEqual(sender.sent[0][1:], sender.sent[1][1:])
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_LAST).status, "sent")

    def test_stale_sending_run_is_closed_and_today_proceeds(self) -> None:
        campaign_id = self._campaign("A")
        stale = self.campaigns.run_for("2026-11-01", INVITE_LAST)
        self.campaigns.lock_content(stale.id, campaign_id, 1, 1, "2026-11-01T22:10:00-03:00")
        sender = _Sender()
        with self.assertLogs("promo_livros.campaign_send", level="WARNING") as logs:
            self.assertEqual(self._invite(sender, _at(13, 15)), "sent")
        self.assertTrue(any("2026-11-01" in line for line in logs.output))
        self.assertEqual(self.campaigns.run_for("2026-11-01", INVITE_LAST).status, "sent")
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "sending")
        self.assertEqual(sender.sent[0][0], GROUPS[0].chat_id)

    def test_resume_with_a_fresh_store_keeps_the_same_content(self) -> None:
        self._campaign("A", images=3)
        sender = _Sender()
        self._invite(sender, _at(13, 15))
        self.campaigns.close()
        self.campaigns = CampaignStore(self.root / "board.sqlite")
        self.assertEqual(self._invite(sender, _at(13, 16)), "sent")
        self.assertEqual(sender.sent[0][1:], sender.sent[1][1:])
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "sent")

    def test_rejected_send_fails_without_marking_the_group(self) -> None:
        self._campaign("A")
        refused = _Sender(fail=WahaError("WAHA recusou o envio. HTTP 500.", session_down=False))
        self.assertEqual(self._invite(refused, _at(13, 15)), "failed")
        run = self.campaigns.run_for(DAY, INVITE_FIXED)
        self.assertEqual(self.campaigns.sent_chat_ids(run.id), set())
        self.assertEqual(run.status, "sending")

    def test_unexpected_send_error_releases_the_group_and_propagates(self) -> None:
        self._campaign("A")
        broken = _Sender(fail=RuntimeError("bug"))
        with self.assertLogs("promo_livros.campaign_send", level="ERROR"):
            with self.assertRaises(RuntimeError):
                self._invite(broken, _at(13, 15))
        run = self.campaigns.run_for(DAY, INVITE_FIXED)
        self.assertEqual(self.campaigns.sent_chat_ids(run.id), set())

    def test_crash_after_sending_never_sends_twice_to_the_same_group(self) -> None:
        self._campaign("A")
        sender = _Sender()
        with patch.object(self.campaigns, "finish_group_send", side_effect=sqlite3.OperationalError("locked")):
            with self.assertRaises(sqlite3.OperationalError):
                self._invite(sender, _at(13, 15))
        self.assertEqual(self._invite(sender, _at(13, 16)), "sent")
        self.assertEqual([chat for chat, _caption, _image in sender.sent], [group.chat_id for group in GROUPS])

    def test_claimed_group_is_not_sent(self) -> None:
        self._campaign("A")
        sender = _Sender()
        with patch.object(self.campaigns, "claim_group_send", return_value=False):
            self.assertEqual(self._invite(sender, _at(13, 15)), "waiting")
        self.assertEqual(sender.sent, [])

    def test_unreachable_locked_photo_waits_without_redrawing(self) -> None:
        self._campaign("A", images=3)
        sender = _Sender()
        self._invite(sender, _at(13, 15))
        locked = self.campaigns.run_for(DAY, INVITE_FIXED)
        with patch("promo_livros.campaign_send.read_image", side_effect=OSError("share offline")):
            with self.assertLogs("promo_livros.campaign_send", level="WARNING"):
                self.assertEqual(self._invite(sender, _at(13, 16)), "waiting")
        after = self.campaigns.run_for(DAY, INVITE_FIXED)
        self.assertEqual((after.image_id, after.text_id), (locked.image_id, locked.text_id))
        self.assertEqual(self._invite(sender, _at(13, 17)), "sent")
        self.assertEqual(sender.sent[0][1:], sender.sent[1][1:])

    def test_vanished_content_with_partial_send_closes_the_run(self) -> None:
        campaign_id = self._campaign("A")
        sender = _Sender()
        self._invite(sender, _at(13, 15))
        (self.root / f"data/campaigns/{campaign_id}/0.jpg").unlink()
        with self.assertLogs("promo_livros.campaign_send", level="WARNING"):
            self.assertEqual(self._invite(sender, _at(13, 16)), "sent")
        self.assertEqual(len(sender.sent), 1)
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "sent")


if __name__ == "__main__":
    unittest.main()
