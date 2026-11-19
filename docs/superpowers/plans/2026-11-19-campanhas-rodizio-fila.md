# Campanhas fixas + rotativas na fila — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Estender as campanhas existentes para modo fixo (`fixed_clock`) e rotativo (slots `campanha` no CSV + convite final), com validade opcional, troca no board e geração de textos por IA no painel.

**Architecture:** Regras puras em `campaign_rules.py`; schema/CRUD em `campaign_store.py` e `board_store.py`; slots rotativos viram `scheduled_posts` com `post_kind='campaign'`; disparos fixos usam `campaign_runs` com `kind='clock'`; o convite `fixed` global some; o convite `last` usa só rotativas. IA em `campaign_copy.py` reutiliza a chave OpenAI das resenhas.

**Tech Stack:** Python 3.13, sqlite3, Pillow, OpenAI HTTP (já em `blurb.py`), `http.server`, pytest/unittest.

**Spec:** `docs/superpowers/specs/2026-11-19-campanhas-rodizio-fila-design.md`

**Commits:** neste PC o `git add` pode falhar com `Permission denied` em `.git/objects` (pasta de rede). Se o passo de commit falhar, siga para a próxima tarefa e faça os commits depois.

## Global Constraints

- Mesmo SQLite (`config.sqlite_path`) para `BoardStore` e `CampaignStore`.
- Campanha **pronta**: `active` + ≥1 foto + ≥1 texto + (`valid_until` vazio ou `day <= valid_until`).
- **Fixa** = `fixed_clock` preenchido; **rotativa** = `fixed_clock` vazio. Pools separados.
- Fixas podem coincidir com livro no mesmo `HH:MM` (gap entre envios).
- Texto de campanha ≤ 1024 chars (`MAX_TEXT_LENGTH`).
- Janela de graça do horário fixo: 60 minutos (`FIXED_GRACE_MINUTES`).
- Sem hardcode de API key; usar `openai_api_key` / `openai_model` do config.

---

## Mapa de arquivos

| Arquivo | Papel |
|---|---|
| `promo_livros/campaign_rules.py` | Validade, parse clock/data da campanha, pools, due de clock |
| `promo_livros/campaign_store.py` | Colunas novas, runs `clock`/`last`, cursor rotativo |
| `promo_livros/board_store.py` | `post_kind`, ids de campanha, `add_campaign_post`, troca |
| `promo_livros/campaign_send.py` | `publish_due_fixed_campaigns`; convite final só rotativas; remover fixed global |
| `promo_livros/board_send.py` | Enviar post `campaign` (imagem da campanha) |
| `promo_livros/fila_csv.py` | Parse linha `campanha` |
| `promo_livros/fila.py` / `fila_aplicar.py` / publish | Montar slots campanha na fila |
| `promo_livros/campaign_copy.py` | Gerar N textos via OpenAI |
| `promo_livros/campaign_panel.py` / `campaign_pages.py` | UI campos + gerar textos |
| `promo_livros/dashboard.py` / `dashboard_belt.py` | Rotas; cards `/hoje` |
| `scripts/enviar_fila.py` | Ordem: fixas → last → fila |

---

### Task 1: Regras puras — validade, modo, clock da campanha

**Files:**
- Modify: `promo_livros/campaign_rules.py`
- Modify: `tests/test_campaign_rules.py`

**Interfaces:**
- Produces:
  - `parse_campaign_clock(raw: str) -> str | None` — vazio→None; senão `HH:MM` válido (sem checar conflito com fila)
  - `parse_valid_until(raw: str) -> str | None` — vazio→None; senão `YYYY-MM-DD`
  - `campaign_valid_on(valid_until: str | None, day: str) -> bool`
  - `is_rotating(fixed_clock: str | None) -> bool`
  - reutilizar `fixed_invite_due` / `fixed_invite_missed` para due das fixas

- [ ] **Step 1: Write the failing tests**

Acrescentar em `tests/test_campaign_rules.py`:

```python
from promo_livros.campaign_rules import (
    campaign_valid_on,
    is_rotating,
    parse_campaign_clock,
    parse_valid_until,
)


class CampaignModeTests(unittest.TestCase):
    def test_empty_clock_means_rotating(self) -> None:
        self.assertIsNone(parse_campaign_clock("  "))
        self.assertTrue(is_rotating(None))
        self.assertFalse(is_rotating("10:00"))

    def test_campaign_clock_allows_queue_overlap(self) -> None:
        self.assertEqual(parse_campaign_clock(" 10:00 "), "10:00")

    def test_bad_campaign_clock_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_campaign_clock("25:00")

    def test_valid_until_empty_or_iso(self) -> None:
        self.assertIsNone(parse_valid_until(""))
        self.assertEqual(parse_valid_until("2026-12-01"), "2026-12-01")
        with self.assertRaises(ValueError):
            parse_valid_until("01/12/2026")

    def test_validity_includes_the_end_day(self) -> None:
        self.assertTrue(campaign_valid_on(None, "2026-11-19"))
        self.assertTrue(campaign_valid_on("2026-11-19", "2026-11-19"))
        self.assertFalse(campaign_valid_on("2026-11-18", "2026-11-19"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_campaign_rules.py::CampaignModeTests -v`  
Expected: FAIL (`ImportError` ou atributos ausentes)

- [ ] **Step 3: Implement**

Em `promo_livros/campaign_rules.py`:

```python
import re
from datetime import date

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_campaign_clock(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    clock_minutes(value, "Horário fixo da campanha")
    return value


def parse_valid_until(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    if _DATE.fullmatch(value) is None:
        raise ValueError("A validade usa o formato AAAA-MM-DD.")
    date.fromisoformat(value)  # rejeita 2026-13-40
    return value


def campaign_valid_on(valid_until: str | None, day: str) -> bool:
    if valid_until is None:
        return True
    return day <= valid_until


def is_rotating(fixed_clock: str | None) -> bool:
    return fixed_clock is None
```

Manter `parse_fixed_clock` (com conflito de fila) só se ainda for usado em testes/UI antiga; a UI nova de campanha usa `parse_campaign_clock`. Na Task 5 a UI global do convite fixo some.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_campaign_rules.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/campaign_rules.py tests/test_campaign_rules.py
git commit -m "feat: regras de modo fixo/rotativo e validade da campanha"
```

---

### Task 2: CampaignStore — schema, CRUD dos campos, pools e runs clock

**Files:**
- Modify: `promo_livros/campaign_store.py`
- Modify: `tests/test_campaign_store.py`

**Interfaces:**
- Produces:
  - `Campaign` ganha `fixed_clock: str | None`, `valid_until: str | None`
  - `Campaign.ready_on(day: str) -> bool`
  - `set_schedule(campaign_id, fixed_clock: str | None, valid_until: str | None) -> None`
  - `ready_rotating(day: str) -> list[Campaign]`
  - `ready_fixed(day: str) -> list[Campaign]`
  - `run_for_clock(day, campaign_id, clock) -> CampaignRun` — kind=`clock`, já com `campaign_id`
  - `run_for(day, 'last')` permanece; `run_for(day, 'fixed')` deixa de ser usado no envio
  - `CampaignRun` ganha `clock: str | None`
  - `last_used_rotating() -> RotationEntry | None` — só runs `kind='last'` com campanha sem `fixed_clock` (posts da fila entram na Task 4)
  - Migração: `ALTER TABLE` + índices parciais únicos

- [ ] **Step 1: Write failing tests**

Em `tests/test_campaign_store.py` (padrão dos testes existentes com tmp path):

```python
def test_schedule_fields_and_ready_pools(self) -> None:
    store = self._store()
    rotating = store.create("Rotativa")
    fixed = store.create("Fixa")
    store.add_image(rotating, "data/campaigns/1/a.jpg")
    store.add_text(rotating, "texto a")
    store.add_image(fixed, "data/campaigns/2/b.jpg")
    store.add_text(fixed, "texto b")
    store.set_schedule(fixed, "10:00", "2026-11-20")
    self.assertEqual([c.id for c in store.ready_rotating("2026-11-19")], [rotating])
    self.assertEqual([c.id for c in store.ready_fixed("2026-11-19")], [fixed])
    self.assertEqual(store.ready_fixed("2026-11-21"), [])

def test_two_fixed_campaigns_same_clock_same_day(self) -> None:
    store = self._store()
    a = store.create("A")
    b = store.create("B")
    for cid in (a, b):
        store.add_image(cid, f"p{cid}.jpg")
        store.add_text(cid, "oi")
        store.set_schedule(cid, "10:00", None)
    run_a = store.run_for_clock("2026-11-19", a, "10:00")
    run_b = store.run_for_clock("2026-11-19", b, "10:00")
    self.assertNotEqual(run_a.id, run_b.id)
    self.assertEqual(run_a.clock, "10:00")
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_campaign_store.py -k "schedule_fields or two_fixed" -v`  
Expected: FAIL

- [ ] **Step 3: Migrate schema and implement**

1. Em `_SCHEMA` / `_migrate()` chamado no `__init__` depois do `executescript`:
   - `ALTER TABLE campaigns ADD COLUMN fixed_clock TEXT`
   - `ALTER TABLE campaigns ADD COLUMN valid_until TEXT`
   - `ALTER TABLE campaign_runs ADD COLUMN clock TEXT`
   - Afrouxar o CHECK de `kind`: recriar tabela se necessário para aceitar `'clock'` e `'last'` (e manter `'fixed'` legado só leitura), **ou** migrar: nova tabela + copy. Preferência prática no SQLite deste projeto: se o CHECK impedir insert de `clock`, recriar `campaign_runs` com:

```sql
kind TEXT NOT NULL CHECK (kind IN ('fixed', 'last', 'clock'))
```

   - Remover `UNIQUE(day, kind)` único; criar:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS campaign_runs_last_day
  ON campaign_runs(day) WHERE kind = 'last';
CREATE UNIQUE INDEX IF NOT EXISTS campaign_runs_clock_day_campaign
  ON campaign_runs(day, campaign_id) WHERE kind = 'clock';
```

2. Atualizar `_CAMPAIGN_SELECT` para incluir `c.fixed_clock, c.valid_until`.
3. `_campaign` / `Campaign.ready_on(day)`.
4. `set_schedule` com `parse_campaign_clock` / `parse_valid_until`.
5. `run_for_clock`:

```python
def run_for_clock(self, day: str, campaign_id: int, clock: str) -> CampaignRun:
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
```

6. `_RUN_SELECT` inclui `clock`.
7. `last_used_rotating`: como `last_used_campaign`, mas `WHERE r.kind = 'last' AND r.locked_at IS NOT NULL AND c.fixed_clock IS NULL` (na Task 4 amplia com UNION dos posts).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_campaign_store.py -v`  
Expected: PASS (atualizar testes antigos que assumem só `fixed`/`last` se quebrarem)

- [ ] **Step 5: Commit**

```bash
git add promo_livros/campaign_store.py tests/test_campaign_store.py
git commit -m "feat: store com horário fixo, validade e runs clock"
```

---

### Task 3: Envio das campanhas fixas + convite final só rotativo

**Files:**
- Modify: `promo_livros/campaign_send.py`
- Modify: `scripts/enviar_fila.py`
- Modify: `tests/test_campaign_send.py`
- Modify: `promo_livros/campaign_panel.py` / `campaign_pages.py` (remover campo `invite_fixed_clock` da UI de settings — pode ficar stub até Task 7 se preferir; mínimo: `publish` não lê mais o setting)

**Interfaces:**
- Produces:
  - `publish_due_fixed_campaigns(config, board, campaigns, sender, *, root, now, quiet_since=None, rng=None) -> str`
  - `publish_due_invite` só processa `kind='last'`; escolha de campanha via `ready_rotating` + `last_used_rotating`
- Consumes: `ready_fixed`, `run_for_clock`, `fixed_invite_due` / `missed`

- [ ] **Step 1: Failing send tests**

```python
def test_fixed_campaign_fires_at_its_clock(self) -> None:
    # cria campanha com fixed_clock 10:00, pronta; now=10:05; sending on
    # assert publish_due_fixed_campaigns manda para o primeiro grupo

def test_fixed_and_queue_same_clock_both_allowed(self) -> None:
    # não é erro ter post de livro 10:00 e campanha fixa 10:00

def test_last_invite_ignores_fixed_campaigns(self) -> None:
    # só rotativa no pool do last
```

Basear no padrão de `tests/test_campaign_send.py` (sender falso, tmp dirs).

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_campaign_send.py -k "fixed_campaign or last_invite_ignores" -v`  
Expected: FAIL

- [ ] **Step 3: Implement send**

Em `campaign_send.py`:

```python
def publish_due_fixed_campaigns(...) -> str:
    if not board.sending_enabled():
        return "off"
    # 1) retomar open_sending_run com kind=='clock' se houver
    # 2) senão, para cada ready_fixed(day): se fixed_invite_due(clock, now_clock) e run ainda pending/sending → processar
    #    se missed e ainda pending sem lock → skip_run
    # Reutilizar _locked_content / claim_group_send / gap_open do módulo
```

Ajustar `_due_run` / escolha de campanha do convite `last` para usar apenas `ready_rotating(day)` e `last_used_rotating()`.

Em `scripts/enviar_fila.py`, ordem:

```python
publish_due_fixed_campaigns(...)
publish_due_invite(...)  # só last
publish_due(...)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_campaign_send.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/campaign_send.py scripts/enviar_fila.py tests/test_campaign_send.py
git commit -m "feat: dispara campanhas fixas e restringe convite final às rotativas"
```

---

### Task 4: Board — post_kind campaign + add/troca + cursor rotativo unificado

**Files:**
- Modify: `promo_livros/board_store.py`
- Modify: `promo_livros/campaign_store.py` (`last_used_rotating` com UNION)
- Modify: `tests/test_board.py` (ou novo `tests/test_board_campaign_post.py`)

**Interfaces:**
- Produces:
  - Colunas: `post_kind TEXT NOT NULL DEFAULT 'book'`, `campaign_id`, `image_id`, `text_id`, `campaign_locked_at`
  - `BoardPost` inclui esses campos
  - `add_campaign_post(day, clock, *, campaign_id=None, image_id=None, text_id=None, caption='', image_path='', locked_at=None) -> int` — **sem** books
  - `set_campaign_content(post_id, campaign_id, image_id, text_id, caption, image_path, locked_at) -> None`
  - Posts `book` continuam exigindo 1–3 books em `add_post`

- [ ] **Step 1: Failing tests**

```python
def test_add_campaign_post_without_books(self) -> None:
    store = self._board()
    post_id = store.add_campaign_post(
        day="2026-11-19",
        clock="11:00",
        campaign_id=1,
        image_id=2,
        text_id=3,
        caption="hook",
        image_path="data/campaigns/1/x.jpg",
        locked_at="2026-11-19T10:00:00",
    )
    post = store.post(post_id)  # ou posts_for
    self.assertEqual(post.post_kind, "campaign")
    self.assertEqual(post.books, ())
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_board_campaign_post.py -v`  
Expected: FAIL

- [ ] **Step 3: Migrate + implement**

Em `_setup` do `BoardStore`, depois do script:

```python
self._ensure_column("scheduled_posts", "post_kind", "TEXT NOT NULL DEFAULT 'book'")
self._ensure_column("scheduled_posts", "campaign_id", "INTEGER")
self._ensure_column("scheduled_posts", "image_id", "INTEGER")
self._ensure_column("scheduled_posts", "text_id", "INTEGER")
self._ensure_column("scheduled_posts", "campaign_locked_at", "TEXT")
```

(`_ensure_column` = PRAGMA table_info + ALTER se faltar; se já existir helper no arquivo, reutilizar.)

`add_campaign_post` faz INSERT com `post_kind='campaign'` e sem `_insert_books`.

Em `CampaignStore.last_used_rotating`:

```sql
SELECT campaign_id, position FROM (
  SELECT r.campaign_id AS campaign_id, c.position AS position, r.locked_at AS locked_at
  FROM campaign_runs r
  JOIN campaigns c ON c.id = r.campaign_id
  WHERE r.kind = 'last' AND r.locked_at IS NOT NULL AND c.fixed_clock IS NULL
  UNION ALL
  SELECT p.campaign_id, c.position, p.campaign_locked_at
  FROM scheduled_posts p
  JOIN campaigns c ON c.id = p.campaign_id
  WHERE p.post_kind = 'campaign'
    AND p.campaign_id IS NOT NULL
    AND p.campaign_locked_at IS NOT NULL
    AND c.fixed_clock IS NULL
)
ORDER BY locked_at DESC
LIMIT 1
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_board_campaign_post.py tests/test_board.py tests/test_campaign_store.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/board_store.py promo_livros/campaign_store.py tests/test_board_campaign_post.py
git commit -m "feat: posts de campanha na fila do board"
```

---

### Task 5: CSV — linha `campanha` e prévia

**Files:**
- Modify: `promo_livros/fila_csv.py`
- Modify: `promo_livros/fila.py` (SlotFila se precisar de flag)
- Modify: `tests/test_fila_csv.py`

**Interfaces:**
- Produces: slot com marcador de campanha (ex. `SlotFila` com `kind='campaign'` ou `amazon is None` + flag `is_campaign=True`). Escolher **um** padrão e usar em todo o plano: preferência `SlotFila.is_campaign: bool`.
- Linha com `asin` (folded) igual a `campanha` → slot campanha; ignora preços/links.

- [ ] **Step 1: Failing tests**

```python
def test_campanha_row_parses_without_books(self) -> None:
    text = "horario;asin;titulo;...\n10:00;campanha;;;;;;;;;;;;;;\n"  # header real do projeto
    # ou montar CSV mínimo válido com as colunas exigidas por parse_fila_csv
    slots = parse_fila_csv(text)  # adaptar à API real (FilaMontada / list[dict])
    self.assertTrue(slots[0]["is_campaign"] or equivalent)

def test_book_and_campanha_in_same_csv(self) -> None:
    ...
```

Olhar `tests/test_fila_csv.py` para o header exato exigido e copiar o padrão.

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_fila_csv.py -k campanha -v`  
Expected: FAIL

- [ ] **Step 3: Implement parse**

Onde monta cada linha, depois de ler `asin`:

```python
if _fold(asin_raw) == "campanha":
    rows.append({"clock": clock, "is_campaign": True})
    continue
```

Propagar até `SlotFila` / payload da prévia (`"Campanha (rodízio)"` no label). Passos de keepa/resenha **não** são criados para esse slot.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_fila_csv.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/fila_csv.py promo_livros/fila.py tests/test_fila_csv.py
git commit -m "feat: CSV aceita slot campanha no horário"
```

---

### Task 6: Montagem da fila — escolher rotativa e gravar post

**Files:**
- Modify: onde `publish_selection` / `board.add_post` são chamados para cada slot (rastrear a partir de `fila_aplicar.publish_selection` / `promo_livros/fila.py`)
- Modify: `tests/test_fila_aplicar.py` (ou novo teste de montagem)

**Interfaces:**
- Consumes: `ready_rotating`, `rotation_order`, `last_used_rotating`, `pick_avoiding`, `add_campaign_post`, imagens/textos do `CampaignStore`
- Para cada slot `is_campaign`, na ordem dos clocks:
  1. `order = rotation_order(rotating_entries, last_used_rotating())`
  2. Se vazio → `add_campaign_post(..., campaign_id=None, caption='', image_path='')` + aviso
  3. Senão pega `order[0]`, sorteia foto/texto, copia JPEG para path usável **ou** grava `image_path` relativo da campanha (`data/campaigns/...`), caption = body do texto, `locked_at=now`

**Nota:** `last_content` hoje só olha `campaign_runs`. Estender para considerar também último `image_id`/`text_id` em `scheduled_posts` daquela campanha, ou aceitar YAGNI e só evitar via runs no início — preferência: estender `last_content` com UNION igual ao cursor.

- [ ] **Step 1: Failing test**

```python
def test_mount_assigns_rotating_campaigns_in_order(self) -> None:
    # 2 campanhas rotativas prontas, CSV com 2 slots campanha
    # após aplicar: posts campaign com campaign_ids na ordem do rodízio
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_fila_aplicar.py -k mount_assigns_rotating -v`  
Expected: FAIL

- [ ] **Step 3: Implement**

Injetar `CampaignStore` no caminho de publish (como o dashboard já tem ambos). Pseudo:

```python
if slot.is_campaign:
    chosen = _pick_rotating(campaigns, day, rng)
    if chosen is None:
        board.add_campaign_post(day=day, clock=slot.clock)
        avisos.append(f"{slot.clock}: sem campanha rotativa pronta")
        continue
    image_id = pick_avoiding([...], last_image, rng)
    text_id = pick_avoiding([...], last_text, rng)
    text = campaigns.text(text_id)
    image = campaigns.image(image_id)
    board.add_campaign_post(
        day=day,
        clock=slot.clock,
        campaign_id=chosen.id,
        image_id=image_id,
        text_id=text_id,
        caption=text.body,
        image_path=image.path,
        locked_at=now_iso,
    )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_fila_aplicar.py tests/test_fila_csv.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/fila_aplicar.py promo_livros/fila.py promo_livros/campaign_store.py tests/test_fila_aplicar.py
git commit -m "feat: montagem da fila escolhe campanha rotativa no slot"
```

---

### Task 7: Envio do post campanha na fila + skip se vazio

**Files:**
- Modify: `promo_livros/board_send.py`
- Modify: `tests/test_board_send.py`

**Interfaces:**
- Em `publish_due`, se `post.post_kind == 'campaign'`:
  - se sem `campaign_id`/imagem → `mark skipped`, return `"skipped"`
  - senão ler bytes via `campaign_images.read_image(root, path)` (não `card_bytes` de card de livro)
  - caption = `post.caption` (sem assinatura de livro, a menos que o projeto já aplique assinatura a tudo — se `apply_signature` roda para todos, manter o mesmo comportamento)
- Gap inalterado

- [ ] **Step 1: Failing tests**

```python
def test_campaign_post_sends_campaign_image(self) -> None: ...
def test_empty_campaign_post_is_skipped(self) -> None: ...
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_board_send.py -k campaign_post -v`  
Expected: FAIL

- [ ] **Step 3: Implement branch in `publish_due`**

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_board_send.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/board_send.py tests/test_board_send.py
git commit -m "feat: envia posts de campanha da fila pelo publish_due"
```

---

### Task 8: Painel — campos da campanha, gerar textos IA, UI `/hoje`

**Files:**
- Create: `promo_livros/campaign_copy.py`
- Create: `tests/test_campaign_copy.py`
- Modify: `promo_livros/campaign_panel.py`, `campaign_pages.py`
- Modify: `promo_livros/dashboard.py` (rota POST gerar + troca de post campanha)
- Modify: `promo_livros/dashboard_belt.py` / páginas da `/hoje`
- Modify: `tests/test_campaign_panel.py`, `tests/test_dashboard_http.py` conforme padrão

**Interfaces:**
- Produces:
  - `generate_campaign_texts(*, api_key, model, campaign_name, count: int, session=None) -> list[str]`
  - count clamp 3..10; cada string strip e ≤ 1024; raise `CampaignError` se API falhar
  - Panel: form `fixed_clock`, `valid_until`; botão gerar; remove input `invite_fixed_clock`
  - `/hoje`: cards fixos por campanha `clock`; post campanha na grade com selects

- [ ] **Step 1: Failing unit test for copy**

```python
class FakeSession:
    def post(self, url, **kwargs):
        class Resp:
            status_code = 200
            def json(self):
                return {
                    "choices": [{
                        "message": {
                            "content": "Hook um.\nHook dois.\nHook três."
                        }
                    }]
                }
            def raise_for_status(self):
                return None
        return Resp()


def test_generate_splits_lines(self) -> None:
    texts = generate_campaign_texts(
        api_key="sk-test",
        model="gpt-4o-mini",
        campaign_name="Grupo X",
        count=3,
        session=FakeSession(),
    )
    self.assertEqual(len(texts), 3)
```

Implementação: POST em `https://api.openai.com/v1/chat/completions` (mesmo endpoint de `blurb.py`), system prompt fixo pedindo N linhas numeradas ou uma por linha, tom WhatsApp/grupos de livros, sem preço inventado.

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_campaign_copy.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement `campaign_copy.py` + wire panel**

Callback `generate(form)`: lê `campaign_id`, `count`; chama `generate_campaign_texts`; `add_text` para cada; redirect com notice.

Troca no board: form na `/hoje` com `post_id`, `campaign_id` ou `image_id`/`text_id`; `set_campaign_content` + atualiza caption/path.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_campaign_copy.py tests/test_campaign_panel.py tests/test_dashboard_http.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/campaign_copy.py promo_livros/campaign_panel.py promo_livros/campaign_pages.py promo_livros/dashboard.py promo_livros/dashboard_belt.py tests/test_campaign_copy.py tests/test_campaign_panel.py tests/test_dashboard_http.py
git commit -m "feat: painel de campanha com IA, validade e troca no board"
```

---

### Task 9: Smoke de regressão

**Files:** nenhum novo além de ajustes se algo quebrar

- [ ] **Step 1: Run full campaign + fila suite**

```bash
python -m pytest tests/test_campaign_rules.py tests/test_campaign_store.py tests/test_campaign_send.py tests/test_campaign_images.py tests/test_campaign_panel.py tests/test_fila_csv.py tests/test_fila_aplicar.py tests/test_board_send.py tests/test_board.py -v
```

Expected: PASS

- [ ] **Step 2: Manual checklist (humano)**

1. Criar campanha rotativa com 2 fotos e gerar 3 textos.
2. Criar campanha fixa 15:00 com validade futura.
3. CSV com um `campanha` e livros; aplicar; ver post na `/hoje`.
4. Trocar foto/texto no board.
5. Confirmar que setting “Convite no horário” sumiu; convite final ainda aparece.

- [ ] **Step 3: Commit final se houver correções**

```bash
git commit -m "fix: ajustes finais do rodízio de campanhas na fila"
```

---

## Spec coverage (self-review)

| Requisito da spec | Task |
|---|---|
| `fixed_clock` / `valid_until` / pronta | 1, 2 |
| Pools fixa vs rotativa | 1, 2, 3 |
| CSV `campanha` só reserva | 5 |
| Montagem escolhe + trava; board troca | 6, 8 |
| Sem rotativa → post vazio + skip no envio | 6, 7 |
| Fixas disparam com graça 60 min; coexistência | 3 |
| Remove invite_fixed_clock; mantém last só rotativas | 3, 8 |
| Cursor rotativo unificado last + posts | 4 |
| Runs clock UNIQUE por campanha/dia | 2 |
| `post_kind=campaign` na fila | 4, 7 |
| IA gera N textos editáveis | 8 |
| Ordem loop fixas → last → fila | 3 |
| Testes listados na spec | 1–8 + 9 |

**Placeholders:** nenhum TBD intencional. Onde o plano diz “olhar teste existente para header CSV”, o implementador deve copiar o fixture real de `tests/test_fila_csv.py` (o header muda com Magalu/Shopee).

**Consistência de nomes:** `parse_campaign_clock`, `ready_rotating` / `ready_fixed`, `run_for_clock`, `publish_due_fixed_campaigns`, `add_campaign_post`, `generate_campaign_texts`, `post_kind='campaign'`.
