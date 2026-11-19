import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from promo_livros.poll_commands import PollCommandError, parse_group_command
from promo_livros.polls import PollError, PollStore, advance_polls, handle_webhook, result_message
from promo_livros.waha import WahaError

NOW = datetime(2026, 10, 5, 20, 0, tzinfo=timezone(timedelta(hours=-3)))
GROUP = "120363430990609445@g.us"


class CommandTests(unittest.TestCase):
    def test_enquete_reads_question_options_and_flags(self) -> None:
        command = parse_group_command(
            "!enquete Qual livro? | Ficção | Terror | Romance --fixar 7d --multi --fecha 48h"
        )
        assert command is not None
        self.assertEqual(command.question, "Qual livro?")
        self.assertEqual(command.options, ("Ficção", "Terror", "Romance"))
        self.assertTrue(command.multiple)
        self.assertEqual(command.pin, "7d")
        self.assertEqual(command.closes_after, timedelta(hours=48))

    def test_resultado_and_encerrar_are_exact_commands(self) -> None:
        self.assertEqual(parse_group_command("!resultado"), "resultado")
        self.assertEqual(parse_group_command("  !encerrar  "), "encerrar")
        self.assertIsNone(parse_group_command("bom dia"))

    def test_enquete_rejects_a_single_option(self) -> None:
        with self.assertRaises(PollCommandError):
            parse_group_command("!enquete Só uma? | Única")


class StoreTests(unittest.TestCase):
    def test_newer_vote_replaces_and_empty_vote_retracts(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = PollStore(Path(folder) / "polls.sqlite")
            poll_id = store.create(
                chat_id=GROUP,
                group_name="Black Livros 01",
                question="Qual?",
                options=("A", "B"),
                multiple=False,
                pin=None,
                send_at=NOW,
                closes_at=None,
            )
            store.mark_sent(poll_id, "true_g_AAA", pin_ok=False)
            first = _vote("evt-1", "true_g_AAA", "5511@c.us", ["A"], 100)
            second = _vote("evt-2", "true_g_AAA", "5511@lid", ["B"], 200)
            retracted = _vote("evt-3", "true_g_AAA", "5511@c.us", [], 300)
            self.assertEqual(handle_webhook(store, first, session="promo-livros", links={"5511@lid": "5511@c.us"}), "ok")
            self.assertEqual(handle_webhook(store, second, session="promo-livros", links={"5511@lid": "5511@c.us"}), "ok")
            detail = store.detail(poll_id)
            self.assertEqual(detail.counts["B"], 1)
            self.assertEqual(detail.voters, 1)
            self.assertEqual(handle_webhook(store, retracted, session="promo-livros", links={}), "ok")
            self.assertEqual(store.detail(poll_id).voters, 0)
            self.assertEqual(handle_webhook(store, second, session="promo-livros", links={"5511@lid": "5511@c.us"}), "duplicate")
            self.assertEqual(store.detail(poll_id).voters, 0)
            store.close()

    def test_vote_matches_the_poll_token_not_the_sender_phone(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = PollStore(Path(folder) / "polls.sqlite")
            first = store.create(
                chat_id=GROUP,
                group_name="Black Livros 01",
                question="Qual?",
                options=("A", "B"),
                multiple=False,
                pin=None,
                send_at=NOW,
                closes_at=None,
            )
            second = store.create(
                chat_id="120363410393297284@g.us",
                group_name="Black Livros 02",
                question="Qual?",
                options=("A", "B"),
                multiple=False,
                pin=None,
                send_at=NOW,
                closes_at=None,
            )
            store.mark_sent(first, "true_120363430990609445@g.us_3EB0C2A4C74B28615CADF5_5511@c.us", pin_ok=False)
            store.mark_sent(second, "true_120363410393297284@g.us_3EB04855E4DCCF011ECF42_5511@c.us", pin_ok=False)
            incoming = "false_120363430990609445@g.us_3EB0C2A4C74B28615CADF5_5511@c.us"
            handle_webhook(store, _vote("evt-1", incoming, "5522@c.us", ["A"], 10), session="promo-livros", links={})
            self.assertEqual(store.detail(first).voters, 1)
            self.assertEqual(store.detail(second).voters, 0)
            store.close()

    def test_older_timestamp_and_failed_vote_do_not_replace_the_ballot(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = PollStore(Path(folder) / "polls.sqlite")
            poll_id = store.create(
                chat_id=GROUP,
                group_name="Black Livros 01",
                question="Qual?",
                options=("A", "B"),
                multiple=False,
                pin=None,
                send_at=NOW,
                closes_at=None,
            )
            store.mark_sent(poll_id, "true_g_AAA", pin_ok=False)
            handle_webhook(store, _vote("evt-1", "true_g_AAA", "5511@c.us", ["A"], 200), session="promo-livros", links={})
            handle_webhook(store, _vote("evt-old", "true_g_AAA", "5511@c.us", ["B"], 100), session="promo-livros", links={})
            failed = _vote("evt-fail", "true_g_AAA", "5522@c.us", [], 300)
            failed["event"] = "poll.vote.failed"
            handle_webhook(store, failed, session="promo-livros", links={})
            detail = store.detail(poll_id)
            self.assertEqual(detail.counts["A"], 1)
            self.assertEqual(detail.voters, 1)
            self.assertEqual(detail.failed_votes, 1)
            store.close()

    def test_admin_command_schedules_a_poll_for_the_same_group(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = PollStore(Path(folder) / "polls.sqlite")
            body = _message("!enquete Qual? | A | B --fixar 24h", participant="9@c.us")
            handle_webhook(
                store,
                body,
                session="promo-livros",
                links={},
                is_admin=lambda chat_id, participant: participant == "9@c.us",
                allowed_groups={GROUP},
                now=NOW,
            )
            rows = store.list_polls()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "agendada")
            self.assertEqual(rows[0].pin, "24h")
            ignored = _message("!enquete Qual? | A | B", participant="1@c.us")
            handle_webhook(
                store,
                ignored,
                session="promo-livros",
                links={},
                is_admin=lambda chat_id, participant: False,
                allowed_groups={GROUP},
                now=NOW,
            )
            self.assertEqual(len(store.list_polls()), 1)
            store.close()


class CycleTests(unittest.TestCase):
    def test_due_poll_is_sent_and_pin_failure_does_not_cancel_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = PollStore(Path(folder) / "polls.sqlite")
            poll_id = store.create(
                chat_id=GROUP,
                group_name="Black Livros 01",
                question="Qual?",
                options=("A", "B"),
                multiple=False,
                pin="7d",
                send_at=NOW,
                closes_at=NOW + timedelta(hours=1),
            )
            sender = _Sender(pin_error=WahaError("não implementado", session_down=False, unsupported=True))
            self.assertEqual(advance_polls(store, sender, NOW, gap_seconds=45, other_sent_at=None), "sent")
            self.assertEqual(store.detail(poll_id).status, "ativa")
            self.assertEqual(store.detail(poll_id).message_id, "poll-1")
            self.assertFalse(store.detail(poll_id).pin_ok)
            self.assertEqual(len(sender.polls), 1)
            self.assertEqual(advance_polls(store, sender, NOW, gap_seconds=45, other_sent_at=None), "idle")
            self.assertEqual(len(sender.polls), 1)
            store.close()

    def test_deadline_posts_the_result_and_unpins(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = PollStore(Path(folder) / "polls.sqlite")
            poll_id = store.create(
                chat_id=GROUP,
                group_name="Black Livros 01",
                question="Qual?",
                options=("A", "B"),
                multiple=False,
                pin="24h",
                send_at=NOW,
                closes_at=NOW + timedelta(minutes=5),
            )
            sender = _Sender()
            advance_polls(store, sender, NOW, gap_seconds=45, other_sent_at=None)
            store.mark_pin(poll_id, True)
            handle_webhook(store, _vote("evt-1", "poll-1", "5511@c.us", ["A"], 10), session="promo-livros", links={})
            later = NOW + timedelta(minutes=6)
            self.assertEqual(advance_polls(store, sender, later, gap_seconds=45, other_sent_at=None), "sent")
            self.assertEqual(store.detail(poll_id).status, "encerrada")
            self.assertIn("Qual?", sender.texts[-1])
            self.assertIn("100%", sender.texts[-1])
            self.assertIn("1 votante", sender.texts[-1])
            self.assertEqual(sender.unpinned, ["poll-1"])
            store.close()

    def test_restart_still_closes_at_the_saved_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "polls.sqlite"
            store = PollStore(path)
            poll_id = store.create(
                chat_id=GROUP,
                group_name="Black Livros 01",
                question="Qual?",
                options=("A", "B"),
                multiple=True,
                pin=None,
                send_at=NOW,
                closes_at=NOW + timedelta(hours=2),
            )
            store.mark_sent(poll_id, "poll-9", pin_ok=False)
            store.close()
            reopened = PollStore(path)
            sender = _Sender()
            self.assertEqual(
                advance_polls(reopened, sender, NOW + timedelta(hours=2), gap_seconds=45, other_sent_at=None),
                "sent",
            )
            self.assertEqual(reopened.detail(poll_id).status, "encerrada")
            reopened.close()


class TextTests(unittest.TestCase):
    def test_result_uses_ten_emoji_blocks(self) -> None:
        text = result_message("Qual?", ("A", "B"), {"A": 1, "B": 1}, 2, partial=False)
        self.assertIn("🟩🟩🟩🟩🟩⬜⬜⬜⬜⬜", text)
        self.assertIn("2 votantes", text)


def _vote(event_id: str, poll_id: str, voter: str, options: list[str], timestamp: int) -> dict:
    return {
        "id": event_id,
        "event": "poll.vote",
        "session": "promo-livros",
        "payload": {
            "vote": {
                "from": voter,
                "selectedOptions": options,
                "timestamp": timestamp,
            },
            "poll": {"id": poll_id},
        },
    }


def _message(text: str, *, participant: str) -> dict:
    return {
        "id": f"msg-{participant}-{text[:24]}",
        "event": "message",
        "session": "promo-livros",
        "payload": {
            "from": GROUP,
            "participant": participant,
            "body": text,
            "fromMe": False,
        },
    }


class _Sender:
    def __init__(self, pin_error: WahaError | None = None) -> None:
        self.pin_error = pin_error
        self.polls: list[tuple[str, str, tuple[str, ...], bool]] = []
        self.texts: list[str] = []
        self.unpinned: list[str] = []

    def connection_state(self) -> str:
        return "connected"

    def send_poll(self, chat_id: str, question: str, options: tuple[str, ...] | list[str], multiple: bool) -> str:
        self.polls.append((chat_id, question, tuple(options), multiple))
        return f"poll-{len(self.polls)}"

    def send(self, chat_id: str, caption: str, image_url: str | None) -> str:
        del chat_id, image_url
        self.texts.append(caption)
        return "text-1"

    def pin_message(self, chat_id: str, message_id: str, duration: int) -> None:
        del chat_id, message_id, duration
        if self.pin_error is not None:
            raise self.pin_error

    def unpin_message(self, chat_id: str, message_id: str) -> None:
        del chat_id
        self.unpinned.append(message_id)


class ExportTests(unittest.TestCase):
    def test_csv_lists_the_current_ballot(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = PollStore(Path(folder) / "polls.sqlite")
            poll_id = store.create(
                chat_id=GROUP,
                group_name="Black Livros 01",
                question="Qual?",
                options=("A", "B", "C"),
                multiple=True,
                pin=None,
                send_at=NOW,
                closes_at=None,
            )
            store.mark_sent(poll_id, "true_g_AAA", pin_ok=False)
            handle_webhook(
                store,
                _vote("evt-1", "true_g_AAA", "5511@c.us", ["A", "C"], 10),
                session="promo-livros",
                links={},
            )
            csv_text = store.votes_csv(poll_id)
            self.assertIn("5511@c.us", csv_text)
            self.assertIn("A | C", csv_text)
            self.assertNotIn("evt-1", csv_text)
            store.close()


class PageTests(unittest.TestCase):
    def test_detail_shows_the_bar_and_participation(self) -> None:
        from promo_livros.dashboard_pages import render_poll_detail

        with tempfile.TemporaryDirectory() as folder:
            store = PollStore(Path(folder) / "polls.sqlite")
            poll_id = store.create(
                chat_id=GROUP,
                group_name="Black Livros 01",
                question="Qual livro?",
                options=("Ficção", "Terror"),
                multiple=False,
                pin="7d",
                send_at=NOW,
                closes_at=None,
            )
            store.mark_sent(poll_id, "true_g_AAA", pin_ok=False)
            handle_webhook(store, _vote("evt-1", "true_g_AAA", "5511@c.us", ["Ficção"], 10), session="promo-livros", links={})
            html = render_poll_detail(store.detail(poll_id), members=10, notice=None, zone_name="America/Sao_Paulo")
            self.assertIn("Qual livro?", html)
            self.assertIn("Enquetes", html)
            self.assertIn("width:100%", html)
            self.assertIn("10% dos 10 membros", html)
            self.assertIn("não confirmado", html)
            store.close()


class JsonShapeTests(unittest.TestCase):
    def test_webhook_ignores_another_session(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = PollStore(Path(folder) / "polls.sqlite")
            body = _vote("evt-1", "true_g_AAA", "5511@c.us", ["A"], 10)
            body["session"] = "esteira"
            self.assertEqual(handle_webhook(store, body, session="promo-livros", links={}), "ignored")
            store.close()


class BatchTests(unittest.TestCase):
    def test_all_groups_share_one_result_and_wait_between_sends(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = PollStore(Path(folder) / "polls.sqlite")
            try:
                first = store.create_for_groups(
                    ((GROUP, "Black Livros 01"), ("120363410393297284@g.us", "Black Livros 02")),
                    question="Qual?",
                    options=("A", "B"),
                    multiple=False,
                    pin=None,
                    send_at=NOW,
                    closes_at=None,
                )
                rows = store.list_polls()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].group_name, "Todos os grupos")
                self.assertEqual(rows[0].id, first)
                sender = _Sender()
                self.assertEqual(advance_polls(store, sender, NOW, gap_seconds=45, other_sent_at=None), "sent")
                self.assertEqual(len(sender.polls), 1)
                self.assertEqual(advance_polls(store, sender, NOW, gap_seconds=45, other_sent_at=None), "waiting")
                later = NOW + timedelta(seconds=45)
                self.assertEqual(advance_polls(store, sender, later, gap_seconds=45, other_sent_at=None), "sent")
                self.assertEqual([item[0] for item in sender.polls], [GROUP, "120363410393297284@g.us"])
                ids = store.batch_ids(first)
                store.mark_sent(ids[0], "poll-a", pin_ok=False)
                store.mark_sent(ids[1], "poll-b", pin_ok=False)
                handle_webhook(store, _vote("v1", "poll-a", "5511@c.us", ["A"], 10), session="promo-livros", links={})
                handle_webhook(store, _vote("v2", "poll-b", "5522@c.us", ["B"], 20), session="promo-livros", links={})
                view = store.combined(first)
                self.assertEqual(view.voters, 2)
                self.assertEqual(view.counts["A"], 1)
                self.assertEqual(view.counts["B"], 1)
                self.assertEqual(view.group_name, "Todos os grupos")
                csv_text = store.votes_csv(first)
                self.assertIn("Black Livros 01", csv_text)
                self.assertIn("Black Livros 02", csv_text)
                after = later + timedelta(seconds=45)
                for item in ids:
                    store.close_now(item, after)
                self.assertEqual(advance_polls(store, sender, after, gap_seconds=45, other_sent_at=None), "sent")
                self.assertIn("Total dos 2 grupos", sender.texts[-1])
                self.assertIn("50%", sender.texts[-1])
                self.assertEqual(advance_polls(store, sender, after, gap_seconds=45, other_sent_at=None), "waiting")
            finally:
                store.close()

    def test_form_can_target_every_group(self) -> None:
        from promo_livros.dashboard_pages import render_poll_list

        html = render_poll_list([], [("Black Livros 01", GROUP)], notice=None, chat_id="", status="")
        self.assertIn('value="todos">Todos os grupos', html)


if __name__ == "__main__":
    unittest.main()
