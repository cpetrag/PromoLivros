# Grade da fila na /hoje — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Organizar a fila agendada de hoje em uma grade compacta, com troca, mover para horário, empurrar e reespaçar, sem recarregar a página.

**Architecture:** As regras de horário ficam numa função pura (`promo_livros/fila_horarios.py`) que recebe a fila `(id, clock)` e devolve os novos horários ou a recusa. O `BoardStore` relê a fila dentro do lock, chama a regra e grava. O painel expõe rotas JSON e a grade é um fragmento a mais do `/hoje/parcial`.

**Tech Stack:** Python 3.12, `http.server`, SQLite, unittest/pytest, JavaScript sem framework.

Spec: `docs/superpowers/specs/2026-11-03-grade-fila-design.md`.

## Global Constraints

- Só posts `status = 'scheduled'` do dia mudam.
- Horário novo nunca igual ou antes de agora, nunca depois de 23:59, nunca repetido entre agendados.
- Fora da janela é `clock >= send_schedule().end`.
- Sugestão de encaixe só quando o intervalo calculado for >= 5 min.
- Empurrar aceita −60 a +180 min. Reespaçar aceita 5 a 180 min.
- Desfazer vale 10 min, no mesmo dia, se todos os ids ainda estiverem agendados.
- Textos da interface em português do Brasil. Nomes de código seguem o arquivo onde estão.

## Arquivos

- Criar `promo_livros/fila_horarios.py`: regra pura de horários.
- Criar `tests/test_fila_horarios.py`.
- Modificar `promo_livros/board_store.py`: `FeedBook`, `FeedPost.shelf`, `apply_clocks`, `snapshot_clocks`, `restore_clocks`, `send_end_for`, `extend_send_end`.
- Modificar `promo_livros/board_send.py`: usar `send_end_for`.
- Modificar `promo_livros/dashboard.py`: rotas `/hoje/trocar`, `/hoje/antes`, `/hoje/horario`, `/hoje/empurrar`, `/hoje/reespacar`, `/hoje/horarios/desfazer` e o callable `queue_clocks` no `DashboardApp`.
- Modificar `promo_livros/dashboard_belt.py`: fragmento `grid`, seletor Lista | Grade, menu ⋯, diálogo de "fora da janela", JS.
- Testes em `tests/test_board.py`, `tests/test_board_send.py`, `tests/test_dashboard_http.py`.

### Task 1: Regra pura de horários

**Files:** Create `promo_livros/fila_horarios.py`, `tests/test_fila_horarios.py`

**Interfaces — Produces:**
- `Limites(agora: str, fim: str, permitir_fora: bool = False)`
- `Fora(count: int, last: str, fit_interval: int | None)`
- `Resultado(clocks: dict[int, str], fora: Fora | None = None, erro: str = "")`; `ok` é `not erro and fora is None`.
- `trocar(fila, a, b, limites) -> Resultado`
- `antes(fila, post_id, alvo_id, limites) -> Resultado`
- `no_horario(fila, post_id, clock, limites) -> Resultado`
- `empurrar(fila, post_id, minutos, limites, intervalo: int | None = None) -> Resultado`
- `reespacar(fila, post_id, intervalo, limites) -> Resultado`
- `fila` é `list[tuple[int, str]]` dos agendados do dia, em ordem de horário. `clocks` traz só os ids que mudaram.

- [ ] Escrever testes: troca; antes vindo de cima e de baixo; no_horario livre e ocupado (erro); empurrar +20 e −20; empurrar para o passado (erro); reespaçar; fora com sugestão; sugestão None abaixo de 5; permitir_fora; 23:59; empurrar com `intervalo` encaixa.
- [ ] Rodar `python -m pytest tests/test_fila_horarios.py -q` e ver falhar por import.
- [ ] Implementar.
- [ ] Rodar e ver passar.

### Task 2: BoardStore grava horários, retrato e extensão do fim

**Files:** Modify `promo_livros/board_store.py`, `promo_livros/board_send.py`; Test `tests/test_board.py`, `tests/test_board_send.py`

**Interfaces — Consumes:** `Resultado` da Task 1. **Produces:**
- `BoardStore.queue_clocks(day) -> list[tuple[int, str]]`
- `BoardStore.apply_clocks(day, change: Callable[[list[tuple[int, str]]], Resultado], *, extend_end: bool = False) -> Resultado` — relê dentro do lock, chama `change`, grava se `ok` e guarda o retrato em `clock_undo`. Com `extend_end`, grava `send_end_extra:<dia>`.
- `BoardStore.restore_clocks(day, now_ts: float) -> str` — mensagem.
- `BoardStore.send_end_for(day, end) -> str`
- `FeedBook(title, price_cents, discount_pct, url, product_id)` e `FeedPost.shelf: tuple[FeedBook, ...] = ()`.

- [ ] Testes: apply grava e reordena `position`; recusa grava nada; id que saiu entre a leitura e a gravação é recusado; desfazer volta; desfazer vencido recusa; `send_end_for` usa o maior; `day_feed` traz `shelf` com todos os livros; `board_send` envia post das 22:10 quando a extensão é 22:11.
- [ ] Ver falhar, implementar, ver passar.

### Task 3: Rotas JSON

**Files:** Modify `promo_livros/dashboard.py`; Test `tests/test_dashboard_http.py`

**Interfaces — Consumes:** Tasks 1–2. **Produces:** `DashboardApp.queue_action: Callable[[str, dict[str, list[str]]], dict] | None`. Ações: `trocar`, `antes`, `horario`, `empurrar`, `reespacar`, `desfazer`.

- [ ] Testes HTTP: exige login; sucesso devolve `{"ok": true}`; fora devolve `{"ok": false, "fora": {...}}`; erro devolve `{"ok": false, "error": ...}`.
- [ ] Ver falhar, implementar, ver passar.

### Task 4: Grade na /hoje

**Files:** Modify `promo_livros/dashboard_belt.py`; Test `tests/test_dashboard_http.py` (fragmento `grid` presente no `/hoje/parcial`)

- [ ] Fragmento `grid`: linhas dos agendados com horário, célula Amazon, célula ML/Shopee, menu ⋯; enviados recolhidos.
- [ ] Seletor Lista | Grade com `localStorage`.
- [ ] JS: arrastar linha (reusa `/hoje/reordenar`), menu ⋯ com Mover para…, Empurrar, Abrir horário, Reespaçar; diálogo "fora"; toast com Desfazer; atualizar via `/hoje/parcial`.
- [ ] `node --check` no JS, testes, conferência visual no navegador.

### Task 5: Deploy

- [ ] Testes no Mac (`unittest`), `pm2 restart promo-livros-painel`, `/hoje` responde 200.
