# Campanhas de convite — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mandar dois convites por dia para todos os grupos (um num horário definido, outro depois do último post da fila), com foto e texto sorteados de campanhas cadastradas no painel.

**Architecture:** Regras puras em `campaign_rules.py`; dados em `CampaignStore` (mesmo SQLite do `BoardStore`, tabelas próprias); envio em `campaign_send.publish_due_invite`, chamado pelo loop `scripts/enviar_fila.py` antes de `publish_due`. A espera entre mensagens sai de `board_send` para `send_gap.py` e passa a valer entre fila, convites e enquetes. Painel: `/campanhas` (callbacks em `campaign_panel.py`, HTML em `campaign_pages.py`) e um cartão "Convites" na lateral da `/hoje`.

**Tech Stack:** Python 3.13, sqlite3, Pillow, `http.server`, pytest/unittest.

**Spec:** `docs/superpowers/specs/2026-11-03-campanhas-convite-design.md`

**Commits:** neste PC o `git add` falha com "Permission denied" em `.git/objects` (pasta de rede). Se o passo de commit falhar, siga para a próxima tarefa e faça os commits no Mac.

---

## Mapa de arquivos

| Arquivo | Papel |
|---|---|
| `promo_livros/send_schedule.py` (mod.) | `clock_minutes`, `format_clock` públicos |
| `promo_livros/send_gap.py` (novo) | `latest_stamp`, `gap_open` |
| `promo_livros/board_send.py` (mod.) | usa `send_gap` |
| `promo_livros/polls.py` (mod.) | usa `send_gap` |
| `promo_livros/campaign_rules.py` (novo) | horários, rodízio, sorteio (puro) |
| `promo_livros/campaign_store.py` (novo) | tabelas e consultas de campanhas e envios |
| `promo_livros/board_store.py` (mod.) | `last_queue_clock`, `has_pending_posts` |
| `promo_livros/campaign_images.py` (novo) | validar, converter e ler fotos |
| `promo_livros/campaign_send.py` (novo) | `publish_due_invite` |
| `scripts/enviar_fila.py` (mod.) | chama o convite e soma as esperas |
| `promo_livros/multipart_form.py` (novo) | lê `multipart/form-data` |
| `promo_livros/dashboard_pages.py` (mod.) | `render_page`, link "Campanhas" no menu |
| `promo_livros/campaign_pages.py` (novo) | HTML de `/campanhas` e do cartão da `/hoje` |
| `promo_livros/campaign_panel.py` (novo) | callbacks do painel |
| `promo_livros/dashboard_belt.py` (mod.) | link no menu, cartão de convites na lateral |
| `promo_livros/dashboard.py` (mod.) | rotas e montagem |

---

### Task 1: Espera comum entre mensagens

**Files:**
- Modify: `promo_livros/send_schedule.py`
- Create: `promo_livros/send_gap.py`
- Modify: `promo_livros/board_send.py:55`, `:104-124`
- Modify: `promo_livros/polls.py:820-822`
- Test: `tests/test_send_gap.py`

- [ ] **Step 1: Write the failing test**

`tests/test_send_gap.py`:

```python
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from promo_livros.send_gap import gap_open, latest_stamp
from promo_livros.send_schedule import clock_minutes, format_clock

ZONE = ZoneInfo("America/Sao_Paulo")


class SendGapTests(unittest.TestCase):
    def test_latest_stamp_ignores_empty_values(self) -> None:
        now = datetime(2026, 11, 3, 13, 0, tzinfo=ZONE)
        early = (now - timedelta(minutes=5)).isoformat(timespec="seconds")
        late = (now - timedelta(seconds=10)).isoformat(timespec="seconds")
        self.assertEqual(latest_stamp((early, None, late, ""), now), late)
        self.assertIsNone(latest_stamp((None, ""), now))

    def test_naive_stamp_takes_the_zone_of_now(self) -> None:
        now = datetime(2026, 11, 3, 13, 0, tzinfo=ZONE)
        self.assertFalse(gap_open("2026-11-03T12:59:30", now, 45))
        self.assertTrue(gap_open("2026-11-03T12:59:00", now, 45))

    def test_no_previous_send_is_open(self) -> None:
        self.assertTrue(gap_open(None, datetime(2026, 11, 3, 13, 0, tzinfo=ZONE), 45))


class ClockHelpersTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        self.assertEqual(clock_minutes("13:15"), 13 * 60 + 15)
        self.assertEqual(format_clock(13 * 60 + 15), "13:15")

    def test_bad_clock_names_the_field(self) -> None:
        with self.assertRaises(ValueError) as caught:
            clock_minutes("25:00", "Convite no horário")
        self.assertIn("Convite no horário", str(caught.exception))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_send_gap.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'promo_livros.send_gap'`

- [ ] **Step 3: Add the public clock helpers**

Em `promo_livros/send_schedule.py`, logo depois de `_format_clock`:

```python
def clock_minutes(value: str, label: str = "Horário") -> int:
    return _clock_minutes(value, label)


def format_clock(minute: int) -> str:
    return _format_clock(minute)
```

- [ ] **Step 4: Create `promo_livros/send_gap.py`**

```python
"""Espera entre mensagens nos grupos. Vale para fila, convites e enquetes."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta


def latest_stamp(stamps: Iterable[str | None], now: datetime) -> str | None:
    present = [item for item in stamps if item]
    if not present:
        return None
    return max(present, key=lambda value: _moment(value, now))


def gap_open(last_sent: str | None, now: datetime, gap_seconds: int) -> bool:
    if not last_sent:
        return True
    return now - _moment(last_sent, now) >= timedelta(seconds=gap_seconds)


def _moment(value: str, now: datetime) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None and now.tzinfo is not None:
        return parsed.replace(tzinfo=now.tzinfo)
    return parsed
```

- [ ] **Step 5: Point `board_send` and `polls` at the new module**

Em `promo_livros/board_send.py`:
- Trocar o import `from datetime import datetime, timedelta` por `from datetime import datetime`.
- Adicionar `from promo_livros.send_gap import gap_open, latest_stamp`.
- Linha 55 vira:

```python
    if not gap_open(latest_stamp((store.last_group_sent_at(), quiet_since), now), now, schedule.group_gap_seconds):
```

- Apagar as funções `_later_stamp` e `_gap_open` (linhas 104-124).

Em `promo_livros/polls.py`, linhas 820-822 viram:

```python
    from promo_livros.send_gap import gap_open, latest_stamp

    if not gap_open(latest_stamp((store.last_outbound_at(), other_sent_at), now), now, gap_seconds):
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_send_gap.py tests/test_board_send.py tests/test_polls.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add promo_livros/send_gap.py promo_livros/send_schedule.py promo_livros/board_send.py promo_livros/polls.py tests/test_send_gap.py
git commit -m "Share the wait between group messages across queue and polls."
```

---

### Task 2: Regras puras dos convites

**Files:**
- Create: `promo_livros/campaign_rules.py`
- Test: `tests/test_campaign_rules.py`

- [ ] **Step 1: Write the failing test**

`tests/test_campaign_rules.py`:

```python
import unittest
from random import Random

from promo_livros.campaign_rules import (
    DEFAULT_LAST_OFFSET_MINUTES,
    InviteSettings,
    RotationEntry,
    fixed_invite_due,
    fixed_invite_missed,
    invite_settings,
    last_invite_clock,
    last_invite_due,
    parse_fixed_clock,
    parse_last_offset,
    pick_avoiding,
    rotation_order,
)


class FixedClockTests(unittest.TestCase):
    def test_empty_turns_the_invite_off(self) -> None:
        self.assertIsNone(parse_fixed_clock("  ", {"10:00"}))

    def test_a_queue_clock_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            parse_fixed_clock("10:00", {"10:00"})
        self.assertIn("horário da fila", str(caught.exception))

    def test_bad_format_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_fixed_clock("25:00", set())

    def test_free_clock_is_kept(self) -> None:
        self.assertEqual(parse_fixed_clock(" 13:15 ", {"13:00"}), "13:15")

    def test_due_only_inside_the_grace_window(self) -> None:
        self.assertFalse(fixed_invite_due("13:15", "13:14"))
        self.assertTrue(fixed_invite_due("13:15", "13:15"))
        self.assertTrue(fixed_invite_due("13:15", "14:14"))
        self.assertFalse(fixed_invite_due("13:15", "14:15"))
        self.assertFalse(fixed_invite_due(None, "13:15"))

    def test_missed_after_the_grace_window(self) -> None:
        self.assertFalse(fixed_invite_missed("13:15", "14:14"))
        self.assertTrue(fixed_invite_missed("13:15", "14:15"))
        self.assertFalse(fixed_invite_missed(None, "23:00"))


class LastInviteTests(unittest.TestCase):
    def test_offset_after_the_last_queue_post(self) -> None:
        self.assertEqual(last_invite_clock("21:20", "22:00", 10), "21:30")

    def test_without_queue_the_window_end_is_the_reference(self) -> None:
        self.assertEqual(last_invite_clock(None, "22:00", 10), "22:10")

    def test_never_passes_the_end_of_the_day(self) -> None:
        self.assertEqual(last_invite_clock("23:55", "22:00", 10), "23:59")

    def test_waits_for_pending_queue_posts(self) -> None:
        self.assertFalse(last_invite_due("21:40", "21:30", queue_pending=True))
        self.assertTrue(last_invite_due("21:40", "21:30", queue_pending=False))
        self.assertFalse(last_invite_due("21:29", "21:30", queue_pending=False))

    def test_offset_limits(self) -> None:
        self.assertEqual(parse_last_offset(" 15 "), 15)
        for raw in ("0", "121", "x", ""):
            with self.assertRaises(ValueError):
                parse_last_offset(raw)


class SettingsTests(unittest.TestCase):
    def test_broken_saved_values_fall_back(self) -> None:
        settings = invite_settings("99:99", "abc")
        self.assertIsNone(settings.fixed_clock)
        self.assertEqual(settings.last_offset_minutes, DEFAULT_LAST_OFFSET_MINUTES)

    def test_saved_values_are_read(self) -> None:
        self.assertEqual(invite_settings("13:15", "20"), InviteSettings("13:15", 20))
        self.assertEqual(invite_settings(None, None), InviteSettings(None, DEFAULT_LAST_OFFSET_MINUTES))


class RotationTests(unittest.TestCase):
    def test_first_use_starts_at_the_top(self) -> None:
        self.assertEqual(rotation_order([RotationEntry(2, 2), RotationEntry(1, 1)], None), [1, 2])

    def test_goes_to_the_next_after_the_last_used(self) -> None:
        ready = [RotationEntry(1, 1), RotationEntry(2, 2), RotationEntry(3, 3)]
        self.assertEqual(rotation_order(ready, RotationEntry(1, 1)), [2, 3, 1])

    def test_wraps_after_the_last(self) -> None:
        ready = [RotationEntry(1, 1), RotationEntry(2, 2), RotationEntry(3, 3)]
        self.assertEqual(rotation_order(ready, RotationEntry(3, 3)), [1, 2, 3])

    def test_a_campaign_that_left_keeps_its_place(self) -> None:
        ready = [RotationEntry(1, 1), RotationEntry(3, 3)]
        self.assertEqual(rotation_order(ready, RotationEntry(2, 2)), [3, 1])

    def test_nothing_ready(self) -> None:
        self.assertEqual(rotation_order([], RotationEntry(1, 1)), [])


class PickTests(unittest.TestCase):
    def test_avoids_the_last_used_when_there_is_another(self) -> None:
        for seed in range(20):
            self.assertEqual(pick_avoiding([1, 2], 1, Random(seed)), 2)

    def test_single_item_repeats(self) -> None:
        self.assertEqual(pick_avoiding([5], 5, Random(0)), 5)

    def test_empty_list_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            pick_avoiding([], None, Random(0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_campaign_rules.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'promo_livros.campaign_rules'`

- [ ] **Step 3: Create `promo_livros/campaign_rules.py`**

```python
"""Regras dos convites: horários, rodízio e sorteio. Sem banco e sem rede."""
from __future__ import annotations

from dataclasses import dataclass
from random import Random

from promo_livros.send_schedule import clock_minutes, format_clock

INVITE_FIXED = "fixed"
INVITE_LAST = "last"
INVITE_KINDS = (INVITE_FIXED, INVITE_LAST)
DEFAULT_LAST_OFFSET_MINUTES = 10
MIN_LAST_OFFSET_MINUTES = 1
MAX_LAST_OFFSET_MINUTES = 120
FIXED_GRACE_MINUTES = 60
_LAST_MINUTE_OF_DAY = 23 * 60 + 59


@dataclass(frozen=True)
class InviteSettings:
    fixed_clock: str | None
    last_offset_minutes: int


@dataclass(frozen=True)
class RotationEntry:
    campaign_id: int
    position: int


def invite_settings(raw_fixed: str | None, raw_offset: str | None) -> InviteSettings:
    """Lê o que está salvo. Valor estragado volta ao padrão para não travar o envio."""
    fixed = (raw_fixed or "").strip() or None
    if fixed is not None:
        try:
            clock_minutes(fixed)
        except ValueError:
            fixed = None
    try:
        offset = parse_last_offset(raw_offset or "")
    except ValueError:
        offset = DEFAULT_LAST_OFFSET_MINUTES
    return InviteSettings(fixed, offset)


def parse_fixed_clock(raw: str, taken_clocks: set[str]) -> str | None:
    value = raw.strip()
    if not value:
        return None
    clock_minutes(value, "Convite no horário")
    if value in taken_clocks:
        raise ValueError(f"{value} já é horário da fila. Escolha outro para o convite.")
    return value


def parse_last_offset(raw: str) -> int:
    try:
        minutes = int(raw.strip())
    except ValueError as exc:
        raise ValueError("Os minutos do convite final precisam ser um número.") from exc
    if not MIN_LAST_OFFSET_MINUTES <= minutes <= MAX_LAST_OFFSET_MINUTES:
        raise ValueError(
            f"Os minutos do convite final ficam entre {MIN_LAST_OFFSET_MINUTES} e {MAX_LAST_OFFSET_MINUTES}."
        )
    return minutes


def fixed_invite_due(fixed_clock: str | None, now_clock: str) -> bool:
    """Só dentro da janela de tolerância: um horário salvo depois de passar não dispara na hora."""
    if fixed_clock is None:
        return False
    start = clock_minutes(fixed_clock)
    return start <= clock_minutes(now_clock) < start + FIXED_GRACE_MINUTES


def fixed_invite_missed(fixed_clock: str | None, now_clock: str) -> bool:
    if fixed_clock is None:
        return False
    return clock_minutes(now_clock) >= clock_minutes(fixed_clock) + FIXED_GRACE_MINUTES


def last_invite_clock(last_queue_clock: str | None, send_end: str, offset_minutes: int) -> str:
    reference = clock_minutes(last_queue_clock or send_end)
    return format_clock(min(reference + offset_minutes, _LAST_MINUTE_OF_DAY))


def last_invite_due(now_clock: str, invite_clock: str, *, queue_pending: bool) -> bool:
    return not queue_pending and clock_minutes(now_clock) >= clock_minutes(invite_clock)


def rotation_order(ready: list[RotationEntry], last_used: RotationEntry | None) -> list[int]:
    """Campanhas prontas a partir da seguinte à última usada, dando a volta."""
    ordered = sorted(ready, key=lambda entry: (entry.position, entry.campaign_id))
    if last_used is None:
        return [entry.campaign_id for entry in ordered]
    marker = (last_used.position, last_used.campaign_id)
    split = next(
        (index for index, entry in enumerate(ordered) if (entry.position, entry.campaign_id) > marker),
        0,
    )
    return [entry.campaign_id for entry in ordered[split:] + ordered[:split]]


def pick_avoiding(item_ids: list[int], last_used_id: int | None, rng: Random) -> int:
    if not item_ids:
        raise ValueError("Não há opção para sortear.")
    options = [item for item in item_ids if item != last_used_id] or list(item_ids)
    return rng.choice(options)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_campaign_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/campaign_rules.py tests/test_campaign_rules.py
git commit -m "Write the invite clock, rotation and draw rules."
```

---

### Task 3: CampaignStore

**Files:**
- Create: `promo_livros/campaign_store.py`
- Test: `tests/test_campaign_store.py`

- [ ] **Step 1: Write the failing test**

`tests/test_campaign_store.py`:

```python
import tempfile
import unittest
from pathlib import Path

from promo_livros.campaign_rules import INVITE_FIXED, INVITE_LAST, RotationEntry
from promo_livros.campaign_store import MAX_TEXT_LENGTH, CampaignError, CampaignStore


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
        self.store.mark_group_sent(run.id, "a@g.us", "msg-1", "2026-11-03T13:15:00-03:00")
        self.store.mark_group_sent(run.id, "b@g.us", "msg-2", "2026-11-03T13:15:45-03:00")
        self.assertEqual(self.store.sent_chat_ids(run.id), {"a@g.us", "b@g.us"})
        self.assertEqual(self.store.last_sent_at(), "2026-11-03T13:15:45-03:00")
        self.store.mark_run_sent(run.id, "2026-11-03T13:15:45-03:00")
        self.assertEqual(self.store.run_for("2026-11-03", INVITE_FIXED).status, "sent")
        self.store.skip_run(run.id)
        self.assertEqual(self.store.run_for("2026-11-03", INVITE_FIXED).status, "sent")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_campaign_store.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'promo_livros.campaign_store'`

- [ ] **Step 3: Create `promo_livros/campaign_store.py`**

```python
"""Campanhas de convite: fotos, textos e o registro de cada convite do dia."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from promo_livros.campaign_rules import INVITE_KINDS, RotationEntry

MAX_NAME_LENGTH = 80
MAX_TEXT_LENGTH = 1024

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
        image = self.image(image_id)
        if image is None:
            return None
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM campaign_images WHERE id = ?", (image_id,))
        return image.path

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

    def set_manual_campaign(self, day: str, kind: str, campaign_id: int | None) -> bool:
        """Só troca enquanto o convite não começou. None devolve ao rodízio."""
        run = self.run_for(day, kind)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE campaign_runs SET campaign_id = ?, manual = ? WHERE id = ? AND status = 'pending'",
                (campaign_id, 0 if campaign_id is None else 1, run.id),
            )
        return cursor.rowcount == 1

    def lock_content(self, run_id: int, campaign_id: int, image_id: int, text_id: int, locked_at: str) -> CampaignRun:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE campaign_runs
                SET campaign_id = ?, image_id = ?, text_id = ?, status = 'sending', locked_at = ?
                WHERE id = ? AND status IN ('pending', 'sending')
                """,
                (campaign_id, image_id, text_id, locked_at, run_id),
            )
            row = self._connection.execute(_RUN_SELECT + " WHERE id = ?", (run_id,)).fetchone()
        return _run(row)

    def skip_run(self, run_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE campaign_runs SET status = 'skipped' WHERE id = ? AND status IN ('pending', 'sending')",
                (run_id,),
            )

    def sent_chat_ids(self, run_id: int) -> set[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT chat_id FROM campaign_run_groups WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        return {str(row["chat_id"]) for row in rows}

    def mark_group_sent(self, run_id: int, chat_id: str, message_id: str, sent_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO campaign_run_groups (run_id, chat_id, message_id, sent_at) VALUES (?, ?, ?, ?)",
                (run_id, chat_id, message_id, sent_at),
            )

    def mark_run_sent(self, run_id: int, sent_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE campaign_runs SET status = 'sent', sent_at = ? WHERE id = ?",
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
    clean = body.replace("\r\n", "\n").strip()
    if not clean:
        raise CampaignError("O texto está vazio.")
    if len(clean) > MAX_TEXT_LENGTH:
        raise CampaignError(f"O texto passa de {MAX_TEXT_LENGTH} caracteres, o limite da legenda no WhatsApp.")
    return clean
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_campaign_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/campaign_store.py tests/test_campaign_store.py
git commit -m "Store invite campaigns and each day's invite."
```

---

### Task 4: Fim da fila no BoardStore

**Files:**
- Modify: `promo_livros/board_store.py` (depois de `has_day`, linha ~565)
- Test: `tests/test_board_queue_end.py`

- [ ] **Step 1: Write the failing test**

`tests/test_board_queue_end.py`:

```python
import tempfile
import unittest
from pathlib import Path

from promo_livros.board_store import BoardBook, BoardStore

DAY = "2026-11-03"


def _book() -> BoardBook:
    return BoardBook("Livro", "", 1000, 2000, 50, "Menor preço em 120 dias.", "https://example", "")


def _add(store: BoardStore, clock: str) -> int:
    return store.add_post(day=DAY, clock=clock, caption="*Livro*", image_path="data/cards/1.jpg", books=[_book()])


class QueueEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.store = BoardStore(Path(self.folder.name) / "board.sqlite")

    def tearDown(self) -> None:
        self.store.close()
        self.folder.cleanup()

    def test_last_clock_counts_sent_and_scheduled_before_the_end(self) -> None:
        first = _add(self.store, "10:00")
        late = _add(self.store, "21:20")
        _add(self.store, "22:30")
        self.store.mark_sent(first)
        self.assertEqual(self.store.last_queue_clock(DAY, "22:00"), "21:20")
        self.store.cancel(DAY, late)
        self.assertEqual(self.store.last_queue_clock(DAY, "22:00"), "10:00")

    def test_empty_day_has_no_clock(self) -> None:
        self.assertIsNone(self.store.last_queue_clock(DAY, "22:00"))

    def test_pending_ignores_posts_after_the_end(self) -> None:
        _add(self.store, "22:30")
        self.assertFalse(self.store.has_pending_posts(DAY, "22:00"))
        early = _add(self.store, "21:00")
        self.assertTrue(self.store.has_pending_posts(DAY, "22:00"))
        self.store.mark_sent(early)
        self.assertFalse(self.store.has_pending_posts(DAY, "22:00"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_board_queue_end.py -v`
Expected: FAIL com `AttributeError: 'BoardStore' object has no attribute 'last_queue_clock'`

- [ ] **Step 3: Add the two methods after `has_day`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_board_queue_end.py tests/test_board.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/board_store.py tests/test_board_queue_end.py
git commit -m "Tell when the day's queue ends."
```

---

### Task 5: Fotos das campanhas

**Files:**
- Create: `promo_livros/campaign_images.py`
- Test: `tests/test_campaign_images.py`

- [ ] **Step 1: Write the failing test**

`tests/test_campaign_images.py`:

```python
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from promo_livros.campaign_images import (
    MAX_SIDE,
    MAX_UPLOAD_BYTES,
    ImageUploadError,
    read_image,
    remove_campaign_dir,
    remove_image,
    save_upload,
)


def _encoded(fmt: str, size: tuple[int, int] = (40, 30), **options) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, fmt, **options)
    return buffer.getvalue()


class SaveUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_png_becomes_jpeg_in_the_campaign_folder(self) -> None:
        relative = save_upload(self.root, 3, _encoded("PNG"))
        self.assertTrue(relative.startswith("data/campaigns/3/"))
        self.assertTrue(relative.endswith(".jpg"))
        with Image.open(self.root / relative) as saved:
            self.assertEqual(saved.format, "JPEG")

    def test_webp_is_accepted(self) -> None:
        relative = save_upload(self.root, 3, _encoded("WEBP"))
        self.assertIsNotNone(read_image(self.root, relative))

    def test_large_image_is_reduced(self) -> None:
        relative = save_upload(self.root, 3, _encoded("PNG", (MAX_SIDE + 904, 100)))
        with Image.open(self.root / relative) as saved:
            self.assertEqual(saved.width, MAX_SIDE)

    def test_exif_is_dropped(self) -> None:
        exif = Image.Exif()
        exif[0x010F] = "Camera"
        relative = save_upload(self.root, 3, _encoded("JPEG", exif=exif))
        with Image.open(self.root / relative) as saved:
            self.assertNotIn("exif", saved.info)

    def test_refused_files(self) -> None:
        with self.assertRaises(ImageUploadError):
            save_upload(self.root, 3, b"")
        with self.assertRaises(ImageUploadError):
            save_upload(self.root, 3, b"not an image")
        with self.assertRaises(ImageUploadError):
            save_upload(self.root, 3, _encoded("GIF"))
        with self.assertRaises(ImageUploadError):
            save_upload(self.root, 3, b"x" * (MAX_UPLOAD_BYTES + 1))
        self.assertFalse((self.root / "data" / "campaigns" / "3").exists())


class ReadImageTests(unittest.TestCase):
    def test_only_reads_inside_the_campaign_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cards = root / "data" / "cards"
            cards.mkdir(parents=True)
            (cards / "1.jpg").write_bytes(b"card")
            self.assertIsNone(read_image(root, "data/cards/1.jpg"))
            self.assertIsNone(read_image(root, "data/campaigns/../cards/1.jpg"))
            self.assertIsNone(read_image(root, "data/campaigns/1/missing.jpg"))

    def test_remove_image_and_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            relative = save_upload(root, 4, _encoded("PNG"))
            remove_image(root, relative)
            self.assertIsNone(read_image(root, relative))
            save_upload(root, 4, _encoded("PNG"))
            remove_campaign_dir(root, 4)
            self.assertFalse((root / "data" / "campaigns" / "4").exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_campaign_images.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'promo_livros.campaign_images'`

- [ ] **Step 3: Create `promo_livros/campaign_images.py`**

```python
"""Fotos das campanhas. Tudo vira JPEG em data/campaigns/{id}/, sem metadados."""
from __future__ import annotations

import io
import shutil
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_SIDE = 4096
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}
JPEG_QUALITY = 88


class ImageUploadError(ValueError):
    """Arquivo recusado. A mensagem vai para a tela."""


def campaign_dir(root: Path, campaign_id: int) -> Path:
    return root / "data" / "campaigns" / str(int(campaign_id))


def save_upload(root: Path, campaign_id: int, payload: bytes) -> str:
    """Valida pelo conteúdo, não pela extensão, e devolve o caminho relativo à raiz."""
    if not payload:
        raise ImageUploadError("O arquivo veio vazio.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ImageUploadError("A foto passa de 8 MB.")
    try:
        with Image.open(io.BytesIO(payload)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(payload)) as source:
            if source.format not in ACCEPTED_FORMATS:
                raise ImageUploadError("Use foto JPEG, PNG ou WebP.")
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageUploadError("Esse arquivo não é uma foto JPEG, PNG ou WebP.") from exc
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    folder = campaign_dir(root, campaign_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4().hex}.jpg"
    image.save(folder / name, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return f"data/campaigns/{int(campaign_id)}/{name}"


def read_image(root: Path, relative_path: str) -> bytes | None:
    resolved = _inside_campaigns(root, relative_path)
    if resolved is None or not resolved.is_file():
        return None
    return resolved.read_bytes()


def remove_image(root: Path, relative_path: str) -> None:
    resolved = _inside_campaigns(root, relative_path)
    if resolved is not None:
        resolved.unlink(missing_ok=True)


def remove_campaign_dir(root: Path, campaign_id: int) -> None:
    shutil.rmtree(campaign_dir(root, campaign_id), ignore_errors=True)


def _inside_campaigns(root: Path, relative_path: str) -> Path | None:
    base = (root / "data" / "campaigns").resolve()
    resolved = (root / relative_path).resolve()
    if base not in resolved.parents:
        return None
    return resolved
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_campaign_images.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/campaign_images.py tests/test_campaign_images.py
git commit -m "Accept campaign photos and keep them as plain JPEG."
```

---

### Task 6: Envio dos convites

**Files:**
- Create: `promo_livros/campaign_send.py`
- Test: `tests/test_campaign_send.py`

- [ ] **Step 1: Write the failing test**

`tests/test_campaign_send.py`:

```python
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from random import Random
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.campaign_rules import INVITE_FIXED, INVITE_LAST
from promo_livros.campaign_send import publish_due_invite
from promo_livros.campaign_store import CampaignStore
from promo_livros.models import WhatsAppGroup
from promo_livros.send_schedule import parse_schedule
from promo_livros.waha import WahaError

ZONE = ZoneInfo("America/Sao_Paulo")
DAY = "2026-11-03"
GROUPS = (
    WhatsAppGroup("Black Livros 01", "120363430990609445@g.us"),
    WhatsAppGroup("Black Livros 02", "120363410393297284@g.us"),
)


class _Sender:
    def __init__(self, state: str = "connected", fail: WahaError | None = None) -> None:
        self.state = state
        self.fail = fail
        self.sent: list[tuple[str, str, bytes]] = []

    def connection_state(self) -> str:
        return self.state

    def send_jpeg(self, chat_id: str, caption: str, image: bytes) -> str:
        if self.fail is not None:
            raise self.fail
        self.sent.append((chat_id, caption, image))
        return f"msg-{len(self.sent)}"


def _at(hour: int, minute: int, day: int = 3) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=ZONE)


class InviteSendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.board = BoardStore(self.root / "board.sqlite")
        self.board.set_sending(True)
        self.board.save_send_schedule(parse_schedule("08:00", "22:00", "40", "45"))
        self.board.put_setting("invite_fixed_clock", "13:15")
        self.campaigns = CampaignStore(self.root / "board.sqlite")

    def tearDown(self) -> None:
        self.campaigns.close()
        self.board.close()
        self.folder.cleanup()

    def _campaign(self, name: str, *, images: int = 1, text: str | None = None) -> int:
        campaign_id = self.campaigns.create(name)
        for index in range(images):
            relative = f"data/campaigns/{campaign_id}/{index}.jpg"
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"jpeg-{campaign_id}-{index}".encode())
            self.campaigns.add_image(campaign_id, relative)
        self.campaigns.add_text(campaign_id, text or f"Entre no {name}!")
        return campaign_id

    def _invite(self, sender: _Sender, now: datetime, quiet_since: str | None = None) -> str:
        config = SimpleNamespace(whatsapp_groups=GROUPS)
        return publish_due_invite(
            config,
            self.board,
            self.campaigns,
            sender,
            root=self.root,
            now=now,
            quiet_since=quiet_since,
            rng=Random(0),
        )

    def test_fixed_invite_goes_to_each_group_with_the_same_content(self) -> None:
        self._campaign("A")
        sender = _Sender()
        now = _at(13, 15)
        self.assertEqual(self._invite(sender, now), "sent")
        self.assertEqual(self._invite(sender, now + timedelta(seconds=10)), "waiting")
        self.assertEqual(self._invite(sender, now + timedelta(seconds=45)), "sent")
        self.assertEqual([chat for chat, _caption, _image in sender.sent], [group.chat_id for group in GROUPS])
        self.assertEqual(sender.sent[0][1:], sender.sent[1][1:])
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "sent")
        self.assertEqual(self._invite(sender, now + timedelta(minutes=5)), "idle")

    def test_fixed_invite_waits_for_its_clock_and_gives_up_after_the_window(self) -> None:
        self._campaign("A")
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(13, 14)), "idle")
        self.assertEqual(self._invite(sender, _at(14, 15)), "idle")
        self.assertEqual(sender.sent, [])

    def test_sending_off_does_nothing(self) -> None:
        self._campaign("A")
        self.board.set_sending(False)
        self.assertEqual(self._invite(_Sender(), _at(13, 15)), "off")

    def test_rotation_alternates_between_the_two_invites(self) -> None:
        self._campaign("A", text="Texto A")
        self._campaign("B", text="Texto B")
        sender = _Sender()
        self._invite(sender, _at(13, 15))
        self._invite(sender, _at(13, 16))
        self.assertEqual(self._invite(sender, _at(22, 9)), "idle")
        self._invite(sender, _at(22, 10))
        self.assertEqual([caption for _chat, caption, _image in sender.sent], ["Texto A", "Texto A", "Texto B"])

    def test_last_invite_waits_for_the_queue(self) -> None:
        self._campaign("A")
        book = BoardBook("Livro", "", 1000, 2000, 50, "Menor preço.", "https://example", "")
        post_id = self.board.add_post(day=DAY, clock="21:20", caption="*Livro*", image_path="data/cards/1.jpg", books=[book])
        self.board.put_setting("invite_fixed_clock", "")
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(21, 35)), "idle")
        self.board.mark_sent(post_id)
        self.assertEqual(self._invite(sender, _at(21, 35)), "sent")
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_LAST).status, "sending")

    def test_manual_choice_wins_over_rotation(self) -> None:
        self._campaign("A", text="Texto A")
        chosen = self._campaign("B", text="Texto B")
        self.campaigns.set_manual_campaign(DAY, INVITE_FIXED, chosen)
        sender = _Sender()
        self._invite(sender, _at(13, 15))
        self.assertEqual(sender.sent[0][1], "Texto B")

    def test_no_ready_campaign_skips_the_invite(self) -> None:
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(13, 15)), "skipped")
        self.assertEqual(self._invite(sender, _at(13, 16)), "idle")
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "skipped")

    def test_missing_photo_moves_to_the_next_campaign(self) -> None:
        broken = self._campaign("A", text="Texto A")
        self._campaign("B", text="Texto B")
        (self.root / f"data/campaigns/{broken}/0.jpg").unlink()
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(13, 15)), "sent")
        self.assertEqual(sender.sent[0][1], "Texto B")

    def test_a_recent_message_holds_the_invite(self) -> None:
        self._campaign("A")
        sender = _Sender()
        now = _at(13, 15)
        quiet = (now - timedelta(seconds=10)).isoformat(timespec="seconds")
        self.assertEqual(self._invite(sender, now, quiet_since=quiet), "waiting")
        self.assertEqual(sender.sent, [])

    def test_disconnected_session_keeps_the_invite_pending(self) -> None:
        self._campaign("A")
        self.assertEqual(self._invite(_Sender(state="disconnected"), _at(13, 15)), "disconnected")
        self.assertEqual(self.campaigns.run_for(DAY, INVITE_FIXED).status, "pending")

    def test_session_down_retries_the_same_group(self) -> None:
        self._campaign("A")
        down = _Sender(fail=WahaError("sem sessão", session_down=True))
        self.assertEqual(self._invite(down, _at(13, 15)), "waiting")
        sender = _Sender()
        self.assertEqual(self._invite(sender, _at(13, 16)), "sent")
        self.assertEqual(sender.sent[0][0], GROUPS[0].chat_id)

    def test_next_day_avoids_the_last_photo(self) -> None:
        self._campaign("A", images=2)
        sender = _Sender()
        self._invite(sender, _at(13, 15))
        self._invite(sender, _at(13, 16))
        self._invite(sender, _at(13, 15, day=4))
        self.assertNotEqual(sender.sent[0][2], sender.sent[2][2])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_campaign_send.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'promo_livros.campaign_send'`

- [ ] **Step 3: Create `promo_livros/campaign_send.py`**

```python
"""Manda os convites das campanhas, fora dos horários da fila."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from random import Random

from promo_livros.board_send import CardSender
from promo_livros.board_store import BoardStore
from promo_livros.campaign_images import read_image
from promo_livros.campaign_rules import (
    INVITE_FIXED,
    INVITE_KINDS,
    InviteSettings,
    RotationEntry,
    fixed_invite_due,
    invite_settings,
    last_invite_clock,
    last_invite_due,
    pick_avoiding,
    rotation_order,
)
from promo_livros.campaign_store import CampaignRun, CampaignStore
from promo_livros.models import AppConfig
from promo_livros.send_gap import gap_open, latest_stamp
from promo_livros.waha import WahaError

logger = logging.getLogger("promo_livros.campaign_send")


@dataclass(frozen=True)
class InviteContent:
    image: bytes
    caption: str


def read_invite_settings(board: BoardStore) -> InviteSettings:
    return invite_settings(board.setting("invite_fixed_clock"), board.setting("invite_last_offset_minutes"))


def last_invite_clock_for(board: BoardStore, day: str, settings: InviteSettings) -> str:
    end = board.send_end_for(day, board.send_schedule().end)
    return last_invite_clock(board.last_queue_clock(day, end), end, settings.last_offset_minutes)


def publish_due_invite(
    config: AppConfig,
    board: BoardStore,
    campaigns: CampaignStore,
    sender: CardSender,
    *,
    root: Path,
    now: datetime,
    quiet_since: str | None = None,
    rng: Random | None = None,
) -> str:
    """Manda o convite vencido para o próximo grupo, com a mesma espera da fila."""
    if not board.sending_enabled():
        return "off"
    groups = config.whatsapp_groups
    if not groups:
        return "no_groups"
    run = _due_run(board, campaigns, now)
    if run is None:
        return "idle"
    if sender.connection_state() != "connected":
        return "disconnected"
    stamp = now.isoformat(timespec="seconds")
    locked = _locked_content(campaigns, root, run, rng or Random(), stamp)
    if locked is None:
        campaigns.skip_run(run.id)
        logger.warning("Convite %s de %s pulado: nenhuma campanha pronta.", run.kind, run.day)
        return "skipped"
    run, content = locked
    done = campaigns.sent_chat_ids(run.id)
    pending = [group for group in groups if group.chat_id not in done]
    if not pending:
        campaigns.mark_run_sent(run.id, stamp)
        return "sent"
    last_sent = latest_stamp((board.last_group_sent_at(), campaigns.last_sent_at(), quiet_since), now)
    if not gap_open(last_sent, now, board.send_schedule().group_gap_seconds):
        return "waiting"
    group = pending[0]
    try:
        message_id = sender.send_jpeg(group.chat_id, content.caption, content.image)
    except WahaError as exc:
        if exc.session_down:
            logger.warning("Convite para %s adiado: %s", group.name, exc)
            return "waiting"
        logger.warning("Convite para %s falhou: %s", group.name, exc)
        return "failed"
    campaigns.mark_group_sent(run.id, group.chat_id, message_id, stamp)
    logger.info("Convite %s enviado para %s.", run.kind, group.name)
    if {item.chat_id for item in groups} <= campaigns.sent_chat_ids(run.id):
        campaigns.mark_run_sent(run.id, stamp)
        logger.info("Convite %s saiu para os %s grupos.", run.kind, len(groups))
    return "sent"


def _due_run(board: BoardStore, campaigns: CampaignStore, now: datetime) -> CampaignRun | None:
    day = now.date().isoformat()
    now_clock = f"{now.hour:02d}:{now.minute:02d}"
    settings = read_invite_settings(board)
    for kind in INVITE_KINDS:
        run = campaigns.run_for(day, kind)
        if run.status == "sending":
            return run
        if run.status == "pending" and _is_due(kind, board, day, now_clock, settings):
            return run
    return None


def _is_due(kind: str, board: BoardStore, day: str, now_clock: str, settings: InviteSettings) -> bool:
    if kind == INVITE_FIXED:
        return fixed_invite_due(settings.fixed_clock, now_clock)
    end = board.send_end_for(day, board.send_schedule().end)
    return last_invite_due(
        now_clock,
        last_invite_clock_for(board, day, settings),
        queue_pending=board.has_pending_posts(day, end),
    )


def _locked_content(
    campaigns: CampaignStore,
    root: Path,
    run: CampaignRun,
    rng: Random,
    stamp: str,
) -> tuple[CampaignRun, InviteContent] | None:
    """Conteúdo já travado segue igual para os grupos que faltam. Senão, sorteia e trava."""
    if run.status == "sending":
        kept = _stored_content(campaigns, root, run)
        if kept is not None:
            return run, kept
    for campaign_id in _candidates(campaigns, run):
        picked = _pick_content(campaigns, root, campaign_id, rng)
        if picked is None:
            continue
        image_id, text_id, content = picked
        return campaigns.lock_content(run.id, campaign_id, image_id, text_id, stamp), content
    return None


def _stored_content(campaigns: CampaignStore, root: Path, run: CampaignRun) -> InviteContent | None:
    image = campaigns.image(run.image_id) if run.image_id else None
    text = campaigns.text(run.text_id) if run.text_id else None
    data = read_image(root, image.path) if image else None
    if data is None or text is None:
        logger.warning("A foto ou o texto do convite %s sumiu no meio do envio. Vou sortear de novo.", run.kind)
        return None
    return InviteContent(data, text.body)


def _candidates(campaigns: CampaignStore, run: CampaignRun) -> list[int]:
    ready = campaigns.ready_campaigns()
    order = rotation_order(
        [RotationEntry(item.id, item.position) for item in ready],
        campaigns.last_used_campaign(),
    )
    preferred = run.campaign_id if run.status == "sending" or run.manual else None
    if preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)
    return order


def _pick_content(
    campaigns: CampaignStore,
    root: Path,
    campaign_id: int,
    rng: Random,
) -> tuple[int, int, InviteContent] | None:
    texts = campaigns.texts(campaign_id)
    images = {image.id: image for image in campaigns.images(campaign_id)}
    if not texts or not images:
        return None
    last_image_id, last_text_id = campaigns.last_content(campaign_id)
    while images:
        image_id = pick_avoiding(list(images), last_image_id, rng)
        data = read_image(root, images[image_id].path)
        if data is not None:
            text_id = pick_avoiding([text.id for text in texts], last_text_id, rng)
            body = next(text.body for text in texts if text.id == text_id)
            return image_id, text_id, InviteContent(data, body)
        logger.warning("A foto %s da campanha %s não está no disco.", images[image_id].path, campaign_id)
        del images[image_id]
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_campaign_send.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/campaign_send.py tests/test_campaign_send.py
git commit -m "Send the day's invites to every group."
```

---

### Task 7: Loop de envio

**Files:**
- Modify: `scripts/enviar_fila.py`

- [ ] **Step 1: Add imports**

Junto dos outros imports de `promo_livros`:

```python
from promo_livros.campaign_send import publish_due_invite
from promo_livros.campaign_store import CampaignStore
from promo_livros.send_gap import latest_stamp
```

- [ ] **Step 2: Replace the body of `main()`**

```python
def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("promo_livros.board_send")
    logger.info("Envio da fila nova no ar.")
    previous = ""
    previous_invite = ""
    previous_poll = ""
    last_refresh = 0.0
    while True:
        try:
            config = load_config(ROOT / "config.yaml")
            store = BoardStore(config.sqlite_path)
            polls = PollStore(config.sqlite_path)
            campaigns = CampaignStore(config.sqlite_path)
            client = WahaClient.from_config(config)
            try:
                last_refresh = _refresh_links(config, store, logger, last_refresh)
                moment = datetime.now(zone(config.schedule.timezone))
                poll_quiet = polls.last_outbound_at()
                try:
                    invite_result = publish_due_invite(
                        config,
                        store,
                        campaigns,
                        client,
                        root=ROOT,
                        now=moment,
                        quiet_since=poll_quiet,
                    )
                except Exception:
                    logger.exception("O ciclo do convite falhou.")
                    invite_result = "failed"
                result = publish_due(
                    config,
                    store,
                    client,
                    root=ROOT,
                    now=moment,
                    quiet_since=latest_stamp((poll_quiet, campaigns.last_sent_at()), moment),
                )
                try:
                    poll_result = advance_polls(
                        polls,
                        client,
                        moment,
                        gap_seconds=store.send_schedule().group_gap_seconds,
                        other_sent_at=latest_stamp((store.last_group_sent_at(), campaigns.last_sent_at()), moment),
                    )
                except Exception:
                    logger.exception("O ciclo da enquete falhou.")
                    poll_result = "failed"
            finally:
                client.close()
                store.close()
                polls.close()
                campaigns.close()
        except Exception:
            logger.exception("O ciclo de envio falhou.")
            time.sleep(15)
            continue
        if result != previous:
            logger.info("Situação: %s.", result)
            previous = result
        if invite_result != previous_invite:
            logger.info("Convites: %s.", invite_result)
            previous_invite = invite_result
        if poll_result != previous_poll:
            logger.info("Enquetes: %s.", poll_result)
            previous_poll = poll_result
        failed = "failed" in {result, invite_result, poll_result}
        time.sleep(30 if failed else 5)
```

- [ ] **Step 3: Check it compiles and the suite still passes**

Run: `python -m py_compile scripts/enviar_fila.py; python -m pytest tests/test_board_send.py tests/test_campaign_send.py -q`
Expected: sem saída do `py_compile`; testes PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/enviar_fila.py
git commit -m "Run the invites in the send loop before the queue."
```

---

### Task 8: Leitura de multipart

**Files:**
- Create: `promo_livros/multipart_form.py`
- Test: `tests/test_multipart_form.py`

- [ ] **Step 1: Write the failing test**

`tests/test_multipart_form.py`:

```python
import unittest

from promo_livros.multipart_form import parse_multipart

BOUNDARY = "----promoBoundary42"


def _body(parts: list[tuple[str, str | None, bytes]]) -> bytes:
    chunks = []
    for name, filename, data in parts:
        disposition = f'form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        chunks.append(
            f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
            + data
            + b"\r\n"
        )
    return b"".join(chunks) + f"--{BOUNDARY}--\r\n".encode()


class MultipartTests(unittest.TestCase):
    def test_fields_and_binary_files(self) -> None:
        binary = bytes(range(256)) * 4 + b"\r\n--not-the-boundary\r\n"
        body = _body([
            ("acao", None, "enviar".encode()),
            ("fotos", "a.png", binary),
            ("fotos", "b.jpg", b"segunda"),
            ("fotos", "", b""),
        ])
        fields, files = parse_multipart(f"multipart/form-data; boundary={BOUNDARY}", body)
        self.assertEqual(fields, {"acao": ["enviar"]})
        self.assertEqual(files["fotos"], [binary, b"segunda"])

    def test_quoted_boundary(self) -> None:
        body = _body([("fotos", "a.jpg", b"x")])
        _fields, files = parse_multipart(f'multipart/form-data; boundary="{BOUNDARY}"', body)
        self.assertEqual(files["fotos"], [b"x"])

    def test_other_content_types_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_multipart("application/x-www-form-urlencoded", b"a=1")
        with self.assertRaises(ValueError):
            parse_multipart("multipart/form-data", b"")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_multipart_form.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'promo_livros.multipart_form'`

- [ ] **Step 3: Create `promo_livros/multipart_form.py`**

```python
"""Lê multipart/form-data do envio de fotos. O módulo cgi não existe mais no Python 3.13."""
from __future__ import annotations

import re

_BOUNDARY = re.compile(r'boundary=(?:"([^"]+)"|([^;\s]+))', re.IGNORECASE)
_NAME = re.compile(r'(?:^|;)\s*name="([^"]*)"', re.IGNORECASE)
_FILENAME = re.compile(r'(?:^|;)\s*filename="([^"]*)"', re.IGNORECASE)


def parse_multipart(content_type: str, body: bytes) -> tuple[dict[str, list[str]], dict[str, list[bytes]]]:
    """Campos de texto e arquivos por nome. Arquivo vazio (campo sem seleção) fica de fora."""
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("O formulário precisa ser multipart/form-data.")
    match = _BOUNDARY.search(content_type)
    if match is None:
        raise ValueError("O formulário não tem boundary.")
    delimiter = b"--" + (match.group(1) or match.group(2)).encode("latin-1")
    fields: dict[str, list[str]] = {}
    files: dict[str, list[bytes]] = {}
    for chunk in body.split(delimiter)[1:]:
        if chunk.startswith(b"--"):
            break
        head, separator, data = chunk.partition(b"\r\n\r\n")
        if not separator:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        disposition = _disposition(head.decode("utf-8", errors="replace"))
        name_match = _NAME.search(disposition)
        if name_match is None:
            continue
        name = name_match.group(1)
        if _FILENAME.search(disposition) is not None:
            if data:
                files.setdefault(name, []).append(data)
        else:
            fields.setdefault(name, []).append(data.decode("utf-8", errors="replace"))
    return fields, files


def _disposition(head: str) -> str:
    for line in head.split("\r\n"):
        key, _, value = line.partition(":")
        if key.strip().lower() == "content-disposition":
            return value.strip()
    return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_multipart_form.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/multipart_form.py tests/test_multipart_form.py
git commit -m "Read photo uploads without the cgi module."
```

---

### Task 9: Páginas de campanha

**Files:**
- Modify: `promo_livros/dashboard_pages.py` (`_nav` e nova `render_page`)
- Create: `promo_livros/campaign_pages.py`
- Test: `tests/test_campaign_pages.py`

- [ ] **Step 1: Write the failing test**

`tests/test_campaign_pages.py`:

```python
import unittest

from promo_livros.campaign_pages import (
    InviteCard,
    render_campaign_detail,
    render_campaign_list,
    render_invite_cards,
)
from promo_livros.campaign_rules import INVITE_FIXED, INVITE_LAST, InviteSettings
from promo_livros.campaign_store import Campaign, CampaignImage, CampaignText


class CampaignPageTests(unittest.TestCase):
    def test_list_escapes_names_and_marks_incomplete(self) -> None:
        html = render_campaign_list(
            [Campaign(1, "Terror <b>", True, 1, 0, 2), Campaign(2, "Kindle", True, 2, 1, 1)],
            InviteSettings("13:15", 10),
            notice="Salvo & pronto",
        )
        self.assertIn("Terror &lt;b&gt;", html)
        self.assertNotIn("Terror <b>", html)
        self.assertIn("Incompleta", html)
        self.assertIn("Pronta", html)
        self.assertIn('value="13:15"', html)
        self.assertIn('action="/campanhas/config"', html)
        self.assertIn("Salvo &amp; pronto", html)
        self.assertIn('href="/campanhas" aria-current="page"', html)

    def test_detail_has_upload_form_and_escaped_texts(self) -> None:
        html = render_campaign_detail(
            Campaign(3, "Kindle", True, 1, 1, 1),
            [CampaignImage(9, 3, "data/campaigns/3/a.jpg")],
            [CampaignText(4, 3, "<script>x</script>")],
            notice=None,
        )
        self.assertIn('action="/campanhas/3/fotos"', html)
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn('src="/campanhas/foto/9.jpg"', html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)
        self.assertNotIn("<script>x</script>", html)
        self.assertIn('maxlength="1024"', html)

    def test_invite_cards_offer_the_ready_campaigns(self) -> None:
        ready = [Campaign(1, "A", True, 1, 1, 1), Campaign(2, "B", True, 2, 1, 1)]
        html = render_invite_cards(
            [
                InviteCard(INVITE_FIXED, "Convite das 13:15", "Aguardando", None, "A", True),
                InviteCard(INVITE_LAST, "Convite final ≈ 22:10", "Aguardando", 2, "B", True),
            ],
            ready,
        )
        self.assertIn("Rodízio: A", html)
        self.assertIn('<option value="2" selected>B</option>', html)
        self.assertIn('action="/hoje/convite"', html)
        self.assertIn('href="/campanhas"', html)

    def test_sent_invite_shows_the_campaign_without_a_form(self) -> None:
        html = render_invite_cards(
            [InviteCard(INVITE_FIXED, "Convite das 13:15", "Enviado", None, "A", False)],
            [],
        )
        self.assertIn("Enviado", html)
        self.assertNotIn("/hoje/convite", html)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_campaign_pages.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'promo_livros.campaign_pages'`

- [ ] **Step 3: Add the menu link and `render_page` in `dashboard_pages.py`**

Em `_nav`, entre `("Assinaturas", "/assinaturas")` e `("Configurações", "/configuracoes")`:

```python
        ("Campanhas", "/campanhas"),
```

Logo antes de `def _page(`:

```python
def render_page(title: str, body: str, *, extra_style: str = "") -> str:
    return _page(title, body, nav=True, extra_style=extra_style)
```

- [ ] **Step 4: Create `promo_livros/campaign_pages.py`**

```python
"""HTML da /campanhas e do cartão de convites da /hoje."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

from promo_livros.campaign_rules import MAX_LAST_OFFSET_MINUTES, MIN_LAST_OFFSET_MINUTES, InviteSettings
from promo_livros.campaign_store import MAX_NAME_LENGTH, MAX_TEXT_LENGTH, Campaign, CampaignImage, CampaignText
from promo_livros.dashboard_pages import render_page

_STYLE = """
.campaigns { display: grid; gap: 8px; margin: 16px 0; }
.campaigns .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--card); }
.campaigns .row form { margin-left: auto; display: flex; gap: 6px; }
.thumbs { display: flex; flex-wrap: wrap; gap: 12px; margin: 12px 0; }
.thumbs figure { margin: 0; display: grid; gap: 6px; }
.thumbs img { border-radius: 8px; object-fit: cover; height: 160px; width: auto; }
.texts form { display: grid; gap: 6px; margin-bottom: 16px; }
"""


@dataclass(frozen=True)
class InviteCard:
    kind: str
    title: str
    status_label: str
    chosen_id: int | None
    campaign_name: str | None
    can_change: bool


def render_campaign_list(campaigns: list[Campaign], settings: InviteSettings, *, notice: str | None) -> str:
    rows = "".join(_list_row(campaign) for campaign in campaigns)
    listing = f'<div class="campaigns">{rows}</div>' if rows else '<p class="muted">Nenhuma campanha ainda.</p>'
    body = f"""
    <main>
      <h1>Campanhas</h1>
      {_notice(notice)}
      <section class="panel-card">
        <h2>Horários dos convites</h2>
        <form method="post" action="/campanhas/config">
          <label>Convite no horário
            <input name="fixo" value="{escape(settings.fixed_clock or "")}" placeholder="13:15" pattern="[0-2][0-9]:[0-5][0-9]">
          </label>
          <label>Convite final, minutos depois do último post
            <input name="final" type="number" min="{MIN_LAST_OFFSET_MINUTES}" max="{MAX_LAST_OFFSET_MINUTES}" required value="{settings.last_offset_minutes}">
          </label>
          <button type="submit">Salvar</button>
        </form>
        <p class="muted">Deixe o horário vazio para não mandar o convite do meio do dia. Ele precisa ficar fora dos horários da fila e só sai até 1 hora depois do horário. O convite final sai depois do último post da fila; sem fila, depois do fim da janela.</p>
      </section>
      {listing}
      <h2>Nova campanha</h2>
      <form method="post" action="/campanhas/acao">
        <input type="hidden" name="acao" value="criar">
        <label>Nome <input name="nome" maxlength="{MAX_NAME_LENGTH}" required></label>
        <button type="submit">Criar</button>
      </form>
    </main>
    """
    return render_page("Campanhas", body, extra_style=_STYLE)


def render_campaign_detail(
    campaign: Campaign,
    images: list[CampaignImage],
    texts: list[CampaignText],
    *,
    notice: str | None,
) -> str:
    toggle = ("desativar", "Desativar") if campaign.active else ("ativar", "Ativar")
    thumbs = "".join(
        f"""
        <figure>
          <img src="/campanhas/foto/{image.id}.jpg" alt="" loading="lazy">
          <form method="post" action="/campanhas/acao">
            <input type="hidden" name="id" value="{campaign.id}">
            <input type="hidden" name="foto" value="{image.id}">
            <button class="ghost" name="acao" value="foto_apagar" type="submit">Remover</button>
          </form>
        </figure>"""
        for image in images
    )
    text_forms = "".join(
        f"""
        <form method="post" action="/campanhas/acao">
          <input type="hidden" name="id" value="{campaign.id}">
          <input type="hidden" name="texto" value="{text.id}">
          <textarea name="corpo" rows="5" maxlength="{MAX_TEXT_LENGTH}" required>{escape(text.body)}</textarea>
          <div>
            <button name="acao" value="texto_editar" type="submit">Salvar texto</button>
            <button class="ghost" name="acao" value="texto_apagar" type="submit" formnovalidate>Remover</button>
          </div>
        </form>"""
        for text in texts
    )
    body = f"""
    <main>
      <p><a href="/campanhas">← Campanhas</a></p>
      <h1>{escape(campaign.name)}</h1>
      {_notice(notice)}
      <form method="post" action="/campanhas/acao">
        <input type="hidden" name="id" value="{campaign.id}">
        <label>Nome <input name="nome" value="{escape(campaign.name)}" maxlength="{MAX_NAME_LENGTH}" required></label>
        <button name="acao" value="renomear" type="submit">Renomear</button>
        <button class="ghost" name="acao" value="{toggle[0]}" type="submit" formnovalidate>{toggle[1]}</button>
      </form>
      <h2>Fotos</h2>
      <form method="post" action="/campanhas/{campaign.id}/fotos" enctype="multipart/form-data">
        <input type="file" name="fotos" accept="image/jpeg,image/png,image/webp" multiple required>
        <button type="submit">Enviar fotos</button>
      </form>
      <p class="muted">JPEG, PNG ou WebP, até 8 MB cada. A foto vai como JPEG, sem os dados da câmera.</p>
      <div class="thumbs">{thumbs or '<p class="muted">Nenhuma foto ainda.</p>'}</div>
      <h2>Textos</h2>
      <p class="muted">Na hora do envio sai uma foto e um texto desta lista, evitando repetir o último.</p>
      <div class="texts">
        {text_forms}
        <form method="post" action="/campanhas/acao">
          <input type="hidden" name="id" value="{campaign.id}">
          <textarea name="corpo" rows="5" maxlength="{MAX_TEXT_LENGTH}" required placeholder="Entre no nosso grupo de ..."></textarea>
          <div><button name="acao" value="texto_novo" type="submit">Adicionar texto</button></div>
        </form>
      </div>
      <form method="post" action="/campanhas/acao" onsubmit="return confirm('Apagar a campanha, as fotos e os textos?')">
        <input type="hidden" name="id" value="{campaign.id}">
        <button class="ghost" name="acao" value="apagar" type="submit">Apagar campanha</button>
      </form>
    </main>
    """
    return render_page("Campanhas", body, extra_style=_STYLE)


def render_invite_cards(cards: list[InviteCard], ready: list[Campaign]) -> str:
    blocks = "".join(_invite_block(card, ready) for card in cards)
    return f"""
    <section class="panel-card" id="convites">
      <h2>Convites para outros grupos</h2>
      {blocks}
      <p><a href="/campanhas">Editar campanhas</a></p>
    </section>
    """


def _invite_block(card: InviteCard, ready: list[Campaign]) -> str:
    if card.can_change:
        rotation = f"Rodízio: {card.campaign_name}" if card.chosen_id is None and card.campaign_name else "Rodízio"
        options = [f'<option value="">{escape(rotation)}</option>']
        for campaign in ready:
            selected = " selected" if campaign.id == card.chosen_id else ""
            options.append(f'<option value="{campaign.id}"{selected}>{escape(campaign.name)}</option>')
        detail = f"""
        <form method="post" action="/hoje/convite">
          <input type="hidden" name="tipo" value="{escape(card.kind)}">
          <select name="campanha" aria-label="Campanha do {escape(card.title)}">{''.join(options)}</select>
          <button class="ghost" type="submit">Trocar</button>
        </form>"""
    else:
        detail = f'<p class="muted">{escape(card.campaign_name or "Sem campanha")}</p>'
    return f"""
    <div class="invite">
      <p><strong>{escape(card.title)}</strong> <span class="pill neutral">{escape(card.status_label)}</span></p>
      {detail}
    </div>
    """


def _list_row(campaign: Campaign) -> str:
    if not campaign.active:
        label, kind = "Desativada", "neutral"
    elif campaign.ready:
        label, kind = "Pronta", "ok"
    else:
        label, kind = "Incompleta", "wait"
    return f"""
    <article class="row">
      <a href="/campanhas/{campaign.id}"><strong>{escape(campaign.name)}</strong></a>
      <span class="muted">{campaign.image_count} fotos · {campaign.text_count} textos</span>
      <span class="pill {kind}">{label}</span>
      <form method="post" action="/campanhas/acao">
        <input type="hidden" name="id" value="{campaign.id}">
        <button class="ghost" name="acao" value="subir" type="submit" aria-label="Subir">↑</button>
        <button class="ghost" name="acao" value="descer" type="submit" aria-label="Descer">↓</button>
      </form>
    </article>
    """


def _notice(notice: str | None) -> str:
    return f'<p class="alert" role="status">{escape(notice)}</p>' if notice else ""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_campaign_pages.py tests/test_dashboard_http.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add promo_livros/dashboard_pages.py promo_livros/campaign_pages.py tests/test_campaign_pages.py
git commit -m "Draw the campaign pages and the invite card."
```

---

### Task 10: Callbacks do painel

**Files:**
- Create: `promo_livros/campaign_panel.py`
- Test: `tests/test_campaign_panel.py`

- [ ] **Step 1: Write the failing test**

`tests/test_campaign_panel.py`:

```python
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from PIL import Image

from promo_livros.board_store import BoardStore
from promo_livros.campaign_panel import campaign_callbacks
from promo_livros.campaign_rules import INVITE_FIXED
from promo_livros.campaign_store import CampaignStore
from promo_livros.models import WhatsAppGroup
from promo_livros.send_schedule import parse_schedule

ZONE = ZoneInfo("America/Sao_Paulo")
DAY = "2026-11-03"
GROUPS = (WhatsAppGroup("Black Livros 01", "120363430990609445@g.us"),)


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), (0, 0, 0)).save(buffer, "PNG")
    return buffer.getvalue()


class CampaignPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.board = BoardStore(self.root / "board.sqlite")
        self.board.save_send_schedule(parse_schedule("08:00", "22:00", "40", "45"))
        self.campaigns = CampaignStore(self.root / "board.sqlite")
        self.panel = campaign_callbacks(
            SimpleNamespace(whatsapp_groups=GROUPS),
            self.board,
            self.campaigns,
            root=self.root,
            current_day=lambda: DAY,
            now=lambda: datetime(2026, 11, 3, 12, 0, tzinfo=ZONE),
        )

    def tearDown(self) -> None:
        self.campaigns.close()
        self.board.close()
        self.folder.cleanup()

    def _ready(self, name: str) -> int:
        campaign_id = self.campaigns.create(name)
        self.panel["upload"](campaign_id, [_png()])
        self.campaigns.add_text(campaign_id, f"Texto {name}")
        return campaign_id

    def test_settings_refuse_a_queue_clock(self) -> None:
        self.assertEqual(self.panel["save_settings"]({"fixo": ["08:40"], "final": ["10"]}), "/campanhas")
        self.assertIsNone(self.board.setting("invite_fixed_clock"))
        self.assertIn("horário da fila", self.panel["page"]())
        self.panel["save_settings"]({"fixo": ["13:15"], "final": ["20"]})
        self.assertEqual(self.board.setting("invite_fixed_clock"), "13:15")
        self.assertEqual(self.board.setting("invite_last_offset_minutes"), "20")

    def test_create_add_text_and_rename(self) -> None:
        target = self.panel["action"]({"acao": ["criar"], "nome": ["Terror"]})
        campaign_id = int(target.rsplit("/", 1)[1])
        self.panel["action"]({"acao": ["texto_novo"], "id": [str(campaign_id)], "corpo": ["Entre!"]})
        self.panel["action"]({"acao": ["renomear"], "id": [str(campaign_id)], "nome": ["Terror BR"]})
        campaign = self.campaigns.campaign(campaign_id)
        self.assertEqual((campaign.name, campaign.text_count), ("Terror BR", 1))

    def test_cannot_touch_content_of_another_campaign(self) -> None:
        first = self._ready("A")
        second = self._ready("B")
        foreign_text = self.campaigns.texts(second)[0]
        foreign_image = self.campaigns.images(second)[0]
        self.panel["action"]({"acao": ["texto_apagar"], "id": [str(first)], "texto": [str(foreign_text.id)]})
        self.panel["action"]({"acao": ["foto_apagar"], "id": [str(first)], "foto": [str(foreign_image.id)]})
        self.assertIsNotNone(self.campaigns.text(foreign_text.id))
        self.assertIsNotNone(self.campaigns.image(foreign_image.id))

    def test_upload_keeps_the_good_files_and_names_the_bad_ones(self) -> None:
        campaign_id = self.campaigns.create("A")
        self.panel["upload"](campaign_id, [_png(), b"lixo"])
        self.assertEqual(len(self.campaigns.images(campaign_id)), 1)
        page = self.panel["detail"](campaign_id)
        self.assertIn("1 foto salva.", page)
        self.assertIn("Arquivo 2", page)
        image = self.campaigns.images(campaign_id)[0]
        self.assertIsNotNone(self.panel["image"](image.id))

    def test_delete_removes_the_folder(self) -> None:
        campaign_id = self._ready("A")
        self.panel["action"]({"acao": ["apagar"], "id": [str(campaign_id)]})
        self.assertIsNone(self.campaigns.campaign(campaign_id))
        self.assertFalse((self.root / "data" / "campaigns" / str(campaign_id)).exists())

    def test_invite_cards_predict_the_rotation(self) -> None:
        self.board.put_setting("invite_fixed_clock", "13:15")
        self._ready("A")
        self._ready("B")
        html = self.panel["invites"]()
        self.assertIn("Convite das 13:15", html)
        self.assertIn("Rodízio: A", html)
        self.assertIn("Rodízio: B", html)
        self.assertIn("Convite final ≈ 22:10", html)

    def test_fixed_off_shows_as_off(self) -> None:
        self.assertIn("Desligado", self.panel["invites"]())

    def test_choose_only_while_pending(self) -> None:
        campaign_id = self._ready("A")
        notice = self.panel["choose"]({"tipo": [INVITE_FIXED], "campanha": [str(campaign_id)]})
        self.assertEqual(notice, "Campanha do convite trocada.")
        run = self.campaigns.run_for(DAY, INVITE_FIXED)
        self.campaigns.mark_run_sent(run.id, "2026-11-03T13:15:00-03:00")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_FIXED], "campanha": [""]}), "Esse convite já saiu.")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_FIXED], "campanha": ["999"]}), "Essa campanha não está pronta.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_campaign_panel.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'promo_livros.campaign_panel'`

- [ ] **Step 3: Create `promo_livros/campaign_panel.py`**

```python
"""Telas de campanha e cartão de convites, no mesmo processo do painel."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from promo_livros.board_store import BoardStore
from promo_livros.campaign_images import ImageUploadError, read_image, remove_campaign_dir, remove_image, save_upload
from promo_livros.campaign_pages import InviteCard, render_campaign_detail, render_campaign_list, render_invite_cards
from promo_livros.campaign_rules import (
    INVITE_FIXED,
    INVITE_KINDS,
    InviteSettings,
    RotationEntry,
    fixed_invite_missed,
    parse_fixed_clock,
    parse_last_offset,
    rotation_order,
)
from promo_livros.campaign_send import last_invite_clock_for, read_invite_settings
from promo_livros.campaign_store import CampaignError, CampaignRun, CampaignStore
from promo_livros.models import AppConfig
from promo_livros.send_schedule import slot_clocks


def campaign_callbacks(
    config: AppConfig,
    board: BoardStore,
    campaigns: CampaignStore,
    *,
    root: Path,
    current_day: Callable[[], str],
    now: Callable[[], datetime],
) -> dict:
    holder: dict[str, str | None] = {"notice": None}

    def take_notice() -> str | None:
        notice = holder["notice"]
        holder["notice"] = None
        return notice

    def page() -> str:
        return render_campaign_list(campaigns.campaigns(), read_invite_settings(board), notice=take_notice())

    def detail(campaign_id: int) -> str | None:
        campaign = campaigns.campaign(campaign_id)
        if campaign is None:
            return None
        return render_campaign_detail(
            campaign,
            campaigns.images(campaign_id),
            campaigns.texts(campaign_id),
            notice=take_notice(),
        )

    def save_settings(form: dict[str, list[str]]) -> str:
        taken = set(slot_clocks(board.send_schedule())) | {post.clock for post in board.posts_for(current_day())}
        try:
            fixed = parse_fixed_clock(_first(form, "fixo"), taken)
            offset = parse_last_offset(_first(form, "final"))
        except ValueError as exc:
            holder["notice"] = str(exc)
            return "/campanhas"
        board.put_setting("invite_fixed_clock", fixed or "")
        board.put_setting("invite_last_offset_minutes", str(offset))
        holder["notice"] = "Horários dos convites salvos."
        return "/campanhas"

    def action(form: dict[str, list[str]]) -> str:
        acao = _first(form, "acao")
        campaign_id = _int(form, "id")
        try:
            if acao == "criar":
                new_id = campaigns.create(_first(form, "nome"))
                holder["notice"] = "Campanha criada. Agora mande as fotos e escreva os textos."
                return f"/campanhas/{new_id}"
            if campaigns.campaign(campaign_id) is None:
                holder["notice"] = "Campanha não encontrada."
                return "/campanhas"
            if acao in {"subir", "descer"}:
                campaigns.move(campaign_id, -1 if acao == "subir" else 1)
                return "/campanhas"
            if acao == "apagar":
                campaigns.delete(campaign_id)
                remove_campaign_dir(root, campaign_id)
                holder["notice"] = "Campanha apagada."
                return "/campanhas"
            holder["notice"] = _edit(campaign_id, acao, form)
        except CampaignError as exc:
            holder["notice"] = str(exc)
        return f"/campanhas/{campaign_id}" if campaign_id else "/campanhas"

    def _edit(campaign_id: int, acao: str, form: dict[str, list[str]]) -> str:
        if acao == "renomear":
            campaigns.rename(campaign_id, _first(form, "nome"))
            return "Nome salvo."
        if acao in {"ativar", "desativar"}:
            campaigns.set_active(campaign_id, acao == "ativar")
            return "Campanha ativada." if acao == "ativar" else "Campanha desativada. Ela sai do rodízio."
        if acao == "texto_novo":
            campaigns.add_text(campaign_id, _raw(form, "corpo"))
            return "Texto adicionado."
        if acao in {"texto_editar", "texto_apagar"}:
            text = campaigns.text(_int(form, "texto"))
            if text is None or text.campaign_id != campaign_id:
                return "Texto não encontrado."
            if acao == "texto_editar":
                campaigns.update_text(text.id, _raw(form, "corpo"))
                return "Texto salvo."
            campaigns.delete_text(text.id)
            return "Texto removido."
        if acao == "foto_apagar":
            image = campaigns.image(_int(form, "foto"))
            if image is None or image.campaign_id != campaign_id:
                return "Foto não encontrada."
            removed = campaigns.delete_image(image.id)
            if removed:
                remove_image(root, removed)
            return "Foto removida."
        return "Ação desconhecida."

    def upload(campaign_id: int, files: list[bytes]) -> str:
        if campaigns.campaign(campaign_id) is None:
            holder["notice"] = "Campanha não encontrada."
            return "/campanhas"
        if not files:
            holder["notice"] = "Escolha ao menos uma foto."
            return f"/campanhas/{campaign_id}"
        saved = 0
        refused: list[str] = []
        for index, payload in enumerate(files, start=1):
            try:
                path = save_upload(root, campaign_id, payload)
            except ImageUploadError as exc:
                refused.append(f"Arquivo {index}: {exc}")
                continue
            campaigns.add_image(campaign_id, path)
            saved += 1
        summary = "1 foto salva." if saved == 1 else f"{saved} fotos salvas."
        holder["notice"] = " ".join([summary, *refused])
        return f"/campanhas/{campaign_id}"

    def image(image_id: int) -> bytes | None:
        found = campaigns.image(image_id)
        return read_image(root, found.path) if found else None

    def invites() -> str:
        day = current_day()
        now_clock = now().strftime("%H:%M")
        settings = read_invite_settings(board)
        ready = campaigns.ready_campaigns()
        entries = {item.id: RotationEntry(item.id, item.position) for item in ready}
        names = {item.id: item.name for item in campaigns.campaigns()}
        last_used = campaigns.last_used_campaign()
        total = len(config.whatsapp_groups)
        cards: list[InviteCard] = []
        for kind in INVITE_KINDS:
            run = campaigns.run_for(day, kind)
            title = _invite_title(kind, settings, day)
            if run.status != "pending":
                label = _run_label(run, campaigns, total)
                cards.append(InviteCard(kind, title, label, None, names.get(run.campaign_id), False))
                continue
            if kind == INVITE_FIXED and settings.fixed_clock is None:
                cards.append(InviteCard(kind, title, "Desligado", None, None, False))
                continue
            if kind == INVITE_FIXED and fixed_invite_missed(settings.fixed_clock, now_clock):
                cards.append(InviteCard(kind, title, "Não saiu hoje", None, None, False))
                continue
            order = rotation_order(list(entries.values()), last_used)
            chosen = run.campaign_id if run.manual and run.campaign_id in entries else None
            predicted = chosen if chosen is not None else (order[0] if order else None)
            if predicted is not None:
                last_used = entries[predicted]
            cards.append(InviteCard(kind, title, "Aguardando", chosen, names.get(predicted), True))
        return render_invite_cards(cards, ready)

    def _invite_title(kind: str, settings: InviteSettings, day: str) -> str:
        if kind == INVITE_FIXED:
            return f"Convite das {settings.fixed_clock}" if settings.fixed_clock else "Convite no horário"
        return f"Convite final ≈ {last_invite_clock_for(board, day, settings)}"

    def choose(form: dict[str, list[str]]) -> str:
        kind = _first(form, "tipo")
        if kind not in INVITE_KINDS:
            return "Convite desconhecido."
        raw = _first(form, "campanha")
        campaign_id = int(raw) if raw.isdigit() else None
        if campaign_id is not None and campaign_id not in {item.id for item in campaigns.ready_campaigns()}:
            return "Essa campanha não está pronta."
        if not campaigns.set_manual_campaign(current_day(), kind, campaign_id):
            return "Esse convite já saiu."
        return "Campanha do convite trocada." if campaign_id is not None else "O convite volta para o rodízio."

    return {
        "page": page,
        "detail": detail,
        "save_settings": save_settings,
        "action": action,
        "upload": upload,
        "image": image,
        "invites": invites,
        "choose": choose,
    }


def _run_label(run: CampaignRun, campaigns: CampaignStore, total: int) -> str:
    if run.status == "sent":
        return "Enviado"
    if run.status == "skipped":
        return "Pulado: nenhuma campanha pronta"
    return f"Enviando {len(campaigns.sent_chat_ids(run.id))}/{total}"


def _first(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name, [])
    return values[0].strip() if values else ""


def _raw(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name, [])
    return values[0] if values else ""


def _int(form: dict[str, list[str]], name: str) -> int:
    raw = _first(form, name)
    return int(raw) if raw.isdigit() else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_campaign_panel.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/campaign_panel.py tests/test_campaign_panel.py
git commit -m "Wire the campaign screens and invite choices."
```

---

### Task 11: Rotas e /hoje

**Files:**
- Modify: `promo_livros/dashboard.py`
- Modify: `promo_livros/dashboard_pages.py` (`render_board`)
- Modify: `promo_livros/dashboard_belt.py` (`page_body`, menu)
- Test: `tests/test_dashboard_http.py`

- [ ] **Step 1: Write the failing tests**

Adicionar em `tests/test_dashboard_http.py`, antes de `def _post_raw(`:

```python
class CampaignRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple] = []

        def upload(campaign_id: int, files: list[bytes]) -> str:
            self.calls.append(("upload", campaign_id, files))
            return f"/campanhas/{campaign_id}"

        def choose(form: dict[str, list[str]]) -> str:
            self.calls.append(("choose", form.get("tipo")))
            return "ok"

        campaigns = {
            "page": lambda: "Lista de campanhas",
            "detail": lambda campaign_id: f"Detalhe {campaign_id}" if campaign_id == 3 else None,
            "save_settings": lambda form: "/campanhas",
            "action": lambda form: "/campanhas",
            "upload": upload,
            "image": lambda image_id: b"\xff\xd8jpeg" if image_id == 5 else None,
            "invites": lambda: "",
            "choose": choose,
        }
        self.app = DashboardApp(
            username="ana",
            password="certa",
            sessions=SessionStore(),
            today=lambda: (None, None),
            whatsapp=lambda: ("connected", None),
            qr_png=lambda: b"",
            group_form=lambda: ([], True, None),
            save_groups=lambda _ids: None,
            campaigns=campaigns,
        )
        DashboardHandler.app = self.app
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.token = self.app.sessions.login("ana", "certa", "ana", "certa")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def test_pages_need_login(self) -> None:
        self.assertIn("Entrar", _get(self.server, "/campanhas"))
        self.assertIn("Lista de campanhas", _get(self.server, "/campanhas", cookie=self.token))
        self.assertIn("Detalhe 3", _get(self.server, "/campanhas/3", cookie=self.token))

    def test_photo_route_serves_jpeg(self) -> None:
        status, content_type, payload = _get_raw(self.server, "/campanhas/foto/5.jpg", self.token)
        self.assertEqual((status, content_type), (200, "image/jpeg"))
        self.assertEqual(payload, b"\xff\xd8jpeg")
        with self.assertRaises(HTTPError):
            _get_raw(self.server, "/campanhas/foto/6.jpg", self.token)

    def test_upload_reads_the_files_and_goes_back_to_the_campaign(self) -> None:
        boundary = "----b"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="fotos"; filename="a.png"\r\n\r\n'.encode()
            + b"\x89PNG\r\nbytes"
            + f"\r\n--{boundary}--\r\n".encode()
        )
        headers = {
            "Cookie": f"promo_livros_session={self.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        }
        status, _type, payload = _post_raw(self.server, "/campanhas/3/fotos", headers=headers, data=body)
        self.assertEqual(status, 200)
        self.assertIn(b"Detalhe 3", payload)
        self.assertEqual(self.calls, [("upload", 3, [b"\x89PNG\r\nbytes"])])

    def test_upload_without_login_does_nothing(self) -> None:
        body = b"--b--\r\n"
        headers = {"Content-Type": "multipart/form-data; boundary=b", "Content-Length": str(len(body))}
        _status, _type, payload = _post_raw(self.server, "/campanhas/3/fotos", headers=headers, data=body)
        self.assertIn(b"Entrar", payload)
        self.assertEqual(self.calls, [])

    def test_choose_invite_from_today(self) -> None:
        self.app.board = None
        body = b"tipo=fixed&campanha=2"
        headers = {
            "Cookie": f"promo_livros_session={self.token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
        }
        _post_raw(self.server, "/hoje/convite", headers=headers, data=body)
        self.assertEqual(self.calls, [("choose", ["fixed"])])
```

E em `PageTests`, um teste do cartão na `/hoje`:

```python
    def test_board_shows_the_invite_card_and_the_campaigns_link(self) -> None:
        from promo_livros.dashboard_pages import render_board
        from promo_livros.send_schedule import default_schedule

        html = render_board(
            "2026-11-03",
            [],
            notice=None,
            sending=True,
            schedule=default_schedule(),
            invites='<section id="convites">Convites aqui</section>',
        )
        self.assertIn("Convites aqui", html)
        self.assertIn('href="/campanhas">Campanhas</a>', html)
        self.assertLess(html.index('id="convites"'), html.index('id="regras"'))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dashboard_http.py -v -k "Campaign or invite_card"`
Expected: FAIL com `TypeError: DashboardApp.__init__() got an unexpected keyword argument 'campaigns'`

- [ ] **Step 3: Pass `invites` through the board page**

Em `promo_livros/dashboard_pages.py`, `render_board`: novo parâmetro `invites: str = "",` depois de `arquivo`, e repassar `invites=invites,` na chamada de `page_body`.

Em `promo_livros/dashboard_belt.py`, `page_body`: novo parâmetro `invites: str = "",` depois de `arquivo`. No `<aside class="side">`, antes de `{_rules_html(schedule, repeat_days)}`:

```python
      {invites}
```

No `<nav class="segments">` de `page_body`, entre Assinaturas e Configurações:

```html
    <a href="/campanhas">Campanhas</a>
```

- [ ] **Step 4: Routes in `dashboard.py`**

Constante, junto das outras:

```python
MAX_CAMPAIGN_UPLOAD_BODY = 40 * 1024 * 1024
```

Import no topo:

```python
from promo_livros.multipart_form import parse_multipart
```

Campo novo no fim de `DashboardApp`:

```python
    campaigns: dict | None = None
```

Em `do_GET`, logo depois do bloco `if path == "/configuracoes" and self.app.settings_page:`:

```python
        if self.app.campaigns is not None and self._campaign_get(path):
            return
```

Em `do_POST`, logo depois do bloco `if path == "/curadoria/fila/csv":` (antes de `form = _form(...)`):

```python
        upload = re.fullmatch(r"/campanhas/(\d+)/fotos", path)
        if upload and self.app.campaigns is not None:
            self._campaign_upload(int(upload.group(1)))
            return
```

Em `do_POST`, logo depois do bloco `poll_action` (já depois da checagem de login):

```python
        if self.app.campaigns is not None:
            if path == "/campanhas/config":
                self._redirect(self.app.campaigns["save_settings"](form), self._token())
                return
            if path == "/campanhas/acao":
                self._redirect(self.app.campaigns["action"](form), self._token())
                return
            if path == "/hoje/convite":
                self.app.campaigns["choose"](form)
                self._redirect("/hoje", self._token())
                return
```

Métodos novos em `DashboardHandler`, depois de `_card`:

```python
    def _campaign_get(self, path: str) -> bool:
        campaigns = self.app.campaigns
        if path == "/campanhas":
            self._html(campaigns["page"]())
            return True
        detail = re.fullmatch(r"/campanhas/(\d+)", path)
        if detail:
            page = campaigns["detail"](int(detail.group(1)))
            if page is None:
                self.send_error(404)
            else:
                self._html(page)
            return True
        photo = re.fullmatch(r"/campanhas/foto/(\d+)\.jpg", path)
        if photo:
            payload = campaigns["image"](int(photo.group(1)))
            if payload is None:
                self.send_error(404)
                return True
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "private, max-age=86400")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return True
        return False

    def _campaign_upload(self, campaign_id: int) -> None:
        if not self._logged_in():
            self._html(login_page(failed=False))
            return
        length = _content_length(self, MAX_CAMPAIGN_UPLOAD_BODY)
        if length is None:
            return
        body = self.rfile.read(length)
        try:
            _fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
        except ValueError:
            self.send_error(400)
            return
        self._redirect(self.app.campaigns["upload"](campaign_id, files.get("fotos", [])), self._token())
```

Em `_board_context`, no dicionário devolvido:

```python
            "invites": extra.get("invites") or "",
```

Em `do_GET`, na chamada de `render_board(...)`, acrescentar `invites=ctx["invites"],`.

- [ ] **Step 5: Build the callbacks in `build_app`**

Em `build_app`, antes de `return DashboardApp(`:

```python
    from promo_livros.campaign_panel import campaign_callbacks
    from promo_livros.campaign_store import CampaignStore

    campaign_panel = campaign_callbacks(
        config,
        board_store,
        CampaignStore(config.sqlite_path),
        root=Path.cwd(),
        current_day=current_day,
        now=lambda: datetime.now(zone(config.schedule.timezone)),
    )

    def choose_invite(form: dict[str, list[str]]) -> None:
        holder["notice"] = campaign_panel["choose"](form)

    campaign_routes = {**campaign_panel, "choose": choose_invite}
```

Em `board()`, dentro do dicionário extra, acrescentar `"invites": invites_html(),` e definir antes de `board()`:

```python
    def invites_html() -> str:
        try:
            return campaign_panel["invites"]()
        except Exception:
            logging.getLogger("promo_livros").exception("Não consegui montar os convites da /hoje.")
            return ""
```

(`campaign_panel` é resolvido quando `board()` roda, depois de `build_app` terminar.)

Na chamada `DashboardApp(...)`, acrescentar `campaigns=campaign_routes,`.

- [ ] **Step 6: Run the dashboard tests**

Run: `python -m pytest tests/test_dashboard_http.py tests/test_dashboard_grid.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add promo_livros/dashboard.py promo_livros/dashboard_pages.py promo_livros/dashboard_belt.py tests/test_dashboard_http.py
git commit -m "Open /campanhas and show the day's invites on /hoje."
```

---

### Task 12: Verificação final

- [ ] **Step 1: Full suite**

Run: `python -m pytest tests -q`
Expected: tudo PASS (nenhum teste antigo quebrado)

- [ ] **Step 2: Manual check in the panel**

1. `python -m promo_livros.dashboard` e abrir `http://127.0.0.1:8787/campanhas`.
2. Salvar um horário que é da grade (ex.: `08:40` com janela 08:00/40 min): aparece "já é horário da fila".
3. Salvar `13:15` e 10 minutos.
4. Criar a campanha "Teste", mandar 2 fotos (um PNG e um JPEG) e 2 textos. A lista mostra "Pronta".
5. Abrir `/hoje`: a lateral mostra "Convite das 13:15 · Aguardando" com "Rodízio: Teste" e "Convite final ≈ HH:MM".
6. Trocar a campanha pelo seletor e ver o aviso "Campanha do convite trocada."
7. Com o envio desligado no painel, rodar `python scripts/enviar_fila.py` e conferir no log `Convites: off.`.

- [ ] **Step 3: Commit the spec tweaks**

```bash
git add docs/superpowers/specs/2026-11-03-campanhas-convite-design.md docs/superpowers/plans/2026-11-03-campanhas-convite.md
git commit -m "Write down the invite campaign plan."
```
