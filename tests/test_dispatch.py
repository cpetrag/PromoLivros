import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from promo_livros.curation import publish_slot
from promo_livros.dispatch import drain_dispatches, enqueue_dispatches
from promo_livros.storage import Storage
from promo_livros.waha import WahaError
from tests.helpers import SAMPLE_YAML, make_product, write_config
from tests.test_day_plan import _FakeKeepa, _row

from promo_livros.config import load_config

EVENING = datetime(2026, 9, 25, 23, 10, tzinfo=timezone.utc)
GROUP_A = "120363430990609445@g.us"
GROUP_B = "120363410393297284@g.us"


class _Sender:
    def __init__(self, state: str = "connected", fail: WahaError | None = None) -> None:
        self.state = state
        self.fail = fail
        self.sent: list[str] = []

    def connection_state(self) -> str:
        return self.state

    def send(self, chat_id: str, caption: str, image_url: str | None) -> str:
        del caption, image_url
        if self.fail is not None:
            raise self.fail
        self.sent.append(chat_id)
        return f"msg-{len(self.sent)}"

    def close(self) -> None:
        return None


def _enabled_config(folder: Path):
    text = SAMPLE_YAML.replace(
        "whatsapp:\n  enabled: false\n",
        "whatsapp:\n"
        "  enabled: true\n"
        "  gap_seconds: 45\n"
        "  groups:\n"
        f'    - name: "Um"\n      id: "{GROUP_A}"\n'
        f'    - name: "Dois"\n      id: "{GROUP_B}"\n',
    )
    return load_config(write_config(folder, text), {"KEEPA_API_KEY": "test-key", "AMAZON_AFFILIATE_TAG": "loja-20"})


class DispatchTests(unittest.TestCase):
    def test_gap_sends_one_group_at_a_time_and_marks_the_book_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = _enabled_config(Path(folder))
            storage = Storage(Path(folder) / "promo.sqlite")
            enqueue_dispatches(
                config,
                storage,
                day="2026-09-25",
                niche_key="ficcao",
                position=0,
                asin="B00TEST001",
                title="Livro",
                price_cents=1_112,
                caption="texto",
                image_url="https://exemplo/capa.jpg",
                now=EVENING,
            )
            storage.replace_queue("2026-09-25", [_row("B00TEST001", position=0)])
            storage.mark_queue("2026-09-25", "ficcao", 0, "queued")
            sender = _Sender()

            first = drain_dispatches(config, storage, sender, EVENING)
            second = drain_dispatches(config, storage, sender, EVENING + timedelta(seconds=10))
            third = drain_dispatches(config, storage, sender, EVENING + timedelta(seconds=46))
            probe = sqlite3.connect(Path(folder) / "promo.sqlite")
            posts = probe.execute("SELECT COUNT(*) FROM posts").fetchone()
            probe.close()
            storage.close()

        self.assertEqual(first, "sent")
        self.assertEqual(second, "waiting")
        self.assertEqual(third, "sent")
        self.assertEqual(sender.sent, [GROUP_A, GROUP_B])
        self.assertEqual(posts[0], 1)

    def test_disconnected_whatsapp_stays_in_queue(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = _enabled_config(Path(folder))
            storage = Storage(Path(folder) / "promo.sqlite")
            enqueue_dispatches(
                config,
                storage,
                day="2026-09-25",
                niche_key="ficcao",
                position=0,
                asin="B00TEST001",
                title="Livro",
                price_cents=1_112,
                caption="texto",
                image_url=None,
                now=EVENING,
            )
            outcome = drain_dispatches(config, storage, _Sender(state="disconnected"), EVENING)
            pending = storage.next_dispatch()
            posted = storage.last_post("B00TEST001")
            storage.close()

        self.assertEqual(outcome, "waiting")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.status, "na_fila")
        self.assertIsNone(posted)

    def test_session_error_returns_the_row_to_the_queue(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = _enabled_config(Path(folder))
            storage = Storage(Path(folder) / "promo.sqlite")
            enqueue_dispatches(
                config,
                storage,
                day="2026-09-25",
                niche_key="ficcao",
                position=0,
                asin="B00TEST001",
                title="Livro",
                price_cents=1_112,
                caption="texto",
                image_url=None,
                now=EVENING,
            )
            sender = _Sender(fail=WahaError("WhatsApp ainda não está pareado.", session_down=True))
            outcome = drain_dispatches(config, storage, sender, EVENING)
            pending = storage.next_dispatch()
            storage.close()

        self.assertEqual(outcome, "waiting")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.status, "na_fila")

    def test_publish_slot_enqueues_and_sends_the_first_group(self) -> None:
        client = _FakeKeepa({"B00TEST001": make_product(asin="B00TEST001")}, {})
        with tempfile.TemporaryDirectory() as folder:
            config = _enabled_config(Path(folder))
            storage = Storage(Path(folder) / "promo.sqlite")
            storage.replace_queue("2026-09-25", [_row("B00TEST001", position=0)])
            sender = _Sender()
            outcome = publish_slot(
                config,
                client,
                storage,
                "ficcao",
                0,
                EVENING,
                dry_run=False,
                sender=sender,
            )
            posted = storage.last_post("B00TEST001")
            waiting = storage.next_dispatch()
            storage.close()

        self.assertEqual(outcome, "posted")
        self.assertEqual(sender.sent, [GROUP_A])
        self.assertIsNotNone(posted)
        self.assertEqual(waiting.chat_id, GROUP_B)


if __name__ == "__main__":
    unittest.main()
