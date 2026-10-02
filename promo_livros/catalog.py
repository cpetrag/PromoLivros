"""Catálogo do CSV e a fila montada na mão. Não escolhe livro sozinho."""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.fila import OpcoesFila, item_de_livro, montar_fila
from promo_livros.ml_links import clean_product_url, is_ml_url, thumbnail_url
from promo_livros.post_card import download_image, render_card
from promo_livros.post_copy import render_caption

_ASIN = re.compile(r"^[A-Z0-9]{10}$")
_ML_ID = re.compile(r"^MLB\d{6,14}$")
_REQUIRED = ("asin", "titulo", "menor_preco_365")
_FOLDER_NAME = "CSV Atualizado"
_ML_FILE = "mercadolivre-livros.csv"


@dataclass(frozen=True)
class CatalogBook:
    asin: str
    position: int
    title: str
    author: str
    category: str
    price_cents: int | None
    list_cents: int | None
    low_365: bool
    url: str
    picked: bool
    store: str = "amazon"
    image_url: str = ""
    kids: bool = False
    not_book: bool = False
    pick_state: str = ""
    pick_day: str = ""


class CatalogError(ValueError):
    pass


class CatalogStore:
    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_books (
                asin TEXT PRIMARY KEY,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                category TEXT NOT NULL,
                price_cents INTEGER,
                list_cents INTEGER,
                low_365 INTEGER NOT NULL,
                url TEXT NOT NULL,
                picked INTEGER NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_books (
                asin TEXT PRIMARY KEY,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                category TEXT NOT NULL,
                price_cents INTEGER,
                list_cents INTEGER,
                low_365 INTEGER NOT NULL,
                url TEXT NOT NULL,
                picked INTEGER NOT NULL
            )
            """
        )
        columns = {str(row["name"]) for row in self._connection.execute("PRAGMA table_info(ml_books)")}
        if "image_url" not in columns:
            self._connection.execute("ALTER TABLE ml_books ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
        self._ensure_kids("catalog_books")
        self._ensure_kids("ml_books")
        self._ensure_pick_seq("catalog_books")
        self._ensure_pick_seq("ml_books")
        self._ensure_flags("catalog_books")
        self._ensure_flags("ml_books")
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def _ensure_kids(self, table: str) -> None:
        columns = {str(row["name"]) for row in self._connection.execute(f"PRAGMA table_info({table})")}
        if "kids" not in columns:
            self._connection.execute(f"ALTER TABLE {table} ADD COLUMN kids INTEGER NOT NULL DEFAULT 0")

    def _ensure_flags(self, table: str) -> None:
        columns = {str(row["name"]) for row in self._connection.execute(f"PRAGMA table_info({table})")}
        if "not_book" not in columns:
            self._connection.execute(f"ALTER TABLE {table} ADD COLUMN not_book INTEGER NOT NULL DEFAULT 0")
        if "pick_state" not in columns:
            self._connection.execute(f"ALTER TABLE {table} ADD COLUMN pick_state TEXT NOT NULL DEFAULT ''")
        if "pick_day" not in columns:
            self._connection.execute(f"ALTER TABLE {table} ADD COLUMN pick_day TEXT NOT NULL DEFAULT ''")

    def _ensure_pick_seq(self, table: str) -> None:
        """A ordem dos cliques decide o par de cada post. Marcação antiga entra pela posição do CSV."""
        columns = {str(row["name"]) for row in self._connection.execute(f"PRAGMA table_info({table})")}
        if "pick_seq" in columns:
            return
        self._connection.execute(f"ALTER TABLE {table} ADD COLUMN pick_seq INTEGER NOT NULL DEFAULT 0")
        self._connection.execute(f"UPDATE {table} SET pick_seq = position WHERE picked = 1")

    def source_name(self) -> str:
        return self._meta("source") or ""

    def ml_source_name(self) -> str:
        return self._meta("ml_source") or ""

    def replace(self, rows: list[dict[str, str]], source: str) -> int:
        books = parse_rows(rows)
        if not books:
            raise CatalogError("O CSV não tem livro com ASIN e título.")
        # CSV novo substitui a lista. A marcação anterior não volta.
        kept: set[str] = set()
        with self._connection:
            self._connection.execute("DELETE FROM catalog_books")
            self._connection.executemany(
                """
                INSERT INTO catalog_books (
                    asin, position, title, author, category,
                    price_cents, list_cents, low_365, url, picked, kids, not_book
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(*_row_values(book, kept), int(book.kids), int(book.not_book)) for book in books],
            )
            self._remember("source", source)
        return len(books)

    def replace_ml(self, rows: list[dict[str, str]], source: str) -> int:
        books = parse_rows(rows, kind="ml")
        if not books:
            raise CatalogError("O CSV não tem livro do Mercado Livre com título.")
        kept: set[str] = set()
        with self._connection:
            self._connection.execute("DELETE FROM ml_books")
            self._connection.executemany(
                """
                INSERT INTO ml_books (
                    asin, position, title, author, category,
                    price_cents, list_cents, low_365, url, picked, kids, not_book, image_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(*_row_values(book, kept), int(book.kids), int(book.not_book), book.image_url) for book in books],
            )
            self._remember("ml_source", source)
        return len(books)

    def books(self) -> list[CatalogBook]:
        rows = self._connection.execute(
            """
            SELECT asin, position, title, author, category, price_cents, list_cents, low_365, url, picked, kids,
                   not_book, pick_state, pick_day
            FROM catalog_books
            ORDER BY position, asin
            """
        ).fetchall()
        return [_book(row) for row in rows]

    def ml_books(self) -> list[CatalogBook]:
        rows = self._connection.execute(
            """
            SELECT asin, position, title, author, category, price_cents, list_cents, low_365, url, picked, kids,
                   not_book, pick_state, pick_day, image_url
            FROM ml_books
            ORDER BY position, asin
            """
        ).fetchall()
        return [_book(row, store="ml") for row in rows]

    def ml_image(self, item_id: str) -> str:
        row = self._connection.execute(
            "SELECT image_url FROM ml_books WHERE asin = ?",
            (item_id.strip().upper(),),
        ).fetchone()
        return str(row["image_url"] or "") if row is not None else ""

    def find_book(self, key: str) -> CatalogBook | None:
        """Acha o livro pelo ASIN ou pelo id MLB. O CSV do dia já traz título, preço e capa."""
        item = (key or "").strip().upper()
        if not item:
            return None
        mercado = item.startswith("MLB")
        table = "ml_books" if mercado else "catalog_books"
        extra = ", image_url" if mercado else ""
        row = self._connection.execute(
            f"""
            SELECT asin, position, title, author, category, price_cents, list_cents, low_365, url,
                   picked, kids, not_book, pick_state, pick_day{extra}
            FROM {table}
            WHERE asin = ?
            """,
            (item,),
        ).fetchone()
        return _book(row, store="ml" if mercado else "amazon") if row is not None else None

    def picked(self) -> list[CatalogBook]:
        return self._picked_in("catalog_books", store="amazon")

    def ml_picked(self) -> list[CatalogBook]:
        return self._picked_in("ml_books", store="ml")

    def queue_for(self, day: str) -> tuple[list[CatalogBook], list[CatalogBook]]:
        """Reserva do dia na frente, depois o que está marcado ou já na fila."""
        return (
            self._queue_in("catalog_books", store="amazon", day=day),
            self._queue_in("ml_books", store="ml", day=day),
        )

    def _queue_in(self, table: str, *, store: str, day: str) -> list[CatalogBook]:
        extra = ", image_url" if table == "ml_books" else ""
        rows = self._connection.execute(
            f"""
            SELECT asin, position, title, author, category, price_cents, list_cents, low_365, url,
                   picked, kids, not_book, pick_state, pick_day{extra}
            FROM {table}
            WHERE pick_state = 'reserva' AND pick_day = ?
            ORDER BY pick_seq, position, asin
            """,
            (day,),
        ).fetchall()
        reservas = [_book(row, store=store) for row in rows]
        return [*reservas, *self._picked_in(table, store=store)]

    def _picked_in(self, table: str, *, store: str) -> list[CatalogBook]:
        """Na ordem em que foram marcados. Reserva e enviado não entram nesta lista."""
        extra = ", image_url" if table == "ml_books" else ""
        rows = self._connection.execute(
            f"""
            SELECT asin, position, title, author, category, price_cents, list_cents, low_365, url,
                   picked, kids, not_book, pick_state, pick_day{extra}
            FROM {table}
            WHERE picked = 1 AND pick_state NOT IN ('reserva', 'enviado')
            ORDER BY pick_seq, position, asin
            """
        ).fetchall()
        return [_book(row, store=store) for row in rows]

    def move_pick(self, asin: str, store: str, direction: int) -> bool:
        """Troca de lugar com o marcado vizinho da mesma loja. Isso muda com quem ele forma par."""
        if direction not in (-1, 1):
            return False
        table = "ml_books" if store == "ml" else "catalog_books"
        order = [book.asin for book in self._picked_in(table, store=store)]
        key = asin.strip().upper()
        if key not in order:
            return False
        place = order.index(key)
        target = place + direction
        if not 0 <= target < len(order):
            return False
        order[place], order[target] = order[target], order[place]
        with self._connection:
            self._connection.executemany(
                f"UPDATE {table} SET pick_seq = ? WHERE asin = ?",
                [(seq, item) for seq, item in enumerate(order, start=1)],
            )
        return True

    def picked_total(self) -> int:
        amazon = self._connection.execute(
            "SELECT COUNT(*) AS total FROM catalog_books WHERE picked = 1"
        ).fetchone()
        mercado = self._connection.execute(
            "SELECT COUNT(*) AS total FROM ml_books WHERE picked = 1"
        ).fetchone()
        return int(amazon["total"]) + int(mercado["total"])

    def set_picked(self, asin: str, picked: bool, day: str = "") -> int:
        if _ASIN.fullmatch(asin.upper()) is None:
            raise CatalogError("ASIN inválido.")
        self._write_pick("catalog_books", asin.upper(), picked, day)
        return self.picked_total()

    def set_ml_picked(self, item_id: str, picked: bool, day: str = "") -> int:
        key = item_id.strip().upper()
        if _ML_ID.fullmatch(key) is None:
            raise CatalogError("Anúncio inválido.")
        self._write_pick("ml_books", key, picked, day)
        return self.picked_total()

    def _write_pick(self, table: str, key: str, picked: bool, day: str = "") -> None:
        with self._connection:
            current = self._connection.execute(
                f"SELECT pick_state, pick_day FROM {table} WHERE asin = ?",
                (key,),
            ).fetchone()
            if current is None:
                raise CatalogError("Esse livro não está no catálogo.")
            if picked and current["pick_state"] == "enviado" and day and current["pick_day"] == day:
                raise CatalogError("Este livro saiu hoje. Ele volta a ficar disponível amanhã.")
            row = self._connection.execute(
                f"SELECT MAX(pick_seq) AS last FROM {table} WHERE picked = 1"
            ).fetchone()
            seq = int(row["last"] or 0) + 1 if picked else 0
            state = "marcado" if picked else ""
            self._connection.execute(
                f"""
                UPDATE {table}
                SET picked = ?, pick_seq = ?, pick_state = ?, pick_day = ?
                WHERE asin = ?
                """,
                (int(picked), seq, state, day if picked else "", key),
            )

    def annotate_kids(self, rows: list[dict[str, str]], kind: str = "amazon") -> int:
        """Marca infantil e o que não é livro, sem mexer na seleção."""
        books = parse_rows(rows, kind="ml" if kind == "ml" else "amazon")
        table = "ml_books" if kind == "ml" else "catalog_books"
        with self._connection:
            self._connection.executemany(
                f"UPDATE {table} SET kids = ?, not_book = ? WHERE asin = ?",
                [(int(book.kids), int(book.not_book), book.asin) for book in books],
            )
        return sum(1 for book in books if book.kids)

    def migrate_pick_states(self, sent_ids: set[str], day: str) -> int:
        """Marcações antigas ganham estado. O que já saiu hoje deixa de contar como marcado."""
        if self._meta("pick_state_v1") == "1":
            return 0
        changed = 0
        with self._connection:
            for table in ("catalog_books", "ml_books"):
                rows = self._connection.execute(
                    f"SELECT asin FROM {table} WHERE picked = 1 AND pick_state = ''"
                ).fetchall()
                for row in rows:
                    asin = str(row["asin"])
                    if asin in sent_ids:
                        self._connection.execute(
                            f"""
                            UPDATE {table}
                            SET picked = 0, pick_seq = 0, pick_state = 'enviado', pick_day = ?
                            WHERE asin = ?
                            """,
                            (day, asin),
                        )
                    else:
                        self._connection.execute(
                            f"UPDATE {table} SET pick_state = 'marcado', pick_day = ? WHERE asin = ?",
                            (day, asin),
                        )
                    changed += 1
            self._remember("pick_state_v1", "1")
        return changed

    def mark_enviado(self, product_id: str, day: str) -> None:
        key = (product_id or "").strip().upper()
        if not key:
            return
        with self._connection:
            for table in ("catalog_books", "ml_books"):
                self._connection.execute(
                    f"""
                    UPDATE {table}
                    SET picked = 0, pick_seq = 0, pick_state = 'enviado', pick_day = ?
                    WHERE asin = ?
                    """,
                    (day, key),
                )

    def aplicar_estados(
        self,
        na_fila: list[tuple[str, str]],
        reserva: list[tuple[str, str]],
        bloqueados: list[tuple[str, str]],
        today: str,
        tomorrow: str,
    ) -> None:
        with self._connection:
            for store, asin in na_fila:
                self._set_state(store, asin, "na_fila", today, picked=True)
            for store, asin in reserva:
                self._set_state(store, asin, "reserva", tomorrow, picked=True)
            for store, asin in bloqueados:
                self._set_state(store, asin, "enviado", today, picked=False)

    def _set_state(self, store: str, asin: str, state: str, day: str, *, picked: bool) -> None:
        table = "ml_books" if store == "ml" else "catalog_books"
        self._connection.execute(
            f"""
            UPDATE {table}
            SET picked = ?, pick_state = ?, pick_day = ?
            WHERE asin = ?
            """,
            (int(picked), state, day, asin),
        )

    def dump_picks(self) -> list[dict[str, str | int]]:
        rows = []
        for table, store in (("catalog_books", "amazon"), ("ml_books", "ml")):
            found = self._connection.execute(
                f"SELECT asin, picked, pick_seq, pick_state, pick_day FROM {table} WHERE picked = 1 OR pick_state != ''"
            ).fetchall()
            for row in found:
                rows.append(
                    {
                        "store": store,
                        "asin": str(row["asin"]),
                        "picked": int(row["picked"]),
                        "pick_seq": int(row["pick_seq"]),
                        "pick_state": str(row["pick_state"]),
                        "pick_day": str(row["pick_day"]),
                    }
                )
        return rows

    def restore_picks(self, rows: list[dict]) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE catalog_books SET picked = 0, pick_seq = 0, pick_state = '', pick_day = ''"
            )
            self._connection.execute(
                "UPDATE ml_books SET picked = 0, pick_seq = 0, pick_state = '', pick_day = ''"
            )
            for row in rows:
                table = "ml_books" if row["store"] == "ml" else "catalog_books"
                self._connection.execute(
                    f"""
                    UPDATE {table}
                    SET picked = ?, pick_seq = ?, pick_state = ?, pick_day = ?
                    WHERE asin = ?
                    """,
                    (int(row["picked"]), int(row["pick_seq"]), row["pick_state"], row["pick_day"], row["asin"]),
                )

    def restore_rows(self, rows: list[dict]) -> None:
        """Devolve marcações sem apagar as outras."""
        with self._connection:
            for row in rows:
                table = "ml_books" if row["store"] == "ml" else "catalog_books"
                self._connection.execute(
                    f"""
                    UPDATE {table}
                    SET picked = ?, pick_seq = ?, pick_state = ?, pick_day = ?
                    WHERE asin = ?
                    """,
                    (int(row["picked"]), int(row["pick_seq"]), row["pick_state"], row["pick_day"], row["asin"]),
                )

    def clear_marks(self) -> list[dict[str, str | int]]:
        """Tira marcados, fila e reserva. Enviado fica. Devolve o que saiu, para desfazer."""
        previous = [
            row
            for row in self.dump_picks()
            if row["pick_state"] != "enviado"
        ]
        with self._connection:
            for table in ("catalog_books", "ml_books"):
                self._connection.execute(
                    f"""
                    UPDATE {table}
                    SET picked = 0, pick_seq = 0, pick_state = '', pick_day = ''
                    WHERE pick_state != 'enviado'
                    """
                )
        return previous

    def id_por_titulo(self, title: str) -> str:
        wanted = (title or "").casefold().strip()
        if not wanted:
            return ""
        for book in (*self.books(), *self.ml_books()):
            if book.title.casefold().strip() == wanted:
                return book.asin
        return ""

    def begin_day(self, day: str) -> int:
        """Na virada, as marcações do dia anterior saem. A reserva deste dia fica."""
        if self._meta("picks_day") == day:
            return 0
        with self._connection:
            amazon = self._connection.execute(
                """
                UPDATE catalog_books
                SET picked = 0, pick_seq = 0, pick_state = ''
                WHERE picked = 1 AND NOT (pick_state = 'reserva' AND pick_day = ?)
                """,
                (day,),
            ).rowcount
            mercado = self._connection.execute(
                """
                UPDATE ml_books
                SET picked = 0, pick_seq = 0, pick_state = ''
                WHERE picked = 1 AND NOT (pick_state = 'reserva' AND pick_day = ?)
                """,
                (day,),
            ).rowcount
            self._remember("picks_day", day)
        return int(amazon) + int(mercado)

    def stored_stamp(self, key: str) -> str:
        return self._meta(key) or ""

    def save_stamp(self, key: str, value: str) -> None:
        with self._connection:
            self._remember(key, value)

    def _remember(self, key: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO catalog_meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def _meta(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM catalog_meta WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return str(row["value"])


def parse_csv(text: str) -> list[dict[str, str]]:
    sample = text.lstrip("\ufeff")
    if "asin" not in sample.splitlines()[0].casefold():
        raise CatalogError("O CSV precisa ter a coluna asin.")
    reader = csv.DictReader(io.StringIO(sample), delimiter=";")
    header = {name.strip().casefold() for name in (reader.fieldnames or [])}
    missing = [name for name in _REQUIRED if name not in header]
    if missing:
        raise CatalogError("Faltam colunas no CSV: " + ", ".join(missing))
    rows = []
    for raw in reader:
        rows.append({(key or "").strip().casefold(): (value or "").strip() for key, value in raw.items()})
    return rows


def parse_rows(rows: list[dict[str, str]], *, kind: str = "amazon") -> list[CatalogBook]:
    books = []
    seen: set[str] = set()
    mercado = kind == "ml"
    pattern = _ML_ID if mercado else _ASIN
    for index, row in enumerate(rows, start=1):
        asin = (row.get("asin") or "").strip().upper()
        title = (row.get("titulo") or "").strip()
        if pattern.fullmatch(asin) is None or not title or asin in seen:
            continue
        seen.add(asin)
        position = _int(row.get("posicao")) or index
        raw_url = (row.get("link") or "").strip()
        if mercado:
            url = clean_product_url(raw_url) or f"https://produto.mercadolivre.com.br/MLB-{asin[3:]}"
        else:
            url = raw_url or f"https://www.amazon.com.br/dp/{asin}"
        books.append(
            CatalogBook(
                asin=asin,
                position=position,
                title=title,
                author=(row.get("autor") or "").strip(),
                category=_category(row),
                price_cents=_cents(row.get("preco")),
                list_cents=_cents(row.get("preco_de")),
                low_365=(row.get("menor_preco_365") or "").casefold() == "sim",
                url=url,
                picked=False,
                store="ml" if mercado else "amazon",
                image_url=ml_picture(row.get("imagem")) if mercado else "",
                kids=_is_kids(row),
                not_book=_is_not_book(row),
            )
        )
    books.sort(key=lambda book: (book.position, book.asin))
    return books


_ML_PICTURE = re.compile(r"https://http2\.mlstatic\.com/D_[A-Za-z0-9_\-]+\.(?:jpg|jpeg|webp|png)")


def ml_picture(value: str | None) -> str:
    """Só aceita foto do CDN do Mercado Livre. Qualquer outra coisa vira vazio."""
    url = (value or "").strip().replace("http://", "https://", 1).split("?")[0]
    return url if _ML_PICTURE.fullmatch(url) else ""


def catalog_kind(rows: list[dict[str, str]]) -> str:
    mercado = 0
    amazon = 0
    for row in rows:
        item = (row.get("asin") or "").strip().upper()
        if _ML_ID.fullmatch(item):
            mercado += 1
        elif _ASIN.fullmatch(item):
            amazon += 1
    if mercado > amazon:
        return "ml"
    return "amazon"


_FINISHED_KEYS = ("finished_local", "finished_utc", "finished_at", "captured_at")


def capture_clock(path: Path, tz_name: str = "America/Sao_Paulo") -> str:
    """Data e hora em que o CSV foi capturado, no fuso da agenda."""
    moment = _capture_moment(path)
    if moment is None:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(tz_name))
    local = moment.astimezone(ZoneInfo(tz_name))
    return f"{local:%d/%m/%Y} às {local:%H:%M}"


def _capture_moment(path: Path) -> datetime | None:
    for candidate in _meta_candidates(path):
        moment = _moment_from_meta(candidate, path.name)
        if moment is not None:
            return moment
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, tz=ZoneInfo("UTC"))


def _meta_candidates(path: Path) -> list[Path]:
    folder = path.parent
    names = [
        path.with_name(f"{path.stem}-meta.json"),
        folder / "mercadolivre-livros-meta.json",
        Path.home() / "ml-crawler" / "mercadolivre-livros-meta.json",
    ]
    found: list[Path] = []
    for item in [*names, *sorted(folder.glob("*-meta.json"))]:
        if item.is_file() and item not in found:
            found.append(item)
    return found


def _moment_from_meta(meta: Path, filename: str) -> datetime | None:
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not _names_file(payload, filename):
        return None
    for key in _FINISHED_KEYS:
        moment = _parse_moment(payload.get(key), utc=key.endswith("_utc"))
        if moment is not None:
            return moment
    return None


def _names_file(value: object, filename: str) -> bool:
    wanted = filename.casefold()
    if isinstance(value, str):
        return Path(value.replace("\\", "/")).name.casefold() == wanted
    if isinstance(value, dict):
        return any(_names_file(item, filename) for item in value.values())
    if isinstance(value, list):
        return any(_names_file(item, filename) for item in value)
    return False


def _parse_moment(value: object, *, utc: bool) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC" if utc else "America/Sao_Paulo"))
    return moment


def file_stamp(path: Path) -> str:
    """Identifica o CSV que está na pasta. Muda quando chega um arquivo novo."""
    moment = _capture_moment(path)
    try:
        modified = path.stat().st_mtime_ns
    except OSError:
        return ""
    when = moment.isoformat() if moment is not None else ""
    return f"{path.name}|{when}|{modified}"


def latest_csv(folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    files = [path for path in folder.glob("amazon_livros_*.csv") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.name)


def mercado_livre_csv(folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    preferred = folder / _ML_FILE
    if preferred.is_file():
        return preferred
    files = [path for path in folder.glob("mercadolivre_livros_*.csv") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.name)


def load_csv_file(path: Path) -> str:
    resolved = path.resolve()
    if resolved.parent.name != _FOLDER_NAME or resolved.suffix.casefold() != ".csv":
        raise CatalogError("Só leio um CSV da pasta CSV Atualizado.")
    if not resolved.is_file():
        raise CatalogError("Não achei o CSV na pasta.")
    return resolved.read_text(encoding="utf-8-sig")


def cover_url(asin: str) -> str:
    return f"https://m.media-amazon.com/images/P/{asin}.jpg"


def cached_ml_cover(
    cache_dir: Path,
    item_id: str,
    download=download_image,
    *,
    cookie: str = "",
    image_url: str = "",
) -> bytes:
    if _ML_ID.fullmatch(item_id) is None:
        raise CatalogError("Anúncio inválido.")
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{item_id}.jpg"
    if target.is_file() and target.stat().st_size > 0:
        return target.read_bytes()
    thumb = ml_picture(image_url) or thumbnail_url(item_id, cookie=cookie)
    if not thumb:
        raise CatalogError("Sem capa.")
    try:
        image = download(thumb)
    except Exception as exc:
        raise CatalogError("Sem capa.") from exc
    out = BytesIO()
    image.save(out, format="JPEG", quality=85)
    payload = out.getvalue()
    target.write_bytes(payload)
    image.close()
    return payload


def cached_cover(cache_dir: Path, asin: str, download=download_image) -> bytes:
    if _ASIN.fullmatch(asin) is None:
        raise CatalogError("ASIN inválido.")
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{asin}.jpg"
    if target.is_file() and target.stat().st_size > 0:
        return target.read_bytes()
    image = _fetch_cover(asin, download)
    out = BytesIO()
    image.save(out, format="JPEG", quality=85)
    payload = out.getvalue()
    target.write_bytes(payload)
    image.close()
    return payload


def publish_selection(
    catalog: CatalogStore,
    store: BoardStore,
    day: str,
    now_clock: str,
    cards_dir: Path,
    resolve_urls=None,
    download=download_image,
    resolve_ml=None,
    thumbnail=thumbnail_url,
    describe=None,
    ordem: str = "mine",
    enviados: dict[str, tuple[str, ...]] | None = None,
    obras_enviadas: tuple[tuple[str, str], ...] = (),
    slots_fixos: list[dict] | None = None,
    sobras_fixas: list[tuple[str, str]] | None = None,
    bloqueados_fixos: list[tuple[str, str]] | None = None,
    livros_extra: list | None = None,
) -> str:
    from datetime import date, timedelta

    schedule = store.send_schedule()
    if slots_fixos is not None:
        return _publish_fixed(
            catalog,
            store,
            day,
            slots_fixos,
            sobras_fixas or [],
            bloqueados_fixos or [],
            cards_dir,
            resolve_urls,
            download,
            resolve_ml,
            thumbnail,
            describe,
            livros_extra,
        )
    amazon_books, ml_books = catalog.queue_for(day)
    fila = montar_fila(
        [item_de_livro(book) for book in amazon_books],
        [item_de_livro(book) for book in ml_books],
        OpcoesFila(
            agora=now_clock,
            inicio=schedule.start,
            fim=schedule.end,
            intervalo=schedule.post_interval_minutes,
            enviados=enviados or {},
            ordem=ordem if ordem in {"mine", "desc", "mix"} else "mine",
            obras_enviadas=obras_enviadas,
        ),
    )
    by_id = {book.asin: book for book in (*amazon_books, *ml_books)}
    pairs = []
    for slot in fila.slots:
        book = by_id.get(slot.amazon.id) if slot.amazon else None
        alt = by_id.get(slot.ml.id) if slot.ml else None
        if book is None and alt is not None:
            book, alt = alt, None
        if book is not None:
            pairs.append((book, alt))
    if not pairs:
        raise CatalogError("Marque pelo menos um livro com preço.")
    clocks = [slot.clock for slot in fila.slots]
    if not clocks:
        raise CatalogError("O horário de envio de hoje já acabou. A marcação ficou salva.")
    notice = _gravar_posts(
        store,
        day,
        pairs,
        clocks,
        cards_dir,
        resolve_urls,
        download,
        resolve_ml,
        thumbnail,
        describe,
    )
    tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    catalog.aplicar_estados(
        [(item.store, item.id) for slot in fila.slots for item in (slot.amazon, slot.ml) if item],
        [(item.store, item.id) for item in fila.sobras],
        [(item.item.store, item.item.id) for item in fila.bloqueados],
        day,
        tomorrow,
    )
    left = len(fila.sobras)
    extra = f" {left} marcados foram para a reserva de amanhã." if left else ""
    return notice.replace(".", f".{extra}", 1)


def _publish_fixed(
    catalog,
    store,
    day,
    slots_fixos,
    sobras_fixas,
    bloqueados_fixos,
    cards_dir,
    resolve_urls,
    download,
    resolve_ml,
    thumbnail,
    describe,
    livros_extra=None,
) -> str:
    from datetime import date, timedelta

    by_id = {book.asin: book for book in (*catalog.books(), *catalog.ml_books(), *(livros_extra or []))}
    pairs = []
    clocks = []
    na_fila: list[tuple[str, str]] = []
    for slot in slots_fixos:
        amazon = by_id.get(slot.get("amazon") or "")
        mercado = by_id.get(slot.get("ml") or "")
        book, alt = amazon, mercado
        if book is None and alt is not None:
            book, alt = alt, None
        if book is None:
            raise CatalogError("A prévia cita um livro que não está mais no catálogo. Peça outra prévia.")
        pairs.append((book, alt))
        clocks.append(slot["clock"])
        if amazon is not None:
            na_fila.append(("amazon", amazon.asin))
        if mercado is not None:
            na_fila.append(("ml", mercado.asin))
    if not pairs:
        raise CatalogError("Marque pelo menos um livro com preço.")
    notice = _gravar_posts(
        store, day, pairs, clocks, cards_dir, resolve_urls, download, resolve_ml, thumbnail, describe
    )
    tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    catalog.aplicar_estados(na_fila, sobras_fixas, bloqueados_fixos, day, tomorrow)
    left = len(sobras_fixas)
    extra = f" {left} marcados foram para a reserva de amanhã." if left else ""
    return notice.replace(".", f".{extra}", 1)


def _gravar_posts(
    store,
    day,
    chosen,
    clocks,
    cards_dir,
    resolve_urls,
    download,
    resolve_ml,
    thumbnail,
    describe,
) -> str:
    prepared = [(book, alt, _covers_for(book, alt, download, thumbnail)) for book, alt in chosen]
    primary_urls = _resolve_mixed([_listing_url(book) for book, _alt, _cover in prepared], resolve_urls, resolve_ml)
    alt_urls = _resolve_mixed(
        [_listing_url(alt) if alt is not None else "" for _book, alt, _cover in prepared],
        resolve_urls,
        resolve_ml,
    )
    raw_ml = [
        before
        for before, after in zip(
            [_listing_url(book) for book, _alt, _cover in prepared]
            + [_listing_url(alt) if alt is not None else "" for _book, alt, _cover in prepared],
            primary_urls + alt_urls,
        )
        if before and is_ml_url(before) and after == before
    ]
    if hasattr(store, "replace_scheduled"):
        store.replace_scheduled(day)
    else:
        store.cancel_day(day)
    cards_dir.mkdir(parents=True, exist_ok=True)
    for index, ((book, alt, covers), clock) in enumerate(zip(prepared, clocks)):
        rows = _store_rows(book, alt, primary_urls[index], alt_urls[index])
        payloads = [_payload(item, url, _safe_describe(describe, item)) for item, url in rows]
        post_id = store.add_post(
            day=day,
            clock=clock,
            caption=render_caption(payloads, sign_index=index),
            image_path="",
            books=[_board_book(payload) for payload in payloads],
        )
        render_card(covers, cards_dir / f"{post_id}.jpg")
        for image in covers:
            image.close()
        store.set_image(post_id, f"data/cards/{post_id}.jpg")
    affiliate = ""
    if resolve_ml is not None and raw_ml:
        affiliate = " Os links do Mercado Livre continuam sem afiliado. Cole os cookies em Configurações."
    return f"{len(chosen)} livros entraram na fila de {day}. Nada foi enviado.{affiliate}"


def _fetch_cover(asin: str, download) -> Image.Image:
    try:
        return download(cover_url(asin))
    except Exception:
        return Image.new("RGB", (280, 400), (245, 241, 232))


def _covers_for(book: CatalogBook, alt: CatalogBook | None, download, thumbnail) -> list[Image.Image]:
    items = [book]
    if alt is not None:
        items.append(alt)
    items.sort(key=lambda item: item.store == "ml")
    return [_one_cover(item, download, thumbnail) for item in items]


def _one_cover(book: CatalogBook, download, thumbnail) -> Image.Image:
    if book.store != "ml":
        return _fetch_cover(book.asin, download)
    thumb = ml_picture(book.image_url) or thumbnail(book.asin)
    if thumb:
        try:
            return download(thumb)
        except Exception:
            pass
    return Image.new("RGB", (280, 400), (245, 241, 232))


def _resolve_mixed(urls: list[str], resolve_amazon, resolve_ml) -> list[str]:
    result = list(urls)
    amazon = [(index, url) for index, url in enumerate(urls) if url and not is_ml_url(url)]
    mercado = [(index, url) for index, url in enumerate(urls) if url and is_ml_url(url)]
    if amazon and resolve_amazon is not None:
        got = resolve_amazon([url for _index, url in amazon])
        if isinstance(got, list) and len(got) == len(amazon):
            for (index, _url), resolved in zip(amazon, got):
                result[index] = resolved
    if mercado and resolve_ml is not None:
        got = resolve_ml([url for _index, url in mercado])
        if isinstance(got, list) and len(got) == len(mercado):
            for (index, _url), resolved in zip(mercado, got):
                result[index] = resolved
    return result


def _book(row: sqlite3.Row, *, store: str = "amazon") -> CatalogBook:
    return CatalogBook(
        asin=str(row["asin"]),
        position=int(row["position"]),
        title=str(row["title"]),
        author=str(row["author"]),
        category=str(row["category"]),
        price_cents=None if row["price_cents"] is None else int(row["price_cents"]),
        list_cents=None if row["list_cents"] is None else int(row["list_cents"]),
        low_365=bool(row["low_365"]),
        url=str(row["url"]),
        picked=bool(row["picked"]),
        store=store,
        image_url=str(row["image_url"] or "") if "image_url" in row.keys() else "",
        kids=bool(row["kids"]) if "kids" in row.keys() else False,
        not_book=bool(row["not_book"]) if "not_book" in row.keys() else False,
        pick_state=str(row["pick_state"]) if "pick_state" in row.keys() else "",
        pick_day=str(row["pick_day"]) if "pick_day" in row.keys() else "",
    )


def _row_values(book: CatalogBook, kept: set[str]) -> tuple:
    return (
        book.asin,
        book.position,
        book.title,
        book.author,
        book.category,
        book.price_cents,
        book.list_cents,
        int(book.low_365),
        book.url,
        int(book.asin in kept),
    )


_KIDS_WORDS = (
    "colorir",
    "pintura",
    "pop up",
    "popup",
    "primeiros",
    "caligrafia",
    "livrinhos",
    "infantil",
    "infantojuvenil",
    "bebe",
    "atividades",
    "adesivos",
    "piadas e charadas",
)
_HARD_KIDS = ("infantil", "infantojuvenil", "bebe", "livrinhos")
_STATIONERY = ("figurinha", "album", "envelopes", "caneta", "marcador")
_OUTSIDE = ("papelaria", "escritorio", "material escolar", "copa do mundo")


def _blob(row: dict[str, str]) -> str:
    raw = " ".join(
        row.get(name) or ""
        for name in ("titulo", "categoria", "categoria_caminho", "categoria_mais_vendido", "badges")
    )
    normalized = unicodedata.normalize("NFD", raw)
    stripped = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", stripped.casefold()).strip()


def _is_kids(row: dict[str, str]) -> bool:
    blob = _blob(row)
    if not blob:
        return False
    adult_coloring = "adulto" in blob and any(word in blob for word in ("colorir", "pintura"))
    if adult_coloring and not any(word in blob for word in _HARD_KIDS):
        return False
    return any(word in blob for word in _KIDS_WORDS)


def _is_not_book(row: dict[str, str]) -> bool:
    title = _blob({"titulo": row.get("titulo") or ""})
    category = _blob(
        {
            "titulo": "",
            "categoria": row.get("categoria") or "",
            "categoria_caminho": row.get("categoria_caminho") or "",
        }
    )
    if any(word in title for word in _STATIONERY):
        return True
    if "adesivo" in title and ("kit" in title or "papelaria" in category):
        return True
    if any(word in category for word in _OUTSIDE) and "livro" not in category:
        return True
    return False


def _category(row: dict[str, str]) -> str:
    leaf = (row.get("categoria") or "").strip()
    if leaf:
        return leaf
    path = (row.get("categoria_caminho") or "").strip()
    if not path:
        return "Sem categoria"
    return path.split(">")[-1].strip() or "Sem categoria"


def _cents(value: str | None) -> int | None:
    text = (value or "").replace("R$", "").replace("\xa0", "").strip()
    if not text:
        return None
    text = text.replace(".", "").replace(",", ".")
    try:
        return int(round(float(text) * 100))
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    try:
        return int(str(value or "").strip().strip('"'))
    except ValueError:
        return None


def _listing_url(book: CatalogBook) -> str:
    """A API de afiliado aceita o anúncio público. O endereço produto.mercadolivre.com.br ela recusa."""
    return clean_product_url(book.url)


def _store_rows(
    book: CatalogBook,
    alt: CatalogBook | None,
    url: str,
    alt_url: str,
) -> list[tuple[CatalogBook, str]]:
    rows = [(book, url)]
    if alt is not None and alt_url:
        rows.append((alt, alt_url))
    rows.sort(key=lambda item: is_ml_url(item[1]))
    return rows


def _payload(book: CatalogBook, url: str, blurb: str = "") -> dict:
    return {
        "title": book.title,
        "blurb": blurb,
        "price_cents": book.price_cents,
        "list_price_cents": book.list_cents,
        "discount_pct": _discount(book.price_cents, book.list_cents),
        "lowest_label": "Menor preço em 365 dias." if book.low_365 else "",
        "coupon": "",
        "url": url,
        "product_id": book.asin,
    }


def _safe_describe(describe, book: CatalogBook) -> str:
    if describe is None:
        return ""
    try:
        return (describe(book.title, book.author) or "").strip()
    except Exception:
        return ""


def _board_book(payload: dict) -> BoardBook:
    return BoardBook(
        title=str(payload["title"]),
        blurb=str(payload.get("blurb") or ""),
        price_cents=int(payload["price_cents"] or 0),
        list_price_cents=payload["list_price_cents"],
        discount_pct=payload["discount_pct"],
        lowest_label=str(payload["lowest_label"]),
        url=str(payload["url"]),
        coupon="",
        product_id=str(payload.get("product_id") or ""),
    )


def split_store_posts(catalog: CatalogStore, store: BoardStore) -> int:
    """Posts ainda na fila que juntavam as duas lojas passam a ter um bloco para cada uma."""
    listings: dict[str, CatalogBook] = {}
    for book in (*catalog.books(), *catalog.ml_books()):
        cleaned = clean_product_url(book.url)
        listings[cleaned] = book
        tail = cleaned.rstrip("/").rsplit("/", 1)[-1]
        listings.setdefault(tail, book)
    changed = 0
    for post in store.unsent_posts():
        if len(post.books) != 1 or not post.books[0].alt_url:
            continue
        current = post.books[0]
        cleaned = clean_product_url(current.alt_url)
        tail = cleaned.rstrip("/").rsplit("/", 1)[-1]
        peer = listings.get(cleaned) or listings.get(tail)
        if peer is None:
            continue
        primary = BoardBook(
            title=current.title,
            blurb=current.blurb,
            price_cents=current.price_cents,
            list_price_cents=current.list_price_cents,
            discount_pct=current.discount_pct,
            lowest_label=current.lowest_label,
            url=current.url,
            coupon=current.coupon,
        )
        books = sorted(
            [primary, _board_book(_payload(peer, current.alt_url))],
            key=lambda item: is_ml_url(item.url),
        )
        from promo_livros.post_copy import signature_of

        caption = render_caption(
            [
                {
                    "title": item.title,
                    "blurb": item.blurb,
                    "price_cents": item.price_cents,
                    "list_price_cents": item.list_price_cents,
                    "discount_pct": item.discount_pct,
                    "lowest_label": item.lowest_label,
                    "coupon": item.coupon,
                    "url": item.url,
                }
                for item in books
            ],
            signature=signature_of(post.caption),
        )
        if store.update_scheduled(post.day, post.id, clock=post.clock, books=books, caption=caption):
            changed += 1
    return changed


def fill_blurbs(store: BoardStore, describe) -> int:
    """Completa a resenha dos posts que ainda não saíram."""
    changed = 0
    for post in store.unsent_posts():
        if not post.books or all((book.blurb or "").strip() for book in post.books):
            continue
        blurbs = []
        for book in post.books:
            current = (book.blurb or "").strip()
            if current:
                blurbs.append(current)
                continue
            try:
                blurbs.append((describe(book.title, "") or "").strip())
            except Exception:
                blurbs.append("")
        if blurbs == [(book.blurb or "") for book in post.books]:
            continue
        try:
            store.set_book_blurbs(post.id, blurbs)
        except ValueError:
            continue
        changed += 1
    return changed


def _discount(price: int | None, listed: int | None) -> float | None:
    if price is None or listed is None or listed <= price:
        return None
    return round((listed - price) * 100 / listed, 1)
