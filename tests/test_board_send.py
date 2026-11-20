import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from random import Random
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from promo_livros.board_send import publish_due
from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.campaign_store import CampaignStore
from promo_livros.models import WhatsAppGroup
from promo_livros.send_schedule import parse_schedule
from promo_livros.waha import WahaError

ZONE = ZoneInfo("America/Sao_Paulo")
GROUPS = (
    WhatsAppGroup("Black Livros 01", "120363430990609445@g.us"),
    WhatsAppGroup("Black Livros 02", "120363410393297284@g.us"),
)


class _Sender:
    def __init__(self, state: str = "connected", fail: WahaError | None = None) -> None:
        self.state = state
        self.fail = fail
        self.sent: list[tuple[str, bytes]] = []
        self.captions: list[str] = []

    def connection_state(self) -> str:
        return self.state

    def send_jpeg(self, chat_id: str, caption: str, image: bytes) -> str:
        if self.fail is not None:
            raise self.fail
        self.captions.append(caption)
        self.sent.append((chat_id, image))
        return f"msg-{len(self.sent)}"


class BoardSendTests(unittest.TestCase):
    def test_due_post_goes_to_each_group_with_the_gap_between_them(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root)
            sender = _Sender()
            now = datetime(2026, 9, 28, 10, 0, tzinfo=ZONE)

            self.assertEqual(_publish(root, store, sender, now), "sent")
            self.assertEqual(len(sender.sent), 1)
            self.assertEqual(_publish(root, store, sender, now + timedelta(seconds=10)), "waiting")
            self.assertEqual(len(sender.sent), 1)

            done = _publish(root, store, sender, now + timedelta(seconds=45))
            self.assertEqual(done, "sent")
            self.assertEqual([chat for chat, _image in sender.sent], [group.chat_id for group in GROUPS])
            self.assertEqual([post.clock for post in store.posts_for("2026-09-28")], ["10:40"])
            later = _publish(root, store, sender, now + timedelta(minutes=5))
            self.assertEqual(later, "idle")
            self.assertEqual(len(sender.sent), 2)
            store.close()

    def test_end_extended_for_the_day_lets_a_late_post_go(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root)
            sender = _Sender()
            store.add_post(
                day="2026-09-28",
                clock="22:10",
                caption="*Tarde*",
                image_path="data/cards/1.jpg",
                books=[_book()],
            )
            late = datetime(2026, 9, 28, 22, 10, tzinfo=ZONE)
            store.cancel_day("2026-09-27")
            for post in store.posts_for("2026-09-28")[:2]:
                store.mark_sent(post.id)
            self.assertEqual(_publish(root, store, sender, late), "idle")
            store.extend_send_end("2026-09-28", "22:11")
            self.assertEqual(_publish(root, store, sender, late), "sent")
            self.assertEqual(store.send_end_for("2026-09-29", "22:00"), "22:00")
            store.close()

    def test_a_recent_poll_holds_the_next_post(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root)
            sender = _Sender()
            now = datetime(2026, 9, 28, 10, 0, tzinfo=ZONE)
            quiet = (now - timedelta(seconds=10)).isoformat(timespec="seconds")

            self.assertEqual(_publish(root, store, sender, now, quiet_since=quiet), "waiting")
            self.assertEqual(sender.sent, [])
            store.close()

    def test_flag_off_future_clock_and_after_the_window_do_not_send(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root)
            sender = _Sender()
            store.set_sending(False)
            now = datetime(2026, 9, 28, 10, 0, tzinfo=ZONE)
            self.assertEqual(_publish(root, store, sender, now), "off")

            store.set_sending(True)
            self.assertEqual(_publish(root, store, sender, now - timedelta(hours=2)), "idle")
            self.assertEqual(sender.sent, [])
            store.close()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root)
            for post in store.posts_for("2026-09-28"):
                store.cancel("2026-09-28", post.id)
            store.add_post(
                day="2026-09-28",
                clock="22:00",
                caption="tarde",
                image_path="data/cards/1.jpg",
                books=[_book()],
            )
            sender = _Sender()
            self.assertEqual(
                _publish(root, store, sender, datetime(2026, 9, 28, 22, 5, tzinfo=ZONE)),
                "idle",
            )
            self.assertEqual(sender.sent, [])
            store.close()

    def test_disconnected_session_keeps_the_post(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root)
            now = datetime(2026, 9, 28, 10, 0, tzinfo=ZONE)
            offline = _Sender(state="disconnected")
            self.assertEqual(_publish(root, store, offline, now), "disconnected")
            self.assertEqual(offline.sent, [])
            down = _Sender(fail=WahaError("sem sessão", session_down=True))
            self.assertEqual(_publish(root, store, down, now), "waiting")
            self.assertEqual([post.clock for post in store.posts_for("2026-09-28")], ["10:00", "10:40"])
            sender = _Sender()
            self.assertEqual(_publish(root, store, sender, now), "sent")
            self.assertEqual(len(sender.sent), 1)
            store.close()

    def test_the_saved_list_picks_the_next_signature_once_per_post(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root)
            store.put_setting("signatures", "Primeira oferta | Segunda oferta")
            sender = _Sender()
            now = datetime(2026, 9, 28, 10, 0, tzinfo=ZONE)
            self.assertEqual(_publish(root, store, sender, now), "sent")
            self.assertEqual(_publish(root, store, sender, now + timedelta(seconds=45)), "sent")
            self.assertEqual(sender.captions[0], sender.captions[1])
            self.assertIn("Primeira oferta", sender.captions[0])
            self.assertNotIn("Segunda oferta", sender.captions[0])
            later = _publish(root, store, sender, now + timedelta(minutes=40))
            self.assertEqual(later, "sent")
            self.assertIn("Segunda oferta", sender.captions[2])
            store.close()

    def test_missing_card_does_not_send(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root, image=False)
            sender = _Sender()
            now = datetime(2026, 9, 28, 10, 0, tzinfo=ZONE)
            self.assertEqual(_publish(root, store, sender, now), "broken")
            self.assertEqual(sender.sent, [])
            store.close()

    def test_campaign_post_sends_campaign_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root)
            campaign_dir = root / "data" / "campaigns" / "1"
            campaign_dir.mkdir(parents=True)
            (campaign_dir / "a.jpg").write_bytes(b"campaign-jpeg")
            for post in store.posts_for("2026-09-28"):
                store.cancel("2026-09-28", post.id)
            store.add_campaign_post(
                "2026-09-28",
                "10:00",
                campaign_id=1,
                image_id=1,
                text_id=1,
                caption="Oferta da campanha",
                image_path="data/campaigns/1/a.jpg",
            )
            sender = _Sender()
            now = datetime(2026, 9, 28, 10, 0, tzinfo=ZONE)

            self.assertEqual(_publish(root, store, sender, now), "sent")
            self.assertEqual(sender.sent[0][1], b"campaign-jpeg")
            self.assertEqual(sender.captions[0], "Oferta da campanha")
            store.close()

    def test_campaign_post_keeps_registered_caption_without_queue_signature(self) -> None:
        # A assinatura da fila troca qualquer linha com link.amazon; campanha não pode passar por isso.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root)
            store.put_setting(
                "signatures",
                "🚨 As melhores ofertas nos nossos grupos: https://aqui.descontos.ai/clubepromos",
            )
            campaign_dir = root / "data" / "campaigns" / "1"
            campaign_dir.mkdir(parents=True)
            (campaign_dir / "a.jpg").write_bytes(b"campaign-jpeg")
            for post in store.posts_for("2026-09-28"):
                store.cancel("2026-09-28", post.id)
            caption = (
                "_Black da Amazon_\n"
                "_Todos cupons da Black da Amazon_\n\n"
                "*Cupons com até 40% de desconto para usar na Black da Amazon*\n"
                "https://link.amazon/B04Ox4N8C"
            )
            store.add_campaign_post(
                "2026-09-28",
                "10:00",
                campaign_id=1,
                image_id=1,
                text_id=1,
                caption=caption,
                image_path="data/campaigns/1/a.jpg",
            )
            sender = _Sender()
            now = datetime(2026, 9, 28, 10, 0, tzinfo=ZONE)

            self.assertEqual(_publish(root, store, sender, now), "sent")
            self.assertEqual(sender.captions[0], caption)
            self.assertNotIn("aqui.descontos.ai", sender.captions[0])
            store.close()

    def test_empty_campaign_post_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = _store(root)
            for post in store.posts_for("2026-09-28"):
                store.cancel("2026-09-28", post.id)
            post_id = store.add_campaign_post("2026-09-28", "10:00")
            sender = _Sender()
            now = datetime(2026, 9, 28, 10, 0, tzinfo=ZONE)

            self.assertEqual(_publish(root, store, sender, now), "skipped")
            self.assertEqual(sender.sent, [])
            self.assertNotIn(post_id, [post.id for post in store.posts_for("2026-09-28")])
            self.assertEqual(_publish(root, store, sender, now), "idle")
            store.close()


class MissingCampaignPhotoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.root = Path(self._folder.name)
        self.store = _store(self.root)
        self.campaigns = CampaignStore(self.root / "board.sqlite")
        self.addCleanup(self.store.close)
        self.addCleanup(self.campaigns.close)
        for post in self.store.posts_for("2026-09-28"):
            self.store.cancel("2026-09-28", post.id)
        self.campaign_id = self.campaigns.create("Campanha")
        self.text_id = self.campaigns.add_text(self.campaign_id, "Entre no grupo")
        self.now = datetime(2026, 9, 28, 10, 0, tzinfo=ZONE)

    def _photo(self, name: str, *, on_disk: bool) -> tuple[int, str]:
        relative = f"data/campaigns/{self.campaign_id}/{name}.jpg"
        image_id = self.campaigns.add_image(self.campaign_id, relative)
        if on_disk:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"jpeg-{name}".encode())
        return image_id, relative

    def _campaign_post(self, image_id: int, relative: str, clock: str = "10:00") -> int:
        return self.store.add_campaign_post(
            "2026-09-28",
            clock,
            campaign_id=self.campaign_id,
            image_id=image_id,
            text_id=self.text_id,
            caption="Convite",
            image_path=relative,
            locked_at="2026-09-28T08:00:00-03:00",
        )

    def _publish(self, now: datetime) -> str:
        config = SimpleNamespace(whatsapp_groups=GROUPS)
        return publish_due(
            config, self.store, _Sender(), root=self.root, now=now, campaigns=self.campaigns, rng=Random(1)
        )

    def test_missing_photo_is_replaced_by_another_from_the_same_campaign(self) -> None:
        missing_id, missing_path = self._photo("gone", on_disk=False)
        spare_id, spare_path = self._photo("spare", on_disk=True)
        post_id = self._campaign_post(missing_id, missing_path)
        sender = _Sender()
        config = SimpleNamespace(whatsapp_groups=GROUPS)

        result = publish_due(
            config, self.store, sender, root=self.root, now=self.now, campaigns=self.campaigns, rng=Random(1)
        )

        self.assertEqual(result, "sent")
        self.assertEqual(sender.sent[0][1], b"jpeg-spare")
        updated = next(post for post in self.store.posts_for("2026-09-28") if post.id == post_id)
        self.assertEqual((updated.image_id, updated.image_path), (spare_id, spare_path))
        self.assertEqual(updated.campaign_locked_at, "2026-09-28T08:00:00-03:00")

    def test_without_any_readable_photo_the_post_is_skipped_and_the_next_one_goes(self) -> None:
        missing_id, missing_path = self._photo("gone", on_disk=False)
        broken_id = self._campaign_post(missing_id, missing_path, "10:00")
        self.store.add_post(
            day="2026-09-28", clock="10:30", caption="*Livro*", image_path="data/cards/1.jpg", books=[_book()]
        )

        self.assertEqual(self._publish(self.now), "skipped")
        self.assertNotIn(broken_id, [post.id for post in self.store.posts_for("2026-09-28")])
        self.assertEqual(self._publish(self.now + timedelta(minutes=30)), "sent")

    def test_without_campaign_store_the_missing_photo_post_is_still_skipped(self) -> None:
        missing_id, missing_path = self._photo("gone", on_disk=False)
        self._campaign_post(missing_id, missing_path)
        config = SimpleNamespace(whatsapp_groups=GROUPS)

        result = publish_due(config, self.store, _Sender(), root=self.root, now=self.now)

        self.assertEqual(result, "skipped")


def _publish(
    root: Path,
    store: BoardStore,
    sender: _Sender,
    now: datetime,
    quiet_since: str | None = None,
) -> str:
    config = SimpleNamespace(whatsapp_groups=GROUPS)
    return publish_due(config, store, sender, root=root, now=now, quiet_since=quiet_since)


def _store(root: Path, *, image: bool = True) -> BoardStore:
    cards = root / "data" / "cards"
    cards.mkdir(parents=True)
    if image:
        (cards / "1.jpg").write_bytes(b"jpeg")
    store = BoardStore(root / "board.sqlite")
    store.set_sending(True)
    store.save_send_schedule(parse_schedule("08:00", "22:00", "40", "45"))
    store.add_post(
        day="2026-09-28",
        clock="10:00",
        caption="*Livro*",
        image_path="data/cards/1.jpg",
        books=[_book()],
    )
    store.add_post(
        day="2026-09-28",
        clock="10:40",
        caption="*Depois*",
        image_path="data/cards/1.jpg",
        books=[_book()],
    )
    return store


def _book() -> BoardBook:
    return BoardBook("Livro", "", 1000, 2000, 50, "Menor preço em 120 dias.", "https://example", "")


if __name__ == "__main__":
    unittest.main()
