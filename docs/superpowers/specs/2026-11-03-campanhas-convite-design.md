# Campanhas de convite para outros grupos

## Objetivo

Mandar, todo dia, dois posts chamando para outros grupos, fora dos horários da fila:

- **Convite do horário livre**: num horário que eu defino.
- **Convite final**: sempre o último post do dia.

O conteúdo vem de **campanhas**. Cada campanha tem N fotos e N textos; na hora do envio o sistema escolhe uma foto e um texto. Pode haver várias campanhas.

Fora do escopo:

- Escolher grupos por campanha (o convite vai para todos os grupos da fila).
- Peso ou agendamento por campanha.
- Convite só de texto.

## Regras

**Dias**: os dois convites saem todo dia, com ou sem fila. Só não saem com o envio desligado no painel (`BoardStore.sending_enabled()`).

**Convite do horário livre**: horário fixo em `board_settings.invite_fixed_clock` (`HH:MM`). Ao salvar, o painel recusa um horário igual a um slot da grade (`send_schedule.slot_clocks`) ou ao horário de um post da fila de hoje. Campo vazio desliga este convite. O convite só começa dentro de 60 minutos depois do horário: se o envio ficou desligado ou o horário foi salvo depois de passar, o convite daquele dia não sai (evita disparar um convite fora de hora para todos os grupos). Depois de começar, termina os grupos que faltam mesmo fora da janela.

**Convite final**: sai `invite_last_offset_minutes` (padrão 10, de 1 a 120) depois do horário do último post da fila do dia (agendado ou já enviado, antes do fim da janela do dia). Sem post no dia, a referência é o fim da janela (`send_end_for`). Além do horário, só sai quando não resta post agendado antes do fim da janela, então acompanha atrasos e mudanças na fila. Se a referência passar de 23:59, o convite sai às 23:59.

**Grupos**: todos os grupos de `config.whatsapp_groups`, com o mesmo `group_gap_seconds` e a mesma pausa de enquetes da fila.

**Campanha pronta**: ativa, com pelo menos 1 foto e 1 texto. Só campanhas prontas entram no rodízio.

**Rodízio**: as campanhas prontas seguem a ordem de `position`. Cada convite usa a próxima depois da última usada em qualquer convite (de qualquer tipo). Se a última usada deixou de estar pronta, segue a ordem a partir da posição dela; se foi apagada, recomeça do início. Se a campanha da vez não tiver nenhuma foto legível no disco, tenta a seguinte do rodízio.

**Troca manual**: na `/hoje`, cada convite do dia mostra a campanha prevista e um seletor para escolher outra campanha pronta. A escolha vale até o convite sair. Depois de enviado, o seletor some.

**Foto e texto**: sorteados uma única vez, quando o convite vence, e gravados no registro do dia. A mesma combinação vai para todos os grupos. O sorteio evita a foto e o texto usados no envio anterior daquela campanha quando há outra opção.

**Uma vez por dia**: cada tipo de convite tem no máximo um registro por dia (`UNIQUE(day, kind)`). Reiniciar o loop retoma os grupos que faltam.

## Dados

Tabelas novas no mesmo SQLite do `BoardStore`:

```sql
CREATE TABLE campaigns (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  position INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE campaign_images (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  path TEXT NOT NULL,          -- relativo à raiz, sempre em data/campaigns/{campaign_id}/
  created_at TEXT NOT NULL
);

CREATE TABLE campaign_texts (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE campaign_runs (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL,           -- YYYY-MM-DD
  kind TEXT NOT NULL CHECK (kind IN ('fixed', 'last')),
  campaign_id INTEGER,         -- escolha manual ou definida no vencimento
  manual INTEGER NOT NULL DEFAULT 0,
  image_id INTEGER,
  text_id INTEGER,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sending', 'sent', 'skipped')),
  locked_at TEXT,              -- quando campanha, foto e texto foram travados; ordena o rodízio
  sent_at TEXT,
  UNIQUE (day, kind)
);

CREATE TABLE campaign_run_groups (
  run_id INTEGER NOT NULL REFERENCES campaign_runs(id) ON DELETE CASCADE,
  chat_id TEXT NOT NULL,
  message_id TEXT,
  sent_at TEXT NOT NULL,
  PRIMARY KEY (run_id, chat_id)
);
```

`campaign_runs` guarda `image_id`/`text_id` em vez de chave estrangeira com cascade: apagar uma foto ou um texto não apaga o histórico.

Settings novos em `board_settings`: `invite_fixed_clock`, `invite_last_offset_minutes`.

## Módulos

**`promo_livros/campaign_rules.py`** (puro, sem IO):

- `fixed_clock_conflict(clock, queue_slots) -> bool`
- `last_invite_clock(last_queue_clock: str | None, send_end: str, offset_minutes: int) -> str`
- `next_in_rotation(ready: list[Campaign], last_used: Campaign | None) -> Campaign | None`
- `pick_avoiding(item_ids: list[int], last_used_id: int | None, rng: Random) -> int`

**`promo_livros/campaign_store.py`**: CRUD de campanhas, fotos e textos; `ready_campaigns()`; `run_for(day, kind)` (cria `pending` se não existir); `peek_run(day, kind)` (só lê, para o painel); `set_manual_campaign`; `lock_content(run_id, campaign_id, image_id, text_id, expected=...)` (não trava se o registro mudou depois da leitura); `claim_group_send`/`finish_group_send`/`release_group_send`; `mark_run_sent`/`mark_run_skipped`; `last_used_campaign()`; `last_content(campaign_id)`.

**`promo_livros/campaign_images.py`**: valida e grava o upload. Aceita JPEG, PNG e WebP pelo conteúdo (Pillow), não pela extensão. Limite de 8 MB e 4096 px no maior lado (reduz se passar). Grava sempre JPEG com nome aleatório (`uuid4`) em `data/campaigns/{id}/`. Remove EXIF.

**`promo_livros/campaign_send.py`**: `publish_due_invite(config, store, campaign_store, sender, *, root, now) -> str`.

1. Envio desligado: `"off"`.
2. Para cada tipo (`fixed`, depois `last`), calcula o horário do dia. Não vencido ou já `sent`/`skipped`: segue.
3. Vencido e sem conteúdo travado: usa a campanha manual se ainda estiver pronta, senão a próxima do rodízio. Nenhuma pronta: `skipped` e log `warning`. Sorteia foto e texto e trava.
4. Manda para o próximo grupo que falta, respeitando `group_gap_seconds` e a pausa de enquetes. Um grupo por chamada, como `publish_due`.
5. Todos os grupos enviados: `sent`.

**Espera comum**: `_later_stamp` e `_gap_open` saem de `board_send` para `promo_livros/send_gap.py` (`latest_stamp`, `gap_open`), usados pela fila, pelos convites e pelas enquetes. O intervalo entre grupos vale entre qualquer mensagem enviada: fila, convite ou enquete.

**`scripts/enviar_fila.py`**: a cada volta chama `publish_due_invite` antes de `publish_due`. Exceção em um não impede o outro; as duas são logadas.

## Painel

**`/campanhas`** (nova, com login):

- Lista de campanhas com nome, ativa, ordem (subir/descer), contagem de fotos e textos, e etiqueta "incompleta" quando falta foto ou texto.
- Página da campanha: renomear, ativar/desativar, apagar; enviar fotos (várias de uma vez, `multipart/form-data`, até 40 MB por envio), ver miniaturas e remover; adicionar, editar e remover textos (até 1024 caracteres, o limite de legenda de imagem do WhatsApp).
- No topo da `/campanhas`, os campos "Convite no horário" (`HH:MM`, opcional) e "Convite final, minutos depois do último post".
- Apagar campanha remove a pasta `data/campaigns/{id}/`.
- Fotos servidas por rota própria que só lê dentro de `data/campaigns/`.

**`/hoje`**: dois cartões acima da fila, "Convite das HH:MM" e "Convite final ≈ HH:MM", com campanha prevista, seletor de troca e status (aguardando, enviando N/M grupos, enviado, pulado: sem campanha pronta).

Todo texto de campanha exibido no painel passa pelo mesmo escape HTML das outras páginas. Formulários seguem a proteção de sessão atual.

## Erros

- Foto do registro sumiu do disco: sorteia outra da mesma campanha, atualiza o registro, log `warning`. Nenhuma foto válida: trata como campanha não pronta.
- Falha no WAHA: mesmo tratamento dos posts da fila (log e nova tentativa na próxima volta, sem marcar o grupo).
- Upload com arquivo inválido (formato, tamanho acima de 8 MB, resolução, erro de disco ou de banco): só esse arquivo é recusado, com o número dele na tela; os arquivos bons do mesmo envio são guardados. Arquivo que não entrou no banco é apagado do disco.
- Envio com corpo acima de 40 MB, sem `Content-Length` ou que não seja `multipart/form-data`: recusado inteiro, nada gravado.

## Testes

- `tests/test_campaign_rules.py`: conflito com slot, convite final com e sem fila, limite em 23:59, rodízio com campanha desativada no meio, sorteio que evita repetir e com um item só.
- `tests/test_campaign_store.py`: CRUD, cascade, `UNIQUE(day, kind)`, campanhas prontas.
- `tests/test_campaign_images.py`: PNG convertido para JPEG, arquivo que não é imagem recusado, redução de tamanho.
- `tests/test_campaign_send.py`: no padrão de `test_board_send.py` com sender falso. Envio desligado, não vencido, troca manual, sem campanha pronta, retomada após reinício, mesma foto e texto em todos os grupos.
- `tests/test_dashboard_http.py`: upload pela rota, horário em conflito recusado, troca de campanha na `/hoje`.
