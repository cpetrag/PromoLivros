"""Campanhas de convite: fotos, textos e o registro de cada convite do dia."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from promo_livros.campaign_rules import INVITE_KINDS, RotationEntry

MAX_NAME_LENGTH = 80
MAX_TEXT_LENGTH = 1024
BUSY_TIMEOUT_MS = 5000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_texts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_runs (
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
CREATE TABLE IF NOT EXISTS campaign_run_groups (
    run_id INTEGER NOT NULL REFERENCES campaign_runs(id) ON DELETE CASCADE,
    chat_id TEXT NOT NULL,
    message_id TEXT,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (run_id, chat_id)
);
"""

_CAMPAIGN_SELECT = """
SELECT c.id, c.name, c.active, c.position,
    (SELECT COUNT(*) FROM campaign_images i WHERE i.campaign_id = c.id) AS image_count,
    (SELECT COUNT(*) FROM campaign_texts t WHERE t.campaign_id = c.id) AS text_count
FROM campaigns c
"""

_RUN_SELECT = """
SELECT id, day, kind, campaign_id, manual, image_id, text_id, status, sent_at
FROM campaign_runs
"""


class CampaignError(ValueError):
    """Pedido inválido vindo do painel. A mensagem vai para a tela."""


@dataclass(frozen=True)
class Campaign:
    id: int
    name: str
    active: bool
    position: int
    image_count: int
    text_count: int

    @property
    def ready(self) -> bool:
        return self.active and self.image_count > 0 and self.text_count > 0


@dataclass(frozen=True)
class CampaignImage:
    id: int
    campaign_id: int
    path: str


@dataclass(frozen=True)
class CampaignText:
    id: int
    campaign_id: int
    body: str


@dataclass(frozen=True)
class CampaignRun:
    id: int
    day: str
    kind: str
    campaign_id: int | None
    manual: bool
    image_id: int | None
    text_id: int | None
    status: str
    sent_at: str | None


class CampaignStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    # Campanhas

    def create(self, name: str) -> int:
        clean = _clean_name(name)
        with self._lock, self._connection:
            row = self._connection.execute("SELECT COALESCE(MAX(position), 0) + 1 AS next FROM campaigns").fetchone()
            cursor = self._connection.execute(
                "INSERT INTO campaigns (name, active, position, created_at) VALUES (?, 1, ?, datetime('now'))",
                (clean, int(row["next"])),
            )
            return int(cursor.lastrowid)

    def rename(self, campaign_id: int, name: str) -> None:
        clean = _clean_name(name)
        with self._lock, self._connection:
            self._connection.execute("UPDATE campaigns SET name = ? WHERE id = ?", (clean, campaign_id))

    def set_active(self, campaign_id: int, active: bool) -> None:
        with self._lock, self._connection:
            self._connection.execute("UPDATE campaigns SET active = ? WHERE id = ?", (1 if active else 0, campaign_id))

    def move(self, campaign_id: int, direction: int) -> None:
        """direction negativo sobe, positivo desce. Troca de lugar com a vizinha."""
        with self._lock, self._connection:
            ids = [int(row["id"]) for row in self._connection.execute("SELECT id FROM campaigns ORDER BY position, id")]
            if campaign_id not in ids:
                return
            index = ids.index(campaign_id)
            target = index + (1 if direction > 0 else -1)
            if not 0 <= target < len(ids):
                return
            ids[index], ids[target] = ids[target], ids[index]
            for position, item in enumerate(ids, start=1):
                self._connection.execute("UPDATE campaigns SET position = ? WHERE id = ?", (position, item))

    def delete(self, campaign_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))

    def campaigns(self) -> list[Campaign]:
        with self._lock:
            rows = self._connection.execute(_CAMPAIGN_SELECT + " ORDER BY c.position, c.id").fetchall()
        return [_campaign(row) for row in rows]

    def campaign(self, campaign_id: int) -> Campaign | None:
        with self._lock:
            row = self._connection.execute(_CAMPAIGN_SELECT + " WHERE c.id = ?", (campaign_id,)).fetchone()
        return _campaign(row) if row else None

    def ready_campaigns(self) -> list[Campaign]:
        return [item for item in self.campaigns() if item.ready]

    # Fotos

    def add_image(self, campaign_id: int, path: str) -> int:
        try:
            with self._lock, self._connection:
                cursor = self._connection.execute(
                    "INSERT INTO campaign_images (campaign_id, path, created_at) VALUES (?, ?, datetime('now'))",
                    (campaign_id, path),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise CampaignError("Campanha não encontrada.") from exc

    def images(self, campaign_id: int) -> list[CampaignImage]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, campaign_id, path FROM campaign_images WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [CampaignImage(int(row["id"]), int(row["campaign_id"]), str(row["path"])) for row in rows]

    def image(self, image_id: int) -> CampaignImage | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, campaign_id, path FROM campaign_images WHERE id = ?",
                (image_id,),
            ).fetchone()
        return CampaignImage(int(row["id"]), int(row["campaign_id"]), str(row["path"])) if row else None

    def delete_image(self, image_id: int) -> str | None:
        """Apaga o registro e devolve o caminho para tirar o arquivo do disco."""
        with self._lock, self._connection:
            row = self._connection.execute(
                "DELETE FROM campaign_images WHERE id = ? RETURNING path",
                (image_id,),
            ).fetchone()
        return str(row["path"]) if row else None

    # Textos

    def add_text(self, campaign_id: int, body: str) -> int:
        clean = _clean_text(body)
        try:
            with self._lock, self._connection:
                cursor = self._connection.execute(
                    "INSERT INTO campaign_texts (campaign_id, body, created_at) VALUES (?, ?, datetime('now'))",
                    (campaign_id, clean),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise CampaignError("Campanha não encontrada.") from exc

    def update_text(self, text_id: int, body: str) -> None:
        clean = _clean_text(body)
        with self._lock, self._connection:
            self._connection.execute("UPDATE campaign_texts SET body = ? WHERE id = ?", (clean, text_id))

    def texts(self, campaign_id: int) -> list[CampaignText]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, campaign_id, body FROM campaign_texts WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            ).fetchall()
        return [CampaignText(int(row["id"]), int(row["campaign_id"]), str(row["body"])) for row in rows]

    def text(self, text_id: int) -> CampaignText | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, campaign_id, body FROM campaign_texts WHERE id = ?",
                (text_id,),
            ).fetchone()
        return CampaignText(int(row["id"]), int(row["campaign_id"]), str(row["body"])) if row else None

    def delete_text(self, text_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM campaign_texts WHERE id = ?", (text_id,))

    # Convites do dia

    def run_for(self, day: str, kind: str) -> CampaignRun:
        if kind not in INVITE_KINDS:
            raise CampaignError("Tipo de convite desconhecido.")
        with self._lock, self._connection:
            self._connection.execute("INSERT OR IGNORE INTO campaign_runs (day, kind) VALUES (?, ?)", (day, kind))
            row = self._connection.execute(_RUN_SELECT + " WHERE day = ? AND kind = ?", (day, kind)).fetchone()
        return _run(row)

    def peek_run(self, day: str, kind: str) -> CampaignRun | None:
        """Como run_for, mas só lê. None quer dizer que o convite ainda não começou (pendente)."""
        if kind not in INVITE_KINDS:
            raise CampaignError("Tipo de convite desconhecido.")
        with self._lock:
            row = self._connection.execute(_RUN_SELECT + " WHERE day = ? AND kind = ?", (day, kind)).fetchone()
        return _run(row) if row else None

    def run(self, run_id: int) -> CampaignRun | None:
        with self._lock:
            row = self._connection.execute(_RUN_SELECT + " WHERE id = ?", (run_id,)).fetchone()
        return _run(row) if row else None

    def set_manual_campaign(self, day: str, kind: str, campaign_id: int | None) -> bool:
        """Só troca enquanto o convite não começou. None devolve ao rodízio."""
        run = self.run_for(day, kind)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE campaign_runs SET campaign_id = ?, manual = ? WHERE id = ? AND status = 'pending'",
                (campaign_id, 0 if campaign_id is None else 1, run.id),
            )
        return cursor.rowcount == 1

    def lock_content(
        self,
        run_id: int,
        campaign_id: int,
        image_id: int,
        text_id: int,
        locked_at: str,
        *,
        expected: CampaignRun | None = None,
    ) -> CampaignRun | None:
        """Trava o conteúdo do convite. Relock mantém a hora original para o rodízio não mudar de ordem.

        Com `expected`, só trava se o registro ainda está como foi lido: uma troca manual feita
        no painel (ou outro envio) depois da leitura devolve None em vez de ser sobrescrita.
        """
        query = """
            UPDATE campaign_runs
            SET campaign_id = ?, image_id = ?, text_id = ?, status = 'sending',
                locked_at = COALESCE(locked_at, ?)
            WHERE id = ? AND status IN ('pending', 'sending')
        """
        parameters: list[object] = [campaign_id, image_id, text_id, locked_at, run_id]
        if expected is not None:
            query += " AND status = ? AND manual = ? AND campaign_id IS ? AND image_id IS ? AND text_id IS ?"
            parameters += [
                expected.status,
                1 if expected.manual else 0,
                expected.campaign_id,
                expected.image_id,
                expected.text_id,
            ]
        with self._lock, self._connection:
            cursor = self._connection.execute(query, parameters)
            if cursor.rowcount != 1:
                return None
            row = self._connection.execute(_RUN_SELECT + " WHERE id = ?", (run_id,)).fetchone()
        return _run(row)

    def skip_run(self, run_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE campaign_runs SET status = 'skipped' WHERE id = ? AND status IN ('pending', 'sending')",
                (run_id,),
            )

    def open_sending_run(self) -> CampaignRun | None:
        """Convite que começou e não terminou, o mais antigo primeiro. Termina mesmo depois da meia-noite."""
        with self._lock:
            row = self._connection.execute(
                _RUN_SELECT + " WHERE status = 'sending' ORDER BY day, locked_at, id LIMIT 1"
            ).fetchone()
        return _run(row) if row else None

    def claim_group_send(self, run_id: int, chat_id: str, claimed_at: str) -> bool:
        """Reserva o grupo antes de mandar. False se outro envio já reservou ou mandou."""
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO campaign_run_groups (run_id, chat_id, message_id, sent_at) VALUES (?, ?, NULL, ?)",
                (run_id, chat_id, claimed_at),
            )
        return cursor.rowcount == 1

    def finish_group_send(self, run_id: int, chat_id: str, message_id: str, sent_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE campaign_run_groups SET message_id = ?, sent_at = ?
                WHERE run_id = ? AND chat_id = ? AND message_id IS NULL
                """,
                (message_id, sent_at, run_id, chat_id),
            )

    def release_group_send(self, run_id: int, chat_id: str) -> None:
        """Desfaz só a reserva; um envio confirmado nunca é apagado."""
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM campaign_run_groups WHERE run_id = ? AND chat_id = ? AND message_id IS NULL",
                (run_id, chat_id),
            )

    def sent_chat_ids(self, run_id: int) -> set[str]:
        """Grupos enviados ou reservados. Reserva órfã conta como feita: pular um grupo é melhor que repetir."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT chat_id FROM campaign_run_groups WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        return {str(row["chat_id"]) for row in rows}

    def mark_run_sent(self, run_id: int, sent_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE campaign_runs SET status = 'sent', sent_at = ? WHERE id = ? AND status IN ('pending', 'sending')",
                (sent_at, run_id),
            )

    def last_used_campaign(self) -> RotationEntry | None:
        """Campanha do último convite travado. Apagada ela some e o rodízio recomeça."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT r.campaign_id, c.position
                FROM campaign_runs r LEFT JOIN campaigns c ON c.id = r.campaign_id
                WHERE r.locked_at IS NOT NULL
                ORDER BY r.locked_at DESC, r.id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None or row["position"] is None:
            return None
        return RotationEntry(int(row["campaign_id"]), int(row["position"]))

    def last_content(self, campaign_id: int) -> tuple[int | None, int | None]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT image_id, text_id FROM campaign_runs
                WHERE campaign_id = ? AND locked_at IS NOT NULL
                ORDER BY locked_at DESC, id DESC
                LIMIT 1
                """,
                (campaign_id,),
            ).fetchone()
        if row is None:
            return None, None
        return row["image_id"], row["text_id"]

    def last_sent_at(self) -> str | None:
        with self._lock:
            row = self._connection.execute("SELECT MAX(sent_at) AS last FROM campaign_run_groups").fetchone()
        return str(row["last"]) if row and row["last"] else None


def _campaign(row: sqlite3.Row) -> Campaign:
    return Campaign(
        id=int(row["id"]),
        name=str(row["name"]),
        active=bool(row["active"]),
        position=int(row["position"]),
        image_count=int(row["image_count"]),
        text_count=int(row["text_count"]),
    )


def _run(row: sqlite3.Row) -> CampaignRun:
    return CampaignRun(
        id=int(row["id"]),
        day=str(row["day"]),
        kind=str(row["kind"]),
        campaign_id=row["campaign_id"],
        manual=bool(row["manual"]),
        image_id=row["image_id"],
        text_id=row["text_id"],
        status=str(row["status"]),
        sent_at=row["sent_at"],
    )


def _clean_name(name: str) -> str:
    clean = " ".join(name.split())
    if not clean:
        raise CampaignError("Dê um nome para a campanha.")
    if len(clean) > MAX_NAME_LENGTH:
        raise CampaignError(f"O nome passa de {MAX_NAME_LENGTH} caracteres.")
    return clean


def _clean_text(body: str) -> str:
    clean = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean:
        raise CampaignError("O texto está vazio.")
    if len(clean) > MAX_TEXT_LENGTH:
        raise CampaignError(f"O texto passa de {MAX_TEXT_LENGTH} caracteres, o limite da legenda no WhatsApp.")
    return clean
