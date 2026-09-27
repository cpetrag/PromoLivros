# Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Subir uma dashboard local com as páginas Hoje, WhatsApp e Grupos, sem publicar livro nem alterar o disparo.

**Architecture:** Um processo separado, `python -m promo_livros.dashboard`, escuta em `127.0.0.1:8787` com a biblioteca HTTP padrão. A grade do dia e a edição do bloco `groups` são funções puras. O SQLite abre só para leitura. O WAHA continua em `127.0.0.1:4443`. O caminho do HD de 1 TB não entra no código: o processo sobe dentro de `/Volumes/HD 1Tb/Vibecoding/Promo Livros` no Mac.

**Tech Stack:** Python 3.11, unittest, sqlite3, http.server, o `WahaClient` e o `config.yaml` que já existem.

**Git:** esta pasta ainda não tem repositório. Se `git commit` falhar por isso, pare e avise. Não rode `git init`.

---

## File structure

- `promo_livros/day_view.py` — monta a grade a partir de slots, fila e disparos. Não abre rede nem arquivo.
- `promo_livros/storage.py` — ganha leitura do dia e uma abertura somente leitura.
- `promo_livros/groups_file.py` — valida a seleção e reescreve só o bloco `groups`.
- `promo_livros/dashboard_auth.py` — token de sessão na memória.
- `promo_livros/waha.py` — consulta a sessão sem engolir erro e baixa o PNG do QR.
- `promo_livros/dashboard_pages.py` — HTML das três páginas e do login.
- `promo_livros/dashboard.py` — servidor, rotas e `python -m promo_livros.dashboard`.
- `tests/test_day_view.py`, `tests/test_groups_file.py`, `tests/test_dashboard_auth.py`, `tests/test_dashboard_http.py` — testes novos.
- `tests/test_waha.py` — cobre a sonda e o QR.
- `.env.example` e `README.md` — variáveis, comando e o trecho do túnel.

Os testes rodam na pasta do projeto:

```powershell
python -m unittest tests.test_day_view tests.test_groups_file tests.test_dashboard_auth tests.test_waha tests.test_dashboard_http -v
```

---

### Task 1: Grade do dia

**Files:**
- Create: `promo_livros/day_view.py`
- Test: `tests/test_day_view.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from datetime import datetime, timezone

from promo_livros.day_view import build_day_view
from promo_livros.models import Dispatch, NicheConfig, PublishSlot, QueuedPost, WhatsAppGroup


def _book(position: int, status: str = "ready", title: str = "Sapiens") -> QueuedPost:
    return QueuedPost(
        day="2026-09-27",
        niche_key="ficcao",
        position=position,
        asin="B000000001",
        title=title,
        author="Autor",
        niche_label="Ficção",
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_day_view -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'promo_livros.day_view'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass

from promo_livros.formatter import format_brl
from promo_livros.models import Dispatch, NicheConfig, PublishSlot, QueuedPost, WhatsAppGroup

BOOK_LABELS = {
    "ready": "pronto",
    "queued": "na fila",
    "posted": "publicado",
    "skipped": "pulado",
}
DISPATCH_LABELS = {
    "na_fila": "na fila",
    "enviando": "enviando",
    "enviada": "enviada",
    "falhou": "falhou",
    "expirada": "expirada",
}
NOT_QUEUED = "ainda não entrou na fila"


@dataclass(frozen=True)
class GroupLine:
    name: str
    chat_id: str
    status_label: str


@dataclass(frozen=True)
class BookLine:
    clock: str
    niche_label: str
    title: str
    price_label: str
    book_status: str
    caption: str
    groups: tuple[GroupLine, ...]
    reserve: bool


@dataclass(frozen=True)
class DayView:
    day: str
    books: tuple[BookLine, ...]


def build_day_view(
    *,
    day: str,
    slots: tuple[PublishSlot, ...],
    niches: tuple[NicheConfig, ...],
    per_niche: int,
    queue: tuple[QueuedPost, ...],
    dispatches: tuple[Dispatch, ...],
    saved_groups: tuple[WhatsAppGroup, ...],
    captions: dict[tuple[str, int], str],
) -> DayView | None:
    if not queue:
        return None
    labels = {niche.key: niche.label for niche in niches}
    books: list[BookLine] = []
    for slot in slots:
        row = next(
            (item for item in queue if item.niche_key == slot.niche_key and item.position == slot.rank),
            None,
        )
        clock = f"{slot.hour:02d}:{slot.minute:02d}"
        niche_label = labels.get(slot.niche_key, slot.niche_key)
        if row is None:
            books.append(BookLine(clock, niche_label, "", "", "sem livro", "", (), False))
            continue
        books.append(_book_line(clock, niche_label, row, False, dispatches, saved_groups, captions))
    for row in queue:
        if row.position < per_niche:
            continue
        books.append(
            _book_line("", row.niche_label, row, True, dispatches, saved_groups, captions)
        )
    return DayView(day=day, books=tuple(books))


def _book_line(
    clock: str,
    niche_label: str,
    row: QueuedPost,
    reserve: bool,
    dispatches: tuple[Dispatch, ...],
    saved_groups: tuple[WhatsAppGroup, ...],
    captions: dict[tuple[str, int], str],
) -> BookLine:
    groups: list[GroupLine] = []
    for group in saved_groups:
        match = next(
            (
                item
                for item in dispatches
                if item.niche_key == row.niche_key
                and item.position == row.position
                and item.chat_id == group.chat_id
            ),
            None,
        )
        label = NOT_QUEUED if match is None else DISPATCH_LABELS.get(match.status, match.status)
        groups.append(GroupLine(group.name, group.chat_id, label))
    return BookLine(
        clock=clock,
        niche_label=niche_label,
        title=row.title,
        price_label=format_brl(row.price_cents),
        book_status=BOOK_LABELS.get(row.status, row.status),
        caption=captions.get((row.niche_key, row.position), ""),
        groups=tuple(groups),
        reserve=reserve,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_day_view -v`

Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add promo_livros/day_view.py tests/test_day_view.py
git commit -m "Add the read-only view of today's book queue."
```

---

### Task 2: Leitura somente leitura do SQLite

**Files:**
- Modify: `promo_livros/storage.py`
- Modify: `tests/test_day_view.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_day_view.py`:

```python
import sqlite3
import tempfile
from pathlib import Path

from promo_livros.storage import DayReadError, Storage
from promo_livros.day_view import captions_for, load_day_rows


def _deal_row(position: int) -> QueuedPost:
    return _book(position)


class ReadOnlyStoreTests(unittest.TestCase):
    def test_reads_queue_and_dispatch_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "promo.sqlite"
            storage = Storage(path)
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

            queue, dispatches = load_day_rows(path, "2026-09-27")

        self.assertEqual(queue[0].title, "Sapiens")
        self.assertEqual(dispatches[0].status, "na_fila")
        self.assertEqual(captions_for(dispatches, queue, "")[("ficcao", 0)], "texto da noite")

    def test_missing_file_is_an_empty_day(self) -> None:
        queue, dispatches = load_day_rows(Path("nao-existe.sqlite"), "2026-09-27")
        self.assertEqual(queue, [])
        self.assertEqual(dispatches, [])

    def test_locked_database_asks_for_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "promo.sqlite"
            storage = Storage(path)
            storage.close()
            holder = sqlite3.connect(path)
            holder.execute("BEGIN EXCLUSIVE")
            with self.assertRaises(DayReadError) as caught:
                load_day_rows(path, "2026-09-27")
            holder.close()
        self.assertIn("Atualize a página", str(caught.exception))
```

`captions_for` usa a caption do disparo quando existe. Sem disparo, renderiza o livro com `render_deal`. O terceiro argumento é a tag de afiliado, vazia neste teste.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_day_view.ReadOnlyStoreTests -v`

Expected: FAIL with `ImportError` for `DayReadError` or `load_day_rows`.

- [ ] **Step 3: Write minimal implementation**

In `promo_livros/storage.py`, add this exception next to the imports' usage site, before `class Storage`:

```python
class DayReadError(Exception):
    """O SQLite está ocupado. A página pede para atualizar."""
```

Add these methods inside `Storage`, after `queue_for_niche`:

```python
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
        except sqlite3.OperationalError as exc:
            raise DayReadError("Atualize a página. A fila está ocupada.") from exc
        store._connection.row_factory = sqlite3.Row
        return store
```

Add to `promo_livros/day_view.py`:

```python
from pathlib import Path

from promo_livros.curation import _deal_from_row
from promo_livros.formatter import render_deal
from promo_livros.storage import DayReadError, Storage


def load_day_rows(path: Path, day: str) -> tuple[list[QueuedPost], list[Dispatch]]:
    if not path.is_file():
        return [], []
    store = Storage.open_readonly(path)
    try:
        return store.queue_for_day(day), store.dispatches_for_day(day)
    except sqlite3.OperationalError as exc:
        raise DayReadError("Atualize a página. A fila está ocupada.") from exc
    finally:
        store.close()


def captions_for(
    dispatches: list[Dispatch] | tuple[Dispatch, ...],
    queue: list[QueuedPost] | tuple[QueuedPost, ...],
    affiliate_tag: str,
) -> dict[tuple[str, int], str]:
    captions: dict[tuple[str, int], str] = {}
    for item in dispatches:
        if item.caption:
            captions[(item.niche_key, item.position)] = item.caption
    for row in queue:
        key = (row.niche_key, row.position)
        if key not in captions:
            captions[key] = render_deal(_deal_from_row(row), affiliate_tag).caption
    return captions
```

`_deal_from_row` já existe em `promo_livros/curation.py`. Importá-la aqui é o caminho curto; não copie o construtor do `Deal`.

Add `import sqlite3` inside `load_day_rows`'s module imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_day_view -v`

Expected: PASS. Se o teste do lock não disparar `DayReadError` no Windows, troque o `timeout` de `open_readonly` para `0` e rode de novo. O teste tem que falhar a abertura, não esperar.

- [ ] **Step 5: Commit**

```bash
git add promo_livros/storage.py promo_livros/day_view.py tests/test_day_view.py
git commit -m "Read today's queue without writing to SQLite."
```

---

### Task 3: Bloco de grupos no YAML

**Files:**
- Create: `promo_livros/groups_file.py`
- Test: `tests/test_groups_file.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from promo_livros.groups_file import (
    GroupsFileError,
    group_choices,
    replace_groups_block,
    selected_groups,
    validate_groups,
)
from promo_livros.models import WhatsAppGroup

YAML = """# topo
whatsapp:
  # não ligar daqui
  enabled: false
  gap_seconds: 45
  groups:
    - name: "Velho"
      id: "120363430990609445@g.us"
website:
  enabled: false
"""


class GroupsFileTests(unittest.TestCase):
    def test_replaces_only_the_groups_block(self) -> None:
        updated = replace_groups_block(
            YAML,
            [("Black Livros 01", "120363430990609445@g.us")],
        )
        self.assertIn("# não ligar daqui", updated)
        self.assertIn("enabled: false", updated)
        self.assertIn('name: "Black Livros 01"', updated)
        self.assertNotIn("Velho", updated)
        self.assertIn("website:", updated)

    def test_rejects_bad_id_duplicate_and_empty_when_enabled(self) -> None:
        with self.assertRaises(GroupsFileError):
            validate_groups([("A", "nao-e-grupo")], enabled=False)
        with self.assertRaises(GroupsFileError):
            validate_groups(
                [("A", "1@g.us"), ("B", "1@g.us")],
                enabled=False,
            )
        with self.assertRaises(GroupsFileError):
            validate_groups([], enabled=True)
        validate_groups([], enabled=False)

    def test_keeps_saved_group_missing_from_the_session(self) -> None:
        saved = WhatsAppGroup("Black Livros 03", "120363412365496470@g.us")
        live = WhatsAppGroup("Black Livros 01", "120363430990609445@g.us")
        choices = group_choices((live,), (saved, live))
        self.assertEqual(choices[1].chat_id, saved.chat_id)
        self.assertTrue(choices[1].missing)
        self.assertTrue(choices[1].checked)

    def test_posted_id_must_be_one_of_the_choices(self) -> None:
        choices = group_choices(
            (WhatsAppGroup("Black Livros 01", "120363430990609445@g.us"),),
            (),
        )
        picked = selected_groups(["120363430990609445@g.us"], choices)
        self.assertEqual(picked, [("Black Livros 01", "120363430990609445@g.us")])
        with self.assertRaises(GroupsFileError):
            selected_groups(["999@g.us"], choices)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_groups_file -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'promo_livros.groups_file'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from promo_livros.models import WhatsAppGroup

_GROUP_ID_RE = re.compile(r"^[0-9-]+@g\.us$")


class GroupsFileError(Exception):
    """A lista não pode ser gravada."""


@dataclass(frozen=True)
class GroupChoice:
    name: str
    chat_id: str
    checked: bool
    missing: bool


def validate_groups(groups: list[tuple[str, str]], *, enabled: bool) -> None:
    if enabled and not groups:
        raise GroupsFileError("O disparo está ligado e a lista de grupos ficou vazia.")
    seen: set[str] = set()
    for name, chat_id in groups:
        if not name.strip():
            raise GroupsFileError("Grupo sem nome.")
        if _GROUP_ID_RE.fullmatch(chat_id) is None:
            raise GroupsFileError(f"Id de grupo inválido '{chat_id}'.")
        if chat_id in seen:
            raise GroupsFileError(f"Grupo repetido '{chat_id}'.")
        seen.add(chat_id)


def group_choices(
    session: tuple[WhatsAppGroup, ...] | list[WhatsAppGroup],
    saved: tuple[WhatsAppGroup, ...] | list[WhatsAppGroup],
) -> list[GroupChoice]:
    saved_ids = {group.chat_id for group in saved}
    rows: list[GroupChoice] = []
    seen: set[str] = set()
    for group in session:
        seen.add(group.chat_id)
        rows.append(GroupChoice(group.name, group.chat_id, group.chat_id in saved_ids, False))
    for group in saved:
        if group.chat_id in seen:
            continue
        rows.append(GroupChoice(group.name, group.chat_id, True, True))
    return rows


def selected_groups(posted_ids: list[str], choices: list[GroupChoice]) -> list[tuple[str, str]]:
    allowed = {choice.chat_id: choice.name for choice in choices}
    groups: list[tuple[str, str]] = []
    for chat_id in posted_ids:
        name = allowed.get(chat_id)
        if name is None:
            raise GroupsFileError(f"Id de grupo inválido '{chat_id}'.")
        groups.append((name, chat_id))
    return groups


def replace_groups_block(text: str, groups: list[tuple[str, str]]) -> str:
    lines = text.splitlines(keepends=True)
    start, end = _groups_span(lines)
    block = ["  groups:\n"]
    for name, chat_id in groups:
        block.append(f'    - name: "{_yaml_string(name)}"\n')
        block.append(f'      id: "{chat_id}"\n')
    return "".join(lines[:start] + block + lines[end:])


def write_groups(path: Path, groups: list[tuple[str, str]], *, enabled: bool) -> None:
    validate_groups(groups, enabled=enabled)
    updated = replace_groups_block(path.read_text(encoding="utf-8"), groups)
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(updated, encoding="utf-8")
    temporary.replace(path)


def _groups_span(lines: list[str]) -> tuple[int, int]:
    in_whatsapp = False
    start = None
    for index, line in enumerate(lines):
        code = line.split("#", 1)[0].strip()
        if code == "whatsapp:":
            in_whatsapp = True
            continue
        if in_whatsapp and line[:1].strip() and not line.lstrip().startswith("#"):
            break
        if in_whatsapp and code == "groups:":
            start = index
            break
    if start is None:
        raise GroupsFileError("config.yaml não tem whatsapp.groups.")
    end = start + 1
    while end < len(lines):
        body = lines[end].split("#", 1)[0]
        if body.strip() == "":
            break
        if body.startswith("    "):
            end += 1
            continue
        break
    return start, end


def _yaml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
```

The indent check `body.startswith("    ")` keeps list items and drops out at the next section. A blank line ends the block and stays in the file after the replacement.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_groups_file -v`

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add promo_livros/groups_file.py tests/test_groups_file.py
git commit -m "Save WhatsApp groups by editing only the YAML list."
```

---

### Task 4: Login na memória

**Files:**
- Create: `promo_livros/dashboard_auth.py`
- Test: `tests/test_dashboard_auth.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from promo_livros.dashboard_auth import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_wrong_password_returns_no_token(self) -> None:
        store = SessionStore()
        self.assertIsNone(store.login("ana", "errada", "ana", "certa"))
        self.assertFalse(store.valid(None))

    def test_right_password_is_accepted_until_forget(self) -> None:
        store = SessionStore()
        token = store.login("ana", "certa", "ana", "certa")
        self.assertIsNotNone(token)
        assert token is not None
        self.assertTrue(store.valid(token))
        store.forget(token)
        self.assertFalse(store.valid(token))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_dashboard_auth -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'promo_livros.dashboard_auth'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import hmac
import secrets


class SessionStore:
    """Tokens vivem só neste processo. Reiniciar pede login de novo."""

    def __init__(self) -> None:
        self._tokens: set[str] = set()

    def login(
        self,
        username: str,
        password: str,
        expected_username: str,
        expected_password: str,
    ) -> str | None:
        user_ok = hmac.compare_digest(username, expected_username)
        password_ok = hmac.compare_digest(password, expected_password)
        if not (user_ok and password_ok):
            return None
        token = secrets.token_urlsafe(32)
        self._tokens.add(token)
        return token

    def valid(self, token: str | None) -> bool:
        return token is not None and token in self._tokens

    def forget(self, token: str | None) -> None:
        if token is not None:
            self._tokens.discard(token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_dashboard_auth -v`

Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add promo_livros/dashboard_auth.py tests/test_dashboard_auth.py
git commit -m "Keep dashboard login tokens in process memory."
```

---

### Task 5: Estado da sessão e QR

**Files:**
- Modify: `promo_livros/waha.py`
- Modify: `tests/test_waha.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_waha.py`. Extend `_Response` with headers, without changing the constructor calls that already exist: add `headers: dict | None = None` and `self.headers = headers or {}`.

```python
    def test_probe_session_raises_when_waha_refuses(self) -> None:
        http = _Http([_Response(500, {})])
        client = WahaClient("http://127.0.0.1:4443", "chave", "promo-livros", http=http)
        with self.assertRaises(WahaError):
            client.probe_session()

    def test_fetch_qr_png_returns_image_bytes(self) -> None:
        response = _Response(200, {})
        response.content = b"\x89PNG\r\n"
        response.headers = {"content-type": "image/png"}
        http = _Http([response])
        client = WahaClient("http://127.0.0.1:4443", "chave", "promo-livros", http=http)

        self.assertEqual(client.fetch_qr_png(), b"\x89PNG\r\n")
        self.assertIn("/api/promo-livros/auth/qr", http.calls[0][1])

    def test_fetch_qr_png_rejects_json(self) -> None:
        response = _Response(200, {"status": "WORKING"})
        response.headers = {"content-type": "application/json"}
        http = _Http([response])
        client = WahaClient("http://127.0.0.1:4443", "", "promo-livros", http=http)
        with self.assertRaises(WahaError):
            client.fetch_qr_png()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_waha.WahaClientTests.test_probe_session_raises_when_waha_refuses tests.test_waha.WahaClientTests.test_fetch_qr_png_returns_image_bytes -v`

Expected: FAIL with `AttributeError: 'WahaClient' object has no attribute 'probe_session'`

- [ ] **Step 3: Write minimal implementation**

Add to `WahaClient` after `connection_state`:

```python
    def probe_session(self) -> str:
        """Igual a connection_state, mas deixa o erro subir."""
        payload = self._request(
            "GET",
            f"/api/sessions/{self.session}",
            timeout=_STATUS_TIMEOUT_SECONDS,
        )
        status = ""
        if isinstance(payload, dict):
            status = str(payload.get("status") or "")
        return _map_session_status(status)

    def fetch_qr_png(self) -> bytes:
        headers = {"accept": "image/png"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            response = self._http.request(
                "GET",
                f"{self.base_url}/api/{self.session}/auth/qr",
                headers=headers,
                json=None,
                timeout=_STATUS_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise WahaError("WAHA não respondeu. Confira WAHA_URL.", session_down=True) from exc
        content_type = ""
        response_headers = getattr(response, "headers", {}) or {}
        if hasattr(response_headers, "get"):
            content_type = str(response_headers.get("content-type") or "")
        if response.status_code >= 400 or "image/" not in content_type.lower() or not response.content:
            raise WahaError("WAHA não devolveu o QR.", session_down=False)
        return bytes(response.content)
```

Do not change `connection_state`. The scheduler still treats a down WAHA as `disconnected`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_waha -v`

Expected: PASS, including the older tests.

- [ ] **Step 5: Commit**

```bash
git add promo_livros/waha.py tests/test_waha.py
git commit -m "Read the WhatsApp session state and QR image from WAHA."
```

---

### Task 6: HTML das páginas

**Files:**
- Create: `promo_livros/dashboard_pages.py`
- Test: `tests/test_dashboard_http.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from promo_livros.dashboard_pages import login_page, render_groups, render_today, render_whatsapp
from promo_livros.day_view import BookLine, DayView, GroupLine
from promo_livros.groups_file import GroupChoice


class PageTests(unittest.TestCase):
    def test_login_page_has_no_queue(self) -> None:
        html = login_page(failed=True)
        self.assertIn("Entrar", html)
        self.assertNotIn("Black Livros", html)
        self.assertIn("Usuário ou senha incorretos", html)

    def test_today_without_queue_says_so(self) -> None:
        html = render_today(day="2026-09-27", view=None, error=None)
        self.assertIn("A fila de hoje ainda não existe", html)
        self.assertIn('href="/whatsapp"', html)

    def test_today_shows_group_status_and_escapes_title(self) -> None:
        view = DayView(
            day="2026-09-27",
            books=(
                BookLine(
                    clock="20:00",
                    niche_label="Ficção",
                    title="<script>",
                    price_label="R$ 34,90",
                    book_status="pronto",
                    caption="linha",
                    groups=(GroupLine("Black Livros 01", "1@g.us", "enviada"),),
                    reserve=False,
                ),
            ),
        )
        html = render_today(day="2026-09-27", view=view, error=None)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn("enviada", html)

    def test_whatsapp_qr_only_when_requested(self) -> None:
        qr = render_whatsapp(state="qr", message=None)
        down = render_whatsapp(state="down", message="O WAHA não respondeu.")
        self.assertIn('/whatsapp/qr', qr)
        self.assertNotIn("/whatsapp/qr", down)
        self.assertIn("O WAHA não respondeu.", down)

    def test_groups_form_marks_missing_and_hides_save_when_offline(self) -> None:
        choices = [
            GroupChoice("Black Livros 01", "120363430990609445@g.us", True, False),
            GroupChoice("Black Livros 03", "120363412365496470@g.us", True, True),
        ]
        online = render_groups(choices, connected=True, notice=None)
        offline = render_groups(choices, connected=False, notice=None)
        self.assertIn("fora da sessão", online)
        self.assertIn("Salvar", online)
        self.assertIn("Conecte o WhatsApp", offline)
        self.assertNotIn(">Salvar<", offline)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_dashboard_http.PageTests -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'promo_livros.dashboard_pages'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from html import escape

from promo_livros.day_view import DayView
from promo_livros.groups_file import GroupChoice

_NAV = """
<nav>
  <a href="/hoje">Hoje</a>
  <a href="/whatsapp">WhatsApp</a>
  <a href="/grupos">Grupos</a>
  <form method="post" action="/logout"><button type="submit">Sair</button></form>
</nav>
"""


def login_page(*, failed: bool) -> str:
    message = "<p>Usuário ou senha incorretos.</p>" if failed else ""
    return _page(
        "Entrar",
        f"""
        <h1>Promo Livros</h1>
        {message}
        <form method="post" action="/login">
          <label>Usuário <input name="username" autocomplete="username"></label>
          <label>Senha <input name="password" type="password" autocomplete="current-password"></label>
          <button type="submit">Entrar</button>
        </form>
        """,
        nav=False,
    )


def render_today(*, day: str, view: DayView | None, error: str | None) -> str:
    if error:
        body = f"<p>{escape(error)}</p>"
    elif view is None:
        body = "<p>A fila de hoje ainda não existe.</p>"
    else:
        blocks = []
        for book in view.books:
            if book.book_status == "sem livro":
                blocks.append(f"<section><h2>{escape(book.clock)} {escape(book.niche_label)}</h2><p>sem livro</p></section>")
                continue
            reserve = " · reserva" if book.reserve else ""
            clock = f"{escape(book.clock)} " if book.clock else ""
            groups = "".join(
                f"<li>{escape(group.name)} · {escape(group.status_label)}</li>"
                for group in book.groups
            )
            blocks.append(
                f"""
                <section>
                  <h2>{clock}{escape(book.niche_label)}{reserve}</h2>
                  <p>{escape(book.title)} · {escape(book.price_label)} · {escape(book.book_status)}</p>
                  <ul>{groups}</ul>
                  <pre>{escape(book.caption)}</pre>
                </section>
                """
            )
        body = f"<h1>{escape(day)}</h1>" + "".join(blocks)
    return _page("Hoje", body, nav=True)


def render_whatsapp(*, state: str, message: str | None) -> str:
    if message:
        body = f"<p>{escape(message)}</p>"
    elif state == "connected":
        body = "<p>Conectado.</p><p>Sessão promo-livros.</p>"
    elif state == "qr":
        body = '<p>Escaneie o QR para parear.</p><img alt="QR do WhatsApp" src="/whatsapp/qr">'
    else:
        body = "<p>Desconectado.</p>"
    return _page("WhatsApp", "<h1>WhatsApp</h1>" + body, nav=True)


def render_groups(choices: list[GroupChoice], *, connected: bool, notice: str | None) -> str:
    note = f"<p>{escape(notice)}</p>" if notice else ""
    if not connected:
        saved = "".join(f"<li>{escape(choice.name)}</li>" for choice in choices if choice.checked)
        body = note + "<p>Conecte o WhatsApp para ver a lista.</p><ul>" + saved + "</ul>"
        return _page("Grupos", "<h1>Grupos</h1>" + body, nav=True)
    rows = []
    for choice in choices:
        checked = " checked" if choice.checked else ""
        missing = " · fora da sessão" if choice.missing else ""
        rows.append(
            f"""
            <label>
              <input type="checkbox" name="chat_id" value="{escape(choice.chat_id)}"{checked}>
              {escape(choice.name)}{missing}
            </label>
            """
        )
    body = note + f"""
      <form method="post" action="/grupos">
        {''.join(rows)}
        <button type="submit">Salvar</button>
      </form>
      <p>O relógio do bot só lê a lista nova quando o processo subir de novo.</p>
    """
    return _page("Grupos", "<h1>Grupos</h1>" + body, nav=True)


def _page(title: str, body: str, *, nav: bool) -> str:
    navigation = _NAV if nav else ""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>{escape(title)}</title></head>
<body>
{navigation}
{body}
</body>
</html>
"""
```

The offline test looks for `>Salvar<`. The submit button is `>Salvar</button>`, which contains `>Salvar<`. The offline page must not include that button.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_dashboard_http.PageTests -v`

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add promo_livros/dashboard_pages.py tests/test_dashboard_http.py
git commit -m "Render the three dashboard pages as HTML."
```

---

### Task 7: Servidor HTTP

**Files:**
- Create: `promo_livros/dashboard.py`
- Modify: `tests/test_dashboard_http.py`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dashboard_http.py`:

```python
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from promo_livros.dashboard import DashboardApp, DashboardHandler
from promo_livros.dashboard_auth import SessionStore
from promo_livros.day_view import DayView


class ServerTests(unittest.TestCase):
    def test_hoje_without_cookie_is_the_login_form(self) -> None:
        body = _get(self.server, "/hoje")
        self.assertIn("Entrar", body)
        self.assertNotIn("Sapiens", body)

    def test_hoje_with_cookie_shows_the_book(self) -> None:
        token = self.app.sessions.login("ana", "certa", "ana", "certa")
        body = _get(self.server, "/hoje", cookie=token)
        self.assertIn("Sapiens", body)
        self.assertNotIn('src="/whatsapp/qr"', body)

    def test_qr_route_without_cookie_is_not_an_image(self) -> None:
        status, content_type, _payload = _get_raw(self.server, "/whatsapp/qr")
        self.assertEqual(status, 200)
        self.assertNotIn("image/png", content_type)

    def setUp(self) -> None:
        book = BookLine(
            clock="20:00",
            niche_label="Ficção",
            title="Sapiens",
            price_label="R$ 34,90",
            book_status="pronto",
            caption="linha",
            groups=(),
            reserve=False,
        )
        app = DashboardApp(
            username="ana",
            password="certa",
            sessions=SessionStore(),
            today=lambda: (None, DayView(day="2026-09-27", books=(book,))),
            whatsapp=lambda: ("connected", None),
            qr_png=lambda: b"\x89PNG",
            group_form=lambda: ([], True, None),
            save_groups=lambda _ids: None,
        )
        self.app = app
        DashboardHandler.app = app
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _get(server: ThreadingHTTPServer, path: str, cookie: str | None = None) -> str:
    _status, _content_type, payload = _get_raw(server, path, cookie)
    return payload.decode("utf-8")


def _get_raw(
    server: ThreadingHTTPServer,
    path: str,
    cookie: str | None = None,
) -> tuple[int, str, bytes]:
    host, port = server.server_address[:2]
    headers = {}
    if cookie:
        headers["Cookie"] = f"promo_livros_session={cookie}"
    request = Request(f"http://{host}:{port}{path}", headers=headers)
    with urlopen(request) as response:
        return response.status, response.headers.get("content-type", ""), response.read()
```

`today` returns `(error, view)`. The cookie test looks for the title `Sapiens`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_dashboard_http.ServerTests -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'promo_livros.dashboard'`

- [ ] **Step 3: Write minimal implementation**

`promo_livros/dashboard.py`:

```python
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from promo_livros.config import load_config
from promo_livros.dashboard_auth import SessionStore
from promo_livros.dashboard_pages import login_page, render_groups, render_today, render_whatsapp
from promo_livros.day_view import DayView
from promo_livros.groups_file import GroupChoice, GroupsFileError, group_choices, selected_groups, write_groups
from promo_livros.models import ConfigError

HOST = "127.0.0.1"
PORT = 8787
COOKIE = "promo_livros_session"


@dataclass
class DashboardApp:
    username: str
    password: str
    sessions: SessionStore
    today: Callable[[], tuple[str | None, DayView | None]]
    whatsapp: Callable[[], tuple[str, str | None]]
    qr_png: Callable[[], bytes]
    group_form: Callable[[], tuple[list[GroupChoice], bool, str | None]]
    save_groups: Callable[[list[str]], None]


class DashboardHandler(BaseHTTPRequestHandler):
    app: DashboardApp

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/whatsapp/qr":
            self._qr()
            return
        if not self._logged_in():
            self._html(login_page(failed=False))
            return
        if path == "/whatsapp":
            state, message = self.app.whatsapp()
            self._html(render_whatsapp(state=state, message=message))
            return
        if path == "/grupos":
            choices, connected, notice = self.app.group_form()
            self._html(render_groups(choices, connected=connected, notice=notice))
            return
        error, view = self.app.today()
        day = view.day if view is not None else ""
        self._html(render_today(day=day, view=view, error=error))

    def do_POST(self) -> None:
        if not _same_origin(self):
            self.send_error(403)
            return
        path = urlparse(self.path).path
        form = _form(self)
        if path == "/login":
            token = self.app.sessions.login(
                _field(form, "username"),
                _field(form, "password"),
                self.app.username,
                self.app.password,
            )
            if token is None:
                self._html(login_page(failed=True))
                return
            self._redirect("/hoje", token)
            return
        if not self._logged_in():
            self._html(login_page(failed=False))
            return
        if path == "/logout":
            self.app.sessions.forget(self._token())
            self._redirect("/", None)
            return
        if path == "/grupos":
            try:
                self.app.save_groups(form.get("chat_id", []))
            except GroupsFileError as exc:
                choices, connected, _notice = self.app.group_form()
                self._html(render_groups(choices, connected=connected, notice=str(exc)))
                return
            self._redirect("/grupos", self._token())
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _qr(self) -> None:
        if not self._logged_in():
            self._html(login_page(failed=False))
            return
        state, message = self.app.whatsapp()
        if state != "qr" or message:
            self._html(render_whatsapp(state=state, message=message or "Não há QR."))
            return
        try:
            payload = self.app.qr_png()
        except Exception:
            self._html(render_whatsapp(state="down", message="WAHA não devolveu o QR."))
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _logged_in(self) -> bool:
        return self.app.sessions.valid(self._token())

    def _token(self) -> str | None:
        header = self.headers.get("Cookie", "")
        for part in header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and value:
                return value
        return None

    def _html(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str, token: str | None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if token:
            self.send_header("Set-Cookie", f"{COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/")
        else:
            self.send_header("Set-Cookie", f"{COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.end_headers()


def _same_origin(handler: BaseHTTPRequestHandler) -> bool:
    origin = handler.headers.get("Origin")
    if not origin:
        return True
    return urlparse(origin).netloc == handler.headers.get("Host", "")


def _form(handler: BaseHTTPRequestHandler) -> dict[str, list[str]]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length).decode("utf-8", errors="replace")
    return parse_qs(raw, keep_blank_values=False)


def _field(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name, [])
    return values[0] if values else ""


def serve(app: DashboardApp) -> None:
    DashboardHandler.app = app
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    server.serve_forever()


def main() -> None:
    try:
        config = load_config(Path("config.yaml"))
    except ConfigError as exc:
        raise SystemExit(f"Configuração: {exc}") from exc
    username = os.environ.get("DASHBOARD_USERNAME", "").strip()
    password = os.environ.get("DASHBOARD_PASSWORD", "").strip()
    if not username or not password:
        raise SystemExit("Defina DASHBOARD_USERNAME e DASHBOARD_PASSWORD no .env.")
    app = build_app(config, username, password)
    serve(app)


def build_app(config, username: str, password: str) -> DashboardApp:
    from datetime import datetime

    from promo_livros.day_view import DayReadError, build_day_view, captions_for, load_day_rows
    from promo_livros.groups_file import group_choices
    from promo_livros.models import WhatsAppGroup
    from promo_livros.schedule_plan import service_day, zone
    from promo_livros.waha import WahaClient, WahaError

    sessions = SessionStore()
    holder = {"groups": config.whatsapp_groups, "enabled": config.whatsapp_enabled}

    def today() -> tuple[str | None, DayView | None]:
        day = service_day(datetime.now(zone(config.schedule.timezone)), config.schedule.timezone)
        try:
            queue, dispatches = load_day_rows(config.sqlite_path, day)
        except DayReadError as exc:
            return str(exc), None
        view = build_day_view(
            day=day,
            slots=config.slots,
            niches=config.niches,
            per_niche=config.schedule.per_niche,
            queue=tuple(queue),
            dispatches=tuple(dispatches),
            saved_groups=holder["groups"],
            captions=captions_for(dispatches, queue, config.affiliate_tag),
        )
        return None, view

    def whatsapp() -> tuple[str, str | None]:
        client = WahaClient.from_config(config)
        try:
            return client.probe_session(), None
        except WahaError as exc:
            return "down", str(exc)
        finally:
            client.close()

    def qr_png() -> bytes:
        client = WahaClient.from_config(config)
        try:
            return client.fetch_qr_png()
        finally:
            client.close()

    def group_form() -> tuple[list[GroupChoice], bool, str | None]:
        state, message = whatsapp()
        if state != "connected":
            return group_choices((), holder["groups"]), False, message
        client = WahaClient.from_config(config)
        try:
            live = client.list_groups()
        except WahaError as exc:
            return group_choices((), holder["groups"]), False, str(exc)
        finally:
            client.close()
        return group_choices(live, holder["groups"]), True, None

    def save(posted_ids: list[str]) -> None:
        choices, connected, message = group_form()
        if not connected:
            raise GroupsFileError(message or "Conecte o WhatsApp para ver a lista.")
        groups = selected_groups(posted_ids, choices)
        write_groups(Path("config.yaml"), groups, enabled=holder["enabled"])
        holder["groups"] = tuple(WhatsAppGroup(name, chat_id) for name, chat_id in groups)

    return DashboardApp(username, password, sessions, today, whatsapp, qr_png, group_form, save)


if __name__ == "__main__":
    main()
```

`holder` guarda os grupos gravados nesta execução da dashboard. O agendador é outro processo e só lê o YAML na próxima subida.

Add to `.env.example`:

```
# Login da dashboard em 127.0.0.1:8787. Distinto do login do painel WAHA.
DASHBOARD_USERNAME=
DASHBOARD_PASSWORD=
```

No `README.md`, depois da seção de WhatsApp, acrescente a seção abaixo. Os blocos de comando ficam com fence normal dentro do README.

## Dashboard

Na pasta do projeto, no Mac (`/Volumes/HD 1Tb/Vibecoding/Promo Livros`):

    python -m promo_livros.dashboard

A página escuta em `127.0.0.1:8787`. Sem `DASHBOARD_USERNAME` e `DASHBOARD_PASSWORD` no `.env`, o processo não sobe. Hoje mostra a fila e não grava no SQLite. WhatsApp mostra a sessão `promo-livros` e o QR quando o WAHA pede pareamento. Grupos grava só a lista em `config.yaml`. O agendador só passa a usar essa lista na próxima subida.

No túnel `promo-livros`, antes da regra final, a entrada nova é o hostname `painel.promolivros.org` com serviço `http://127.0.0.1:8787`. O nome `painel` aponta para o mesmo túnel de `esteira`. `esteira.promolivros.org/dashboard` continua sendo o painel do WAHA. A sessão em `~/waha/sessions-livros` não muda de disco neste passo.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_dashboard_http tests.test_day_view tests.test_groups_file tests.test_dashboard_auth tests.test_waha -v`

Expected: PASS.

Also run the whole suite:

Run: `python -m unittest discover -s tests -v`

Expected: PASS. The new server test binds `127.0.0.1` on a free port and shuts it down.

- [ ] **Step 5: Commit**

```bash
git add promo_livros/dashboard.py tests/test_dashboard_http.py .env.example README.md
git commit -m "Serve the dashboard on localhost with a login gate."
```

---

## Spec coverage

- Três páginas, login e cookie na memória: Tasks 4, 6 e 7.
- Grade com status de livro e de grupo, dia vazio e texto da mensagem: Tasks 1, 2 e 6.
- QR só no estado QR, imagem via WAHA, erro quando não é imagem: Tasks 5 e 7.
- Grupos da sessão, item fora da sessão, salvar só o bloco, lista vazia recusada com disparo ligado, comentários preservados: Task 3 e o `save` da Task 7.
- SQLite somente leitura e banco ocupado: Task 2.
- Processo na pasta do projeto, porta 8787, sem caminho do disco no código: Task 7.
- Túnel `painel.promolivros.org` documentado, painel do WAHA intocado, volume da sessão fora deste trabalho: README na Task 7.
- Fora do plano: enviar agora, pular, segurar, editar nicho ou horário, ligar `whatsapp.enabled`, site, imagem gerada, mover a sessão do WAHA.

## Self-review

- `build_day_view`, `load_day_rows`, `captions_for`, `GroupChoice`, `SessionStore.login/valid/forget`, `probe_session`, `fetch_qr_png`, `DashboardApp` e as funções `render_*` usam os mesmos nomes nas tasks seguintes.
- `today` devolve `(error, view)`. A página Hoje usa essa ordem.
- `group_form` devolve `(choices, connected, notice)`.
- Não há tarefa de mover `~/waha/sessions-livros`.
