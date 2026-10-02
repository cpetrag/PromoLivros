"""Membros dos grupos, sem contar administrador. A movimentação do dia fica no sqlite."""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

_LEFT = "left"
_MEMBER = "participant"


@dataclass(frozen=True)
class GroupMembers:
    name: str
    liquid: int
    joined: int
    left: int

    @property
    def net(self) -> int:
        return self.joined - self.left


@dataclass(frozen=True)
class MembershipView:
    available: bool
    groups: tuple[GroupMembers, ...] = ()

    @property
    def liquid(self) -> int:
        return sum(group.liquid for group in self.groups)

    @property
    def joined(self) -> int:
        return sum(group.joined for group in self.groups)

    @property
    def left(self) -> int:
        return sum(group.left for group in self.groups)

    @property
    def net(self) -> int:
        return self.joined - self.left


class MembershipStore:
    """Guarda o conjunto de membros para saber quem entrou e quem saiu.

    A primeira leitura de cada grupo só cria a base. Não conta como entrada,
    porque o WhatsApp não devolve o histórico do dia.
    """

    def __init__(self, path: Path) -> None:
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS group_roster (
                chat_id TEXT NOT NULL,
                member_hash TEXT NOT NULL,
                PRIMARY KEY (chat_id, member_hash)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS group_roster_seen (
                chat_id TEXT PRIMARY KEY
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS group_flow (
                day TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                member_hash TEXT NOT NULL,
                kind TEXT NOT NULL,
                PRIMARY KEY (day, chat_id, member_hash, kind)
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def observe(self, day: str, chat_id: str, name: str, people: list[tuple[str, str]]) -> GroupMembers:
        if not people:
            raise ValueError("A lista de membros veio vazia.")
        current = {_hash(member_id) for member_id, role in people if member_id and role != _LEFT}
        with self._lock, self._connection:
            seen = self._connection.execute(
                "SELECT 1 FROM group_roster_seen WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if seen is None:
                self._replace(chat_id, current)
                self._connection.execute(
                    "INSERT INTO group_roster_seen (chat_id) VALUES (?)",
                    (chat_id,),
                )
            else:
                previous = {
                    str(row["member_hash"])
                    for row in self._connection.execute(
                        "SELECT member_hash FROM group_roster WHERE chat_id = ?",
                        (chat_id,),
                    )
                }
                self._flow(day, chat_id, current - previous, "join")
                self._flow(day, chat_id, previous - current, "leave")
                self._replace(chat_id, current)
            joined, left = self._counts(day, chat_id)
        return GroupMembers(name=name, liquid=_liquid(people), joined=joined, left=left)

    def _replace(self, chat_id: str, current: set[str]) -> None:
        self._connection.execute("DELETE FROM group_roster WHERE chat_id = ?", (chat_id,))
        self._connection.executemany(
            "INSERT INTO group_roster (chat_id, member_hash) VALUES (?, ?)",
            [(chat_id, member_hash) for member_hash in current],
        )

    def _flow(self, day: str, chat_id: str, members: set[str], kind: str) -> None:
        self._connection.executemany(
            """
            INSERT INTO group_flow (day, chat_id, member_hash, kind)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(day, chat_id, member_hash, kind) DO NOTHING
            """,
            [(day, chat_id, member_hash, kind) for member_hash in members],
        )

    def _counts(self, day: str, chat_id: str) -> tuple[int, int]:
        row = self._connection.execute(
            """
            SELECT
                SUM(CASE WHEN kind = 'join' THEN 1 ELSE 0 END) AS joined,
                SUM(CASE WHEN kind = 'leave' THEN 1 ELSE 0 END) AS left_count
            FROM group_flow
            WHERE day = ? AND chat_id = ?
            """,
            (day, chat_id),
        ).fetchone()
        return int(row["joined"] or 0), int(row["left_count"] or 0)


def _liquid(people: list[tuple[str, str]]) -> int:
    return sum(1 for _member_id, role in people if role == _MEMBER)


def _hash(member_id: str) -> str:
    return hashlib.sha256(member_id.encode("utf-8")).hexdigest()
