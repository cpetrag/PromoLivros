# Magazine Luiza no Promo Livros

## Objetivo

Incluir a Magazine Luiza como loja no sistema, no mesmo papel da Shopee: Amazon continua o lado principal do post; Magalu divide a segunda metade com Mercado Livre e Shopee.

No CSV da fila, links Magalu são monetizados (rewrite de URL com IDs de afiliado, sem API Magalu) e depois encurtados no Aqui (`aqui.descontos.ai`). Sem encurtador ok, a oferta Magalu fica de fora daquela linha/post.

## Decisões

| Tema | Escolha |
|---|---|
| Lado do post | Amazon principal; Magalu na 2ª metade (com ML/Shopee) |
| Abordagem de catálogo | Espelhar Shopee (`ml_books` + detecção por id/URL) |
| Colunas do CSV da fila | Reusar `asin_ml` / `link_ml` / preços `_ml` |
| Conversão + encurtar | Só no aplicar do CSV da fila (neste ciclo) |
| Sem Aqui / falha Magalu | Oferta Magalu fora (`LinkQuebrado` / ignorado) |
| Encurtador | Serviço existente; Promo Livros só cliente HTTP |
| Quem usa o Aqui | Somente Magalu (Amazon/ML/Shopee não) |

## Fora de escopo

- Converter/encurtar Magalu na Curadoria / `publish_selection`
- Implementar o núcleo do encurtador (já existe em `aqui.descontos.ai`)
- Encurtar Amazon, Mercado Livre ou Shopee
- Terceiro lado no post (máximo continua 2 ofertas)
- Painel/analytics do Aqui

## Arquitetura

```
CSV Magalu / Curadoria  →  catalog (ml_books, store=magalu)
                              ↓
montar_fila: Amazon × (ML | Shopee | Magalu) por índice
                              ↓
CSV da fila (aplicar):  magalu_links.converter → Aqui POST /links → shortUrl no post
                              ↓
Curadoria aplicar:      Magalu grava URL do catálogo (sem converter/encurtar neste ciclo)
```

## Identidade Magalu

Hosts tratados como Magalu (hostname contém):

- `magazineluiza`
- `magazinevoce`
- `divulgador.magalu`
- `influenciadormagalu`
- `magalu.com`

`product_id` no catálogo: código do path de produto (`/p/{codigo}/…` ou equivalente normalizado no import).

Atualizar:

- `promo_livros/lojas.py` — `store_of`, `STORE_ORDER` (`amazon` → `ml` → `shopee` → `magalu`)
- `catalog._second_store_of` / `_in_second_store` — reconhecer Magalu além de ML/Shopee

## Catálogo e Curadoria

- `CatalogStore.replace_magalu` via `_replace_second("magalu", …)` na mesma tabela `ml_books`
- Import de CSV em `CSV Atualizado/` no padrão `magalu-livros*.csv` / `magalu_livros_*.csv` (espelho Shopee)
- Nova aba na Curadoria: Magazine Luiza
- Marks Magalu entram na lista da segunda metade junto com ML e Shopee (ordem de marcação / `pick_seq`)
- Labels/cores na grade e Curadoria incluem Magalu
- `post_copy` / ordem de lojas incluem Magalu quando o post já tiver essa URL

## Fila

- `montar_fila`: segunda lista = ML + Shopee + Magalu
- `SlotFila` ganha campo `magalu` (espelho de `shopee`); em cada índice cabe no máximo uma das três
- Sem peso percentual nem rodízio de loja — só índice + ordem de marcação
- `extra` / segunda oferta Amazon no CSV da fila continua válida; máx. 2 ofertas por linha

## CSV da fila

Colunas obrigatórias atuais permanecem. Magalu entra quando `link_ml` (ou id) for Magalu → `store=magalu`.

Parse (`parse_fila_csv`):

- Detectar Magalu antes de cair em ML genérico (hosts Magalu / path `/p/` Magalu)
- Aceitar Magalu como origem da segunda oferta nas colunas `_ml`
- Mensagens de erro/aviso citam Magazine Luiza quando couber

Prévia e modal de passos:

- Nome da loja nos passos: “da Magazine Luiza”
- Passo `link` chama o conversor Magalu + Aqui

## Conversão Magalu (`magalu_links.py`)

Sem API Magalu. Só reescrever URL com afiliado.

Credenciais (sempre do `.env`, nunca hardcoded):

- `MAGALU_PROMOTER_ID`
- `MAGALU_PARTNER_ID`

Se a URL original tiver `seller_id`, preservar.

### Regras (nessa ordem)

1. **Redirect divulgador** — se a URL contém `divulgador.magalu.com`: seguir redirect até a URL final do produto; aplicar as regras abaixo nela.
2. **Link de produto (`/p/`)** — trocar o segmento `p` por `divulgador/oferta`; manter slug, código, sku e segmentos relevantes; setar/sobrescrever `promoter_id` e `partner_id`; preservar `seller_id`.
3. **Já é divulgador** — normalizar para `…/{slug}/divulgador/oferta/{codigo}/{sku}/…/`; sobrescrever `promoter_id` e `partner_id`; preservar `seller_id`.
4. **Qualquer outro Magalu** — manter URL; só adicionar/sobrescrever `promoter_id`, `partner_id` e `seller_id` (este só se já existia).

Não inventar parâmetros além desses três. Não alterar URL que não for Magalu.

### Retorno interno do conversor

```text
link_convertido, tipo (produto | divulgador | generico | redirect_resolvido), ok, erro
```

URL inválida → devolver original com `ok=false`.

## Encurtador Aqui (cliente)

Módulo cliente (ex.: `aqui_links.py`). Só Magalu chama no passo `link` do CSV.

- Base: `AQUI_BASE_URL` (default `https://aqui.descontos.ai`)
- Auth: `Authorization: Bearer $AQUI_API_KEY` (API também aceita `X-Api-Key`)
- `POST /api/v1/links` com JSON `{ "url": <link_convertido>, "title": <titulo opcional> }`
- Sucesso **201**: usar `response.shortUrl` como `url_final` do livro
- Não usar o campo `url` da resposta (é o destino)

### Pipeline no passo `link` (`store == "magalu"`)

1. Converter Magalu (`ok` deve ser true)
2. Criar link no Aqui
3. `book["url_final"] = shortUrl`

### Falhas → `LinkQuebrado` (Magalu fora da linha)

- `MAGALU_PROMOTER_ID` / `MAGALU_PARTNER_ID` ausentes
- `AQUI_API_KEY` ausente
- URL inválida / não Magalu após redirect
- Conversão com `ok=false`
- Aqui ≠ 201 ou sem `shortUrl`
- Timeout / erro de rede

Amazon, ML e Shopee neste passo **não** chamam o Aqui. Comportamento atual deles permanece.

## Configuração (`.env.example`)

```env
MAGALU_PROMOTER_ID=
MAGALU_PARTNER_ID=
AQUI_API_KEY=
AQUI_BASE_URL=https://aqui.descontos.ai
```

## Arquivos principais

| Arquivo | Papel |
|---|---|
| `promo_livros/magalu_links.py` | Detecção, rewrite, redirect |
| `promo_livros/aqui_links.py` | Cliente HTTP do encurtador |
| `promo_livros/lojas.py` | `store_of`, `STORE_ORDER` |
| `promo_livros/catalog.py` | `replace_magalu`, segunda loja |
| `promo_livros/fila.py` | `montar_fila`, `SlotFila.magalu` |
| `promo_livros/fila_csv.py` | Parse Magalu nas colunas `_ml`; `_converter_magalu` |
| `promo_livros/dashboard_curation.py` / `dashboard.py` | Aba, import, wiring resolve |
| `promo_livros/post_copy.py` | Legenda com Magalu |
| `.env.example` | Novas variáveis |
| `tests/test_magalu_*.py`, `test_fila*.py` | Cobertura |

## Testes

- `magalu_links`: hosts; `/p/` → divulgador/oferta; path já divulgador; genérico; preserve `seller_id`; redirect mockado; inválida → `ok=false`
- Cliente Aqui: 201 → `shortUrl`; erro/rede → falha clara
- `fila_csv`: Magalu nas colunas `_ml`; falha Magalu/Aqui → fora; Amazon/Shopee sem chamada Aqui
- `montar_fila` / catálogo: Magalu divide a segunda metade (espelho dos testes Shopee)

## Critérios de sucesso

1. Curadoria importa e marca Magalu; Magalu aparece na 2ª metade da fila por índice.
2. CSV da fila com `link_ml` Magalu monetiza + encurta e grava `shortUrl` no post.
3. Falha Magalu/Aqui remove só essa oferta Magalu (fluxo de ignorado existente).
4. Amazon/ML/Shopee não passam pelo Aqui.
5. Credenciais só via `.env`.
