"""Fila nova: um post por horário, com um a três livros."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path


CLOCK_UNDO_SECONDS = 10 * 60


@dataclass(frozen=True)
class BoardBook:
    title: str
    blurb: str
    price_cents: int
    list_price_cents: int | None
    discount_pct: float | None
    lowest_label: str
    url: str
    coupon: str
    alt_url: str = ""
    alt_price_cents: int | None = None
    product_id: str = ""


@dataclass(frozen=True)
class BoardPost:
    id: int
    day: str
    position: int
    clock: str
    caption: str
    image_path: str
    books: tuple[BoardBook, ...]


@dataclass(frozen=True)
class SentLine:
    when: str
    title: str
    detail: str


@dataclass(frozen=True)
class FeedSend:
    group_name: str
    status: str
    at: str


@dataclass(frozen=True)
class FeedBook:
    title: str
    price_cents: int
    discount_pct: float | None
    url: str
    product_id: str = ""


@dataclass(frozen=True)
class FeedPost:
    id: int
    clock: str
    status: str
    title: str
    price_cents: int
    discount_pct: float | None
    url: str
    sends: tuple[FeedSend, ...]
    caption: str = ""
    blurb: str = ""
    lowest_label: str = ""
    list_price_cents: int | None = None
    link_state: str = ""
    live_price_cents: int | None = None
    day: str = ""
    shelf: tuple[FeedBook, ...] = ()


class BoardStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._setup()

    def close(self) -> None:
        self._connection.close()

    def _setup(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                position INTEGER NOT NULL,
                clock TEXT NOT NULL,
                status TEXT NOT NULL,
                caption TEXT NOT NULL,
                image_path TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scheduled_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                title TEXT NOT NULL,
                blurb TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                list_price_cents INTEGER,
                discount_pct REAL,
                lowest_label TEXT NOT NULL,
                url TEXT NOT NULL,
                coupon TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS board_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS board_sends (
                post_id INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                group_name TEXT NOT NULL,
                status TEXT NOT NULL,
                message_id TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (post_id, chat_id)
            );
            CREATE TABLE IF NOT EXISTS board_checks (
                post_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                live_cents INTEGER,
                checked_at TEXT NOT NULL
            );
            """
        )
        _add_column(self._connection, "scheduled_books", "alt_url", "TEXT NOT NULL DEFAULT ''")
        _add_column(self._connection, "scheduled_books", "alt_price_cents", "INTEGER")
        _add_column(self._connection, "scheduled_books", "product_id", "TEXT NOT NULL DEFAULT ''")
        self._connection.commit()

    def sending_enabled(self) -> bool:
        from datetime import datetime

        with self._lock:
            if not self._sending_enabled():
                return False
            raw = self._setting("paused_until")
            if not raw:
                return True
            try:
                moment = datetime.fromisoformat(raw)
            except ValueError:
                return True
            now = datetime.now(moment.tzinfo) if moment.tzinfo else datetime.now()
            if now < moment:
                return False
            with self._connection:
                self._connection.execute(
                    "DELETE FROM board_settings WHERE key = 'paused_until'",
                )
            return self._sending_enabled()

    def _sending_enabled(self) -> bool:
        row = self._connection.execute(
            "SELECT value FROM board_settings WHERE key = 'sending'",
        ).fetchone()
        return bool(row and row["value"] == "1")

    def set_sending(self, enabled: bool) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO board_settings (key, value) VALUES ('sending', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("1" if enabled else "0",),
            )
            self._connection.execute(
                "DELETE FROM board_settings WHERE key = 'paused_until'",
            )

    def pause_until(self, when) -> None:
        """Pausa com retorno sozinho. O envio volta a ficar ligado quando a hora passa."""
        stamp = when.isoformat(timespec="minutes")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO board_settings (key, value) VALUES ('sending', '1')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
            )
            self._connection.execute(
                """
                INSERT INTO board_settings (key, value) VALUES ('paused_until', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (stamp,),
            )

    def setting(self, key: str) -> str | None:
        with self._lock:
            return self._setting(key)

    def _setting(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM board_settings WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def take_signature(self) -> str | None:
        """Próxima assinatura da lista salva. Sem lista, o texto padrão continua."""
        from promo_livros.signatures import parse_block

        with self._lock, self._connection:
            lines = parse_block(self._setting("signatures") or "")
            if not lines:
                return None
            raw = self._setting("signature_cursor") or "0"
            try:
                cursor = int(raw)
            except ValueError:
                cursor = 0
            chosen = lines[cursor % len(lines)]
            self._connection.execute(
                """
                INSERT INTO board_settings (key, value) VALUES ('signature_cursor', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(cursor + 1),),
            )
            return chosen

    def rewrite_caption(self, post_id: int, caption: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE scheduled_posts SET caption = ? WHERE id = ?",
                (caption, post_id),
            )

    def put_setting(self, key: str, value: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO board_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def send_schedule(self):
        from promo_livros.send_schedule import default_schedule, parse_schedule

        try:
            return parse_schedule(
                self.setting("send_start") or "08:00",
                self.setting("send_end") or "22:00",
                self.setting("send_interval_minutes") or "40",
                self.setting("group_gap_seconds") or "45",
            )
        except ValueError:
            return default_schedule()

    def save_send_schedule(self, schedule) -> None:
        self.put_setting("send_start", schedule.start)
        self.put_setting("send_end", schedule.end)
        self.put_setting("send_interval_minutes", str(schedule.post_interval_minutes))
        self.put_setting("group_gap_seconds", str(schedule.group_gap_seconds))

    def retime_day(self, day: str, clocks: list[str]) -> int:
        with self._lock, self._connection:
            posts = self._posts_for(day)
            if len(clocks) < len(posts):
                return 0
            for post, clock in zip(posts, clocks):
                self._connection.execute(
                    """
                    UPDATE scheduled_posts
                    SET clock = ?
                    WHERE id = ? AND day = ? AND status = 'scheduled'
                    """,
                    (clock, post.id, day),
                )
            return len(posts)

    def replace_scheduled(self, day: str) -> int:
        """Tira da fila o que ainda não saiu. O status é replaced, não cancelled."""
        with self._lock, self._connection:
            cleared = self._connection.execute(
                """
                UPDATE scheduled_posts
                SET status = 'replaced', position = -id
                WHERE day = ? AND status = 'scheduled'
                """,
                (day,),
            ).rowcount
            self._connection.execute("DELETE FROM board_settings WHERE key = 'rush_post_id'")
        return int(cleared)

    def replace_scheduled_after(self, day: str, clock: str) -> int:
        """Tira só o que ainda está para sair depois deste horário."""
        with self._lock, self._connection:
            cleared = self._connection.execute(
                """
                UPDATE scheduled_posts
                SET status = 'replaced', position = -id
                WHERE day = ? AND status = 'scheduled' AND clock > ?
                """,
                (day, clock),
            ).rowcount
            self._connection.execute("DELETE FROM board_settings WHERE key = 'rush_post_id'")
        return int(cleared)

    def repeat_days(self) -> int:
        raw = self.setting("janela_repeticao_dias") or "1"
        try:
            days = int(raw)
        except ValueError:
            return 1
        return min(30, max(1, days))

    def sent_product_clocks(self, today: str, days: int | None = None) -> dict[str, list[str]]:
        """ASIN ou MLB já enviado na janela, com o horário de cada saída."""
        from datetime import date, timedelta

        from promo_livros.fila import produto_de_url

        window = self.repeat_days() if days is None else days
        end = date.fromisoformat(today)
        start = (end - timedelta(days=max(1, window) - 1)).isoformat()
        found: dict[str, list[str]] = {}
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, clock
                FROM scheduled_posts
                WHERE day >= ? AND day <= ?
                  AND (
                    status = 'sent'
                    OR EXISTS (
                      SELECT 1 FROM board_sends
                      WHERE post_id = scheduled_posts.id AND status = 'sent'
                    )
                  )
                ORDER BY clock, id
                """,
                (start, today),
            ).fetchall()
            for row in rows:
                books = self._connection.execute(
                    """
                    SELECT title, url, product_id
                    FROM scheduled_books
                    WHERE post_id = ?
                    ORDER BY sort_order, id
                    """,
                    (row["id"],),
                ).fetchall()
                for book in books:
                    product_id = str(book["product_id"] or "") or produto_de_url(str(book["url"] or ""))
                    if not product_id:
                        continue
                    found.setdefault(product_id.upper(), []).append(str(row["clock"]))
        return found

    def move_to_day(self, post_id: int, day: str, clock: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE scheduled_posts
                SET day = ?, clock = ?, position = ?
                WHERE id = ? AND status = 'scheduled'
                """,
                (day, clock, self._next_position(day), post_id),
            )
        return cursor.rowcount == 1

    def cancel_day(self, day: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE scheduled_posts
                SET status = 'cancelled', position = -id
                WHERE day = ? AND status = 'scheduled'
                """,
                (day,),
            )
            self._connection.execute(
                "DELETE FROM board_settings WHERE key = 'rush_post_id'",
            )

    def close_past_days(self, day: str) -> int:
        """Cancela o que ficou agendado antes desta data. A fila vale para a data e a hora."""
        with self._lock, self._connection:
            cleared = self._connection.execute(
                """
                UPDATE scheduled_posts
                SET status = 'cancelled', position = -id
                WHERE day < ? AND status = 'scheduled'
                """,
                (day,),
            ).rowcount
            if cleared:
                self._connection.execute(
                    "DELETE FROM board_settings WHERE key = 'rush_post_id'",
                )
        return int(cleared)

    def day_feed(self, day: str) -> list[FeedPost]:
        with self._lock:
            posts = self._feeds("day = ?", (day,), order="clock, id")
        waiting = [post for post in posts if post.status == "scheduled"]
        done = [post for post in posts if post.status != "scheduled"]
        return waiting + done

    def sent_feed(self) -> list[FeedPost]:
        """Todos os posts enviados, do mais recente ao mais antigo."""
        with self._lock:
            return self._feeds(
                "status = 'sent'",
                (),
                order="day DESC, clock DESC, id DESC",
                stamp_day=True,
            )

    def _feeds(self, where: str, params: tuple, *, order: str, stamp_day: bool = False) -> list[FeedPost]:
        rows = self._connection.execute(
            f"""
            SELECT id, day, clock, status, caption
            FROM scheduled_posts
            WHERE {where}
            ORDER BY {order}
            """,
            params,
        ).fetchall()
        posts: list[FeedPost] = []
        for row in rows:
            books = self._connection.execute(
                """
                SELECT title, blurb, price_cents, list_price_cents, discount_pct,
                       lowest_label, url, product_id
                FROM scheduled_books
                WHERE post_id = ?
                ORDER BY sort_order, id
                """,
                (row["id"],),
            ).fetchall()
            book = books[0] if books else None
            check = self._connection.execute(
                "SELECT state, live_cents FROM board_checks WHERE post_id = ?",
                (row["id"],),
            ).fetchone()
            sends = tuple(
                FeedSend(
                    group_name=item["group_name"],
                    status=item["status"],
                    at=_clock_from_stamp(item["updated_at"]),
                )
                for item in self._connection.execute(
                    """
                    SELECT group_name, status, updated_at
                    FROM board_sends
                    WHERE post_id = ?
                    ORDER BY updated_at, group_name
                    """,
                    (row["id"],),
                )
            )
            title = book["title"] if book else row["caption"].split("\n", 1)[0].strip("* ")
            posts.append(
                FeedPost(
                    id=row["id"],
                    clock=row["clock"],
                    status=row["status"],
                    title=title,
                    price_cents=book["price_cents"] if book else 0,
                    discount_pct=book["discount_pct"] if book else None,
                    url=book["url"] if book else "",
                    sends=sends,
                    caption=row["caption"] or "",
                    blurb=book["blurb"] if book else "",
                    lowest_label=book["lowest_label"] if book else "",
                    list_price_cents=book["list_price_cents"] if book else None,
                    link_state=check["state"] if check else "",
                    live_price_cents=check["live_cents"] if check else None,
                    day=str(row["day"] or "") if stamp_day else "",
                    shelf=tuple(
                        FeedBook(
                            title=item["title"],
                            price_cents=item["price_cents"],
                            discount_pct=item["discount_pct"],
                            url=item["url"],
                            product_id=item["product_id"] or "",
                        )
                        for item in books
                    ),
                )
            )
        return posts

    def posts_for(self, day: str) -> list[BoardPost]:
        with self._lock:
            return self._posts_for(day)

    def _posts_for(self, day: str) -> list[BoardPost]:
        rows = self._connection.execute(
            """
            SELECT id, day, position, clock, caption, image_path
            FROM scheduled_posts
            WHERE day = ? AND status = 'scheduled'
            ORDER BY clock, position, id
            """,
            (day,),
        ).fetchall()
        return [self._post(row) for row in rows]

    def has_day(self, day: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM scheduled_posts WHERE day = ? AND status = 'scheduled' LIMIT 1",
                (day,),
            ).fetchone()
        return row is not None

    def last_queue_clock(self, day: str, end_clock: str) -> str | None:
        """Último post do dia antes do fim da janela, agendado ou já enviado. Referência do convite final."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT MAX(clock) AS last FROM scheduled_posts
                WHERE day = ? AND status IN ('scheduled', 'sent') AND clock < ?
                """,
                (day, end_clock),
            ).fetchone()
        return str(row["last"]) if row and row["last"] else None

    def has_pending_posts(self, day: str, end_clock: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM scheduled_posts WHERE day = ? AND status = 'scheduled' AND clock < ? LIMIT 1",
                (day, end_clock),
            ).fetchone()
        return row is not None

    def latest_day(self) -> str | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT day FROM scheduled_posts
                WHERE status = 'scheduled'
                ORDER BY day DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return str(row["day"])

    def add_post(
        self,
        *,
        day: str,
        clock: str,
        caption: str,
        image_path: str,
        books: list[BoardBook],
    ) -> int:
        if not books or len(books) > 3:
            raise ValueError("Um post leva de 1 a 3 livros.")
        with self._lock, self._connection:
            position = self._next_position(day)
            cursor = self._connection.execute(
                """
                INSERT INTO scheduled_posts (day, position, clock, status, caption, image_path)
                VALUES (?, ?, ?, 'scheduled', ?, ?)
                """,
                (day, position, clock, caption, image_path),
            )
            post_id = int(cursor.lastrowid)
            self._insert_books(post_id, books)
        return post_id

    def shift(self, day: str, post_id: int, direction: int) -> None:
        with self._lock:
            self._shift(day, post_id, direction)

    def _shift(self, day: str, post_id: int, direction: int) -> None:
        posts = self._posts_for(day)
        index = next((i for i, post in enumerate(posts) if post.id == post_id), None)
        if index is None:
            return
        other = index + direction
        if other < 0 or other >= len(posts):
            return
        current, neighbor = posts[index], posts[other]
        with self._connection:
            self._connection.execute(
                "UPDATE scheduled_posts SET position = -1 WHERE id = ?",
                (current.id,),
            )
            self._connection.execute(
                "UPDATE scheduled_posts SET position = ?, clock = ? WHERE id = ?",
                (current.position, current.clock, neighbor.id),
            )
            self._connection.execute(
                "UPDATE scheduled_posts SET position = ?, clock = ? WHERE id = ?",
                (neighbor.position, neighbor.clock, current.id),
            )

    def set_image(self, post_id: int, image_path: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE scheduled_posts SET image_path = ? WHERE id = ?",
                (image_path, post_id),
            )

    def cancel(self, day: str, post_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE scheduled_posts
                SET status = 'cancelled', position = -id
                WHERE id = ? AND day = ? AND status = 'scheduled'
                """,
                (post_id, day),
            )
            self._clear_rush(post_id)

    def restore(self, day: str, post_id: int) -> bool:
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT id FROM scheduled_posts
                WHERE id = ? AND day = ? AND status = 'cancelled'
                """,
                (post_id, day),
            ).fetchone()
            if row is None:
                return False
            position = self._next_position(day)
            self._connection.execute(
                """
                UPDATE scheduled_posts
                SET status = 'scheduled', position = ?
                WHERE id = ? AND status = 'cancelled'
                """,
                (position, post_id),
            )
            return True

    def skip(self, day: str, post_id: int) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE scheduled_posts
                SET status = 'skipped', position = -id
                WHERE id = ? AND day = ? AND status = 'scheduled'
                """,
                (post_id, day),
            )
            if cursor.rowcount:
                self._clear_rush(post_id)
            return cursor.rowcount == 1

    def rush(self, day: str, post_id: int, now_clock: str) -> bool:
        """Marca o post para sair no próximo ciclo, na frente dos outros já vencidos."""
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT id FROM scheduled_posts
                WHERE id = ? AND day = ? AND status = 'scheduled'
                """,
                (post_id, day),
            ).fetchone()
            if row is None:
                return False
            self._connection.execute(
                """
                UPDATE scheduled_posts
                SET clock = ?
                WHERE id = ? AND status = 'scheduled'
                """,
                (now_clock, post_id),
            )
            self._connection.execute(
                """
                INSERT INTO board_settings (key, value) VALUES ('rush_post_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(post_id),),
            )
            return True

    def reorder(self, day: str, ids: list[int]) -> bool:
        """Mantém os horários da fila e entrega cada um ao post na nova ordem."""
        with self._lock, self._connection:
            posts = self._posts_for(day)
            if len(ids) != len(posts) or {post.id for post in posts} != set(ids):
                return False
            clocks = [post.clock for post in posts]
            for index, post_id in enumerate(ids):
                self._connection.execute(
                    """
                    UPDATE scheduled_posts
                    SET clock = ?, position = ?
                    WHERE id = ? AND day = ? AND status = 'scheduled'
                    """,
                    (clocks[index], index + 1, post_id, day),
                )
            return True

    def queue_clocks(self, day: str) -> list[tuple[int, str]]:
        with self._lock:
            return [(post.id, post.clock) for post in self._posts_for(day)]

    def apply_clocks(self, day: str, change, *, extend_end: bool = False, now_ts: float | None = None):
        """Relê a fila com o banco travado para escrita, aplica a regra e grava só se ela aprovar.

        O envio roda em outro processo. BEGIN IMMEDIATE impede que ele marque um post como enviado
        entre a leitura e a gravação.
        """
        import json
        import time

        from promo_livros.fila_horarios import Resultado

        stamp = time.time() if now_ts is None else now_ts
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                rows = self._connection.execute(
                    """
                    SELECT id, clock, position FROM scheduled_posts
                    WHERE day = ? AND status = 'scheduled'
                    ORDER BY clock, position, id
                    """,
                    (day,),
                ).fetchall()
                result = change([(int(row["id"]), str(row["clock"])) for row in rows])
                if not result.ok or not result.clocks:
                    self._connection.rollback()
                    return result
                for post_id, clock in result.clocks.items():
                    updated = self._connection.execute(
                        "UPDATE scheduled_posts SET clock = ? WHERE id = ? AND day = ? AND status = 'scheduled'",
                        (clock, post_id, day),
                    ).rowcount
                    if updated != 1:
                        self._connection.rollback()
                        before = next((str(row["clock"]) for row in rows if int(row["id"]) == post_id), "")
                        return Resultado(erro=f"O post das {before} acabou de sair.")
                self._renumber(day)
                snapshot = [
                    {"id": int(row["id"]), "clock": str(row["clock"]), "position": int(row["position"])}
                    for row in rows
                ]
                self._put(
                    "clock_undo",
                    json.dumps({"day": day, "at": stamp, "posts": snapshot}),
                )
                if extend_end:
                    last = self._connection.execute(
                        "SELECT MAX(clock) AS last FROM scheduled_posts WHERE day = ? AND status = 'scheduled'",
                        (day,),
                    ).fetchone()["last"]
                    if last:
                        self._put(f"send_end_extra:{day}", _one_minute_after(str(last)))
                self._connection.commit()
                return result
            except Exception:
                self._connection.rollback()
                raise

    def replace_post_books(self, day: str, changes: dict[int, tuple[tuple[BoardBook, ...], list[BoardBook], str]]) -> str:
        """Troca livros e legenda de vários posts de uma vez. Devolve o erro ou "" se gravou.

        Cada mudança traz os livros que o post tinha quando a troca foi montada. Se o envio
        mandou o post ou alguém mexeu nele nesse meio tempo, nada é gravado.
        """
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                for post_id, (expected, books, caption) in changes.items():
                    row = self._connection.execute(
                        "SELECT id, day, position, clock, caption, image_path, status FROM scheduled_posts WHERE id = ?",
                        (post_id,),
                    ).fetchone()
                    if row is None or row["day"] != day or row["status"] != "scheduled":
                        self._connection.rollback()
                        return "Um desses posts acabou de sair. Nada mudou."
                    if self._post(row).books != tuple(expected):
                        self._connection.rollback()
                        return "O post das {} mudou agora há pouco. Atualize a página.".format(row["clock"])
                    if not books or len(books) > 3:
                        self._connection.rollback()
                        return "Um post leva de 1 a 3 livros."
                for post_id, (_expected, books, caption) in changes.items():
                    self._connection.execute("DELETE FROM scheduled_books WHERE post_id = ?", (post_id,))
                    self._insert_books(post_id, books)
                    self._connection.execute("UPDATE scheduled_posts SET caption = ? WHERE id = ?", (caption, post_id))
                    self._connection.execute("DELETE FROM board_checks WHERE post_id = ?", (post_id,))
                self._connection.commit()
                return ""
            except Exception:
                self._connection.rollback()
                raise

    def restore_clocks(self, day: str, now_ts: float | None = None) -> str:
        import json
        import time

        stamp = time.time() if now_ts is None else now_ts
        with self._lock, self._connection:
            raw = self._setting("clock_undo") or ""
            if not raw:
                return "Não há horários para desfazer."
            saved = json.loads(raw)
            if saved.get("day") != day:
                return "Não há horários para desfazer."
            if stamp - float(saved.get("at") or 0) > CLOCK_UNDO_SECONDS:
                return "O prazo de desfazer acabou."
            posts = saved.get("posts") or []
            ids = [int(item["id"]) for item in posts]
            marks = ",".join("?" for _ in ids)
            alive = self._connection.execute(
                f"SELECT COUNT(*) AS total FROM scheduled_posts WHERE status = 'scheduled' AND id IN ({marks})",
                ids,
            ).fetchone()["total"] if ids else 0
            if alive != len(ids):
                return "Um desses posts já saiu. Os horários ficam como estão."
            for item in posts:
                self._connection.execute(
                    "UPDATE scheduled_posts SET clock = ?, position = ? WHERE id = ? AND status = 'scheduled'",
                    (item["clock"], int(item["position"]), int(item["id"])),
                )
            self._connection.execute("DELETE FROM board_settings WHERE key = 'clock_undo'")
        return "Os horários voltaram."

    def send_end_for(self, day: str, end: str) -> str:
        """Fim da janela para o envio. A extensão do dia vale quando a fila passou do horário com confirmação."""
        extra = self.setting(f"send_end_extra:{day}") or ""
        return max(end, extra) if extra else end

    def extend_send_end(self, day: str, end: str) -> None:
        self.put_setting(f"send_end_extra:{day}", end)

    def _renumber(self, day: str) -> None:
        rows = self._connection.execute(
            """
            SELECT id FROM scheduled_posts
            WHERE day = ? AND status = 'scheduled'
            ORDER BY clock, position, id
            """,
            (day,),
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            self._connection.execute(
                "UPDATE scheduled_posts SET position = ? WHERE id = ?",
                (index, int(row["id"])),
            )

    def _put(self, key: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO board_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def fail_if_unsent(self, day: str, post_id: int) -> bool:
        with self._lock, self._connection:
            if not self._is_unsent(post_id):
                return False
            cursor = self._connection.execute(
                """
                UPDATE scheduled_posts
                SET status = 'failed', position = -id
                WHERE id = ? AND day = ? AND status = 'scheduled'
                """,
                (post_id, day),
            )
            if cursor.rowcount:
                self._clear_rush(post_id)
            return cursor.rowcount == 1

    def save_check(self, post_id: int, state: str, live_cents: int | None) -> None:
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO board_checks (post_id, state, live_cents, checked_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(post_id) DO UPDATE SET
                    state = excluded.state,
                    live_cents = excluded.live_cents,
                    checked_at = excluded.checked_at
                """,
                (post_id, state, live_cents, stamp),
            )

    def check_is_fresh(self, post_id: int, minutes: int = 20) -> bool:
        from datetime import datetime, timedelta, timezone

        with self._lock:
            row = self._connection.execute(
                "SELECT checked_at FROM board_checks WHERE post_id = ?",
                (post_id,),
            ).fetchone()
        if row is None:
            return False
        try:
            checked = datetime.fromisoformat(str(row["checked_at"]))
        except ValueError:
            return False
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - checked < timedelta(minutes=minutes)

    def post_by_id(self, post_id: int) -> BoardPost | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT id, day, position, clock, caption, image_path
                FROM scheduled_posts
                WHERE id = ?
                """,
                (post_id,),
            ).fetchone()
            if row is None:
                return None
            return self._post(row)

    def update_scheduled(self, day: str, post_id: int, *, clock: str, books: list[BoardBook], caption: str) -> bool:
        if not books or len(books) > 3:
            return False
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT status FROM scheduled_posts WHERE id = ? AND day = ?",
                (post_id, day),
            ).fetchone()
            if row is None or row["status"] != "scheduled":
                return False
            self._connection.execute(
                """
                UPDATE scheduled_posts
                SET clock = ?, caption = ?
                WHERE id = ? AND status = 'scheduled'
                """,
                (clock, caption, post_id),
            )
            self._connection.execute("DELETE FROM scheduled_books WHERE post_id = ?", (post_id,))
            self._insert_books(post_id, books)
            return True

    def apply_live_price(self, day: str, post_id: int) -> str | None:
        from dataclasses import replace

        from promo_livros.post_copy import render_caption, signature_of

        with self._lock:
            check = self._connection.execute(
                "SELECT state, live_cents FROM board_checks WHERE post_id = ?",
                (post_id,),
            ).fetchone()
            if check is None or check["state"] != "price" or not check["live_cents"]:
                return "Não há preço novo para este post."
            row = self._connection.execute(
                """
                SELECT id, day, position, clock, caption, image_path, status
                FROM scheduled_posts
                WHERE id = ? AND day = ?
                """,
                (post_id, day),
            ).fetchone()
            if row is None or row["status"] != "scheduled":
                return "Só dá para atualizar um post que ainda está na fila."
            post = self._post(row)
            cents = int(check["live_cents"])
        if not post.books:
            return "Post sem livro."
        current = post.books[0]
        discount = current.discount_pct
        if current.list_price_cents and current.list_price_cents > cents:
            discount = (current.list_price_cents - cents) * 100 / current.list_price_cents
        books = [replace(current, price_cents=cents, discount_pct=discount), *post.books[1:]]
        caption = render_caption(_caption_fields(books), signature=signature_of(post.caption))
        if not self.update_scheduled(day, post_id, clock=post.clock, books=books, caption=caption):
            return "Só dá para atualizar um post que ainda está na fila."
        self.save_check(post_id, "ok", cents)
        return None

    def _clear_rush(self, post_id: int) -> None:
        if self._setting("rush_post_id") == str(post_id):
            self._connection.execute(
                "DELETE FROM board_settings WHERE key = 'rush_post_id'",
            )

    def next_due_post(self, day: str, now_clock: str, end_clock: str) -> BoardPost | None:
        with self._lock:
            rush = self._setting("rush_post_id")
            if rush and rush.isdigit():
                rushed = self._connection.execute(
                    """
                    SELECT id, day, position, clock, caption, image_path
                    FROM scheduled_posts
                    WHERE id = ? AND day = ? AND status = 'scheduled'
                    """,
                    (int(rush), day),
                ).fetchone()
                if rushed is not None:
                    return self._post(rushed)
                with self._connection:
                    self._connection.execute(
                        "DELETE FROM board_settings WHERE key = 'rush_post_id'",
                    )
            row = self._connection.execute(
                """
                SELECT id, day, position, clock, caption, image_path
                FROM scheduled_posts
                WHERE day = ? AND status = 'scheduled' AND clock <= ? AND clock < ?
                ORDER BY clock, position, id
                LIMIT 1
                """,
                (day, now_clock, end_clock),
            ).fetchone()
            if row is None:
                return None
            return self._post(row)

    def sent_group_ids(self, post_id: int) -> set[str]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT chat_id FROM board_sends
                WHERE post_id = ? AND status = 'sent'
                """,
                (post_id,),
            ).fetchall()
        return {str(row["chat_id"]) for row in rows}

    def last_group_sent_at(self) -> str | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT updated_at FROM board_sends
                WHERE status = 'sent'
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return str(row["updated_at"])

    def claim_group_send(self, post_id: int, chat_id: str, group_name: str, updated_at: str) -> str:
        """'send' se este processo pode publicar. 'done' se esse grupo já recebeu. 'busy' se outro envio está no meio."""
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT status, updated_at FROM board_sends WHERE post_id = ? AND chat_id = ?",
                (post_id, chat_id),
            ).fetchone()
            if row is not None and row["status"] == "sent":
                return "done"
            if row is not None and row["status"] == "sending" and _still_fresh(str(row["updated_at"]), updated_at):
                return "busy"
            self._connection.execute(
                """
                INSERT INTO board_sends (post_id, chat_id, group_name, status, message_id, updated_at)
                VALUES (?, ?, ?, 'sending', NULL, ?)
                ON CONFLICT(post_id, chat_id) DO UPDATE SET
                    group_name = excluded.group_name,
                    status = 'sending',
                    message_id = NULL,
                    updated_at = excluded.updated_at
                """,
                (post_id, chat_id, group_name, updated_at),
            )
        return "send"

    def finish_group_send(self, post_id: int, chat_id: str, message_id: str, updated_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE board_sends
                SET status = 'sent', message_id = ?, updated_at = ?
                WHERE post_id = ? AND chat_id = ? AND status = 'sending'
                """,
                (message_id, updated_at, post_id, chat_id),
            )

    def release_group_send(self, post_id: int, chat_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                DELETE FROM board_sends
                WHERE post_id = ? AND chat_id = ? AND status = 'sending'
                """,
                (post_id, chat_id),
            )

    def set_book_blurbs(self, post_id: int, blurbs: list[str]) -> None:
        from promo_livros.post_copy import render_caption, signature_of

        with self._lock, self._connection:
            post_row = self._connection.execute(
                """
                SELECT id, day, position, clock, caption, image_path, status
                FROM scheduled_posts
                WHERE id = ?
                """,
                (post_id,),
            ).fetchone()
            if post_row is None or post_row["status"] != "scheduled":
                return
            rows = self._connection.execute(
                "SELECT id FROM scheduled_books WHERE post_id = ? ORDER BY sort_order, id",
                (post_id,),
            ).fetchall()
            if len(rows) != len(blurbs):
                raise ValueError("A frase precisa bater com os livros do post.")
            for row, blurb in zip(rows, blurbs):
                self._connection.execute(
                    "UPDATE scheduled_books SET blurb = ? WHERE id = ?",
                    (blurb, row["id"]),
                )
            post = self._post(post_row)
            caption = render_caption(
                _caption_fields(post.books),
                signature=signature_of(post.caption),
            )
            self._connection.execute(
                "UPDATE scheduled_posts SET caption = ? WHERE id = ? AND status = 'scheduled'",
                (caption, post_id),
            )

    def unsent_posts(self) -> list[BoardPost]:
        """Agendados que nenhum grupo recebeu e que não estão no meio de um envio."""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, day, position, clock, caption, image_path
                FROM scheduled_posts
                WHERE status = 'scheduled'
                  AND NOT EXISTS (
                    SELECT 1 FROM board_sends
                    WHERE board_sends.post_id = scheduled_posts.id
                      AND board_sends.status IN ('sent', 'sending')
                  )
                ORDER BY day, clock, position, id
                """
            ).fetchall()
            return [self._post(row) for row in rows]

    def replace_urls_if_unsent(self, post_id: int, urls: list[str]) -> bool:
        """Troca as URLs e a legenda. Devolve false se o envio já começou."""
        from promo_livros.post_copy import render_caption, signature_of

        with self._lock:
            self._connection.rollback()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                if not self._is_unsent(post_id):
                    self._connection.rollback()
                    return False
                rows = self._connection.execute(
                    "SELECT id FROM scheduled_books WHERE post_id = ? ORDER BY sort_order, id",
                    (post_id,),
                ).fetchall()
                if len(rows) != len(urls):
                    self._connection.rollback()
                    return False
                for row, url in zip(rows, urls):
                    self._connection.execute(
                        "UPDATE scheduled_books SET url = ? WHERE id = ?",
                        (url, row["id"]),
                    )
                post_row = self._connection.execute(
                    """
                    SELECT id, day, position, clock, caption, image_path
                    FROM scheduled_posts
                    WHERE id = ? AND status = 'scheduled'
                    """,
                    (post_id,),
                ).fetchone()
                if post_row is None:
                    self._connection.rollback()
                    return False
                caption = render_caption(
                    _caption_fields(self._post(post_row).books),
                    signature=signature_of(post_row["caption"]),
                )
                self._connection.execute(
                    "UPDATE scheduled_posts SET caption = ? WHERE id = ? AND status = 'scheduled'",
                    (caption, post_id),
                )
                self._connection.commit()
                return True
            except Exception:
                self._connection.rollback()
                raise

    def _is_unsent(self, post_id: int) -> bool:
        row = self._connection.execute(
            """
            SELECT 1
            FROM scheduled_posts
            WHERE id = ? AND status = 'scheduled'
              AND NOT EXISTS (
                SELECT 1 FROM board_sends
                WHERE board_sends.post_id = scheduled_posts.id
                  AND board_sends.status IN ('sent', 'sending')
              )
            """,
            (post_id,),
        ).fetchone()
        return row is not None

    def mark_sent(self, post_id: int) -> None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT day FROM scheduled_posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            self._connection.execute(
                """
                UPDATE scheduled_posts
                SET status = 'sent'
                WHERE id = ? AND status = 'scheduled'
                """,
                (post_id,),
            )
            self._clear_rush(post_id)
            if row is not None:
                self._mark_catalog_sent(post_id, str(row["day"]))

    def _mark_catalog_sent(self, post_id: int, day: str) -> None:
        from promo_livros.fila import produto_de_url

        books = self._connection.execute(
            "SELECT url, product_id FROM scheduled_books WHERE post_id = ?",
            (post_id,),
        ).fetchall()
        for book in books:
            product_id = str(book["product_id"] or "") or produto_de_url(str(book["url"] or ""))
            if not product_id:
                continue
            for table in ("catalog_books", "ml_books"):
                columns = {str(item[1]) for item in self._connection.execute(f"PRAGMA table_info({table})")}
                if "pick_state" not in columns:
                    continue
                self._connection.execute(
                    f"""
                    UPDATE {table}
                    SET picked = 0, pick_seq = 0, pick_state = 'enviado', pick_day = ?
                    WHERE asin = ?
                    """,
                    (day, product_id.upper()),
                )

    def image_path_for(self, post_id: int) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT image_path FROM scheduled_posts WHERE id = ?",
                (post_id,),
            ).fetchone()
        if row is None or not row["image_path"]:
            return None
        return str(row["image_path"])

    def sent_lines(self) -> list[SentLine]:
        """Histórico completo do que foi enviado."""
        with self._lock:
            return self._sent_lines("")

    def _sent_lines(self, cutoff: str) -> list[SentLine]:
        lines: list[SentLine] = []
        if _table(self._connection, "dispatches"):
            clause = "AND day >= ?" if cutoff else ""
            params: tuple = (cutoff,) if cutoff else ()
            rows = self._connection.execute(
                f"""
                SELECT day, title, group_name, COALESCE(sent_at, queued_at) AS when_at
                FROM dispatches
                WHERE status = 'enviada' {clause}
                ORDER BY when_at DESC, id DESC
                """,
                params,
            ).fetchall()
            lines.extend(
                SentLine(row["when_at"] or row["day"], row["title"], row["group_name"])
                for row in rows
            )
        clause = "AND day >= ?" if cutoff else ""
        params = (cutoff,) if cutoff else ()
        rows = self._connection.execute(
            f"""
            SELECT day, clock, caption
            FROM scheduled_posts
            WHERE status = 'sent' {clause}
            ORDER BY day DESC, clock DESC
            """,
            params,
        ).fetchall()
        for row in rows:
            title = row["caption"].split("\n", 1)[0].strip("* ")
            lines.append(SentLine(f"{row['day']} {row['clock']}", title, "fila nova"))
        return lines

    def _post(self, row: sqlite3.Row) -> BoardPost:
        books = self._connection.execute(
            """
            SELECT title, blurb, price_cents, list_price_cents, discount_pct,
                   lowest_label, url, coupon, alt_url, alt_price_cents, product_id
            FROM scheduled_books
            WHERE post_id = ?
            ORDER BY sort_order, id
            """,
            (row["id"],),
        ).fetchall()
        return BoardPost(
            id=row["id"],
            day=row["day"],
            position=row["position"],
            clock=row["clock"],
            caption=row["caption"],
            image_path=row["image_path"],
            books=tuple(
                BoardBook(
                    title=item["title"],
                    blurb=item["blurb"],
                    price_cents=item["price_cents"],
                    list_price_cents=item["list_price_cents"],
                    discount_pct=item["discount_pct"],
                    lowest_label=item["lowest_label"],
                    url=item["url"],
                    coupon=item["coupon"],
                    alt_url=item["alt_url"] or "",
                    alt_price_cents=None if item["alt_price_cents"] is None else int(item["alt_price_cents"]),
                    product_id=str(item["product_id"] or ""),
                )
                for item in books
            ),
        )

    def _insert_books(self, post_id: int, books: list[BoardBook]) -> None:
        self._connection.executemany(
            """
            INSERT INTO scheduled_books (
                post_id, sort_order, title, blurb, price_cents, list_price_cents,
                discount_pct, lowest_label, url, coupon, alt_url, alt_price_cents, product_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    post_id,
                    index,
                    book.title,
                    book.blurb,
                    book.price_cents,
                    book.list_price_cents,
                    book.discount_pct,
                    book.lowest_label,
                    book.url,
                    book.coupon,
                    book.alt_url,
                    book.alt_price_cents,
                    book.product_id,
                )
                for index, book in enumerate(books)
            ],
        )

    def _next_position(self, day: str) -> int:
        row = self._connection.execute(
            """
            SELECT COALESCE(MAX(position), 0) AS last
            FROM scheduled_posts
            WHERE day = ? AND status = 'scheduled'
            """,
            (day,),
        ).fetchone()
        return int(row["last"]) + 1


def _one_minute_after(clock: str) -> str:
    hour, minute = (int(part) for part in clock.split(":"))
    total = min(hour * 60 + minute + 1, 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"


def _caption_fields(books: tuple[BoardBook, ...] | list[BoardBook]) -> list[dict]:
    return [
        {
            "title": book.title,
            "blurb": book.blurb,
            "price_cents": book.price_cents,
            "list_price_cents": book.list_price_cents,
            "discount_pct": book.discount_pct,
            "lowest_label": book.lowest_label,
            "coupon": book.coupon,
            "url": book.url,
            "alt_url": book.alt_url,
            "alt_price_cents": book.alt_price_cents,
        }
        for book in books
    ]


def _clock_from_stamp(value: str) -> str:
    text = value or ""
    if "T" in text and len(text) >= 16:
        return text[11:16]
    return ""


def _still_fresh(previous: str, current: str) -> bool:
    from datetime import datetime, timedelta

    try:
        started = datetime.fromisoformat(previous)
        moment = datetime.fromisoformat(current)
    except ValueError:
        return False
    return moment - started < timedelta(minutes=2)


def _add_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    have = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in have:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _table(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None
