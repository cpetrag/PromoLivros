"""Campanhas de convite: fotos, textos e o registro de cada convite do dia."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from promo_livros.campaign_rules import (
    INVITE_KINDS,
    RotationEntry,
    campaign_valid_on,
    is_rotating,
    parse_campaign_clock,
    parse_valid_until,
)

MAX_NAME_LENGTH = 80
MAX_TEXT_LENGTH = 1024
BUSY_TIMEOUT_MS = 5000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    fixed_clock TEXT,
    valid_until TEXT
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
    kind TEXT NOT NULL CHECK (kind IN ('fixed', 'last', 'clock')),
    campaign_id INTEGER,
    manual INTEGER NOT NULL DEFAULT 0,
    image_id INTEGER,
    text_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sending', 'sent', 'skipped')),
    locked_at TEXT,
    sent_at TEXT,
    clock TEXT
);
CREATE TABLE IF NOT EXISTS campaign_run_groups (
    run_id INTEGER NOT NULL REFERENCES campaign_runs(id) ON DELETE CASCADE,
    chat_id TEXT NOT NULL,
    message_id TEXT,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (run_id, chat_id)
);
"""

# Bancos criados antes dos convites por horário têm CHECK (kind) sem 'clock' e UNIQUE (day, kind).
# O SQLite não altera CHECK/UNIQUE no lugar, então a tabela é refeita preservando ids e grupos.
#
# Cada instrução roda separada dentro de um único BEGIN IMMEDIATE/COMMIT: queda no meio desfaz tudo
# e a tabela de histórico nunca fica trocada por uma vazia.
_REBUILD_RUNS_STATEMENTS = (
    "DROP TABLE IF EXISTS campaign_runs_new",
    """
CREATE TABLE campaign_runs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fixed', 'last', 'clock')),
    campaign_id INTEGER,
    manual INTEGER NOT NULL DEFAULT 0,
    image_id INTEGER,
    text_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sending', 'sent', 'skipped')),
    locked_at TEXT,
    sent_at TEXT,
    clock TEXT
)
""",
    """
INSERT INTO campaign_runs_new (id, day, kind, campaign_id, manual, image_id, text_id, status, locked_at, sent_at)
    SELECT id, day, kind, campaign_id, manual, image_id, text_id, status, locked_at, sent_at FROM campaign_runs
""",
    "DROP TABLE campaign_runs",
    "ALTER TABLE campaign_runs_new RENAME TO campaign_runs",
)

# 'fixed' fica único por dia só para o legado; o envio novo usa 'clock' (uma por campanha) e 'last'.
_RUN_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS campaign_runs_fixed_day ON campaign_runs(day) WHERE kind = 'fixed';
CREATE UNIQUE INDEX IF NOT EXISTS campaign_runs_last_day ON campaign_runs(day) WHERE kind = 'last';
CREATE UNIQUE INDEX IF NOT EXISTS campaign_runs_clock_day_campaign
    ON campaign_runs(day, campaign_id) WHERE kind = 'clock';
"""

_CAMPAIGN_SELECT = """
SELECT c.id, c.name, c.active, c.position, c.fixed_clock, c.valid_until,
    (SELECT COUNT(*) FROM campaign_images i WHERE i.campaign_id = c.id) AS image_count,
    (SELECT COUNT(*) FROM campaign_texts t WHERE t.campaign_id = c.id) AS text_count
FROM campaigns c
"""

_RUN_SELECT = """
SELECT id, day, kind, campaign_id, manual, image_id, text_id, status, sent_at, clock
FROM campaign_runs
"""


_ROTATING_RUN_LOCKS = """
SELECT r.campaign_id AS campaign_id, c.position AS position, r.locked_at AS locked_at, r.id AS row_id
FROM campaign_runs r
JOIN campaigns c ON c.id = r.campaign_id
WHERE r.kind = 'last' AND r.locked_at IS NOT NULL AND c.fixed_clock IS NULL
"""

_ROTATING_BOARD_LOCKS = """
SELECT p.campaign_id AS campaign_id, c.position AS position, p.campaign_locked_at AS locked_at, p.id AS row_id
FROM scheduled_posts p
JOIN campaigns c ON c.id = p.campaign_id
WHERE p.post_kind = 'campaign'
  AND p.campaign_id IS NOT NULL
  AND p.campaign_locked_at IS NOT NULL
  AND p.status NOT IN ('replaced', 'cancelled')
  AND c.fixed_clock IS NULL
"""

# Fila refeita ou limpa não envia o post; contá-lo faria o rodízio andar sem convite algum.
_LAST_CONTENT_RUNS = """
SELECT image_id, text_id, locked_at, id AS row_id FROM campaign_runs
WHERE campaign_id = ? AND locked_at IS NOT NULL
"""

_LAST_CONTENT_BOARD = """
SELECT image_id, text_id, campaign_locked_at AS locked_at, id AS row_id FROM scheduled_posts
WHERE campaign_id = ? AND post_kind = 'campaign' AND campaign_locked_at IS NOT NULL
  AND status NOT IN ('replaced', 'cancelled')
"""

_LAST_CONTENT_UNION = f"""
SELECT image_id, text_id FROM (
{_LAST_CONTENT_RUNS}
UNION ALL
{_LAST_CONTENT_BOARD}
)
ORDER BY locked_at DESC, row_id DESC
LIMIT 1
"""

_LAST_ROTATING_RUNS = f"SELECT campaign_id, position FROM ({_ROTATING_RUN_LOCKS}) ORDER BY locked_at DESC, row_id DESC LIMIT 1"

_LAST_ROTATING_UNION = f"""
SELECT campaign_id, position FROM (
{_ROTATING_RUN_LOCKS}
UNION ALL
{_ROTATING_BOARD_LOCKS}
)
ORDER BY locked_at DESC, row_id DESC
LIMIT 1
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
    fixed_clock: str | None = None
    valid_until: str | None = None

    @property
    def ready(self) -> bool:
        return self.active and self.image_count > 0 and self.text_count > 0

    def ready_on(self, day: str) -> bool:
        return self.ready and campaign_valid_on(self.valid_until, day)


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
    clock: str | None = None


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
        try:
            self._connection.executescript(_SCHEMA)
            self._migrate()
            self._connection.commit()
        except BaseException:
            # Migração que falha não pode deixar o arquivo preso pela conexão aberta.
            self._connection.close()
            raise

    def _migrate(self) -> None:
        """Leva bancos antigos ao esquema atual. Idempotente: roda a cada abertura."""
        self._add_column_if_missing("campaigns", "fixed_clock")
        self._add_column_if_missing("campaigns", "valid_until")
        self._add_column_if_missing("campaign_runs", "clock")
        if self._runs_table_needs_rebuild():
            self._rebuild_runs_table()
        self._connection.executescript(_RUN_INDEXES)

    def _runs_table_needs_rebuild(self) -> bool:
        row = self._connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'campaign_runs'"
        ).fetchone()
        return row is not None and "'clock'" not in row["sql"]

    def _rebuild_runs_table(self) -> None:
        # Com foreign_keys ligado, o DROP apagaria campaign_run_groups em cascata.
        # O PRAGMA não vale dentro de transação, por isso fica fora do BEGIN.
        self._connection.commit()
        self._connection.execute("PRAGMA foreign_keys = OFF")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                # Outra abertura pode ter migrado enquanto esperávamos o lock.
                if self._runs_table_needs_rebuild():
                    for statement in _REBUILD_RUNS_STATEMENTS:
                        self._connection.execute(statement)
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise
        finally:
            self._connection.execute("PRAGMA foreign_keys = ON")

    def _add_column_if_missing(self, table: str, column: str) -> None:
        columns = {row["name"] for row in self._connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")

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

    def set_schedule(self, campaign_id: int, fixed_clock: str | None, valid_until: str | None) -> None:
        """Horário fixo (None = rotativa) e última data de validade (None = sem prazo)."""
        try:
            clock = parse_campaign_clock(fixed_clock or "")
            until = parse_valid_until(valid_until or "")
        except ValueError as exc:
            raise CampaignError(str(exc)) from exc
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE campaigns SET fixed_clock = ?, valid_until = ? WHERE id = ?",
                (clock, until, campaign_id),
            )

    def ready_rotating(self, day: str) -> list[Campaign]:
        return [item for item in self.campaigns() if item.ready_on(day) and is_rotating(item.fixed_clock)]

    def ready_fixed(self, day: str) -> list[Campaign]:
        return [item for item in self.campaigns() if item.ready_on(day) and not is_rotating(item.fixed_clock)]

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

    def run_for_clock(self, day: str, campaign_id: int, clock: str) -> CampaignRun:
        """Convite de uma campanha fixa no dia. Um por campanha, então duas no mesmo horário não colidem."""
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO campaign_runs (day, kind, campaign_id, clock)
                VALUES (?, 'clock', ?, ?)
                """,
                (day, campaign_id, clock),
            )
            row = self._connection.execute(
                _RUN_SELECT + " WHERE day = ? AND kind = 'clock' AND campaign_id = ?",
                (day, campaign_id),
            ).fetchone()
        return _run(row)

    def peek_run(self, day: str, kind: str) -> CampaignRun | None:
        """Como run_for, mas só lê. None quer dizer que o convite ainda não começou (pendente)."""
        if kind not in INVITE_KINDS:
            raise CampaignError("Tipo de convite desconhecido.")
        with self._lock:
            row = self._connection.execute(_RUN_SELECT + " WHERE day = ? AND kind = ?", (day, kind)).fetchone()
        return _run(row) if row else None

    def peek_clock_run(self, day: str, campaign_id: int) -> CampaignRun | None:
        """Como run_for_clock, mas só lê: o painel não pode criar convites ao desenhar a tela."""
        with self._lock:
            row = self._connection.execute(
                _RUN_SELECT + " WHERE day = ? AND kind = 'clock' AND campaign_id = ?",
                (day, campaign_id),
            ).fetchone()
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

    def last_used_rotating(self) -> RotationEntry | None:
        """Última campanha rotativa usada, no convite final ou num post de campanha da fila.

        As duas origens dividem um só cursor, então o rodízio segue em ordem entre elas.
        """
        query = _LAST_ROTATING_RUNS
        if self._board_campaign_columns_exist():
            query = _LAST_ROTATING_UNION
        with self._lock:
            row = self._connection.execute(query).fetchone()
        if row is None:
            return None
        return RotationEntry(int(row["campaign_id"]), int(row["position"]))

    def _board_campaign_columns_exist(self) -> bool:
        """O board compartilha este arquivo, mas pode não ter criado a tabela ou migrado as colunas ainda."""
        with self._lock:
            columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(scheduled_posts)")}
        return {"post_kind", "campaign_id", "campaign_locked_at"} <= columns

    def last_content(self, campaign_id: int) -> tuple[int | None, int | None]:
        """Última foto e texto da campanha, no convite final ou num post dela na fila."""
        query = f"{_LAST_CONTENT_RUNS} ORDER BY locked_at DESC, row_id DESC LIMIT 1"
        parameters: tuple[int, ...] = (campaign_id,)
        if self._board_campaign_columns_exist():
            query = _LAST_CONTENT_UNION
            parameters = (campaign_id, campaign_id)
        with self._lock:
            row = self._connection.execute(query, parameters).fetchone()
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
        fixed_clock=row["fixed_clock"],
        valid_until=row["valid_until"],
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
        clock=row["clock"],
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
