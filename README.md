# Promo Livros

Busca livros em oferta na Amazon.com.br pelo [Product Finder do Keepa](https://keepa.com/api-docs/product-finder.html) e faz a curadoria sozinho. O disparo usa um WAHA só deste bot, no Mac. O site continua desligado.

## Estrutura

```
promo_livros/
  main.py              agendador e linha de comando
  curation.py          fila da manhã e publicação da noite
  selection.py         escolha dos livros e reservas por nicho
  schedule_plan.py     horários 20:00–21:40
  keepa_client.py      HTTP da API, query e categorias
  keepa_time.py        conversão do relógio do Keepa
  filters.py           critérios reaplicados em cima do /product
  price_history.py     "menor preço em N dias"
  synopsis.py          sinopse que o Keepa devolve
  blurb.py             frase de uma linha via OpenAI
  formatter.py         texto da mensagem, no formato do WhatsApp
  waha.py              conexão HTTP com o WAHA dos livros
  dispatch.py          fila de disparo para os grupos
  whatsapp_poster.py   adaptador do envio
  website_poster.py    publicação no site, ainda desligada
  storage.py           SQLite: posts, fila do dia, disparos, categorias
  models.py            tipos da configuração e da fila
  config.py            .env + config.yaml
config.yaml            limites, nichos, horários e grupos
.env                   chaves (não commitar)
site/                  página estática publicada em promolivros.org
```

## Requisitos

- Python 3.11 ou mais novo
- Conta com chave da API Keepa
- Tag do Amazon Associates (pode ficar vazia enquanto você testa a curadoria)

A biblioteca `keepa` do pip é um cliente da comunidade. Este projeto fala com a API por HTTP, como nos exemplos oficiais, para controlar tokens e retries no próprio código.

## Configurar

No PowerShell, na pasta do projeto:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Preencha o `.env`:

```
KEEPA_API_KEY=sua_chave
AMAZON_AFFILIATE_TAG=seunome-20
OPENAI_API_KEY=sua_chave_openai
WAHA_URL=http://127.0.0.1:4443
WAHA_API_KEY=
WAHA_SESSION=promo-livros
WAHA_DASHBOARD_USERNAME=
WAHA_DASHBOARD_PASSWORD=
```

Os limites (ranking, nota, desconto, tolerância, horários e nichos) ficam no `config.yaml`. `whatsapp.enabled` fica em `false` até você querer disparar. `website.enabled` continua em `false`. Sem `OPENAI_API_KEY`, a mensagem sai sem a frase sobre o livro.

## Categoria Livros

O id da raiz **não está no código**. Na primeira execução o bot chama `GET /category?domain=12&category=0&parents=0` e escolhe a categoria raiz cujo nome é o `category_name` do YAML (padrão: `Livros`). O id fica no SQLite. Para consultar de novo:

```powershell
python -m promo_livros --once --dry-run --refresh-category
```

Se o nome não existir, o log lista os nomes que a API devolveu. Ajuste `category_name` e rode outra vez.

## A query do Product Finder

O finder só combina filtros com **E**. "Amazon vendendo **ou** Buy Box" não cabe numa query só, então cada ciclo faz duas buscas no `POST /query?domain=12` e junta os ASINs. A da Amazon vem primeiro.

Com o `config.yaml` padrão, a busca da Amazon é:

```json
{
  "rootCategory": ["<id de Livros, resolvido na API>"],
  "productType": 0,
  "current_SALES_gte": 1,
  "current_SALES_lte": 20000,
  "avg30_SALES_gte": 1,
  "avg30_SALES_lte": 30000,
  "salesRankDrops30_gte": 10,
  "current_RATING_gte": 45,
  "current_COUNT_REVIEWS_gte": 100,
  "trackingSince_lte": "<agora menos 180 dias, em minutos Keepa>",
  "current_AMAZON_gte": 1,
  "availabilityAmazon": [0],
  "deltaPercent90_AMAZON_gte": 20,
  "isLowest_AMAZON": true,
  "sort": [["current_SALES", "asc"]],
  "page": 0,
  "perPage": 50
}
```

A segunda troca o bloco de preço por:

```json
{
  "current_BUY_BOX_SHIPPING_gte": 1,
  "deltaPercent90_BUY_BOX_SHIPPING_gte": 20,
  "isLowest_BUY_BOX_SHIPPING": true
}
```

Detalhes que o YAML não mostra, mas a query precisa:

- `current_SALES_gte: 1` e `avg30_SALES_gte: 1` existem porque `-1` no Keepa significa "sem dado". Um filtro só com `lte` deixaria esse `-1` passar.
- `current_*_gte: 1` descarta oferta ausente (`-1`) e preço zero.
- `deltaPercent90_*_gte` positivo significa queda em relação à média de 90 dias. `20` é "pelo menos 20% abaixo".
- `isLowest_*` só entra quando `historic_low_tolerance_percent` é `0`. Com tolerância de 5%, por exemplo, o corte "até 5% acima do mínimo" é feito no Python, porque o finder só tem o sim/não do mínimo exato.
- `trackingSince_lte` é calculado a cada ciclo. Valor menor = rastreado há mais tempo.
- `productType: 0` é livro físico. E-book (`2`) não traz preço de marketplace.
- A página mínima da API é 50. Se `max_asins_per_run` for menor, a query ainda pede 50, mas só esse limite segue para o `/product`.

Cada ASIN que sobra é lido em `GET /product` com `stats=180`. O histórico `csv` vem ligado: o parâmetro `history=0` é que o desliga, e o código não manda isso.

No `/product` os mesmos critérios são reaplicados, porque o dado pode ter mudado entre a query e o detalhe. Preço, média e mínimo histórico saem do objeto `stats` (índices oficiais do csv: Amazon `0`, ranking `3`, nota `16`, avaliações `17`, Buy Box com frete `18`). O campo `stats.min` é o menor valor **já registrado**. `stats=180` não troca esse mínimo; o mínimo só dos últimos 180 dias seria `minInInterval`. Se `stats.min` vier vazio, o código olha o `csv`.

A oferta usada na mensagem é a da Amazon quando ela está em estoque (`availabilityAmazon = 0`) e passa nas travas de preço. Se não passar, entra a Buy Box nova (preço com frete). Sem as duas, o livro é ignorado: é oferta só de terceiros, fora da Buy Box.

## Rodar

Sempre na pasta do projeto, com o venv ativo.

A busca roda uma vez por dia, às 6h, no fuso de Brasília. À noite saem três publicações por hora, às 20:00, 20:20, 20:40, 21:00, 21:20 e 21:40. Às 22h para. Cada horário é um nicho diferente: ficção, não ficção (História) e biografia, e depois de novo. Dois livros de cada, mais dois reservas por nicho, para o caso de o preço subir antes da hora.

Montar a fila de hoje e ver as mensagens, sem gravar:

```powershell
python -m promo_livros --once --dry-run
```

Gravar a fila (o processo normal das 6h):

```powershell
python -m promo_livros --once
```

Deixar o relógio ligado:

```powershell
python -m promo_livros
```

Se o processo sobe depois das 6h e ainda não existe fila no dia, ele monta na hora, desde que seja antes das 20h. Um horário da noite que passou há menos de 10 minutos ainda publica. Os outros esperam o dia seguinte.

`Ctrl+C` encerra. Uma busca que falha por rede não mata o processo: o erro vai para o log e o próximo horário segue.

`--dry-run` também vale no modo agendado. Ele não grava a fila nem a tabela `posts`.

`--publish` manda o próximo horário de hoje que já passou e ainda tem livro pronto. Serve para testar uma mensagem sem esperar o relógio.

## Mensagem

O texto já sai no formato do WhatsApp. A frase do meio é um resumo de uma linha feito pela OpenAI a partir da sinopse que o Keepa devolve. O Keepa não traz o texto das resenhas dos leitores. Se a sinopse vier vazia ou a OpenAI falhar, essa linha some e o resto da mensagem segue.

```
📚 *Título do livro*
Ficção

Conta a história de alguém.

R$ YY,YY. Menor preço em 214 dias.
https://www.amazon.com.br/dp/ASIN?tag=sua-tag
```

O preço é o da oferta escolhida (Amazon ou Buy Box). "Menor preço em N dias" é o tempo desde que um valor mais baixo deixou de valer. A capa vai junto. O link usa `AMAZON_AFFILIATE_TAG`. Se a tag estiver vazia, o link sai sem ela e o log avisa.

Na hora de cada publicação o bot consulta o preço de novo. Se subiu, ou se o livro deixou de passar na régua, ele é pulado e entra o reserva do mesmo nicho.

## O que não repete

O SQLite (`data/promo_livros.sqlite`) guarda ASIN, título, preço em centavos e a data. Nos 30 dias seguintes (`repost_window_days`) o mesmo ASIN só volta se o preço novo for **menor** que o último postado. Com o WhatsApp desligado, a publicação da noite grava essa linha ao registrar o log. Com o WhatsApp ligado, grava quando o primeiro grupo recebe a mensagem. Dry-run não entra nessa tabela.

A fila do dia fica na tabela `daily_queue`. Um livro que já saiu à noite não é substituído por uma busca nova no mesmo dia.

## Tokens

Cada resposta traz `tokensLeft`, `refillIn` e `refillRate`. O log registra o saldo depois de cada chamada.

Antes de uma chamada, se o saldo conhecido não cobre o custo mais a reserva (`min_tokens_reserve`, padrão 20), o processo espera a recarga em vez de estourar. No começo de cada ciclo uma consulta de categoria (1 token) atualiza o saldo de verdade: token parado expira em 60 minutos, então o número da rodada anterior não serve.

Custo típico de um ciclo com o padrão:

| Chamada | Tokens |
| --- | --- |
| Confirmar a categoria | 1 |
| Cada Product Finder | 10 + 1 a cada 100 ASINs devolvidos |
| Cada ASIN em `/product` | 1, e até mais 1 se a nota for pedida (`rating=1`) |

De manhã são duas buscas por nicho e só os detalhes dos livros que entram na fila (dois para publicar e dois reservas). À noite, uma consulta por livro na hora de publicar. A página não passa de `max_asins_per_run` de propósito. O código não pede `stats=1` no finder (isso acrescentaria dezenas de tokens) nem o parâmetro `buybox` (mais 2 por ASIN). A Buy Box usada aqui é a do array `stats`, que já vem com `stats=180`.

Rede instável e HTTP 5xx tentam de novo, com espera crescente. HTTP 429 espera o `refillIn`. O erro de um livro não interrompe os outros.

## Log para calibrar

O arquivo é `logs/promo_livros.log` (e o mesmo texto aparece no terminal). De manhã o log mostra quantos livros entraram em cada nicho e a mensagem de cada horário. À noite mostra a publicação ou o pulo por preço. Cada livro eliminado na régua conta **uma vez**, no primeiro motivo:

`dados_incompletos`, `tipo_produto`, `ranking_atual`, `ranking_media_30d`, `quedas_ranking_30d`, `nota`, `avaliacoes`, `rastreio_insuficiente`, `so_terceiros`, `nao_e_menor_preco`, `desconto_insuficiente`, `ja_postado`.

O log da busca mostra quantos ASINs a query devolveu e o `totalResults`. Se os dois estão em zero, afrouxe um limite no YAML e rode de novo. Se estão em milhares, aperte.

## Site

[promolivros.org](https://promolivros.org) é a página estática que estava no ar em 25 set 2026. Rodar o bot não reescreve `site/index.html` e não envia arquivo para o Mac.

No Mac, os arquivos ficam em `/Users/cpetrag/vibecoding/promo-livros/site/` e o Python os serve em `127.0.0.1:4188`. O pm2 sobe `promo-livros-web` e `promo-livros-tunnel`. O túnel é o `promo-livros` (`569e5fde-a230-46e3-ae6a-a8538a3555eb`), config `~/.cloudflared/promo-livros.yml`. O túnel `mac-capture` (`~/.cloudflared/config.yml`, pm2 `tunnel`) não entra nesse fluxo.

`website.enabled: true` faz o programa parar. `website_poster.py` ainda não publica.

## WhatsApp

O envio usa um WAHA só deste bot. A outra esteira, na porta 3000, não foi alterada e a fila dela não é lida.

| | Promo Livros | Outra esteira |
| --- | --- | --- |
| Container | `waha-livros` | `waha` |
| Porta no Mac | `127.0.0.1:4443` | `127.0.0.1:3000` |
| Sessão | `promo-livros` | `esteira` |
| Volume | `~/waha/sessions-livros` | `~/waha/sessions` |
| Fila | tabela `dispatches` deste SQLite | não é usada aqui |

Imagem `devlikeapro/waha:arm`, versão 2026.9.1, motor GOWS. O processo que dispara precisa rodar no Mac, porque a API escuta só em localhost. `WAHA_URL`, `WAHA_SESSION` e `WAHA_API_KEY` ficam no `.env`.

O painel para parear é [esteira.promolivros.org/dashboard](https://esteira.promolivros.org/dashboard). A raiz do mesmo endereço é a página da API. O login é `WAHA_DASHBOARD_USERNAME` e `WAHA_DASHBOARD_PASSWORD` no `.env`. O DNS é o `CNAME esteira` para `569e5fde-a230-46e3-ae6a-a8538a3555eb.cfargotunnel.com`, com proxy, no mesmo túnel do site.

No horário do livro, a fila `dispatches` ganha uma linha por grupo de `whatsapp.groups`. O primeiro grupo sai na hora. Os outros esperam `gap_seconds` (padrão 45). O livro seguinte continua no relógio, às :00, :20 e :40. Se o WhatsApp cair, a linha fica `na_fila` e o minuto seguinte tenta de novo. Às 22:00 o que não saiu expira e o livro não entra nos 30 dias. A tabela é criada na primeira execução depois dessa versão do código.

`python -m promo_livros --groups` lista os grupos da sessão. `whatsapp.enabled` está em `false`: a noite só escreve o log e grava o livro nos 30 dias. Os grupos no YAML são Black Livros 01, 02 e 03. O número novo ainda precisa entrar neles. Os ids continuam os mesmos depois que ele entra.

## Dashboard

Na pasta do projeto, no Mac (`/Volumes/HD 1Tb/Vibecoding/Promo Livros`):

```
python -m promo_livros.dashboard
```

A página escuta em `127.0.0.1:8787`. Sem `DASHBOARD_USERNAME` e `DASHBOARD_PASSWORD` no `.env`, o processo não sobe. Hoje mostra a fila e não grava no SQLite. WhatsApp mostra a sessão `promo-livros` e o QR quando o WAHA pede pareamento. Grupos grava só a lista em `config.yaml`. O agendador só passa a usar essa lista na próxima subida.

No túnel `promo-livros`, antes da regra final, a entrada nova é o hostname `painel.promolivros.org` com serviço `http://127.0.0.1:8787`. O nome `painel` aponta para o mesmo túnel de `esteira`. `esteira.promolivros.org/dashboard` continua sendo o painel do WAHA. A sessão em `~/waha/sessions-livros` não muda de disco neste passo.

## O que foi feito

Curadoria, em `n:\Vibecoding\Promo Livros`:

- Busca diária no Keepa, domínio 12 (Amazon.com.br). A raiz Livros foi resolvida na API: id `6740748011`, gravado no SQLite.
- Três nichos, dois livros e dois reservas cada: Ficção (`7872687011`), Não ficção / História (`7843068011`), Biografia (`7841731011`).
- Janela 20:00–22:00, três posts por hora, um nicho por vez. Às 22:00 para. O agendador é o processo `python -m promo_livros`. Ele não foi deixado rodando.
- Régua de livro físico, ranking, nota, avaliações, desconto contra a média de 90 dias, menor preço histórico, tempo de rastreio, Amazon ou Buy Box. Preços em centavos.
- "Menor preço em N dias" sai do histórico do Keepa. A frase de uma linha sai da sinopse (o Keepa não manda o texto das resenhas), via OpenAI `gpt-4.1-mini`, no máximo 180 caracteres. Sem `OPENAI_API_KEY`, o post sai sem essa frase. A chave ainda não foi colocada.
- Link de afiliado com a tag do `.env`. Capa da Amazon junto da mensagem.
- Repost só depois de 30 dias, e só se o preço novo for menor. Dry-run não grava fila nem `posts`.
- `--once` monta a fila. `--once --dry-run` só mostra. `--publish` manda um horário já vencido. `--groups` lista grupos. `--refresh-category` ignora o id em cache.

Fila gravada em 26 set 2026, status `ready`. Nada em `posts`. História não teve livro. Biografia teve um. Ficção teve quatro.

| Horário | Nicho | Livro | Preço | Menor preço |
| --- | --- | --- | --- | --- |
| 20:00 | Ficção | Memórias do subsolo (`6550974119`) | R$ 11,12 | 213 dias |
| 20:20 | Não ficção | vazio | | |
| 20:40 | Biografia | Cezar (`6556700665`) | R$ 39,52 | 347 dias |
| 21:00 | Ficção | Todas as mentiras (`8584395970`) | R$ 27,32 | 191 dias |
| 21:20 | Não ficção | vazio | | |
| 21:40 | Biografia | vazio | | |
| reserva | Ficção | Manual de Epicteto (`6558887592`) | R$ 8,22 | 1063 dias |
| reserva | Ficção | Bluey: Vovozinhas (`6555478357`) | R$ 12,81 | 1035 dias |

O saldo Keepa depois dessa montagem era 213 tokens. Essa busca não foi repetida.

Site e túnel:

- Página estática no ar em promolivros.org, servida no Mac na porta 4188.
- Subdomínio `esteira.promolivros.org` no mesmo túnel, apontando para a porta 4443.
- O túnel do Mac Capture não foi editado nem reiniciado.

WhatsApp:

- Container `waha-livros` criado e deixado em `unless-stopped`. Sessão `promo-livros`.
- Painel com usuário e senha no `.env`. A API exige `WAHA_API_KEY`.
- Módulo de disparo escrito (`dispatch.py`, `waha.py`). `whatsapp.enabled` segue `false`. Nenhuma mensagem foi enviada.
- O pareamento pelo QR não foi concluído. O número ainda não está nos grupos.

Imagem do post, combinada e não implementada: de manhã a API gera só a cena (livro em pé, mesa escura, luz suave, sem texto), em qualidade baixa, 1024×1024. A capa real da Amazon é colada por cima. A faixa com o preço e "menor preço em N dias" é desenhada no código. Se o preço cair à noite, só a faixa é refeita. Se a API falhar, sai a capa original com a mesma faixa. Dry-run não gasta. A noite não chama a API de imagem.

## O que falta

1. Parear o WhatsApp em `/dashboard`, com um celular que não seja o da outra esteira.
2. Colocar esse número em Black Livros 01, 02 e 03.
3. Ligar `whatsapp.enabled` e rodar o processo no Mac. Sem o número nos grupos, o disparo falha.
4. Colocar `OPENAI_API_KEY` e, se for o caso, remontar a fila com `--once` enquanto nada estiver em `posts`.
5. Implementar a imagem do post no escopo acima.
6. Deixar o site como está até haver um pedido para publicar a oferta lá.

## Testes

```powershell
python -m unittest discover -s tests -v
```

Eles cobrem a query, os filtros, o texto, o SQLite, o YAML, a conexão com o WAHA e a fila de disparo. Não chamam o Keepa nem enviam mensagem.
