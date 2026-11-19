# Campanhas em rodízio na fila (fixas + rotativas)

## Objetivo

Estender o sistema de campanhas já existente (`/campanhas`, `CampaignStore`, convites) para dois modos na mesma entidade:

- **Fixa**: campanha com `fixed_clock` (`HH:MM`) dispara todo dia nesse horário, mesmo que a fila tenha um livro no mesmo horário.
- **Rotativa**: campanha sem `fixed_clock` entra no pool usado quando o CSV marca um slot como `campanha`, e também no convite final.

Na criação/edição da campanha, o painel pode pedir N variações de texto geradas por IA (OpenAI já usada nas resenhas); os textos ficam editáveis.

## Fora de escopo

- Peso ou prioridade por campanha.
- Escolher grupos por campanha.
- A/B automático por performance.
- Trocar o pipeline de envio da fila por um único “tudo é slot” (abordagem 3 rejeitada).

## Regras

### Modos da campanha

| Campo | Vazio | Preenchido |
| --- | --- | --- |
| `fixed_clock` | Rotativa — só pool de slots CSV + convite final | Fixa — dispara no `HH:MM` |
| `valid_until` (`YYYY-MM-DD`) | Sem validade | A partir do dia seguinte à data, não entra em rodízio nem em disparos fixos novos |

**Pronta**: ativa, pelo menos 1 foto e 1 texto, e (se tiver `valid_until`) o dia corrente ≤ `valid_until`.

Campanhas fixas e rotativas **não compartilham o mesmo pool**. Fixas não são escolhidas por slots `campanha` do CSV nem pelo convite final. Rotativas não disparam sozinhas por horário.

### CSV e montagem da fila

- Na coluna `asin` (primeira loja), valor literal `campanha` (case-insensitive). Demais colunas de livro da linha são ignoradas. `horario` obrigatório.
- Importar só **reserva** o slot (não chama Keepa/link/resenha).
- Na prévia: “Campanha (rodízio)” + horário.
- Ao aplicar/montar a fila do dia, para cada slot `campanha`:
  1. Escolhe a próxima rotativa pronta (ordem por `position`, a partir da última usada em qualquer uso rotativo).
  2. Sorteia foto e texto evitando o último uso daquela campanha quando houver outra opção.
  3. Grava post da fila com `post_kind = campaign` e `campaign_id` / `image_id` / `text_id` travados; caption e imagem resolvidos a partir disso.
- Sem rotativa pronta: cria o post campanha **sem** conteúdo travado e avisa na montagem; no board o usuário escolhe manualmente. Se ainda vazio na hora do envio → `skipped` + log.
- Depois de montada a fila, no `/hoje` dá para trocar a campanha do horário, a foto ou o texto.

### Campanhas fixas

- Não passam pelo CSV.
- Todo dia, para cada campanha pronta com `fixed_clock`, o loop cria/retoma um run daquele horário.
- Podem coincidir com um livro (ou slot campanha) no mesmo `HH:MM`: dois envios; respeitam o mesmo `group_gap_seconds` entre qualquer mensagem.
- Janela de graça do horário fixo: 60 minutos (igual ao convite fixo atual). Se o envio ficou desligado e a janela passou, aquele dia não dispara.

### Convites atuais

- Remove o horário livre global (`invite_fixed_clock` / setting “Convite no horário”).
- Mantém o **convite final** (offset após o último post da fila), usando só o pool de **rotativas**.

### Rodízio e sorteio

- Cursor de rodízio **rotativo**: compartilhado entre slots CSV do dia e o convite final. A “última usada” olha o mais recente entre (a) posts `post_kind=campaign` com `campaign_id` travado e (b) runs `kind=last` com conteúdo travado — ordenados por `locked_at` / momento da montagem.
- Campanhas fixas: cada uma tem o próprio run diário; **não** avançam o cursor rotativo.
- Foto/texto: mesma regra `pick_avoiding` de hoje.

### Validade no meio do dia

- Runs/posts já travados com campanha que depois “vence” (ou é desativada) **seguem** com o conteúdo travado.
- Novos slots e novos disparos fixos do dia não a usam.

## Dados

### `campaigns` (colunas novas)

```sql
ALTER TABLE campaigns ADD COLUMN fixed_clock TEXT;      -- HH:MM ou NULL
ALTER TABLE campaigns ADD COLUMN valid_until TEXT;      -- YYYY-MM-DD ou NULL
```

Validação ao salvar: `fixed_clock` vazio ou `HH:MM` válido; `valid_until` vazio ou data ISO. Não precisa ser único (várias fixas no mesmo horário são permitidas).

### `campaign_runs` (evolução)

Hoje: `kind IN ('fixed', 'last')` e `UNIQUE(day, kind)`.

Novo: `kind` ∈ `{clock, last}`.

- **`clock`**: um run por campanha fixa por dia. Na criação já grava `campaign_id` e copia `clock` do cadastro. Unicidade: `UNIQUE(day, kind, campaign_id)` (assim duas fixas às 10:00 não colidem).
- **`last`**: um run por dia, como hoje. Unicidade: `UNIQUE(day, kind)` com `campaign_id` nulo até travar. Em SQLite isso exige índice parcial ou manter a constraint atual só para `last` e outra para `clock` — na implementação: índice único parcial `WHERE kind = 'last'` em `(day)` e índice único parcial `WHERE kind = 'clock'` em `(day, campaign_id)`.

Migração: runs antigos `kind='fixed'` deixam de ser criados (setting global some). Histórico antigo pode permanecer só para leitura ou ser ignorado pelo painel.

Campos de conteúdo (`campaign_id`, `image_id`, `text_id`, `manual`, `status`, `locked_at`, `sent_at`) e `campaign_run_groups` permanecem.

### `scheduled_posts` (slots rotativos na fila)

```sql
ALTER TABLE scheduled_posts ADD COLUMN post_kind TEXT NOT NULL DEFAULT 'book';
  -- 'book' | 'campaign'
ALTER TABLE scheduled_posts ADD COLUMN campaign_id INTEGER;
ALTER TABLE scheduled_posts ADD COLUMN image_id INTEGER;
ALTER TABLE scheduled_posts ADD COLUMN text_id INTEGER;
```

- Post `campaign`: sem linhas em `scheduled_books`. Caption e `image_path` espelham o texto/foto travados (para o envio reutilizar o caminho atual o máximo possível).
- Troca no board atualiza `campaign_id` / `image_id` / `text_id` e regenera caption/`image_path`.

Settings: remover uso de `invite_fixed_clock`. Manter `invite_last_offset_minutes`.

## Fluxo de envio

Ordem em cada volta de `scripts/enviar_fila.py`:

1. **`publish_due_fixed_campaigns`** — campanhas prontas com `fixed_clock` vencido na janela; um grupo por chamada; trava conteúdo na primeira vez.
2. **`publish_due_invite`** — só `kind=last` (convite final), pool rotativo.
3. **`publish_due`** — fila do dia; se `post_kind=campaign`, envia imagem + caption travados (sem montar card de livro).

Exceção em um passo não impede os outros. Gap e pausa de enquetes continuam em `send_gap`.

## Módulos

| Módulo | Papel |
| --- | --- |
| `campaign_rules.py` | Pronto com validade; separar pools fixa/rotativa; rodízio só rotativas; due de `fixed_clock` com graça 60 min |
| `campaign_store.py` | CRUD dos novos campos; `ready_rotating` / `ready_fixed`; runs `clock` + `last`; cursor rotativo |
| `campaign_send.py` | Fixas por clock; convite final só rotativas |
| `fila_csv.py` / aplicar | Parse `campanha`; pular keepa/resenha; na montagem escolher e travar |
| `board_store.py` | `post_kind` + ids de campanha; update de troca no board |
| `board_send.py` | Enviar post campanha sem livros |
| `campaign_panel.py` / pages | Campos horário/validade; etiquetas; sumir horário global; UI de gerar N textos |
| `campaign_copy.py` (novo) | Chama OpenAI com prompt fixo; devolve N strings ≤ 1024; sem gravar sozinho |
| `dashboard.py` | Rotas POST de gerar textos e de troca no `/hoje` |

## Painel

**`/campanhas`**

- Lista: etiquetas `fixa HH:MM` / `rotativa` / `vencida` / `incompleta`.
- Detalhe: editar `fixed_clock`, `valid_until`; fotos; textos; botão **Gerar variações** (quantidade 3–10).
- Geração: acrescenta N textos novos (não apaga existentes). Sem `openai_api_key`: botão desabilitado com aviso.
- Topo da lista: só “Convite final, minutos depois do último post” (some “Convite no horário”).

**`/hoje`**

- Cards dos disparos fixos do dia (um por campanha fixa pronta / run), com status e troca manual de campanha **fixa** pronta no mesmo espírito do convite atual.
- Card do convite final (rotativas).
- Na grade: posts campanha distintos; seletor de campanha rotativa + foto + texto.

## IA (textos)

- Mesma chave/modelo das resenhas (`openai_api_key`, `openai_model`).
- Prompt fixo no código: tom WhatsApp, promo/convite de grupos de livros; cada variação ≤ 1024 caracteres (limite de legenda de imagem).
- Falha/timeout: nada gravado; mensagem no painel; textos antigos intactos.

## Erros

- Foto do registro sumiu do disco: sorteia outra da mesma campanha; nenhuma válida → trata como não pronta / skipped.
- WAHA: mesmo retry da fila.
- Upload de foto: regras atuais (formato, 8 MB, etc.).
- Linha CSV `campanha` com lixo nas colunas de livro: ignorado, sem erro.
- Slot campanha sem conteúdo na hora do envio: `skipped` + warning.

## Testes

- `test_campaign_rules.py`: validade; pools fixa vs rotativa; due com graça; rodízio só rotativas.
- `test_fila_csv.py`: linha `campanha`; mistura com livros no mesmo arquivo.
- `test_fila_aplicar` / montagem: N slots → ordem do rodízio; sem rotativa → post vazio + aviso.
- `test_campaign_store.py`: `fixed_clock` / `valid_until`; duas fixas no mesmo horário no mesmo dia; um único `last` por dia.
- `test_campaign_send.py`: fixa no horário; coexistência com livro no mesmo clock; convite final só rotativas.
- `test_board_send.py` (ou equivalente): post `campaign` na fila.
- `test_dashboard_http.py` / painel: gerar N textos com API mock; troca no `/hoje`.

## Migração / compatibilidade

1. Adicionar colunas com default seguro (`post_kind='book'`, clocks/validity NULL).
2. Parar de ler/gravar `invite_fixed_clock`; limpar da UI.
3. Runs `kind='fixed'` antigos: não reutilizar no loop novo; painel de hoje só mostra `clock` + `last`.
4. Campanhas existentes sem `fixed_clock` passam a ser rotativas (comportamento alinhado ao rodízio atual de convites).
