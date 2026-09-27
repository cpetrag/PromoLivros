from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from promo_livros.models import Dispatch, LastPost, QueuedPost


class DayReadError(Exception):
    """O SQLite está ocupado. A página pede para atualizar."""


_BUSY_QUEUE_MESSAGE = "Atualize a página. A fila está ocupada."
_UNREADABLE_QUEUE_MESSAGE = "Não consegui ler a fila de hoje."


def day_read_error_from_sqlite(exc: sqlite3.Error) -> DayReadError:
    code = getattr(exc, "sqlite_errorcode", None)
    if code == sqlite3.SQLITE_BUSY:
        return DayReadError(_BUSY_QUEUE_MESSAGE)
    return DayReadError(_UNREADABLE_QUEUE_MESSAGE)


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._setup()

    def close(self) -> None:
        self._connection.close()

    def _setup(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asin TEXT NOT NULL,
                title TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                posted_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_posts_asin_posted
                ON posts (asin, posted_at DESC);

            CREATE TABLE IF NOT EXISTS category_cache (
                domain_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                category_id INTEGER NOT NULL,
                resolved_at TEXT NOT NULL,
                PRIMARY KEY (domain_id, name)
            );

            CREATE TABLE IF NOT EXISTS subcategory_cache (
                domain_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                child_ids TEXT NOT NULL,
                resolved_at TEXT NOT NULL,
                PRIMARY KEY (domain_id, category_id)
            );

            CREATE TABLE IF NOT EXISTS daily_queue (
                day TEXT NOT NULL,
                niche_key TEXT NOT NULL,
                position INTEGER NOT NULL,
                asin TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                niche_label TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                avg90_cents INTEGER NOT NULL,
                historic_min_cents INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                review_count INTEGER NOT NULL,
                image_url TEXT,
                price_source TEXT NOT NULL,
                synopsis TEXT NOT NULL,
                lowest_for_days INTEGER,
                blurb TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (day, niche_key, position)
            );

            CREATE TABLE IF NOT EXISTS dispatches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                niche_key TEXT NOT NULL,
                position INTEGER NOT NULL,
                asin TEXT NOT NULL,
                title TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                group_name TEXT NOT NULL,
                caption TEXT NOT NULL,
                image_url TEXT,
                status TEXT NOT NULL,
                wa_message_id TEXT,
                error TEXT,
                queued_at TEXT NOT NULL,
                sent_at TEXT,
                UNIQUE (day, niche_key, position, chat_id)
            );
            """
        )
        self._connection.commit()

    def has_queue(self, day: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM daily_queue WHERE day = ? LIMIT 1",
            (day,),
        ).fetchone()
        return row is not None

    def day_has_posted(self, day: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM daily_queue WHERE day = ? AND status = 'posted' LIMIT 1",
            (day,),
        ).fetchone()
        return row is not None

    def replace_queue(self, day: str, rows: list[QueuedPost]) -> bool:
        """Troca a fila do dia. Se algum livro já foi publicado, a fila fica como está."""
        if self.day_has_posted(day):
            return False
        with self._connection:
            self._connection.execute("DELETE FROM daily_queue WHERE day = ?", (day,))
            self._connection.executemany(
                """
                INSERT INTO daily_queue (
                    day, niche_key, position, asin, title, author, niche_label,
                    price_cents, avg90_cents, historic_min_cents, rating, review_count,
                    image_url, price_source, synopsis, lowest_for_days, blurb, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.day,
                        row.niche_key,
                        row.position,
                        row.asin,
                        row.title,
                        row.author,
                        row.niche_label,
                        row.price_cents,
                        row.avg90_cents,
                        row.historic_min_cents,
                        row.rating,
                        row.review_count,
                        row.image_url,
                        row.price_source,
                        row.synopsis,
                        row.lowest_for_days,
                        row.blurb,
                        row.status,
                    )
                    for row in rows
                ],
            )
        return True

    def queue_for_niche(self, day: str, niche_key: str) -> list[QueuedPost]:
        rows = self._connection.execute(
            """
            SELECT day, niche_key, position, asin, title, author, niche_label,
                   price_cents, avg90_cents, historic_min_cents, rating, review_count,
                   image_url, price_source, synopsis, lowest_for_days, blurb, status
            FROM daily_queue
            WHERE day = ? AND niche_key = ?
            ORDER BY position
            """,
            (day, niche_key),
        ).fetchall()
        return [_queued(row) for row in rows]

    def queue_for_day(self, day: str) -> list[QueuedPost]:
        rows = self._connection.execute(
            """
            SELECT day, niche_key, position, asin, title, author, niche_label,
                   price_cents, avg90_cents, historic_min_cents, rating, review_count,
                   image_url, price_source, synopsis, lowest_for_days, blurb, status
            FROM daily_queue
            WHERE day = ?
            ORDER BY niche_key, position
            """,
            (day,),
        ).fetchall()
        return [_queued(row) for row in rows]

    def dispatches_for_day(self, day: str) -> list[Dispatch]:
        rows = self._connection.execute(
            """
            SELECT id, day, niche_key, position, asin, title, price_cents, chat_id,
                   group_name, caption, image_url, status, queued_at
            FROM dispatches
            WHERE day = ?
            ORDER BY niche_key, position, id
            """,
            (day,),
        ).fetchall()
        return [_dispatch(row) for row in rows]

    @classmethod
    def open_readonly(cls, path: Path) -> Storage:
        store = cls.__new__(cls)
        store.path = path
        uri = f"{path.resolve().as_uri()}?mode=ro"
        try:
            store._connection = sqlite3.connect(uri, uri=True, timeout=0.2)
        except sqlite3.Error as exc:
            raise day_read_error_from_sqlite(exc) from exc
        store._connection.row_factory = sqlite3.Row
        return store

    def mark_queue(self, day: str, niche_key: str, position: int, status: str) -> None:
        self._connection.execute(
            """
            UPDATE daily_queue
            SET status = ?
            WHERE day = ? AND niche_key = ? AND position = ?
            """,
            (status, day, niche_key, position),
        )
        self._connection.commit()

    def cached_children(self, domain_id: int, category_id: int) -> list[int] | None:
        row = self._connection.execute(
            """
            SELECT child_ids
            FROM subcategory_cache
            WHERE domain_id = ? AND category_id = ?
            """,
            (domain_id, category_id),
        ).fetchone()
        if row is None:
            return None
        text = row["child_ids"]
        if not text:
            return []
        return [int(part) for part in text.split(",") if part]

    def save_children(self, domain_id: int, category_id: int, child_ids: list[int], resolved_at: datetime) -> None:
        self._connection.execute(
            """
            INSERT INTO subcategory_cache (domain_id, category_id, child_ids, resolved_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (domain_id, category_id) DO UPDATE SET
                child_ids = excluded.child_ids,
                resolved_at = excluded.resolved_at
            """,
            (
                domain_id,
                category_id,
                ",".join(str(child_id) for child_id in child_ids),
                resolved_at.astimezone(timezone.utc).isoformat(),
            ),
        )
        self._connection.commit()

    def last_post(self, asin: str) -> LastPost | None:
        row = self._connection.execute(
            """
            SELECT asin, title, price_cents, posted_at
            FROM posts
            WHERE asin = ?
            ORDER BY posted_at DESC
            LIMIT 1
            """,
            (asin,),
        ).fetchone()
        if row is None:
            return None
        posted_at = datetime.fromisoformat(row["posted_at"])
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        return LastPost(
            asin=row["asin"],
            title=row["title"],
            price_cents=row["price_cents"],
            posted_at=posted_at,
        )

    def enqueue_dispatch(
        self,
        *,
        day: str,
        niche_key: str,
        position: int,
        asin: str,
        title: str,
        price_cents: int,
        chat_id: str,
        group_name: str,
        caption: str,
        image_url: str | None,
        now: datetime,
    ) -> bool:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO dispatches (
                day, niche_key, position, asin, title, price_cents, chat_id, group_name,
                caption, image_url, status, queued_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'na_fila', ?)
            """,
            (
                day,
                niche_key,
                position,
                asin,
                title,
                price_cents,
                chat_id,
                group_name,
                caption,
                image_url,
                now.astimezone(timezone.utc).isoformat(),
            ),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def next_dispatch(self) -> Dispatch | None:
        row = self._connection.execute(
            """
            SELECT id, day, niche_key, position, asin, title, price_cents, chat_id,
                   group_name, caption, image_url, status, queued_at
            FROM dispatches
            WHERE status = 'na_fila'
            ORDER BY queued_at, id
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return _dispatch(row)

    def claim_dispatch(self, dispatch_id: int) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE dispatches
            SET status = 'enviando', error = NULL
            WHERE id = ? AND status = 'na_fila'
            """,
            (dispatch_id,),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def release_dispatch(self, dispatch_id: int) -> None:
        self._connection.execute(
            """
            UPDATE dispatches
            SET status = 'na_fila'
            WHERE id = ? AND status = 'enviando'
            """,
            (dispatch_id,),
        )
        self._connection.commit()

    def release_stale_sends(self, older_than: datetime) -> None:
        if older_than.tzinfo is None:
            older_than = older_than.replace(tzinfo=timezone.utc)
        self._connection.execute(
            """
            UPDATE dispatches
            SET status = 'na_fila'
            WHERE status = 'enviando' AND queued_at < ?
            """,
            (older_than.astimezone(timezone.utc).isoformat(),),
        )
        self._connection.commit()

    def mark_dispatch_sent(self, dispatch_id: int, message_id: str, sent_at: datetime) -> None:
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        self._connection.execute(
            """
            UPDATE dispatches
            SET status = 'enviada', wa_message_id = ?, error = NULL, sent_at = ?
            WHERE id = ?
            """,
            (message_id, sent_at.astimezone(timezone.utc).isoformat(), dispatch_id),
        )
        self._connection.commit()

    def fail_dispatch(self, dispatch_id: int, error: str) -> None:
        self._connection.execute(
            """
            UPDATE dispatches
            SET status = 'falhou', error = ?
            WHERE id = ?
            """,
            (error[:280], dispatch_id),
        )
        self._connection.commit()

    def last_dispatch_sent_at(self) -> datetime | None:
        row = self._connection.execute(
            """
            SELECT sent_at
            FROM dispatches
            WHERE status = 'enviada' AND sent_at IS NOT NULL
            ORDER BY sent_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        sent_at = datetime.fromisoformat(row["sent_at"])
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        return sent_at

    def dispatch_was_sent(self, day: str, niche_key: str, position: int) -> bool:
        row = self._connection.execute(
            """
            SELECT 1
            FROM dispatches
            WHERE day = ? AND niche_key = ? AND position = ? AND status = 'enviada'
            LIMIT 1
            """,
            (day, niche_key, position),
        ).fetchone()
        return row is not None

    def queue_position_posted(self, day: str, niche_key: str, position: int) -> bool:
        row = self._connection.execute(
            """
            SELECT status
            FROM daily_queue
            WHERE day = ? AND niche_key = ? AND position = ?
            """,
            (day, niche_key, position),
        ).fetchone()
        return row is not None and row["status"] == "posted"

    def expire_dispatches(self, day: str) -> int:
        rows = self._connection.execute(
            """
            SELECT DISTINCT niche_key, position
            FROM dispatches
            WHERE day = ? AND status IN ('na_fila', 'enviando')
            """,
            (day,),
        ).fetchall()
        cursor = self._connection.execute(
            """
            UPDATE dispatches
            SET status = 'expirada'
            WHERE day = ? AND status IN ('na_fila', 'enviando')
            """,
            (day,),
        )
        for row in rows:
            if self.dispatch_was_sent(day, row["niche_key"], row["position"]):
                continue
            current = self._connection.execute(
                """
                SELECT status FROM daily_queue
                WHERE day = ? AND niche_key = ? AND position = ?
                """,
                (day, row["niche_key"], row["position"]),
            ).fetchone()
            if current is not None and current["status"] == "queued":
                self.mark_queue(day, row["niche_key"], row["position"], "skipped")
        self._connection.commit()
        return cursor.rowcount

    def record_post(self, asin: str, title: str, price_cents: int, posted_at: datetime) -> None:
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        self._connection.execute(
            """
            INSERT INTO posts (asin, title, price_cents, posted_at)
            VALUES (?, ?, ?, ?)
            """,
            (asin, title, price_cents, posted_at.astimezone(timezone.utc).isoformat()),
        )
        self._connection.commit()

    def cached_category(self, domain_id: int, name: str) -> int | None:
        row = self._connection.execute(
            """
            SELECT category_id
            FROM category_cache
            WHERE domain_id = ? AND name = ?
            """,
            (domain_id, name.casefold()),
        ).fetchone()
        if row is None:
            return None
        return int(row["category_id"])

    def save_category(self, domain_id: int, name: str, category_id: int, resolved_at: datetime) -> None:
        self._connection.execute(
            """
            INSERT INTO category_cache (domain_id, name, category_id, resolved_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (domain_id, name) DO UPDATE SET
                category_id = excluded.category_id,
                resolved_at = excluded.resolved_at
            """,
            (
                domain_id,
                name.casefold(),
                category_id,
                resolved_at.astimezone(timezone.utc).isoformat(),
            ),
        )
        self._connection.commit()


def _dispatch(row: sqlite3.Row) -> Dispatch:
    queued_at = datetime.fromisoformat(row["queued_at"])
    if queued_at.tzinfo is None:
        queued_at = queued_at.replace(tzinfo=timezone.utc)
    return Dispatch(
        id=int(row["id"]),
        day=row["day"],
        niche_key=row["niche_key"],
        position=int(row["position"]),
        asin=row["asin"],
        title=row["title"],
        price_cents=int(row["price_cents"]),
        chat_id=row["chat_id"],
        group_name=row["group_name"],
        caption=row["caption"],
        image_url=row["image_url"],
        status=row["status"],
        queued_at=queued_at,
    )


def _queued(row: sqlite3.Row) -> QueuedPost:
    days = row["lowest_for_days"]
    return QueuedPost(
        day=row["day"],
        niche_key=row["niche_key"],
        position=row["position"],
        asin=row["asin"],
        title=row["title"],
        author=row["author"],
        niche_label=row["niche_label"],
        price_cents=row["price_cents"],
        avg90_cents=row["avg90_cents"],
        historic_min_cents=row["historic_min_cents"],
        rating=row["rating"],
        review_count=row["review_count"],
        image_url=row["image_url"],
        price_source=row["price_source"],
        synopsis=row["synopsis"],
        lowest_for_days=None if days is None else int(days),
        blurb=row["blurb"],
        status=row["status"],
    )
