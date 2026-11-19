# PROMPT — Gestor Natura Promoções (v1)

> Cole este documento inteiro no Cursor (Agent). Ele é a especificação completa do projeto. Trabalhe por fases (seção 17), confirme cada critério de aceite antes de seguir e não invente requisitos fora daqui. Quando algo não estiver definido, escolha a opção mais simples, registre em `docs/DECISOES.md` e siga.

---

## 0. Papel e regras de trabalho

Você é um engenheiro full-stack sênior. Vai construir do zero um sistema que publica promoções da Natura em grupos de WhatsApp a partir de uma fila diária.

Regras obrigatórias:

1. **Projeto de referência só para leitura:** `N:\Vibecoding\Promo Livros` (no Mac: `/Volumes/HD 1Tb/Vibecoding/Promo Livros`). Pode ler para copiar padrões. **Nunca crie, edite, mova ou apague nada nesse diretório.** Também não mexa no banco, no `.env`, no container `waha-livros` nem nos processos PM2 dele.
2. **Pasta do novo projeto:** `/Volumes/HD 1Tb/Vibecoding/Gestor Natura` (no Windows: `N:\Vibecoding\Gestor Natura`). Tudo fica no HD externo de 1 TB: código, SQLite, imagens e os arquivos do WAHA. O disco principal do Mac está sem espaço.
3. Idioma da interface, dos logs e dos textos: **português do Brasil**. Código e nomes de variáveis podem ser em inglês.
4. Fuso horário único: **America/Sao_Paulo** em tudo (agendamento, virada do dia, exibição).
5. Segredos só no `.env` (com `.env.example` commitado sem valores).
6. Escreva testes para a lógica pura: cálculo de preço, link, parse do CSV, slots, rodízio, virada do dia, worker com WAHA mockado.
7. Não use Baileys nem whatsapp-web.js. O WhatsApp é **só via WAHA** (HTTP).

---

## 1. Visão geral

Fluxo:

```
Extensão Chrome (busca do site da Natura — produtos Natura e Avon)
  → CSV com horários (produto ou promoção fixa, preço SEM cupom, URL, imagem…;
    a coluna `post` agrupa produtos "casados" que saem juntos no mesmo post)
  → Painel: Importar CSV
       → valida linhas (erros por linha)
       → baixa as imagens para o HD
       → garante o parâmetro consultoria no link
       → aplica o cupom global (preço final e % de economia)
       → IA gera a chamada de cada produto (ou 1 chamada geral no post casado, conforme configuração)
       → posts casados: gera a montagem (fotos lado a lado + preço com cupom de cada um)
       → nas linhas de promoção fixa: sorteia uma arte e a IA gera o texto
  → Fila do dia (horários do CSV, ajustáveis no painel)
  → Worker: no horário, envia foto + legenda para TODOS os grupos ativos,
    um grupo por vez, com delay aleatório entre eles
  → Enviados / métricas / logs (7 dias)
```

Escopo da v1: 1 número de WhatsApp, N grupos, 1 cupom global ativo, fila que zera todo dia. Um **post** pode ter **1 produto**, **vários produtos casados** (opcional, até um máximo configurável) ou ser uma **promoção fixa**.

---

## 2. Stack e infraestrutura

| Item | Decisão |
|---|---|
| App | **Next.js 15 (App Router) + TypeScript**, React Server Components onde fizer sentido |
| Banco | **SQLite** com `better-sqlite3` + **Drizzle ORM** (migrations versionadas). `journal_mode=WAL`, `busy_timeout=5000` |
| Worker | Processo Node separado (`worker/index.ts`, rodando com `tsx`) que importa a mesma camada de dados. Laço a cada 15 s |
| UI | Tailwind CSS + componentes próprios (sem biblioteca pesada). Drag-and-drop da fila com `@dnd-kit` |
| IA | `openai` (SDK oficial), modelo padrão `gpt-4.1-mini` (configurável no painel) |
| Arte por template | **satori + @resvg/resvg-js** no servidor → PNG 1080×1080 |
| CSV | `papaparse` |
| Validação | `zod` |
| Auth | Cookie de sessão assinado (`iron-session`), usuário e senha do `.env` |
| WhatsApp | **WAHA**, engine **GOWS**, container próprio `waha-natura` |
| Processos | **PM2** (`gestor-natura-web`, `gestor-natura-worker`) + Docker (WAHA) |
| Acesso externo | Cloudflare Tunnel (subdomínio do painel) |
| Testes | Vitest |

### Portas no Mac Mini

Já ocupadas, **não usar**: 3000 (WAHA da esteira), 3070 (amz-link-api), 4188 (site promolivros), 4443 (WAHA livros), 8787 (painel livros).

Usar: painel **3110**, WAHA **4444**. Ambos escutando só em `127.0.0.1`.

### Estrutura de pastas

```
Gestor Natura/
  app/                    # Next.js (rotas, páginas, API routes)
  components/
  lib/
    db/ (schema.ts, client.ts, migrations/)
    pricing.ts            # cupom, preço final, economia
    links.ts              # consultoria
    csv.ts                # parse + validação do CSV
    schedule.ts           # slots, espelho, excedente, próximo horário livre
    caption.ts            # template → legenda
    signatures.ts         # rodízio
    ai.ts                 # OpenAI (produto e fixa)
    images.ts             # download/armazenamento/limpeza
    art/                  # layouts satori (artes das fixas + montagem dos posts casados)
    grouping.ts           # posts casados: validar, juntar, separar, mover produto, regra de marcas
    whatsapp/
      provider.ts         # interface WhatsAppProvider
      waha.ts             # implementação WAHA
    logger.ts             # grava em system_logs
    time.ts               # helpers de fuso
  worker/index.ts
  extension/              # extensão Chrome MV3
  data/                   # gestor-natura.sqlite (gitignored)
  storage/
    products/AAAA-MM-DD/  # imagens baixadas (apagadas após 7 dias)
    arts/                 # artes das promoções fixas (permanentes)
  waha/
    docker-compose.yml
    sessions/             # volume da sessão (gitignored)
  docs/ (DECISOES.md, SETUP.md, mock/Main.dc.html, mock/Extensao.dc.html)
  ecosystem.config.cjs
  .env.example
```

---

## 3. Variáveis de ambiente (`.env.example`)

```
# Painel
DASHBOARD_USERNAME=
DASHBOARD_PASSWORD=
SESSION_SECRET=                # 32+ caracteres
PORT=3110
TZ=America/Sao_Paulo

# Banco e arquivos (caminhos absolutos no HD externo)
DATABASE_PATH=/Volumes/HD 1Tb/Vibecoding/Gestor Natura/data/gestor-natura.sqlite
STORAGE_DIR=/Volumes/HD 1Tb/Vibecoding/Gestor Natura/storage

# OpenAI
OPENAI_API_KEY=

# WAHA (só do Gestor Natura)
WAHA_URL=http://127.0.0.1:4444
WAHA_API_KEY=
WAHA_SESSION=natura
WAHA_DASHBOARD_USERNAME=
WAHA_DASHBOARD_PASSWORD=
```

Sem `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD`/`SESSION_SECRET` o painel **não sobe** (erro claro no console). Sem `OPENAI_API_KEY` o painel sobe, mostra um aviso e os posts saem sem a chamada.

---

## 4. Extensão Chrome (MV3) — captura

Pasta `extension/`. Use como base a estrutura de `Promo Livros/extensao/` (MV3, content script + painel lateral), **mas aqui a saída é um arquivo CSV**, sem falar com a API do painel.

### Comportamento

- `content_scripts` em `https://www.minhaloja.natura.com/*` (e `https://minhaloja.natura.com/*`). Atua na **página de resultados de busca**.
- O content script lê os cards de produto da página. **Inspecione o HTML real da busca** antes de escrever os seletores. Prefira dados estruturados se existirem (JSON embutido / `__NEXT_DATA__` / JSON-LD) e use o DOM como plano B. Isole os seletores em um único arquivo (`extension/selectors.js`) para manutenção.
- O painel lateral (side panel) mostra:
  - configurações: **horário de início**, **intervalo** (min), **consultoria** (opcional), **máximo de produtos por post** (1–4, padrão 2; 1 = nunca casa) e **regra de marcas** (Livre · 1 Natura + 1 Avon · Mesma marca), guardados em `chrome.storage.local`;
  - a lista de produtos encontrados (Natura e Avon), com checkbox (marcar/desmarcar todos), miniatura, nome, marca, de → por e o **horário calculado** de cada um;
  - em cada produto marcado, o botão **"Casar com o próximo"**: o próximo produto marcado entra no **mesmo post** (mesmo horário). Pode encadear até o máximo por post; ao atingir, o botão mostra "Post cheio (máx. N)" e fica desativado. Produtos casados aparecem ligados visualmente. Casar não consome slot de horário: o post inteiro ocupa um slot;
  - se um post casado violar a regra de marcas, mostrar um aviso no item (não bloqueia a exportação; o painel também avisa);
  - **inserir promoção fixa**: escolher a promoção (lista digitada nas configurações da extensão: id + nome) e a posição (após o N-ésimo item). A fixa ocupa um slot de horário;
  - resumo: "N posts · M linhas · 10:30 → 13:00 · a cada 25 min";
  - botão **Exportar CSV** → `fila-natura-AAAA-MM-DD.csv`.
- A extensão **não** gera texto, **não** aplica cupom e **não** monta imagem.

### Formato do CSV (contrato com o painel)

- Separador `;`, UTF-8 **com BOM**, todos os campos entre aspas (mesmo padrão dos CSVs do Promo Livros).
- Cabeçalho exato:

```
post;horario;tipo;promo_fixa;sku;nome;marca;linha;categoria;preco_de;preco_por;nota;avaliacoes;descricao;url;imagem
```

| Coluna | Regra |
|---|---|
| `post` | número sequencial do post (1, 2, 3…). **Linhas com o mesmo `post` saem juntas** (post casado) e devem ter o mesmo `horario`. Post de 1 produto ou fixa = número único |
| `horario` | `HH:MM` (obrigatório) |
| `tipo` | `produto` ou `fixa` |
| `promo_fixa` | id ou nome da promoção fixa (obrigatório se `tipo=fixa`; vazio se produto) |
| `sku` | código do produto (obrigatório se produto) |
| `nome`, `marca`, `linha`, `categoria` | texto |
| `preco_de`, `preco_por` | preço **sem cupom**. Aceitar `R$ 1.234,56`, `1234,56` e `1234.56` |
| `nota`, `avaliacoes` | opcionais |
| `descricao` | descrição curta / benefícios (insumo da IA) |
| `url` | link do produto (domínio `minhaloja.natura.com`) |
| `imagem` | URL da imagem do produto |

Exemplo de linhas:

```
"1";"10:30";"produto";"";"NATBRA-12345";"Ekos Polpa Hidratante Castanha 400 ml";"Natura";"Ekos";"Corpo";"R$ 99,90";"R$ 59,90";"4,8";"312";"Hidratação intensa com óleo de castanha…";"https://www.minhaloja.natura.com/p/…";"https://…/imagem.jpg"
"2";"10:55";"produto";"";"NATBRA-23456";"Humor Próprio Colônia Feminino 75 ml";"Natura";"Humor";"Perfumaria";"R$ 149,90";"R$ 104,90";"";"";"Floral frutado…";"https://www.minhaloja.natura.com/p/…";"https://…/humor.jpg"
"2";"10:55";"produto";"";"AVNBRA-34567";"Far Away Deo Colônia 50 ml";"Avon";"Far Away";"Perfumaria";"R$ 129,90";"R$ 64,90";"";"";"Oriental adocicado…";"https://www.minhaloja.natura.com/p/…?marca=avon";"https://…/faraway.jpg"
"3";"11:20";"fixa";"leve-3-ganhe-30";"";"";"";"";"";"";"";"";"";"";"";""
```

(As linhas com `post` = 2 formam um post casado Natura + Avon.)

Validação do agrupamento no painel: linhas do mesmo `post` com horários diferentes → erro; post com mais produtos que o máximo configurado → erro na linha excedente; fixa não pode ser casada com produto → erro; violação da regra de marcas → **aviso** (importa mesmo assim).

---

## 5. Modelo de dados (Drizzle / SQLite)

Valores monetários **em centavos (inteiro)**. Datas como texto ISO; o dia de serviço como `YYYY-MM-DD` e o horário como `HH:MM` no fuso de São Paulo.

```
settings            (key TEXT PK, value TEXT JSON)
  -- coupon_code, coupon_pct, consultoria, window_start, window_end, interval_min,
  -- delay_min_s, delay_max_s, tolerance_min, message_template, ai_model,
  -- ai_max_chars, signature_cursor,
  -- max_products_per_post (1–4, padrão 2), brand_rule ('free'|'mixed'|'same'),
  -- multi_text_mode ('per_product'|'general'), template_multi_block, template_multi_post

signatures          (id, text, active BOOL, position INT, created_at)

groups              (id, jid UNIQUE, name, active BOOL, members INT NULL, updated_at)

imports             (id, filename, created_at, rows_total, rows_ok, rows_error,
                     errors_json, mode TEXT -- 'replace' | 'append')

queue_items         (id, service_day, slot_time, position,          -- 1 linha = 1 POST
                     type TEXT -- 'product' | 'fixed'   (post de produto: 1 ou mais produtos),
                     import_id NULL, csv_post NULL,
                     -- fixa
                     fixed_promo_id NULL, fixed_art_id NULL,
                     -- post
                     ai_text NULL,          -- texto da fixa OU chamada geral do post casado
                     ai_error NULL, caption_override NULL,
                     montage_path NULL,     -- imagem gerada quando o post tem 2+ produtos
                     text_mode NULL,        -- 'per_product' | 'general' (herda da configuração)
                     signature_id NULL, mention_all BOOL DEFAULT 0,
                     status TEXT, -- 'pending' | 'sending' | 'sent' | 'partial' | 'failed' | 'skipped' | 'missed' | 'expired'
                     created_at, updated_at, sent_at NULL)

queue_products      (id, queue_item_id, position,                      -- produtos do post (1..max)
                     sku, name, brand, line, category, rating, reviews, description,
                     price_from_cents, price_promo_cents, price_final_cents, savings_pct,
                     source_url, final_url, image_url, image_path,
                     ai_text NULL, ai_error NULL)

dispatches          (id, queue_item_id, group_id, planned_at, sent_at NULL,
                     state TEXT, -- 'queued' | 'sent' | 'failed' | 'missed'
                     attempts INT, last_error NULL, message_id NULL)

fixed_promos        (id, slug UNIQUE, name, campaign_url, ai_brief, active BOOL, created_at)

fixed_promo_arts    (id, fixed_promo_id, origin TEXT -- 'upload' | 'template',
                     file_path, layout NULL, fields_json NULL, created_at)

ai_cache            (key TEXT PK, text, model, created_at)   -- key = sku + hash(description)

system_logs         (id, at, level TEXT -- 'INFO' | 'AVISO' | 'ERRO',
                     event TEXT, -- 'importacao' | 'fila' | 'envio' | 'whatsapp' | 'ia' | 'limpeza' | 'auth'
                     message, meta_json NULL)
```

Índices: `queue_items(service_day, slot_time)`, `queue_products(queue_item_id, position)`, `dispatches(state, planned_at)`, `system_logs(at)`.

**Atenção (herdado do Promo Livros):** o arquivo SQLite fica num volume que o Windows também enxerga pela rede. Documente em `docs/SETUP.md`: **não abrir o banco pelo Windows com o painel/worker rodando** (o WAL não aguenta clientes em máquinas diferentes).

---

## 6. Regras de negócio

### 6.1 Preço e cupom

- Um **cupom global ativo**: `coupon_code` + `coupon_pct`.
- `price_final = round(price_promo × (1 − coupon_pct/100))`
- `savings_pct = round((1 − price_final / price_from) × 100)`
- Exemplo (teste obrigatório): de R$ 100,00, por R$ 80,00, cupom 10% → final **R$ 72,00**, economia **28%**.
- Trocar o cupom nas Configurações **recalcula** preço final, economia e legenda de todos os itens `pending` da fila (não mexe nos enviados).
- Formatação BRL: `R$ 1.234,56`.

### 6.2 Link com consultoria

- Função `applyConsultoria(url, consultoria)`: aceita só `https://(www.)minhaloja.natura.com/...`. Define/substitui o parâmetro `consultoria` e **preserva todos os outros** (ex.: `marca=natura`). Idempotente.
- Exemplo: `https://www.minhaloja.natura.com/c/promocao-da-semana?marca=natura` + `pechincheiro` → `https://www.minhaloja.natura.com/c/promocao-da-semana?marca=natura&consultoria=pechincheiro`. Se o CSV já trouxer outra consultoria, a do painel vence.
- URL fora do domínio = erro de linha na importação.

### 6.3 Fila diária e horários

- A fila pertence a um `service_day`. **Às 00:00** (São Paulo) a virada do dia marca os itens `pending` do dia anterior como `expired` (saem da tela Hoje). Enviados ficam em Enviados.
- Os **horários vêm do CSV**.
- Linhas cujo horário já passou na hora da importação (mais que a tolerância) são movidas, mantendo a ordem, para o **próximo horário livre** em diante, usando o intervalo do CSV (a mediana das diferenças entre linhas consecutivas; se não der para inferir, o intervalo padrão das Configurações).
- **Janela** (`window_start`–`window_end`, padrão 08:00–22:00). Itens com horário depois do fim da janela são **excedente**. O painel avisa e oferece:
  1. **Ajustar o intervalo**: mostra o **espelho da fila** (antes → depois de cada item, quais ainda excedem) para intervalos de 15/20/25/30 min ou um valor digitado, com o resumo "Com 20 min cabem os 34 itens. Último às 21:30.";
  2. **Descartar o excedente**.
- No painel também posso: editar o horário de um item, arrastar para reordenar (os horários ficam nos slots e os itens trocam de lugar), pular, remover, editar texto, regerar texto e **redistribuir a fila inteira por intervalo** (mesmo espelho).
- **Segunda importação no mesmo dia:** perguntar **Substituir os pendentes** (padrão) ou **Acrescentar depois do último item**.
- Não há revalidação de preço/estoque: o sistema confia no CSV.

### 6.4 Envio e desconexão

- No `slot_time` do item, o worker cria **uma linha em `dispatches` por grupo ativo**. O primeiro grupo sai na hora; cada próximo espera um **delay aleatório** entre `delay_min_s` e `delay_max_s` (padrão 20–60 s).
- Antes de cada envio, o worker confere o status da sessão. Se não for `WORKING`:
  - a fila **pausa** e o painel mostra o **banner vermelho** (seção 9);
  - quando um slot passa da tolerância (`tolerance_min`, padrão 10 min) sem conseguir enviar, o item vira **`missed` ("não enviado")** e os dispatches pendentes viram `missed`;
  - ao reconectar, o worker **segue do próximo horário** (não manda os atrasados em rajada).
- Item `missed` → botão **Reagendar** (vai para o próximo horário livre).
- Falha de envio em um grupo: até 3 tentativas com backoff (15 s, 45 s, 90 s) dentro da tolerância. Se esgotar: dispatch `failed`; o item vira `partial` (algum grupo recebeu) ou `failed` (nenhum). Botão **Tentar de novo** reenvia **só os grupos que falharam**.
- Um horário que passou há menos que a tolerância ainda sai (ex.: worker reiniciado).

### 6.5 Menção a todos

- **Desligada por padrão.** Cada item da fila tem o botão **@todos** (liga/desliga) ao lado do post.
- Ligado: menção oculta (todos os participantes do grupo no campo de menções, **sem** @ visíveis na legenda). Busque os participantes no WAHA no momento do envio (cache de 10 min por grupo).

### 6.6 Assinaturas em rodízio

- Linhas finais cadastradas (ativas/inativas, ordem). Ao montar a fila, cada item recebe a **próxima assinatura ativa** a partir de `signature_cursor`, que avança e dá a volta. Padrão do `/assinaturas` do Promo Livros.

### 6.7 Imagens

- Na importação, baixar a `imagem` de cada produto para `storage/products/AAAA-MM-DD/<sku>.<ext>` (timeout 15 s, 2 tentativas, só `image/*`, máx. 5 MB). Falha → item com aviso, prévia com placeholder; o envio usa a URL original como alternativa.
- O envio manda o arquivo local (base64), não a URL.
- **Limpeza diária às 04:00**: apaga imagens de produto e `system_logs` com mais de **7 dias**. Artes das fixas são permanentes. Histórico de `queue_items`/`dispatches`: manter 30 dias (configurável).

### 6.8 Posts casados (vários produtos no mesmo post) — opcional

- Um post de produto tem de 1 até `max_products_per_post` produtos (padrão 2, configurável de 1 a 4). Com o máximo em 1, o recurso fica desligado.
- Combinações livres: 2 Natura, 2 Avon, 1 Natura + 1 Avon etc. A **regra de marcas** é opcional: `free` (padrão) · `mixed` (pelo menos 1 Natura e 1 Avon) · `same` (todos da mesma marca). Violação = **aviso** visível na importação e no item da fila; não impede o envio.
- **Origem do agrupamento:** a coluna `post` do CSV (extensão, botão "Casar com o próximo").
- **No painel**, na fila:
  - **Juntar com o próximo** (em item pendente de 1 produto, respeitando o máximo);
  - **Separar** (o post casado vira posts individuais: o primeiro fica no horário e os outros vão para os próximos horários livres, com aviso de excedente se precisar);
  - **Trocar/mover produto** entre posts pendentes (arrastar o produto de um post para outro).
- Cada produto tem o próprio preço final com cupom, economia e link (com `consultoria` e a `marca` correta).
- **Imagem:** gerar uma **montagem** (`montage_path`) com as fotos lado a lado (2 = duas colunas; 3–4 = grade) e, sobre cada foto, uma etiqueta com o preço final com cupom. PNG 1080×1080, gerado com satori + resvg a partir das imagens baixadas, refeito quando o post muda (juntar/separar/trocar ou troca de cupom). O envio continua sendo **1 mensagem por grupo** (montagem + legenda).
- **Texto:** configurável em `multi_text_mode` (padrão nas Configurações, com troca por post na prévia):
  - `per_product`: uma chamada de IA para cada produto, um bloco por produto;
  - `general`: uma única chamada de IA para o post todo + blocos curtos (nome, preços, link).
- Menção a todos, assinatura, disparos e status valem para o post inteiro.

---

## 7. IA (OpenAI)

Adapte o padrão de `Promo Livros/promo_livros/blurb.py` (texto curto, validação, cache, falhar sem inventar). Não use `web_search`: a descrição vem no CSV.

### 7.1 Chamada de produto (na importação)

- Entrada: nome, marca, linha, categoria, descrição, nota/avaliações.
- Saída: **1 frase** (no máximo `ai_max_chars`, padrão 160), tom de grupo de promoções, natural, sem exagero.
- Proibido no texto: preço, %, cupom, link, frete, promessas de saúde/medicinais e informações que não estejam na entrada.
- Validar (tamanho, sem `R$`/`%`/URL). Uma nova tentativa se falhar. Se falhar de novo: `ai_text = null`, `ai_error` preenchido, log `ia`, e o post sai sem a chamada.
- Concorrência máx. 4 chamadas simultâneas, com barra de progresso na importação.
- Cache em `ai_cache` (chave = sku + hash da descrição).
- Chave recusada (401/403) → interrompe as próximas chamadas daquela importação e avisa.
- Botão **Regerar texto** por item (ignora o cache).

### 7.1b Chamada geral de post casado (`multi_text_mode = general`)

- Entrada: os dados de todos os produtos do post.
- Saída: 1 frase que apresenta o conjunto (ex.: "Dupla perfumada do dia: um floral leve da Natura e um clássico da Avon…"), mesmas proibições e validações da 7.1, mesmo cache (chave = skus ordenados + hashes).
- No modo `per_product`, usa a chamada individual de cada produto (7.1). Trocar o modo na prévia gera o que faltar, sem refazer o que já existe.

### 7.2 Texto de promoção fixa (ao entrar na fila)

- Entrada: `ai_brief` da promoção + cupom vigente.
- Saída: 1–2 frases, variando a cada inserção (temperatura mais alta; envie também os textos já usados hoje para evitar repetição).
- Ao entrar na fila (pelo CSV ou pelo painel): **sorteia uma arte** da promoção (evitar repetir a última usada) e gera o texto. Os dois ficam editáveis (trocar arte / regerar texto).

---

## 8. Legenda (template)

- Template configurável nas Configurações, com as variáveis:
  `{chamada} {nome} {marca} {linha} {categoria} {nota} {preco_de} {preco_por} {preco_final} {cupom} {cupom_pct} {economia_pct} {link} {assinatura}`
- Template padrão (produto):

```
{chamada}

*{nome}*
De ~{preco_de}~ por {preco_por}
Com o cupom *{cupom}*: *{preco_final}* ({economia_pct} de economia)

{link}

{assinatura}
```

- Template padrão (fixa):

```
{chamada}

Cupom *{cupom}*: mais {cupom_pct} no carrinho.

{link}

{assinatura}
```

- Templates de post casado (dois campos nas Configurações):
  - `template_multi_block` — repetido para cada produto:

```
{chamada_produto}
*{nome}*
De ~{preco_de}~ por {preco_por}
c/ cupom: *{preco_final}* ({economia_pct} de economia)
{link}
```

  - `template_multi_post` — envolve os blocos:

```
{chamada_geral}

{blocos}

Use o cupom *{cupom}* em todos.

{assinatura}
```

  - No modo `per_product`, `{chamada_geral}` fica vazio e a linha some. No modo `general`, `{chamada_produto}` fica vazio e a linha some de cada bloco. Os blocos são separados por uma linha em branco.
- Linha cuja variável principal vier vazia é removida (ex.: sem `{chamada}`, a primeira linha some, sem deixar linhas em branco duplicadas).
- `caption_override` (edição manual no painel) tem prioridade sobre o template.
- Prévia no painel no estilo de balão do WhatsApp (imagem + texto, mostrando `*negrito*` e `~riscado~` renderizados).

---

## 9. Painel (rotas e telas)

Login obrigatório em todas as rotas (middleware). Visual igual ao mock (seção 10). Polling de `/api/status` a cada 10 s para o banner e os contadores.

1. **`/` Fila do dia (Hoje)**
   - Cartões: Na fila hoje · Enviados · Não enviados · Falhas · Próximo envio (ou "pausado").
   - Barra: **Importar CSV**, **Inserir promoção fixa**, **Redistribuir por intervalo**, resumo da janela/intervalo/delay.
   - Tabela: horário · miniatura · item (nome + marca/linha ou "Promoção fixa · arte X de Y (sorteada)") · preços (de riscado, por, final com cupom) · status (chip + nota, ex.: "falhou em 1 de 3 grupos") · ações (**@todos**, ↑ ↓ / arrastar, **Reagendar** para não enviado, **Tentar de novo** para falha).
   - **Post casado** na tabela: miniatura dividida com as cores/fotos dos produtos e o selo "2×"; nome "Produto A + Produto B"; subtítulo "Post casado · 2 produtos · Natura + Avon"; preços de cada produto separados por " · "; ações extras **Separar** e (em item de 1 produto) **Juntar com o próximo**.
   - Item "próximo" destacado. Clicar no item abre a **prévia** à direita: balão do WhatsApp (no post casado mostra a **montagem**), seletor **"Texto do post casado: 1 chamada por produto | 1 chamada geral"**, estado do "mencionar todos", botões Regerar texto / Editar / Trocar arte (fixa) / Pular, e a lista **Disparos deste item** (estado por grupo).
2. **Modal Importar CSV**
   - Upload → contadores (linhas lidas, produtos, fixas, com erro) → lista de erros por linha → etapas com progresso (imagens, consultoria, cupom, IA, fixas) → aviso de excedente com **Ajustar intervalo (espelho)** ou **Descartar excedentes** → **Aplicar na fila**.
   - Espelho: seletor de intervalo, resumo do que cabe, tabela # · item · antes · depois (vermelho quando excede).
3. **`/fixas` Promoções fixas**
   - Lista (nome, nº de artes, uso hoje, ativa/pausada) + **Nova promoção fixa**.
   - Edição: nome, link da campanha (consultoria aplicada), **informações para a IA**, grade de artes (upload PNG/JPG ou "Criar por template").
   - **Editor por template**: 4 layouts (**Faixa**, **Centro**, **Dividido**, **Selo**), campos título / subtítulo / desconto em destaque / mostrar cupom / cor (4 opções + hex) / imagem de fundo opcional, **preview ao vivo**, **Salvar arte (PNG 1080×1080)** gerado no servidor (satori + resvg).
4. **`/assinaturas`** — lista ordenável, ativa/inativa, marca "próxima", adicionar/editar/remover.
5. **`/configuracoes`** — cupom (código, %, com fórmula e exemplo), consultoria (com exemplo de link), janela/intervalo, delay mín./máx., tolerância, modelo da IA, máximo de caracteres, bloco **Posts com vários produtos (casados)** (máximo por post 1–4, regra de marcas, modo de texto da IA), templates (produto, fixa, bloco e post casado) com chips de variáveis clicáveis.
6. **`/whatsapp`** — status da sessão (número, sessão, container/porta, engine), **QR** para parear quando desconectado (atualiza sozinho), **Gerar novo QR**, lista de grupos da sessão com checkbox (ativo) e nº de membros, **Atualizar lista**.
7. **`/enviados`** — histórico: horário, item, grupos (x/y), menção, resultado; filtro por dia.
8. **`/logs`** — filtros Todos / Só erros / WhatsApp / Envio / Importação / IA; tabela monoespaçada; nota de retenção de 7 dias.

**Banner de desconexão** (todas as telas, topo): fundo vermelho forte, ícone de alerta, "WhatsApp desconectado desde HH:MM — fila pausada", texto explicando que os horários perdidos ficam como "não enviado" e que o envio segue do próximo horário, botão **Reconectar (QR)** → `/whatsapp`. A barra lateral também mostra o status (bolinha verde/vermelha + `waha-natura · :4444 · GOWS`).

### API (route handlers)

```
POST /api/auth/login | POST /api/auth/logout
GET  /api/status                      # sessão WA, contadores, próximo envio, banner
GET  /api/queue?day=                  # itens + dispatches
POST /api/import                      # multipart → preview {rows, errors, excess}
POST /api/import/:id/apply            # {mode, interval?, discardExcess?} → job
GET  /api/import/:id/progress         # progresso das etapas
GET  /api/queue/mirror?interval=      # espelho
POST /api/queue/redistribute          # {interval}
PATCH /api/queue/:id                  # horário, caption_override, mention_all, posição
POST /api/queue/:id/regenerate | /skip | /reschedule | /retry | /swap-art
POST /api/queue/:id/join-next | /split          # posts casados
POST /api/queue/move-product          # {productId, toQueueItemId}
PATCH /api/queue/:id/text-mode        # {mode: 'per_product'|'general'}
POST /api/queue/insert-fixed          # {fixedPromoId, afterPosition}
CRUD /api/fixed-promos, /api/fixed-promos/:id/arts (upload | template)
POST /api/art/preview                 # PNG do template (preview)
CRUD /api/signatures
GET/PUT /api/settings
GET  /api/whatsapp/session | POST /api/whatsapp/start | GET /api/whatsapp/qr
GET  /api/whatsapp/groups | PUT /api/groups/:id
GET  /api/sent?day= | GET /api/logs?filter=
```

---

## 10. Design (seguir o mock)

Existe um mock navegável com o painel e a extensão. Os arquivos estão em **`docs/mock/`** (copie para lá antes de começar):

- `docs/mock/Main.dc.html` — painel inteiro: Fila (com post casado, prévia, montagem, @todos, reagendar/tentar de novo), modal de importação com espelho, Promoções fixas com editor de 4 layouts, Assinaturas, Configurações, WhatsApp, Enviados e Logs;
- `docs/mock/Extensao.dc.html` — painel lateral da extensão (seleção, "Casar com o próximo", máximo por post, regra de marcas, inserir fixa, exportar CSV).

São HTML + JS num formato de protótipo (marcação com `{{variáveis}}`, `<sc-for>`/`<sc-if>` e uma classe `Component` com os dados de exemplo e a lógica de interação). **Use-os como referência de layout, textos, estados e comportamento, não como código para copiar.** Reimplemente em React/Tailwind. Onde o mock e este documento divergirem, vale este documento. Os dados do mock são de exemplo.

Reproduza:

- **Fontes:** IBM Plex Sans (UI) e IBM Plex Mono (horários, números, códigos).
- **Cores:** fundo `#F4F2EC`; superfície `#FFFFFF`; barra superior `#FBFAF6`; texto `#1D1C1A`; texto secundário `#5F5B53`; bordas `#E2DED4` / `#CFCABE`; barra lateral `#1D1C1A`.
- **Destaque:** verde `#0B6B5A` (hover `#07493D`, fundo suave `#E3F0EC`, texto `#0B4F43`).
- **Estados:** sucesso `#1E6B3A` sobre `#E2F2E6`; aviso `#6B4600` sobre `#FBF0D9`; erro `#8A1F16` sobre `#FBE4E1`; banner de desconexão `#A1251B` com texto branco.
- **Layout:** barra lateral escura com menu e status do WhatsApp; conteúdo com cartões brancos de borda fina e cantos de 12 px; chips arredondados para status; tabela da fila com linha selecionada em `#EEF6F3` e filete verde à esquerda.
- **Responsivo:** em telas estreitas o menu empilha em cima e as tabelas rolam na horizontal.
- **Acessibilidade:** botões reais, `aria-label` nos botões só com ícone, `aria-pressed` nos toggles, contraste AA.
- Sem emojis na interface (a legenda do post pode ter, se o usuário escrever).

---

## 11. WhatsApp — WAHA

### 11.1 Container próprio no HD externo

`waha/docker-compose.yml` (rodar via ssh no Mac):

```yaml
services:
  waha-natura:
    image: devlikeapro/waha:arm        # mesma imagem/versão do waha-livros (2026.9.1); confira
    container_name: waha-natura
    restart: unless-stopped
    ports:
      - "127.0.0.1:4444:3000"
    environment:
      - WHATSAPP_DEFAULT_ENGINE=GOWS
      - WAHA_API_KEY=${WAHA_API_KEY}
      - WAHA_DASHBOARD_USERNAME=${WAHA_DASHBOARD_USERNAME}
      - WAHA_DASHBOARD_PASSWORD=${WAHA_DASHBOARD_PASSWORD}
      - TZ=America/Sao_Paulo
    volumes:
      - ./sessions:/app/.sessions
```

- Desde a versão 2026.6.1, o WAHA Core (gratuito) inclui todos os recursos que eram do Plus (mídia, várias sessões etc.).
- Compose e volume de sessões ficam no HD. Para que a **imagem** também fique no HD, é preciso mudar o local do disco virtual do runtime Docker do Mac (Docker Desktop → Resources → Disk image location; OrbStack/Colima têm opção equivalente). Documente em `docs/SETUP.md` e confirme qual runtime está instalado (`docker context ls`, `docker info`).
- **Não reutilize** o container `waha-livros` nem a porta 4443.

### 11.2 Interface e implementação

```ts
interface WhatsAppProvider {
  sessionStatus(): Promise<'WORKING' | 'SCAN_QR' | 'STARTING' | 'STOPPED' | 'FAILED'>;
  startSession(): Promise<void>;
  qrPng(): Promise<Buffer>;
  me(): Promise<{ id: string; pushName?: string } | null>;
  listGroups(): Promise<{ jid: string; name: string; members?: number }[]>;
  participants(jid: string): Promise<string[]>;
  sendImage(p: { chatId: string; caption: string; image: { mimetype: string; filename: string; base64: string }; mentions?: string[] }): Promise<{ messageId: string }>;
}
```

`lib/whatsapp/waha.ts` porta a lógica de `Promo Livros/promo_livros/waha.py`:

- cabeçalho `X-Api-Key`;
- mapeamento de status;
- detecção de "sessão caída" na resposta (para pausar a fila, não para contar como falha do grupo);
- extração do id da mensagem;
- tratamento de erro com mensagem legível.

Endpoints usados (confirme no Swagger do próprio container em `http://127.0.0.1:4444/`):

- `GET /api/sessions/{session}`
- `POST /api/sessions/{session}/start` (ou criar a sessão se não existir)
- `GET /api/{session}/auth/qr` (formato imagem)
- `GET /api/sessions/{session}/me`
- `GET /api/{session}/groups`
- `GET /api/{session}/groups/{id}/participants`
- `POST /api/sendImage` com `{ session, chatId, caption, file: { mimetype, filename, data }, mentions? }`

**Menção oculta:** passe os ids dos participantes em `mentions` sem colocar @ no texto. Valide com o engine GOWS num grupo de teste; se o WAHA aceitar um atalho para "todos", pode usar, mas mantenha a lista explícita como plano B.

---

## 12. Worker (`worker/index.ts`)

Processo PM2 separado. A cada 15 s:

1. **Virada do dia** (00:00) → `expired` nos `pending` do dia anterior. Log `fila`.
2. **Limpeza** (04:00, uma vez por dia) → imagens e logs com mais de 7 dias, histórico com mais de 30 dias. Log `limpeza`.
3. **Status do WhatsApp** → guarda em memória e numa tabela/setting para o `/api/status`; registra transições (caiu às HH:MM / voltou). Se caiu: pausa.
4. **Itens vencidos sem envio** (passaram da tolerância e a sessão estava fora) → `missed`.
5. **Itens a disparar** (`pending` com `slot_time <= agora` dentro da tolerância e sessão `WORKING`) → `sending`, cria os dispatches com `planned_at` escalonado (delay aleatório acumulado).
6. **Dispatches a enviar** (`queued` com `planned_at <= agora`) → monta a legenda final, anexa a imagem (1 produto: foto local; post casado: montagem; fixa: arte sorteada), resolve as menções se `mention_all`, envia, atualiza o estado, tenta de novo com backoff.
7. Fecha o item quando todos os dispatches terminarem → `sent` / `partial` / `failed`, com `sent_at`.

Robustez:

- Lock por item (transação + estado `sending`) para nunca enviar em duplicidade, mesmo com reinício.
- Ao subir, retoma dispatches `queued` ainda dentro da tolerância.
- Todos os eventos vão para `system_logs`.

---

## 13. Importação (detalhe)

1. `POST /api/import`: parse com papaparse (BOM, `;`), validação zod por linha, erros por linha ("Linha 17 — preco_por vazio", "Linha 23 — url fora de minhaloja.natura.com", "Linha 9 — promoção fixa 'xyz' não encontrada"), cálculo de slots/excedente → preview.
2. `POST /api/import/:id/apply` cria um job (em memória + tabela `imports`), executado em etapas com progresso: baixar imagens → consultoria → cupom → IA (produtos) → fixas (sorteio da arte + IA) → gravar `queue_items` com a assinatura do rodízio.
3. Se `mode=replace`: os `pending` do dia viram `skipped` antes de gravar.
4. Linhas com erro não entram. A importação continua com as válidas.

---

## 14. Processos e deploy (Mac Mini, via ssh)

- `ecosystem.config.cjs` com `gestor-natura-web` (`next start -p 3110`) e `gestor-natura-worker` (`tsx worker/index.ts`), `cwd` no HD, logs do PM2 também no HD (`./logs`).
- Cloudflare Tunnel: novo hostname para o painel → `http://127.0.0.1:3110` (e, opcional, outro para o dashboard do WAHA → `:4444`). **Não edite nem reinicie** os túneis existentes do Promo Livros / Mac Capture sem pedir; crie uma entrada nova ou um túnel novo e documente.
- `docs/SETUP.md`: passo a passo (instalar dependências no HD, `.env`, migrations, subir WAHA, parear QR, entrar nos grupos, PM2, túnel, carregar a extensão em modo desenvolvedor).

---

## 15. Fora do escopo da v1

- Revalidação de preço/estoque antes do envio
- Vários números/sessões
- Grupos diferentes por tipo de post
- Fila multi-dia / reciclagem de ofertas
- Rastreamento de cliques
- Alerta externo (Telegram/WhatsApp) de desconexão
- Editor de arte livre (estilo Canva)
- Extensão mandando os itens direto para o painel

---

## 16. O que portar do Promo Livros (ler, nunca alterar)

| Arquivo no livros | Uso aqui |
|---|---|
| `promo_livros/waha.py` | `lib/whatsapp/waha.ts` (status, QR, grupos, participantes, envio, sessão caída) |
| `promo_livros/dispatch.py` + tabela `dispatches` | Worker: uma linha por grupo, espera entre grupos, nova tentativa |
| `promo_livros/dashboard_auth.py` | Login por usuário/senha do `.env` |
| `promo_livros/fila_csv.py` | Parse com erro por linha e prévia antes de aplicar |
| `promo_livros/blurb.py` | Regras da IA (curto, validação, cache, sem inventar) |
| `/assinaturas` (dashboard) | Rodízio de assinaturas |
| Virada à meia-noite e tolerância | `lib/schedule.ts` / worker |
| `extensao/` | Estrutura MV3 + painel lateral da extensão |
| `config.yaml` (bloco `whatsapp`) e o README (seção WhatsApp) | Setup do container próprio |

---

## 17. Plano por fases (com critérios de aceite)

**Fase 1 — Base**
Next.js + Tailwind + Drizzle + migrations + login + layout (barra lateral, topo, banner) + `system_logs` + `settings` com valores padrão.
✅ Login funciona; sem as variáveis de ambiente o painel não sobe; as telas vazias navegam.

**Fase 2 — Regras puras + testes**
`pricing`, `links`, `csv` (incluindo a coluna `post`), `schedule` (slots, próximo livre, excedente, espelho, redistribuir), `grouping` (máximo por post, regra de marcas, juntar/separar/mover), `caption` (1 produto, casado nos dois modos, fixa), `signatures`, `time`.
✅ Vitest verde, incluindo o exemplo 100/80/10% → R$ 72,00 / 28%, o link com consultoria preservando `marca` e um post casado Natura + Avon nos dois modos de texto.

**Fase 3 — Importação + IA + imagens**
Modal completo, job com progresso, download de imagens, IA com cache e falha segura, prévia do post.
✅ Importar um CSV de exemplo gera a fila com textos, preços e imagens (posts casados com montagem); erros e avisos aparecem por linha; o excedente oferece espelho/descartar.

**Fase 4 — Fila interativa**
Arrastar, editar horário, pular, regerar, @todos, inserir fixa, redistribuir, segunda importação (substituir/acrescentar), juntar/separar/mover produto, modo de texto por post.
✅ Todas as ações persistem; a prévia e a montagem acompanham.

**Fase 5 — Promoções fixas + artes**
CRUD, upload, editor de 4 layouts com preview ao vivo, PNG 1080×1080, sorteio de arte ao entrar na fila.
✅ Fixa vinda do CSV ou do painel entra com arte sorteada e texto IA editáveis.

**Fase 6 — WAHA + tela WhatsApp**
`docker-compose`, provider, status, QR, grupos, participantes.
✅ Parear pelo painel; listar e ativar grupos; envio de teste para 1 grupo com imagem e legenda.

**Fase 7 — Worker**
Disparos por grupo com delay aleatório, tentativas, `missed` em desconexão, retomada, virada do dia, limpeza.
✅ Simulando queda (parar o container): banner aparece, item vira "não enviado", ao voltar segue do próximo horário; nenhum envio duplicado após reiniciar o worker.

**Fase 8 — Extensão**
Captura na busca da Natura (Natura e Avon), painel lateral, horários, "Casar com o próximo" com máximo e regra de marcas, inserir fixa, exportar CSV no contrato da seção 4.
✅ O CSV exportado importa sem erros no painel.

**Fase 9 — Deploy**
PM2, túnel, `docs/SETUP.md`, `README.md`.
✅ Sistema rodando no Mac Mini a partir do HD externo, acessível pelo subdomínio com login.

---

## 18. Dados de exemplo para desenvolvimento

Crie `docs/exemplo-fila.csv` com ~12 produtos plausíveis (Natura: Kaiak, Ekos, Tododia, Una, Essencial, Chronos, Humor; Avon: Far Away, Renew, Avon Care), incluindo **2 posts casados** (1 Natura + 1 Avon, e 2 Natura) e 2 linhas de fixa (`leve-3-ganhe-30`, `semana-ekos`). Crie um seed com:

- cupom `PECHINCHA15` / 15%;
- consultoria `pechincheiro`;
- janela 08:00–22:00, intervalo 30 min, delay 20–60 s, tolerância 10 min;
- máximo de 2 produtos por post, regra de marcas livre, texto "1 chamada por produto";
- 4 assinaturas;
- as 2 promoções fixas com 1 arte de template cada.
