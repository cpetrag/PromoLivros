"""Enquetes: fila, votos e mensagens de resultado."""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import secrets
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from promo_livros.poll_commands import PollCommandError, parse_group_command
from promo_livros.send_gap import gap_open, latest_stamp
from promo_livros.waha import WahaError

logger = logging.getLogger("promo_livros.polls")

PIN_SECONDS = {"24h": 86400, "7d": 604800, "30d": 2592000}
_STALE = timedelta(minutes=2)
_ADMIN_ROLES = {"admin", "superadmin"}


class PollError(ValueError):
    """A enquete não pôde ser gravada."""


class PollSender(Protocol):
    def connection_state(self) -> str:
        """connected quando a sessão pode mandar mensagem."""

    def send_poll(self, chat_id: str, question: str, options: list[str], multiple: bool) -> str:
        """Envia a enquete e devolve o id da mensagem."""

    def send(self, chat_id: str, caption: str, image_url: str | None) -> str:
        """Envia um texto e devolve o id da mensagem."""

    def pin_message(self, chat_id: str, message_id: str, duration: int) -> None:
        """Fixa a mensagem. Pode falhar se o motor não suportar."""

    def unpin_message(self, chat_id: str, message_id: str) -> None:
        """Desafixa a mensagem."""


@dataclass(frozen=True)
class PollSummary:
    id: int
    chat_id: str
    group_name: str
    question: str
    status: str
    pin: str | None
    send_at: str
    closes_at: str | None
    voters: int
    multiple: bool


@dataclass(frozen=True)
class PollDetail:
    id: int
    chat_id: str
    group_name: str
    question: str
    options: tuple[str, ...]
    multiple: bool
    pin: str | None
    pin_ok: bool
    status: str
    message_id: str | None
    send_at: str
    closes_at: str | None
    counts: dict[str, int]
    voters: int
    failed_votes: int
    series: tuple[tuple[int, int], ...]
    batch_size: int = 1
    group_lines: tuple[tuple[str, str, int], ...] = ()


class PollStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._setup()

    def close(self) -> None:
        self._connection.close()

    def _setup(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                group_name TEXT NOT NULL,
                question TEXT NOT NULL,
                multiple INTEGER NOT NULL,
                pin TEXT,
                send_at TEXT NOT NULL,
                closes_at TEXT,
                status TEXT NOT NULL,
                wa_message_id TEXT,
                pin_ok INTEGER NOT NULL DEFAULT 0,
                failed_votes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT,
                batch_id TEXT
            );
            CREATE TABLE IF NOT EXISTS poll_options (
                poll_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                label TEXT NOT NULL,
                PRIMARY KEY (poll_id, position)
            );
            CREATE TABLE IF NOT EXISTS poll_votes (
                poll_id INTEGER NOT NULL,
                voter_id TEXT NOT NULL,
                options_json TEXT NOT NULL,
                vote_timestamp INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (poll_id, voter_id)
            );
            CREATE TABLE IF NOT EXISTS poll_events (
                event_id TEXT PRIMARY KEY,
                poll_id INTEGER,
                kind TEXT NOT NULL,
                body TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS poll_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS poll_outbound (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                sent_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS poll_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                vote_timestamp INTEGER NOT NULL,
                voters INTEGER NOT NULL
            );
            """
        )
        _ensure_column(self._connection, "polls", "batch_id", "TEXT")
        self._connection.commit()

    def create(
        self,
        *,
        chat_id: str,
        group_name: str,
        question: str,
        options: tuple[str, ...] | list[str],
        multiple: bool,
        pin: str | None,
        send_at: datetime,
        closes_at: datetime | None,
        batch_id: str | None = None,
    ) -> int:
        labels = _validated_options(question, options)
        if pin not in {None, *PIN_SECONDS}:
            raise PollError("Fixar a enquete só pode ser por 24h, 7 dias ou 30 dias.")
        stamp = _stamp(send_at)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO polls (
                    chat_id, group_name, question, multiple, pin, send_at, closes_at,
                    status, created_at, updated_at, batch_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'agendada', ?, ?, ?)
                """,
                (
                    chat_id,
                    group_name,
                    question.strip(),
                    1 if multiple else 0,
                    pin,
                    stamp,
                    _stamp(closes_at) if closes_at else None,
                    stamp,
                    stamp,
                    batch_id,
                ),
            )
            poll_id = int(cursor.lastrowid)
            self._connection.executemany(
                "INSERT INTO poll_options (poll_id, position, label) VALUES (?, ?, ?)",
                [(poll_id, index, label) for index, label in enumerate(labels)],
            )
        return poll_id

    def create_for_groups(
        self,
        groups: tuple[tuple[str, str], ...] | list[tuple[str, str]],
        *,
        question: str,
        options: tuple[str, ...] | list[str],
        multiple: bool,
        pin: str | None,
        send_at: datetime,
        closes_at: datetime | None,
    ) -> int:
        if not groups:
            raise PollError("Escolha ao menos um grupo.")
        batch_id = secrets.token_hex(8) if len(groups) > 1 else None
        first: int | None = None
        for chat_id, group_name in groups:
            poll_id = self.create(
                chat_id=chat_id,
                group_name=group_name,
                question=question,
                options=options,
                multiple=multiple,
                pin=pin,
                send_at=send_at,
                closes_at=closes_at,
                batch_id=batch_id,
            )
            if first is None:
                first = poll_id
        if first is None:
            raise PollError("Escolha ao menos um grupo.")
        return first

    def list_polls(self, *, chat_id: str | None = None, status: str | None = None) -> list[PollSummary]:
        clauses = ["1 = 1"]
        params: list[object] = []
        if chat_id:
            clauses.append("p.chat_id = ?")
            params.append(chat_id)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT p.*, (
                    SELECT COUNT(*) FROM poll_votes v
                    WHERE v.poll_id = p.id AND v.options_json != '[]'
                ) AS voters
                FROM polls p
                WHERE {' AND '.join(clauses)}
                ORDER BY p.id DESC
                """,
                params,
            ).fetchall()
        seen: set[str] = set()
        summaries: list[PollSummary] = []
        for row in rows:
            batch_id = str(row["batch_id"]) if row["batch_id"] else ""
            if batch_id:
                if batch_id in seen:
                    continue
                seen.add(batch_id)
                summary = self._batch_summary(batch_id)
            else:
                summary = _summary(row)
            if status and summary.status != status:
                continue
            summaries.append(summary)
        return summaries

    def detail(self, poll_id: int) -> PollDetail:
        with self._lock:
            row = self._connection.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
            if row is None:
                raise PollError("Enquete não encontrada.")
            options = tuple(
                str(item["label"])
                for item in self._connection.execute(
                    "SELECT label FROM poll_options WHERE poll_id = ? ORDER BY position",
                    (poll_id,),
                )
            )
            votes = self._connection.execute(
                "SELECT voter_id, options_json, vote_timestamp FROM poll_votes WHERE poll_id = ?",
                (poll_id,),
            ).fetchall()
            points = self._connection.execute(
                """
                SELECT vote_timestamp, voters FROM poll_points
                WHERE poll_id = ?
                ORDER BY vote_timestamp, id
                """,
                (poll_id,),
            ).fetchall()
        counts = {label: 0 for label in options}
        voters = 0
        for vote in votes:
            chosen = _options_of(str(vote["options_json"]))
            if not chosen:
                continue
            voters += 1
            for label in chosen:
                if label in counts:
                    counts[label] += 1
        return PollDetail(
            id=int(row["id"]),
            chat_id=str(row["chat_id"]),
            group_name=str(row["group_name"]),
            question=str(row["question"]),
            options=options,
            multiple=bool(row["multiple"]),
            pin=str(row["pin"]) if row["pin"] else None,
            pin_ok=bool(row["pin_ok"]),
            status=str(row["status"]),
            message_id=str(row["wa_message_id"]) if row["wa_message_id"] else None,
            send_at=str(row["send_at"]),
            closes_at=str(row["closes_at"]) if row["closes_at"] else None,
            counts=counts,
            voters=voters,
            failed_votes=int(row["failed_votes"]),
            series=tuple((int(point["vote_timestamp"]), int(point["voters"])) for point in points),
        )

    def batch_ids(self, poll_id: int) -> list[int]:
        with self._lock:
            row = self._connection.execute("SELECT batch_id FROM polls WHERE id = ?", (poll_id,)).fetchone()
            if row is None:
                raise PollError("Enquete não encontrada.")
            batch_id = str(row["batch_id"]) if row["batch_id"] else ""
            if not batch_id:
                return [poll_id]
            rows = self._connection.execute(
                "SELECT id FROM polls WHERE batch_id = ? ORDER BY id",
                (batch_id,),
            ).fetchall()
        return [int(item["id"]) for item in rows]

    def batch_chat_ids(self, poll_id: int) -> list[str]:
        ids = self.batch_ids(poll_id)
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._connection.execute(
                f"SELECT id, chat_id FROM polls WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        by_id = {int(row["id"]): str(row["chat_id"]) for row in rows}
        return [by_id[item] for item in ids]

    def combined(self, poll_id: int) -> PollDetail:
        ids = self.batch_ids(poll_id)
        parts = [self.detail(item) for item in ids]
        if len(parts) == 1:
            return parts[0]
        counts = {label: 0 for label in parts[0].options}
        voters = 0
        failed = 0
        for part in parts:
            voters += part.voters
            failed += part.failed_votes
            for label, count in part.counts.items():
                counts[label] = counts.get(label, 0) + count
        sent = [part for part in parts if part.message_id]
        return PollDetail(
            id=poll_id,
            chat_id=parts[0].chat_id,
            group_name="Todos os grupos",
            question=parts[0].question,
            options=parts[0].options,
            multiple=parts[0].multiple,
            pin=parts[0].pin,
            pin_ok=all(part.pin_ok for part in sent) if sent else False,
            status=_batch_status([part.status for part in parts]),
            message_id=parts[0].message_id,
            send_at=parts[0].send_at,
            closes_at=parts[0].closes_at,
            counts=counts,
            voters=voters,
            failed_votes=failed,
            series=self._combined_series(ids),
            batch_size=len(parts),
            group_lines=tuple((part.group_name, part.status, part.voters) for part in parts),
        )

    def mark_sent(self, poll_id: int, message_id: str, pin_ok: bool) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE polls
                SET status = 'ativa', wa_message_id = ?, pin_ok = ?, updated_at = send_at
                WHERE id = ?
                """,
                (message_id, 1 if pin_ok else 0, poll_id),
            )

    def mark_pin(self, poll_id: int, pin_ok: bool) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE polls SET pin_ok = ? WHERE id = ?",
                (1 if pin_ok else 0, poll_id),
            )

    def mark_closed(self, poll_id: int, now: datetime) -> None:
        stamp = _stamp(now)
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE polls
                SET status = 'encerrada', closed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (stamp, stamp, poll_id),
            )

    def votes_csv(self, poll_id: int) -> str:
        ids = self.batch_ids(poll_id)
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT p.group_name, v.voter_id, v.options_json, v.updated_at
                FROM poll_votes v
                JOIN polls p ON p.id = v.poll_id
                WHERE v.poll_id IN ({placeholders}) AND v.options_json != '[]'
                ORDER BY p.id, v.updated_at, v.voter_id
                """,
                ids,
            ).fetchall()
        grouped = len(ids) > 1
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        if grouped:
            writer.writerow(["grupo", "votante", "opcoes", "data"])
        else:
            writer.writerow(["votante", "opcoes", "data"])
        for row in rows:
            chosen = " | ".join(_options_of(str(row["options_json"])))
            if grouped:
                writer.writerow([row["group_name"], row["voter_id"], chosen, row["updated_at"]])
            else:
                writer.writerow([row["voter_id"], chosen, row["updated_at"]])
        return buffer.getvalue()

    def last_outbound_at(self) -> str | None:
        with self._lock:
            row = self._connection.execute("SELECT sent_at FROM poll_outbound WHERE id = 1").fetchone()
        if row is None:
            return None
        return str(row["sent_at"])

    def note_outbound(self, now: datetime) -> None:
        stamp = _stamp(now)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO poll_outbound (id, sent_at) VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET sent_at = excluded.sent_at
                """,
                (stamp,),
            )

    def recover(self, now: datetime) -> None:
        cutoff = _stamp(now - _STALE)
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE polls SET status = 'ativa'
                WHERE status = 'enviando' AND wa_message_id IS NOT NULL AND updated_at <= ?
                """,
                (cutoff,),
            )
            self._connection.execute(
                """
                UPDATE polls SET status = 'agendada'
                WHERE status = 'enviando' AND wa_message_id IS NULL AND updated_at <= ?
                """,
                (cutoff,),
            )
            self._connection.execute(
                """
                UPDATE polls SET status = 'ativa'
                WHERE status = 'encerrando' AND updated_at <= ?
                """,
                (cutoff,),
            )
            self._connection.execute(
                """
                UPDATE poll_jobs SET status = 'pending'
                WHERE status = 'sending' AND updated_at <= ?
                """,
                (cutoff,),
            )

    def claim(self, poll_id: int, expected: str, new: str, now: datetime) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE polls SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (new, _stamp(now), poll_id, expected),
            )
        return cursor.rowcount == 1

    def close_now(self, poll_id: int, now: datetime) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE polls SET closes_at = ?, updated_at = ?
                WHERE id = ? AND status = 'ativa'
                """,
                (_stamp(now), _stamp(now), poll_id),
            )
        return cursor.rowcount == 1

    def enqueue(self, poll_id: int | None, kind: str, payload: str, now: datetime) -> None:
        stamp = _stamp(now)
        with self._lock, self._connection:
            pending = self._connection.execute(
                """
                SELECT 1 FROM poll_jobs
                WHERE poll_id IS ? AND kind = ? AND status = 'pending'
                """,
                (poll_id, kind),
            ).fetchone()
            if pending is not None:
                return
            self._connection.execute(
                """
                INSERT INTO poll_jobs (poll_id, kind, payload, status, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (poll_id, kind, payload, stamp, stamp),
            )

    def next_action(self, now: datetime) -> tuple[str, int] | None:
        stamp = _stamp(now)
        with self._lock:
            closing = self._connection.execute(
                """
                SELECT id FROM polls
                WHERE status = 'ativa' AND closes_at IS NOT NULL AND closes_at <= ?
                ORDER BY closes_at, id
                LIMIT 1
                """,
                (stamp,),
            ).fetchone()
            if closing is not None:
                return ("close", int(closing["id"]))
            job = self._connection.execute(
                """
                SELECT id FROM poll_jobs
                WHERE status = 'pending'
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()
            if job is not None:
                return ("job", int(job["id"]))
            sending = self._connection.execute(
                """
                SELECT id FROM polls
                WHERE status = 'agendada' AND send_at <= ?
                ORDER BY send_at, id
                LIMIT 1
                """,
                (stamp,),
            ).fetchone()
        if sending is None:
            return None
        return ("send", int(sending["id"]))

    def claim_job(self, job_id: int, now: datetime) -> sqlite3.Row | None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE poll_jobs SET status = 'sending', updated_at = ? WHERE id = ? AND status = 'pending'",
                (_stamp(now), job_id),
            )
            if cursor.rowcount != 1:
                return None
            return self._connection.execute("SELECT * FROM poll_jobs WHERE id = ?", (job_id,)).fetchone()

    def finish_job(self, job_id: int, now: datetime) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE poll_jobs SET status = 'done', updated_at = ? WHERE id = ?",
                (_stamp(now), job_id),
            )

    def release_job(self, job_id: int, now: datetime) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE poll_jobs SET status = 'pending', updated_at = ? WHERE id = ?",
                (_stamp(now), job_id),
            )

    def remember(self, event_id: str, kind: str, body: dict, poll_id: int | None, now: datetime) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO poll_events (event_id, poll_id, kind, body, received_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (event_id, poll_id, kind, json.dumps(body, ensure_ascii=False), _stamp(now)),
            )
        return cursor.rowcount == 1

    def poll_id_for_message(self, message_id: str) -> int | None:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, wa_message_id FROM polls WHERE wa_message_id IS NOT NULL"
            ).fetchall()
        for row in rows:
            if _same_message(str(row["wa_message_id"]), message_id):
                return int(row["id"])
        return None

    def apply_vote(self, poll_id: int, voter_id: str, options: list[str], timestamp: int, now: datetime) -> None:
        encoded = json.dumps(list(options), ensure_ascii=False)
        with self._lock, self._connection:
            current = self._connection.execute(
                "SELECT vote_timestamp FROM poll_votes WHERE poll_id = ? AND voter_id = ?",
                (poll_id, voter_id),
            ).fetchone()
            if current is not None and int(current["vote_timestamp"]) >= timestamp:
                return
            self._connection.execute(
                """
                INSERT INTO poll_votes (poll_id, voter_id, options_json, vote_timestamp, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(poll_id, voter_id) DO UPDATE SET
                    options_json = excluded.options_json,
                    vote_timestamp = excluded.vote_timestamp,
                    updated_at = excluded.updated_at
                """,
                (poll_id, voter_id, encoded, timestamp, _stamp(now)),
            )
            voters = self._connection.execute(
                """
                SELECT COUNT(*) AS total FROM poll_votes
                WHERE poll_id = ? AND options_json != '[]'
                """,
                (poll_id,),
            ).fetchone()
            self._connection.execute(
                "INSERT INTO poll_points (poll_id, vote_timestamp, voters) VALUES (?, ?, ?)",
                (poll_id, timestamp, int(voters["total"])),
            )

    def count_failed(self, poll_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE polls SET failed_votes = failed_votes + 1 WHERE id = ?",
                (poll_id,),
            )

    def latest_active(self, chat_id: str) -> int | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT id FROM polls
                WHERE chat_id = ? AND status = 'ativa'
                ORDER BY id DESC
                LIMIT 1
                """,
                (chat_id,),
            ).fetchone()
        if row is None:
            return None
        return int(row["id"])

    def duplicate(self, poll_id: int, now: datetime) -> int:
        ids = self.batch_ids(poll_id)
        source = self.detail(ids[0])
        closes_at = None
        if source.closes_at:
            span = datetime.fromisoformat(source.closes_at) - datetime.fromisoformat(source.send_at)
            closes_at = now + span
        if len(ids) == 1:
            return self.create(
                chat_id=source.chat_id,
                group_name=source.group_name,
                question=source.question,
                options=source.options,
                multiple=source.multiple,
                pin=source.pin,
                send_at=now,
                closes_at=closes_at,
            )
        groups = [(self.detail(item).chat_id, self.detail(item).group_name) for item in ids]
        return self.create_for_groups(
            groups,
            question=source.question,
            options=source.options,
            multiple=source.multiple,
            pin=source.pin,
            send_at=now,
            closes_at=closes_at,
        )

    def choose_pin(self, poll_id: int, pin: str) -> None:
        if pin not in PIN_SECONDS:
            raise PollError("Fixar a enquete só pode ser por 24h, 7 dias ou 30 dias.")
        with self._lock, self._connection:
            self._connection.execute("UPDATE polls SET pin = ? WHERE id = ?", (pin, poll_id))

    def abandon(self, poll_id: int, now: datetime) -> bool:
        stamp = _stamp(now)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE polls
                SET status = 'encerrada', closed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'agendada'
                """,
                (stamp, stamp, poll_id),
            )
        return cursor.rowcount == 1

    def _batch_summary(self, batch_id: str) -> PollSummary:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT p.*, (
                    SELECT COUNT(*) FROM poll_votes v
                    WHERE v.poll_id = p.id AND v.options_json != '[]'
                ) AS voters
                FROM polls p
                WHERE p.batch_id = ?
                ORDER BY p.id
                """,
                (batch_id,),
            ).fetchall()
        first = rows[0]
        return PollSummary(
            id=int(first["id"]),
            chat_id=str(first["chat_id"]),
            group_name="Todos os grupos",
            question=str(first["question"]),
            status=_batch_status([str(row["status"]) for row in rows]),
            pin=str(first["pin"]) if first["pin"] else None,
            send_at=str(first["send_at"]),
            closes_at=str(first["closes_at"]) if first["closes_at"] else None,
            voters=sum(int(row["voters"]) for row in rows),
            multiple=bool(first["multiple"]),
        )

    def _combined_series(self, poll_ids: list[int]) -> tuple[tuple[int, int], ...]:
        placeholders = ",".join("?" for _ in poll_ids)
        with self._lock:
            points = self._connection.execute(
                f"""
                SELECT poll_id, vote_timestamp, voters FROM poll_points
                WHERE poll_id IN ({placeholders})
                ORDER BY vote_timestamp, id
                """,
                poll_ids,
            ).fetchall()
        latest = {item: 0 for item in poll_ids}
        series: list[tuple[int, int]] = []
        for point in points:
            latest[int(point["poll_id"])] = int(point["voters"])
            series.append((int(point["vote_timestamp"]), sum(latest.values())))
        return tuple(series)


def handle_webhook(
    store: PollStore,
    body: dict,
    *,
    session: str,
    links: dict[str, str],
    is_admin: Callable[[str, str], bool] | None = None,
    allowed_groups: set[str] | None = None,
    group_names: dict[str, str] | None = None,
    now: datetime | None = None,
) -> str:
    if body.get("session") != session:
        return "ignored"
    moment = now or datetime.now().astimezone()
    event = str(body.get("event") or "")
    event_id = str(body.get("id") or "")
    if not event_id:
        return "ignored"
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    if event in {"poll.vote", "poll.vote.failed"}:
        return _take_vote(store, body, event, event_id, payload, links, moment)
    if event == "message":
        return _take_command(
            store,
            body,
            event_id,
            payload,
            links,
            is_admin,
            allowed_groups,
            group_names or {},
            moment,
        )
    return "ignored"


def advance_polls(
    store: PollStore,
    sender: PollSender,
    now: datetime,
    *,
    gap_seconds: int,
    other_sent_at: str | None,
) -> str:
    store.recover(now)
    action = store.next_action(now)
    if action is None:
        return "idle"
    if sender.connection_state() != "connected":
        return "disconnected"
    last_sent = latest_stamp((store.last_outbound_at(), other_sent_at), now)
    if not gap_open(last_sent, now, gap_seconds):
        return "waiting"
    kind, target = action
    try:
        if kind == "send":
            return _send_poll(store, sender, target, now)
        if kind == "close":
            return _close_poll(store, sender, target, now)
        return _run_job(store, sender, target, now)
    except WahaError as exc:
        logger.warning("Enquete adiada: %s", exc)
        return "waiting" if exc.session_down else "failed"


def result_message(
    question: str,
    options: tuple[str, ...] | list[str],
    counts: dict[str, int],
    voters: int,
    *,
    partial: bool,
    groups: int = 1,
) -> str:
    lines: list[str] = []
    if partial:
        lines.extend(["Parcial", ""])
    if groups > 1:
        lines.extend([f"Total dos {groups} grupos", ""])
    lines.extend([question, ""])
    for label in options:
        count = counts.get(label, 0)
        percent = round(100 * count / voters) if voters else 0
        filled = max(0, min(10, round(percent / 10)))
        bar = "🟩" * filled + "⬜" * (10 - filled)
        lines.append(f"{label}  {bar}  {percent}% · {count}")
    noun = "votante" if voters == 1 else "votantes"
    lines.extend(["", f"{voters} {noun}"])
    return "\n".join(lines)


def person_is_admin(people: list[tuple[str, str]], participant: str, links: dict[str, str]) -> bool:
    for member_id, role in people:
        if role in _ADMIN_ROLES and _same_person(member_id, participant, links):
            return True
    return False


def _send_poll(store: PollStore, sender: PollSender, poll_id: int, now: datetime) -> str:
    if not store.claim(poll_id, "agendada", "enviando", now):
        return "idle"
    poll = store.detail(poll_id)
    try:
        message_id = sender.send_poll(poll.chat_id, poll.question, list(poll.options), poll.multiple)
    except WahaError:
        store.claim(poll_id, "enviando", "agendada", now)
        raise
    pin_ok = _try_pin(sender, poll, message_id)
    store.mark_sent(poll_id, message_id, pin_ok)
    store.note_outbound(now)
    logger.info("Enquete %s enviada para %s.", poll_id, poll.group_name)
    return "sent"


def _close_poll(store: PollStore, sender: PollSender, poll_id: int, now: datetime) -> str:
    if not store.claim(poll_id, "ativa", "encerrando", now):
        return "idle"
    own = store.detail(poll_id)
    view = store.combined(poll_id)
    text = result_message(
        view.question,
        view.options,
        view.counts,
        view.voters,
        partial=False,
        groups=view.batch_size,
    )
    try:
        sender.send(own.chat_id, text, None)
    except WahaError:
        store.claim(poll_id, "encerrando", "ativa", now)
        raise
    if own.pin_ok and own.message_id:
        try:
            sender.unpin_message(own.chat_id, own.message_id)
        except WahaError as exc:
            logger.warning("Não desafixei a enquete %s: %s", poll_id, exc)
    store.mark_closed(poll_id, now)
    store.note_outbound(now)
    logger.info("Enquete %s encerrada em %s.", poll_id, own.group_name)
    return "sent"


def _run_job(store: PollStore, sender: PollSender, job_id: int, now: datetime) -> str:
    job = store.claim_job(job_id, now)
    if job is None:
        return "idle"
    kind = str(job["kind"])
    try:
        if kind == "partial" and job["poll_id"] is not None:
            _post_partial(store, sender, int(job["poll_id"]))
        elif kind == "reply":
            payload = json.loads(str(job["payload"]))
            sender.send(str(payload["chat_id"]), str(payload["text"]), None)
        elif kind == "pin" and job["poll_id"] is not None:
            _pin_again(store, sender, int(job["poll_id"]))
        elif kind == "unpin" and job["poll_id"] is not None:
            _unpin_again(store, sender, int(job["poll_id"]))
        elif kind == "close" and job["poll_id"] is not None:
            store.release_job(job_id, now)
            return _close_poll(store, sender, int(job["poll_id"]), now)
    except WahaError:
        store.release_job(job_id, now)
        raise
    store.finish_job(job_id, now)
    store.note_outbound(now)
    return "sent"


def _post_partial(store: PollStore, sender: PollSender, poll_id: int) -> None:
    own = store.detail(poll_id)
    view = store.combined(poll_id)
    sender.send(
        own.chat_id,
        result_message(
            view.question,
            view.options,
            view.counts,
            view.voters,
            partial=True,
            groups=view.batch_size,
        ),
        None,
    )


def _pin_again(store: PollStore, sender: PollSender, poll_id: int) -> None:
    poll = store.detail(poll_id)
    if not poll.message_id or not poll.pin:
        logger.warning("Enquete %s não tem mensagem para fixar.", poll_id)
        return
    if _try_pin(sender, poll, poll.message_id):
        store.mark_pin(poll_id, True)


def _unpin_again(store: PollStore, sender: PollSender, poll_id: int) -> None:
    poll = store.detail(poll_id)
    if not poll.message_id:
        return
    try:
        sender.unpin_message(poll.chat_id, poll.message_id)
    except WahaError as exc:
        logger.warning("Não desafixei a enquete %s: %s", poll_id, exc)
        if exc.session_down:
            raise
        return
    store.mark_pin(poll_id, False)


def _try_pin(sender: PollSender, poll: PollDetail, message_id: str) -> bool:
    if not poll.pin:
        return False
    try:
        sender.pin_message(poll.chat_id, message_id, PIN_SECONDS[poll.pin])
    except WahaError as exc:
        logger.warning("Não fixei a enquete %s: %s", poll.id, exc)
        return False
    return True


def _take_vote(
    store: PollStore,
    body: dict,
    event: str,
    event_id: str,
    payload: dict,
    links: dict[str, str],
    now: datetime,
) -> str:
    vote = payload.get("vote") if isinstance(payload.get("vote"), dict) else {}
    poll = payload.get("poll") if isinstance(payload.get("poll"), dict) else {}
    message_id = str(poll.get("id") or "")
    poll_id = store.poll_id_for_message(message_id) if message_id else None
    if not store.remember(event_id, event, body, poll_id, now):
        return "duplicate"
    if poll_id is None:
        logger.warning("Voto sem enquete correspondente: %s", _message_token(message_id) or "sem id")
        return "ok"
    if event == "poll.vote.failed":
        store.count_failed(poll_id)
        logger.info("Voto da enquete %s não pôde ser lido.", poll_id)
        return "ok"
    voter = str(vote.get("from") or "")
    if not voter:
        return "ok"
    selected = vote.get("selectedOptions")
    options = [str(item) for item in selected] if isinstance(selected, list) else []
    timestamp = _timestamp(vote.get("timestamp"))
    store.apply_vote(poll_id, links.get(voter, voter), options, timestamp, now)
    return "ok"


def _take_command(
    store: PollStore,
    body: dict,
    event_id: str,
    payload: dict,
    links: dict[str, str],
    is_admin: Callable[[str, str], bool] | None,
    allowed_groups: set[str] | None,
    group_names: dict[str, str],
    now: datetime,
) -> str:
    if payload.get("fromMe"):
        return "ignored"
    chat_id = str(payload.get("from") or "")
    text = str(payload.get("body") or payload.get("text") or "")
    if not chat_id.endswith("@g.us"):
        return "ignored"
    try:
        command = parse_group_command(text)
    except PollCommandError:
        command = None
        parse_error = True
    else:
        parse_error = False
    if command is None and not parse_error:
        return "ignored"
    if not store.remember(event_id, "message", body, None, now):
        return "duplicate"
    if allowed_groups is not None and chat_id not in allowed_groups:
        return "ok"
    participant = str(payload.get("participant") or "")
    if is_admin is None or not participant or not is_admin(chat_id, participant):
        return "ok"
    if parse_error:
        store.enqueue(
            None,
            "reply",
            json.dumps(
                {
                    "chat_id": chat_id,
                    "text": "Não entendi. Use !enquete Pergunta | opção 1 | opção 2 --fixar 7d --multi --fecha 48h",
                },
                ensure_ascii=False,
            ),
            now,
        )
        return "ok"
    if command == "resultado":
        _queue_partial(store, chat_id, now)
        return "ok"
    if command == "encerrar":
        _queue_close(store, chat_id, now)
        return "ok"
    assert not isinstance(command, str)
    closes_at = now + command.closes_after if command.closes_after else None
    store.create(
        chat_id=chat_id,
        group_name=group_names.get(chat_id, chat_id),
        question=command.question,
        options=command.options,
        multiple=command.multiple,
        pin=command.pin,
        send_at=now,
        closes_at=closes_at,
    )
    del links
    return "ok"


def _queue_partial(store: PollStore, chat_id: str, now: datetime) -> None:
    poll_id = store.latest_active(chat_id)
    if poll_id is None:
        store.enqueue(
            None,
            "reply",
            json.dumps({"chat_id": chat_id, "text": "Não há enquete ativa neste grupo."}, ensure_ascii=False),
            now,
        )
        return
    store.enqueue(poll_id, "partial", "", now)


def _queue_close(store: PollStore, chat_id: str, now: datetime) -> None:
    poll_id = store.latest_active(chat_id)
    if poll_id is None:
        store.enqueue(
            None,
            "reply",
            json.dumps({"chat_id": chat_id, "text": "Não há enquete ativa neste grupo."}, ensure_ascii=False),
            now,
        )
        return
    store.close_now(poll_id, now)


def _summary(row: sqlite3.Row) -> PollSummary:
    return PollSummary(
        id=int(row["id"]),
        chat_id=str(row["chat_id"]),
        group_name=str(row["group_name"]),
        question=str(row["question"]),
        status=str(row["status"]),
        pin=str(row["pin"]) if row["pin"] else None,
        send_at=str(row["send_at"]),
        closes_at=str(row["closes_at"]) if row["closes_at"] else None,
        voters=int(row["voters"]),
        multiple=bool(row["multiple"]),
    )


def _validated_options(question: str, options: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    title = question.strip()
    labels = tuple(item.strip() for item in options if item.strip())
    if not title or len(title) > 255:
        raise PollError("A pergunta precisa ter entre 1 e 255 caracteres.")
    if not 2 <= len(labels) <= 12:
        raise PollError("A enquete precisa de 2 a 12 opções.")
    if any(len(label) > 100 for label in labels):
        raise PollError("Cada opção aceita no máximo 100 caracteres.")
    if len({label.casefold() for label in labels}) != len(labels):
        raise PollError("As opções precisam ser diferentes.")
    return labels


def _options_of(encoded: str) -> list[str]:
    try:
        loaded = json.loads(encoded)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if str(item)]


_WA_TOKEN = re.compile(r"[0-9A-F]*[A-F][0-9A-F]{9,}")


def _message_token(value: str) -> str:
    found = _WA_TOKEN.findall(value.upper())
    return found[-1] if found else ""


def _same_message(stored: str, incoming: str) -> bool:
    if stored == incoming:
        return True
    left = _message_token(stored)
    right = _message_token(incoming)
    return bool(left) and left == right


def _same_person(left: str, right: str, links: dict[str, str]) -> bool:
    return links.get(left, left) == links.get(right, right)


def _timestamp(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _batch_status(statuses: list[str]) -> str:
    if any(item in {"ativa", "encerrando"} for item in statuses):
        return "ativa"
    if any(item in {"agendada", "enviando"} for item in statuses):
        return "agendada"
    return "encerrada"


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    have = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in have:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
