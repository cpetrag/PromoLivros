import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from promo_livros.day_view import build_day_view, captions_for, load_day_rows
from promo_livros.models import Dispatch, NicheConfig, PublishSlot, QueuedPost, WhatsAppGroup
from promo_livros.storage import DayReadError, Storage


def _book(
    position: int,
    status: str = "ready",
    title: str = "Sapiens",
    niche_label: str = "Ficção",
) -> QueuedPost:
    return QueuedPost(
        day="2026-09-27",
        niche_key="ficcao",
        position=position,
        asin="B000000001",
        title=title,
        author="Autor",
        niche_label=niche_label,
        price_cents=3490,
        avg90_cents=5000,
        historic_min_cents=3490,
        rating=45,
        review_count=100,
        image_url=None,
        price_source="amazon",
        synopsis="",
        lowest_for_days=10,
        blurb="",
        status=status,
    )


class DayViewTests(unittest.TestCase):
    def test_empty_queue_has_no_grade(self) -> None:
        view = build_day_view(
            day="2026-09-27",
            slots=(PublishSlot(20, 0, "ficcao", 0),),
            niches=(NicheConfig("ficcao", "Ficção", 1),),
            per_niche=1,
            queue=(),
            dispatches=(),
            saved_groups=(),
            captions={},
        )
        self.assertIsNone(view)

    def test_slot_shows_book_price_and_group_status(self) -> None:
        group = WhatsAppGroup("Black Livros 01", "120363430990609445@g.us")
        dispatch = Dispatch(
            id=1,
            day="2026-09-27",
            niche_key="ficcao",
            position=0,
            asin="B000000001",
            title="Sapiens",
            price_cents=3490,
            chat_id=group.chat_id,
            group_name=group.name,
            caption="texto da noite",
            image_url=None,
            status="enviada",
            queued_at=datetime(2026, 9, 27, 23, 0, tzinfo=timezone.utc),
        )
        waiting = WhatsAppGroup("Black Livros 02", "120363410393297284@g.us")
        view = build_day_view(
            day="2026-09-27",
            slots=(PublishSlot(20, 0, "ficcao", 0),),
            niches=(NicheConfig("ficcao", "Ficção", 1),),
            per_niche=1,
            queue=(_book(0), _book(1, title="Reserva")),
            dispatches=(dispatch,),
            saved_groups=(group, waiting),
            captions={("ficcao", 0): "texto da noite", ("ficcao", 1): "texto reserva"},
        )

        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual(view.books[0].clock, "20:00")
        self.assertEqual(view.books[0].title, "Sapiens")
        self.assertEqual(view.books[0].price_label, "R$ 34,90")
        self.assertEqual(view.books[0].book_status, "pronto")
        self.assertEqual(view.books[0].caption, "texto da noite")
        self.assertEqual(view.books[0].groups[0].status_label, "enviada")
        self.assertEqual(view.books[0].groups[1].status_label, "ainda não entrou na fila")
        self.assertTrue(view.books[1].reserve)
        self.assertEqual(view.books[1].title, "Reserva")

    def test_reserve_uses_niche_config_label(self) -> None:
        view = build_day_view(
            day="2026-09-27",
            slots=(PublishSlot(20, 0, "ficcao", 0),),
            niches=(NicheConfig("ficcao", "Ficção", 1),),
            per_niche=1,
            queue=(_book(0), _book(1, title="Reserva", niche_label="")),
            dispatches=(),
            saved_groups=(),
            captions={},
        )
        self.assertIsNotNone(view)
        assert view is not None
        self.assertTrue(view.books[1].reserve)
        self.assertEqual(view.books[1].niche_label, "Ficção")


class ReadOnlyStoreTests(unittest.TestCase):
    def test_reads_queue_and_dispatch_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite"
            storage = Storage(db_path)
            storage.replace_queue("2026-09-27", [_book(0)])
            storage.enqueue_dispatch(
                day="2026-09-27",
                niche_key="ficcao",
                position=0,
                asin="B000000001",
                title="Sapiens",
                price_cents=3490,
                chat_id="120363430990609445@g.us",
                group_name="Black Livros 01",
                caption="texto da noite",
                image_url=None,
                now=datetime(2026, 9, 27, 23, 0, tzinfo=timezone.utc),
            )
            storage.close()

            queue, dispatches = load_day_rows(db_path, "2026-09-27")
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0].title, "Sapiens")
            self.assertEqual(len(dispatches), 1)
            self.assertEqual(dispatches[0].status, "na_fila")
            caps = captions_for(dispatches, queue, "")
            self.assertEqual(caps[("ficcao", 0)], "texto da noite")

    def test_missing_file_is_an_empty_day(self) -> None:
        missing = Path("nao-existe.sqlite")
        if missing.exists():
            missing.unlink()
        queue, dispatches = load_day_rows(missing, "2026-09-27")
        self.assertEqual(queue, [])
        self.assertEqual(dispatches, [])

    def test_locked_database_asks_for_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "locked.sqlite"
            storage = Storage(db_path)
            storage.replace_queue("2026-09-27", [_book(0)])
            storage.close()

            holder = sqlite3.connect(db_path)
            holder.execute("BEGIN EXCLUSIVE")
            try:
                with self.assertRaises(DayReadError) as ctx:
                    load_day_rows(db_path, "2026-09-27")
                self.assertIn("Atualize a página", str(ctx.exception))
            finally:
                holder.close()


if __name__ == "__main__":
    unittest.main()
