import sqlite3
import tempfile
import unittest
from pathlib import Path

from promo_livros.campaign_rules import INVITE_FIXED, INVITE_LAST, RotationEntry
from promo_livros.campaign_store import MAX_NAME_LENGTH, MAX_TEXT_LENGTH, CampaignError, CampaignStore

# Esquema anterior às campanhas fixas/rotativas, para provar a migração de bancos já existentes.
_LEGACY_SCHEMA = """
CREATE TABLE campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE campaign_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fixed', 'last')),
    campaign_id INTEGER,
    manual INTEGER NOT NULL DEFAULT 0,
    image_id INTEGER,
    text_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sending', 'sent', 'skipped')),
    locked_at TEXT,
    sent_at TEXT,
    UNIQUE (day, kind)
);
CREATE TABLE campaign_run_groups (
    run_id INTEGER NOT NULL REFERENCES campaign_runs(id) ON DELETE CASCADE,
    chat_id TEXT NOT NULL,
    message_id TEXT,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (run_id, chat_id)
);
"""


class CampaignStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.store = CampaignStore(Path(self.folder.name) / "board.sqlite")

    def tearDown(self) -> None:
        self.store.close()
        self.folder.cleanup()

    def test_create_lists_in_order_and_counts_content(self) -> None:
        first = self.store.create("  Grupo   Terror ")
        second = self.store.create("Grupo Kindle")
        self.store.add_image(first, "data/campaigns/1/a.jpg")
        self.store.add_text(first, "Entre!")
        listed = self.store.campaigns()
        self.assertEqual([item.id for item in listed], [first, second])
        self.assertEqual(listed[0].name, "Grupo Terror")
        self.assertEqual((listed[0].image_count, listed[0].text_count), (1, 1))

    def test_ready_needs_active_image_and_text(self) -> None:
        campaign_id = self.store.create("A")
        self.assertEqual(self.store.ready_campaigns(), [])
        self.store.add_image(campaign_id, "data/campaigns/1/a.jpg")
        self.assertEqual(self.store.ready_campaigns(), [])
        self.store.add_text(campaign_id, "Texto")
        self.assertEqual([item.id for item in self.store.ready_campaigns()], [campaign_id])
        self.store.set_active(campaign_id, False)
        self.assertEqual(self.store.ready_campaigns(), [])

    def test_move_swaps_neighbors(self) -> None:
        first = self.store.create("A")
        second = self.store.create("B")
        self.store.move(second, -1)
        self.assertEqual([item.id for item in self.store.campaigns()], [second, first])
        self.store.move(second, -1)
        self.assertEqual([item.id for item in self.store.campaigns()], [second, first])

    def test_delete_removes_images_and_texts(self) -> None:
        campaign_id = self.store.create("A")
        image_id = self.store.add_image(campaign_id, "data/campaigns/1/a.jpg")
        text_id = self.store.add_text(campaign_id, "Texto")
        self.store.delete(campaign_id)
        self.assertIsNone(self.store.campaign(campaign_id))
        self.assertIsNone(self.store.image(image_id))
        self.assertIsNone(self.store.text(text_id))

    def test_validation_messages(self) -> None:
        with self.assertRaises(CampaignError):
            self.store.create("   ")
        campaign_id = self.store.create("A")
        with self.assertRaises(CampaignError):
            self.store.add_text(campaign_id, "  ")
        with self.assertRaises(CampaignError):
            self.store.add_text(campaign_id, "x" * (MAX_TEXT_LENGTH + 1))
        with self.assertRaises(CampaignError):
            self.store.add_image(999, "data/campaigns/999/a.jpg")

    def test_text_keeps_inner_lines(self) -> None:
        campaign_id = self.store.create("A")
        text_id = self.store.add_text(campaign_id, "Linha 1\r\nLinha 2\n")
        self.assertEqual(self.store.text(text_id).body, "Linha 1\nLinha 2")
        self.store.update_text(text_id, "Outro")
        self.assertEqual(self.store.text(text_id).body, "Outro")

    def test_run_is_one_per_day_and_kind(self) -> None:
        first = self.store.run_for("2026-11-03", INVITE_FIXED)
        again = self.store.run_for("2026-11-03", INVITE_FIXED)
        other = self.store.run_for("2026-11-03", INVITE_LAST)
        self.assertEqual(first.id, again.id)
        self.assertNotEqual(first.id, other.id)
        self.assertEqual(first.status, "pending")
        with self.assertRaises(CampaignError):
            self.store.run_for("2026-11-03", "outro")

    def test_manual_choice_only_while_pending(self) -> None:
        campaign_id = self.store.create("A")
        self.assertTrue(self.store.set_manual_campaign("2026-11-03", INVITE_FIXED, campaign_id))
        run = self.store.run_for("2026-11-03", INVITE_FIXED)
        self.assertEqual((run.campaign_id, run.manual), (campaign_id, True))
        self.store.lock_content(run.id, campaign_id, 1, 1, "2026-11-03T13:15:00-03:00")
        self.assertFalse(self.store.set_manual_campaign("2026-11-03", INVITE_FIXED, None))

    def test_last_used_follows_lock_time(self) -> None:
        first = self.store.create("A")
        second = self.store.create("B")
        self.assertIsNone(self.store.last_used_campaign())
        fixed = self.store.run_for("2026-11-03", INVITE_FIXED)
        last = self.store.run_for("2026-11-03", INVITE_LAST)
        self.store.lock_content(fixed.id, first, 10, 20, "2026-11-03T13:15:00-03:00")
        self.store.lock_content(last.id, second, 11, 21, "2026-11-03T22:10:00-03:00")
        self.assertEqual(self.store.last_used_campaign(), RotationEntry(second, 2))
        self.assertEqual(self.store.last_content(first), (10, 20))
        self.assertEqual(self.store.last_content(999), (None, None))
        self.store.delete(second)
        self.assertIsNone(self.store.last_used_campaign())

    def test_group_sends_and_last_sent_at(self) -> None:
        run = self.store.run_for("2026-11-03", INVITE_FIXED)
        self.assertIsNone(self.store.last_sent_at())
        for chat_id, message_id, stamp in (
            ("a@g.us", "msg-1", "2026-11-03T13:15:00-03:00"),
            ("b@g.us", "msg-2", "2026-11-03T13:15:45-03:00"),
        ):
            self.assertTrue(self.store.claim_group_send(run.id, chat_id, stamp))
            self.store.finish_group_send(run.id, chat_id, message_id, stamp)
        self.assertEqual(self.store.sent_chat_ids(run.id), {"a@g.us", "b@g.us"})
        self.assertEqual(self.store.last_sent_at(), "2026-11-03T13:15:45-03:00")
        self.store.mark_run_sent(run.id, "2026-11-03T13:15:45-03:00")
        self.assertEqual(self.store.run_for("2026-11-03", INVITE_FIXED).status, "sent")
        self.store.skip_run(run.id)
        self.assertEqual(self.store.run_for("2026-11-03", INVITE_FIXED).status, "sent")

    def test_group_claim_is_exclusive_and_counts_as_done(self) -> None:
        run = self.store.run_for("2026-11-03", INVITE_FIXED)
        self.assertTrue(self.store.claim_group_send(run.id, "a@g.us", "2026-11-03T13:15:00-03:00"))
        self.assertFalse(self.store.claim_group_send(run.id, "a@g.us", "2026-11-03T13:15:01-03:00"))
        self.assertEqual(self.store.sent_chat_ids(run.id), {"a@g.us"})
        self.store.finish_group_send(run.id, "a@g.us", "msg-1", "2026-11-03T13:15:02-03:00")
        self.assertEqual(self.store.last_sent_at(), "2026-11-03T13:15:02-03:00")
        self.store.release_group_send(run.id, "a@g.us")
        self.assertEqual(self.store.sent_chat_ids(run.id), {"a@g.us"})

    def test_released_claim_can_be_claimed_again(self) -> None:
        run = self.store.run_for("2026-11-03", INVITE_FIXED)
        self.store.claim_group_send(run.id, "a@g.us", "2026-11-03T13:15:00-03:00")
        self.store.release_group_send(run.id, "a@g.us")
        self.assertEqual(self.store.sent_chat_ids(run.id), set())
        self.assertIsNone(self.store.last_sent_at())
        self.assertTrue(self.store.claim_group_send(run.id, "a@g.us", "2026-11-03T13:16:00-03:00"))

    def test_open_sending_run_returns_the_oldest(self) -> None:
        self.assertIsNone(self.store.open_sending_run())
        campaign_id = self.store.create("A")
        today = self.store.run_for("2026-11-04", INVITE_FIXED)
        yesterday = self.store.run_for("2026-11-03", INVITE_LAST)
        self.store.run_for("2026-11-02", INVITE_LAST)
        self.store.lock_content(today.id, campaign_id, 1, 1, "2026-11-04T13:15:00-03:00")
        self.store.lock_content(yesterday.id, campaign_id, 1, 1, "2026-11-03T23:59:00-03:00")
        self.assertEqual(self.store.open_sending_run().id, yesterday.id)
        self.store.mark_run_sent(yesterday.id, "2026-11-04T00:01:00-03:00")
        self.assertEqual(self.store.open_sending_run().id, today.id)

    def test_delete_image_twice_returns_path_then_none(self) -> None:
        campaign_id = self.store.create("A")
        image_id = self.store.add_image(campaign_id, "data/campaigns/1/a.jpg")
        self.assertEqual(self.store.delete_image(image_id), "data/campaigns/1/a.jpg")
        self.assertIsNone(self.store.delete_image(image_id))

    def test_delete_text_removes_it(self) -> None:
        campaign_id = self.store.create("A")
        text_id = self.store.add_text(campaign_id, "Texto")
        self.store.delete_text(text_id)
        self.assertIsNone(self.store.text(text_id))
        self.assertEqual(self.store.texts(campaign_id), [])

    def test_text_turns_lone_carriage_return_into_newline(self) -> None:
        campaign_id = self.store.create("A")
        text_id = self.store.add_text(campaign_id, "Linha 1\rLinha 2")
        self.assertEqual(self.store.text(text_id).body, "Linha 1\nLinha 2")

    def test_manual_choice_none_returns_to_rotation(self) -> None:
        campaign_id = self.store.create("A")
        self.store.set_manual_campaign("2026-11-03", INVITE_FIXED, campaign_id)
        self.assertTrue(self.store.set_manual_campaign("2026-11-03", INVITE_FIXED, None))
        run = self.store.run_for("2026-11-03", INVITE_FIXED)
        self.assertEqual((run.campaign_id, run.manual), (None, False))

    def test_skipped_run_cannot_be_locked_or_sent(self) -> None:
        campaign_id = self.store.create("A")
        run = self.store.run_for("2026-11-03", INVITE_FIXED)
        self.store.skip_run(run.id)
        self.assertIsNone(self.store.lock_content(run.id, campaign_id, 1, 1, "2026-11-03T13:15:00-03:00"))
        self.store.mark_run_sent(run.id, "2026-11-03T13:15:45-03:00")
        self.assertEqual(self.store.run_for("2026-11-03", INVITE_FIXED).status, "skipped")

    def test_lock_content_on_missing_run_returns_none(self) -> None:
        self.assertIsNone(self.store.lock_content(999, 1, 1, 1, "2026-11-03T13:15:00-03:00"))

    def test_relock_keeps_first_lock_time(self) -> None:
        first = self.store.create("A")
        second = self.store.create("B")
        fixed = self.store.run_for("2026-11-03", INVITE_FIXED)
        last = self.store.run_for("2026-11-03", INVITE_LAST)
        self.store.lock_content(fixed.id, first, 10, 20, "2026-11-03T13:15:00-03:00")
        self.store.lock_content(last.id, second, 11, 21, "2026-11-03T22:10:00-03:00")
        relocked = self.store.lock_content(fixed.id, first, 10, 20, "2026-11-03T23:00:00-03:00")
        self.assertIsNotNone(relocked)
        self.assertEqual(relocked.status, "sending")
        self.assertEqual(self.store.last_used_campaign(), RotationEntry(second, 2))

    def test_peek_run_only_reads(self) -> None:
        self.assertIsNone(self.store.peek_run("2026-11-03", INVITE_FIXED))
        self.assertIsNone(self.store.peek_run("2026-11-03", INVITE_FIXED))
        created = self.store.run_for("2026-11-03", INVITE_FIXED)
        self.assertEqual(self.store.peek_run("2026-11-03", INVITE_FIXED), created)
        self.assertIsNone(self.store.peek_run("2026-11-03", INVITE_LAST))
        with self.assertRaises(CampaignError):
            self.store.peek_run("2026-11-03", "outro")

    def test_run_by_id(self) -> None:
        created = self.store.run_for("2026-11-03", INVITE_FIXED)
        self.assertEqual(self.store.run(created.id), created)
        self.assertIsNone(self.store.run(999))

    def test_lock_refuses_a_choice_changed_after_the_read(self) -> None:
        first = self.store.create("A")
        second = self.store.create("B")
        read = self.store.run_for("2026-11-03", INVITE_FIXED)
        self.store.set_manual_campaign("2026-11-03", INVITE_FIXED, second)
        self.assertIsNone(
            self.store.lock_content(read.id, first, 1, 1, "2026-11-03T13:15:00-03:00", expected=read)
        )
        current = self.store.run(read.id)
        self.assertEqual((current.status, current.campaign_id, current.manual), ("pending", second, True))
        locked = self.store.lock_content(current.id, second, 2, 2, "2026-11-03T13:15:05-03:00", expected=current)
        self.assertEqual((locked.status, locked.campaign_id), ("sending", second))

    def test_lock_refuses_a_run_another_sender_locked(self) -> None:
        first = self.store.create("A")
        read = self.store.run_for("2026-11-03", INVITE_FIXED)
        self.store.lock_content(read.id, first, 1, 1, "2026-11-03T13:15:00-03:00", expected=read)
        self.assertIsNone(
            self.store.lock_content(read.id, first, 2, 2, "2026-11-03T13:15:01-03:00", expected=read)
        )
        self.assertEqual(self.store.run(read.id).image_id, 1)

    def test_connection_uses_wal_and_waits_for_locks(self) -> None:
        connection = self.store._connection
        self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 5000)

    def test_long_name_is_rejected(self) -> None:
        long_name = "x" * (MAX_NAME_LENGTH + 1)
        with self.assertRaises(CampaignError):
            self.store.create(long_name)
        campaign_id = self.store.create("A")
        with self.assertRaises(CampaignError):
            self.store.rename(campaign_id, long_name)
        self.assertEqual(self.store.campaign(campaign_id).name, "A")

    def test_schedule_fields_and_ready_pools(self) -> None:
        store = self.store
        rotating = store.create("Rotativa")
        fixed = store.create("Fixa")
        store.add_image(rotating, "data/campaigns/1/a.jpg")
        store.add_text(rotating, "texto a")
        store.add_image(fixed, "data/campaigns/2/b.jpg")
        store.add_text(fixed, "texto b")
        store.set_schedule(fixed, "10:00", "2026-11-20")
        self.assertEqual([c.id for c in store.ready_rotating("2026-11-19")], [rotating])
        self.assertEqual([c.id for c in store.ready_fixed("2026-11-19")], [fixed])
        self.assertEqual(store.ready_fixed("2026-11-21"), [])

    def test_two_fixed_campaigns_same_clock_same_day(self) -> None:
        store = self.store
        a = store.create("A")
        b = store.create("B")
        for cid in (a, b):
            store.add_image(cid, f"p{cid}.jpg")
            store.add_text(cid, "oi")
            store.set_schedule(cid, "10:00", None)
        run_a = store.run_for_clock("2026-11-19", a, "10:00")
        run_b = store.run_for_clock("2026-11-19", b, "10:00")
        self.assertNotEqual(run_a.id, run_b.id)
        self.assertEqual(run_a.clock, "10:00")
        self.assertEqual(run_a.kind, "clock")
        self.assertEqual(run_a.campaign_id, a)
        self.assertEqual(store.run_for_clock("2026-11-19", a, "10:00").id, run_a.id)

    def test_peek_clock_run_reads_without_creating(self) -> None:
        campaign_id = self.store.create("A")
        self.assertIsNone(self.store.peek_clock_run("2026-11-19", campaign_id))
        created = self.store.run_for_clock("2026-11-19", campaign_id, "10:00")
        peeked = self.store.peek_clock_run("2026-11-19", campaign_id)
        self.assertEqual(peeked.id, created.id)
        self.assertIsNone(self.store.peek_clock_run("2026-11-20", campaign_id))

    def test_set_schedule_stores_and_clears_values(self) -> None:
        campaign_id = self.store.create("A")
        self.store.set_schedule(campaign_id, " 09:30 ", "2026-12-31")
        campaign = self.store.campaign(campaign_id)
        self.assertEqual((campaign.fixed_clock, campaign.valid_until), ("09:30", "2026-12-31"))
        self.store.set_schedule(campaign_id, None, None)
        campaign = self.store.campaign(campaign_id)
        self.assertEqual((campaign.fixed_clock, campaign.valid_until), (None, None))

    def test_set_schedule_rejects_bad_values(self) -> None:
        campaign_id = self.store.create("A")
        with self.assertRaises(CampaignError):
            self.store.set_schedule(campaign_id, "25:00", None)
        with self.assertRaises(CampaignError):
            self.store.set_schedule(campaign_id, None, "2026-13-40")
        with self.assertRaises(CampaignError):
            self.store.set_schedule(campaign_id, None, "20/11/2026")
        campaign = self.store.campaign(campaign_id)
        self.assertEqual((campaign.fixed_clock, campaign.valid_until), (None, None))

    def test_ready_on_requires_validity(self) -> None:
        campaign_id = self.store.create("A")
        self.store.add_image(campaign_id, "a.jpg")
        self.store.add_text(campaign_id, "oi")
        self.store.set_schedule(campaign_id, None, "2026-11-19")
        campaign = self.store.campaign(campaign_id)
        self.assertTrue(campaign.ready_on("2026-11-19"))
        self.assertFalse(campaign.ready_on("2026-11-20"))
        self.store.set_active(campaign_id, False)
        self.assertFalse(self.store.campaign(campaign_id).ready_on("2026-11-19"))

    def test_last_used_rotating_ignores_fixed_campaigns_and_clock_runs(self) -> None:
        rotating = self.store.create("Rotativa")
        fixed = self.store.create("Fixa")
        self.store.set_schedule(fixed, "10:00", None)
        self.assertIsNone(self.store.last_used_rotating())
        early = self.store.run_for("2026-11-03", INVITE_LAST)
        self.store.lock_content(early.id, rotating, 1, 1, "2026-11-03T22:00:00-03:00")
        late = self.store.run_for("2026-11-04", INVITE_LAST)
        self.store.lock_content(late.id, fixed, 2, 2, "2026-11-04T22:00:00-03:00")
        clock_run = self.store.run_for_clock("2026-11-05", rotating, "11:00")
        self.store.lock_content(clock_run.id, rotating, 3, 3, "2026-11-05T11:00:00-03:00")
        self.assertEqual(self.store.last_used_rotating(), RotationEntry(rotating, 1))

    def test_old_database_is_migrated_keeping_runs_and_groups(self) -> None:
        path = Path(self.folder.name) / "old.sqlite"
        legacy = sqlite3.connect(path)
        legacy.executescript(_LEGACY_SCHEMA)
        legacy.execute("INSERT INTO campaigns (name, position, created_at) VALUES ('A', 1, 'x')")
        legacy.execute("INSERT INTO campaign_runs (day, kind, campaign_id) VALUES ('2026-11-03', 'fixed', 1)")
        legacy.execute("INSERT INTO campaign_run_groups (run_id, chat_id, sent_at) VALUES (1, 'a@g.us', 'x')")
        legacy.commit()
        legacy.close()
        store = CampaignStore(path)
        try:
            self.assertEqual(store.campaign(1).fixed_clock, None)
            self.assertEqual(store.run(1).clock, None)
            self.assertEqual(store.sent_chat_ids(1), {"a@g.us"})
            self.assertEqual(store.run_for("2026-11-03", INVITE_FIXED).id, 1)
            run = store.run_for_clock("2026-11-03", 1, "10:00")
            self.assertEqual(run.kind, "clock")
            self.assertEqual(store.run_for("2026-11-03", INVITE_LAST).kind, "last")
        finally:
            store.close()
        reopened = CampaignStore(path)
        reopened.close()

    def _legacy_database(self, name: str) -> Path:
        path = Path(self.folder.name) / name
        legacy = sqlite3.connect(path)
        legacy.executescript(_LEGACY_SCHEMA)
        legacy.execute("INSERT INTO campaigns (name, position, created_at) VALUES ('A', 1, 'x')")
        legacy.execute("INSERT INTO campaign_runs (day, kind, campaign_id) VALUES ('2026-11-03', 'fixed', 1)")
        legacy.execute("INSERT INTO campaign_run_groups (run_id, chat_id, sent_at) VALUES (1, 'a@g.us', 'x')")
        legacy.commit()
        legacy.close()
        return path

    def test_migration_survives_orphan_campaign_runs_new_from_an_interrupted_run(self) -> None:
        path = self._legacy_database("orphan.sqlite")
        leftover = sqlite3.connect(path)
        leftover.execute("CREATE TABLE campaign_runs_new (id INTEGER PRIMARY KEY, junk TEXT)")
        leftover.commit()
        leftover.close()
        store = CampaignStore(path)
        try:
            self.assertEqual(store.run(1).day, "2026-11-03")
            self.assertEqual(store.sent_chat_ids(1), {"a@g.us"})
            inspector = sqlite3.connect(path)
            try:
                names = {row[0] for row in inspector.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            finally:
                inspector.close()
            self.assertNotIn("campaign_runs_new", names)
        finally:
            store.close()

    def test_failed_migration_rolls_back_and_keeps_history(self) -> None:
        path = self._legacy_database("rollback.sqlite")
        blocker = sqlite3.connect(path)
        # Um índice com o nome da tabela nova faz o CREATE falhar no meio da reconstrução.
        blocker.execute("CREATE INDEX campaign_runs_new ON campaign_runs(day)")
        blocker.commit()
        blocker.close()
        with self.assertRaises(sqlite3.Error):
            CampaignStore(path)
        check = sqlite3.connect(path)
        try:
            self.assertEqual(check.execute("SELECT COUNT(*) FROM campaign_runs").fetchone()[0], 1)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM campaign_run_groups").fetchone()[0], 1)
            self.assertNotIn("'clock'", check.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'campaign_runs' AND type = 'table'"
            ).fetchone()[0])
        finally:
            check.close()

    def test_move_down_and_noop_at_bottom(self) -> None:
        first = self.store.create("A")
        second = self.store.create("B")
        self.store.move(first, 1)
        self.assertEqual([item.id for item in self.store.campaigns()], [second, first])
        self.store.move(first, 1)
        self.assertEqual([item.id for item in self.store.campaigns()], [second, first])
