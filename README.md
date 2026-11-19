# Promo Livros

A fila do dia sai da Curadoria do painel: a pessoa marca livros na Amazon e no Mercado Livre. Cada post leva uma oferta de cada loja, e a página mostra quem vai com quem antes de definir a fila. O disparo usa um WAHA só deste bot, no Mac. O site continua desligado. A busca automática do Keepa existe no código, mas não monta a fila enquanto a curadoria estiver em modo manual.

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
  blurb.py             frase de até 12 palavras; a fila usa a pesquisa na internet
  book_match.py        avisa o mesmo título nas duas lojas e forma o par de cada post
  pick_plan.py         a fila prevista da Curadoria: horário, oferta da Amazon e a do Mercado Livre
  link_offer.py        lê título, preço e capa de um link avulso da Amazon ou do Mercado Livre
  catalog.py           CSVs, marcação e montagem da fila
  ml_links.py          link de afiliado do Mercado Livre e leitura de foto
  post_copy.py         legenda do WhatsApp, com um bloco por loja
  dashboard.py         painel em 127.0.0.1:8787
  dashboard_curation.py  página da Curadoria
  formatter.py         texto da mensagem antiga, no formato do WhatsApp
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

Os limites (ranking, nota, desconto, tolerância, horários e nichos) ficam no `config.yaml`. `whatsapp.enabled` fica em `false` até você querer disparar. `website.enabled` continua em `false`. Sem `OPENAI_API_KEY`, o post sai sem a linha da resenha. O painel ainda precisa de `DASHBOARD_USERNAME` e `DASHBOARD_PASSWORD`.

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

A busca roda uma vez por dia, às 6h, no fuso de Brasília. As publicações vão das 8h às 22h, três por hora, um nicho por vez: ficção, não ficção (História) e biografia, e depois de novo. O último horário é 21:40. Às 22h para. São 14 livros de cada nicho nessa grade, mais dois reservas, para o caso de o preço subir antes da hora. Horário sem livro fica vazio.

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

O texto abaixo é o da fila automática do Keepa. A fila da Curadoria usa outro formato, com um bloco por loja: está em "Legenda". Na fila automática, a frase do meio é um resumo de uma linha feito pela OpenAI a partir da sinopse que o Keepa devolve. O Keepa não traz o texto das resenhas dos leitores. Se a sinopse vier vazia ou a OpenAI falhar, essa linha some e o resto da mensagem segue.

```
📚 *Título do livro*
Ficção

Conta a história de alguém.

R$ YY,YY. Menor preço em 214 dias.
https://www.amazon.com.br/dp/ASIN?tag=sua-tag
```

O preço é o da oferta escolhida (Amazon ou Buy Box). "Menor preço em N dias" é o tempo desde que um valor mais baixo deixou de valer. A capa vai junto. O link dos posts que ainda não foram para nenhum grupo sai da API local de afiliado (`amz-link-api`, contrato em `amz-link-api/API.md`). A tag é `AMAZON_AFFILIATE_TAG`. O texto usa o campo `url` da API, em geral um `link.amazon`. Post que já saiu para um grupo fica com o link que foi enviado. Sem `AMZ_TOKEN` no `.env`, o link continua `https://www.amazon.com.br/dp/ASIN?tag=`.

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

O envio passa pela `zapo-bridge/`, um processo Node (biblioteca [zapo-js](https://zapo.to)) sem container. Ela atende o mesmo subconjunto da API do WAHA que o `promo_livros/waha.py` usa, então o Python não mudou: só `WAHA_URL` no `.env` aponta para a porta 4450 (a 4443 e a 4444 ficam presas pelo Docker Desktop). A outra esteira, na porta 3000, não foi alterada e a fila dela não é lida.

| | Promo Livros | Outra esteira |
| --- | --- | --- |
| Processo | pm2 `zapo-bridge` | container `waha` |
| Porta no Mac | `127.0.0.1:4450` | `127.0.0.1:3000` |
| Sessão | `promo-livros` | `esteira` |
| Credenciais | `zapo-bridge/data/zapo.sqlite` | `~/waha/sessions` |
| Fila | tabela `dispatches` deste SQLite | não é usada aqui |

A ponte lê `WAHA_API_KEY` e `WAHA_SESSION` do `.env` do projeto. As opções dela (porta, URL do webhook, navegador que aparece no celular) estão em `zapo-bridge/.env.example`. Votos de enquete e comandos `!enquete` chegam ao painel em `BRIDGE_WEBHOOK_URL` (padrão `http://127.0.0.1:8787/whatsapp/webhook`); o `PUT` de webhook do `scripts/_deploy_enquetes.py` responde 501 e não é mais necessário. Para parear, use o QR do [painel](https://painel.promolivros.org). Apagar `zapo-bridge/data/` obriga a parear de novo.

```
cd "/Volumes/HD 1Tb/Vibecoding/Promo Livros/zapo-bridge"
npm ci
pm2 start ecosystem.config.cjs && pm2 save
```

O `waha/` antigo (container `waha-livros`) fica só como referência para voltar atrás.

No horário do livro, a fila `dispatches` ganha uma linha por grupo de `whatsapp.groups`. O primeiro grupo sai na hora. Os outros esperam `gap_seconds` (padrão 45). O livro seguinte continua no relógio, às :00, :20 e :40. Se o WhatsApp cair, a linha fica `na_fila` e o minuto seguinte tenta de novo. Às 22:00 o que não saiu expira e o livro não entra nos 30 dias. A tabela é criada na primeira execução depois dessa versão do código.

`python -m promo_livros --groups` lista os grupos da sessão. `whatsapp.enabled` está em `false`: a noite só escreve o log e grava o livro nos 30 dias. Os grupos no YAML são Black Livros 01, 02 e 03. O número novo ainda precisa entrar neles. Os ids continuam os mesmos depois que ele entra.

## Dashboard

Na pasta do projeto, no Mac (`/Volumes/HD 1Tb/Vibecoding/Promo Livros`), com o Python do venv `promo-livros-venv`:

```
/Volumes/HD 1Tb/Vibecoding/promo-livros-venv/bin/python -m promo_livros.dashboard
```

Não use o Python do Homebrew: ele não tem o PyYAML. O `ps` mostra o caminho do Homebrew mesmo quando o processo foi o do venv.

A página escuta em `127.0.0.1:8787`. Sem `DASHBOARD_USERNAME` e `DASHBOARD_PASSWORD` no `.env`, o processo não sobe. O painel é [painel.promolivros.org](https://painel.promolivros.org). O código novo só aparece depois de reiniciar esse processo. O envio dos posts é outro processo (`promo-livros-envio`) e não sobe junto. Reiniciar o painel apaga a sessão: é preciso entrar de novo.

No túnel `promo-livros` (`~/.cloudflared/promo-livros.yml`), `painel.promolivros.org` aponta para `http://127.0.0.1:8787`. A regra de `esteira.promolivros.org` saiu do túnel em 25 out 2026: a ponte não tem painel próprio.

No pm2, o painel é `promo-livros-painel` (`scripts/painel_run.sh`, com o Python do venv).

| Página | Caminho | O que faz |
| --- | --- | --- |
| Hoje | `/hoje` | Fila, horários e membros dos grupos |
| Enviados | `/enviados` | O que já saiu |
| WhatsApp | `/whatsapp` | Sessão e QR |
| Grupos | `/grupos` | Lista gravada no `config.yaml` |
| Assinaturas | `/assinaturas` | Linha final da legenda, uma por post, em rodízio |
| Configurações | `/configuracoes` | Cookies e tag do Mercado Livre |
| Curadoria | `/curadoria` | Marcação dos livros e montagem da fila |

O menu Configurações só aparece depois do login. A página de login não tem navegação.

Um 502 do Cloudflare, com o túnel no ar, em geral é o processo da porta 8787 caído ou com a conexão do SQLite quebrada. O arquivo `data/promo_livros.sqlite` pode estar íntegro e mesmo assim a conexão antiga responder `file is not a database`. Reiniciar só o painel abre outra conexão. Não abra esse SQLite por outro programa enquanto o painel estiver no ar: o banco fica no volume que o Windows também enxerga, e o WAL não aguenta dois clientes.

## Curadoria

A página é [painel.promolivros.org/curadoria](https://painel.promolivros.org/curadoria). Há duas abas.

| Aba | Arquivo | Identificador |
| --- | --- | --- |
| Amazon | `CSV Atualizado/amazon_livros_*.csv` | ASIN de 10 caracteres |
| Mercado Livre | `CSV Atualizado/mercadolivre-livros.csv` | id `MLB` seguido de dígitos, na coluna `asin` |

Na virada do dia (meia-noite em São Paulo) as marcações saem. Sempre que o CSV da pasta muda, a Curadoria recarrega esse arquivo sozinha — na abertura da página ou ao subir o painel — e as marcações daquela loja saem junto. O botão "Importar os CSVs da pasta" e um CSV enviado do computador fazem a mesma troca na hora.

O checkbox marca aquele livro naquela loja. Marcar na Amazon não marca o anúncio do Mercado Livre.

A **fila prevista**, no topo da página, é o que vai acontecer: uma linha por post, com o horário, a oferta da Amazon e a do Mercado Livre. Ela vem do servidor a cada marcação, então as duas abas aparecem ali mesmo sem trocar de aba.

| Controle na fila prevista | O que faz |
| --- | --- |
| ↑ e ↓ | Move o livro na ordem da loja dele, trocando com quem ele divide o post |
| ✕ | Desmarca o livro |
| `sem oferta da Amazon` | Esse post vai sair só com a outra loja |

A ordem dentro de cada loja é a ordem dos cliques, gravada em `pick_seq`. O primeiro marcado na Amazon vai com o primeiro marcado no Mercado Livre. No card do livro, a linha azul mostra o horário e com quem ele sai.

O intervalo entre posts fica em "Minutos entre posts" (de 5 a 180), gravado em `send_interval_minutes`. Salvar o intervalo não mexe nos horários que já estão na fila. Só o próximo "Definir a fila" usa o número novo.

"Definir a fila" cancela os posts do dia que ainda estão agendados e monta de novo. Os já enviados e os que falharam ficam. Entram no máximo 60 posts, nos horários que ainda cabem depois de agora. Livro sem preço não entra. O botão demora: baixa as capas e pede os links de afiliado antes de trocar de página.

Cada post vale para uma data e uma hora. Na virada do dia, o que ficou agendado no dia anterior sai da fila. O que já foi enviado permanece em Enviados. A tela de hoje começa vazia até a próxima "Definir a fila".

Enquanto o painel sobe, ele grava `curation=manual`. Com isso, o job das 5h (`scripts/fila_do_dia.py`) acorda, registra que a curadoria é manual e sai sem crawler e sem Keepa.

### Ordenar e filtrar

Os controles ficam acima da grade e valem nas duas abas. A escolha fica no navegador, separada por aba.

| Controle | Efeito |
| --- | --- |
| Ordenar por | Ordem do CSV, maior desconto, menor preço, maior preço, maior economia em reais, título de A a Z |
| Desconto mínimo | Qualquer, ou 20% a 70% |
| Preço até (R$) | Esconde o que passa desse valor |
| Categoria | Uma categoria do CSV, com a contagem ao lado |
| Só marcados | Só os checkboxes ligados |
| Ocultar infantis | Esconde livro com Infantil no título ou no caminho da categoria. A marcação dele continua, se já estava ligada |
| Ver produto | Abre a página do anúncio, fora do painel, para conferir |
| Só menor preço em 365 dias | A badge do CSV da Amazon. O CSV do Mercado Livre não preenche essa coluna |
| Buscar | Título ou categoria |
| Limpar filtros | Volta à ordem do CSV e tira os recortes |

Na aba Mercado Livre a categoria não separa assunto: o crawler grava todos como "Português".

### Como os dois títulos entram no mesmo post

`pair_posts`, em `promo_livros/book_match.py`, percorre os marcados na Amazon na ordem dos cliques. Para cada um, pega o próximo marcado no Mercado Livre cujo título não é o mesmo. O que sobra de uma loja vira post só daquela loja. `pick_plan.plan_rows` é a mesma função com os horários ao lado, e é o que a página mostra.

O mesmo título não ocupa os dois lugares do post. O aviso "Existe na Amazon" ou "Existe no Mercado Livre" no card é só o preço do mesmo título na outra loja: não marca esse anúncio. Um kit não é tratado como o livro avulso nessa comparação.

Exemplo: Dom Casmurro marcado na Amazon e Memórias do Cárcere no Mercado Livre. Os dois saem no mesmo post, cada um com o próprio título, preço, desconto e link.

Livro sem preço não entra na fila nem aparece na fila prevista.

### Legenda

`promo_livros/post_copy.py` escreve um bloco por loja. A Amazon vem primeiro. Quando há Mercado Livre, o link da Amazon também leva o nome da loja. A assinatura entra uma vez no fim.

```
📖 *Dom Casmurro*
ℹ️ _Um homem ciumento relê a própria juventude no Rio antigo._
💲 R$ 12,00, (40%) menor preço dos últimos 365 dias

🔗 Amazon: https://link.amazon/...

📖 *Memórias do Cárcere*
ℹ️ _O relato de Graciliano Ramos sobre os anos de prisão._
💲 R$ 28,00, (45% de desconto)

🔗 Mercado Livre: https://meli.la/...

ℹ️ Assine o Kindle Unlimited com até 3 meses grátis: https://link.amazon/...
```

A linha do preço usa "menor preço dos últimos 365 dias" quando o CSV traz essa marca. Sem a marca, e havendo desconto, fica "(45% de desconto)". O percentual é o calculado entre preço e preço de lista, não o número do badge do CSV.

O card do post mostra as duas capas quando o post tem as duas lojas.

### Post montado a partir de um link

"Programar post", em `/hoje`, tem dois blocos de oferta. Em cada um, cole o link e clique em **Puxar dados**: `promo_livros/link_offer.py` lê título, preço, preço de lista e capa, e preenche os campos, que continuam editáveis. Com os dois blocos preenchidos o post sai igual aos da Curadoria, com a Amazon primeiro. Com um só, sai de uma loja.

A primeira tentativa não sai da máquina: se o ASIN ou o id MLB do link estiver no CSV já importado, o dado vem de lá, na hora, com o preço e a capa daquele arquivo. Só quando o link é de fora do CSV o painel vai à loja:

| Loja | De onde vem o dado |
| --- | --- |
| Mercado Livre | Com os cookies de Configurações, `www.mercadolivre.com.br/p/api/items/MLB…`; depois `api.mercadolibre.com/items/MLB…`; por último a página do anúncio |
| Amazon | A página do produto; se a Amazon recusar a leitura simples, o Playwright abre a página |

O Mercado Livre não entrega anúncio para quem não tem sessão: a API pública responde HTTP 403 e a página vem vazia, até no navegador sem interface. Então link do Mercado Livre fora do CSV só é lido com os cookies de Configurações preenchidos; sem eles o aviso diz isso.

Só endereços da Amazon e do Mercado Livre são buscados, sempre em `https`. Qualquer outro link é recusado antes de qualquer requisição. A capa só é aceita do CDN da loja. Sem título ou sem preço o painel avisa, em vez de montar post pela metade.

### Resenha

A linha `ℹ️ _…_` é `OpenAIBlurb.research`, em `promo_livros/blurb.py`. Modelo no `config.yaml`: `gpt-4.1-mini`. A chave é `OPENAI_API_KEY`.

Na hora de definir a fila, e de novo na subida do painel para posts agendados que ainda estão sem frase, o código pede uma frase de no máximo 12 palavras. A chamada principal é a Responses API (`/v1/responses`) com a ferramenta `web_search`. Se essa busca falha, o código lê trechos da Wikipédia em português e pede a frase só com esses trechos. Se o livro não aparece, a linha fica de fora. Não há frase inventada no lugar.

Entra na legenda uma frase de 4 a 12 palavras, com ponto final, sem preço, desconto, frete ou nota. Frase aceita fica em `data/blurb_cache.json` para o mesmo título não ser pesquisado de novo. Falha não entra no cache. Chave recusada (HTTP 401 ou 403) interrompe as próximas pesquisas; os posts seguem sem a linha. Sem `OPENAI_API_KEY`, o painel avisa no log e não chama a API.

Post já enviado não é reescrito.

`OpenAIBlurb.pitch` continua no código da fila antiga do Keepa. Ele usa título e sinopse, e o teste trava o texto desse prompt. A Curadoria não chama `pitch`.

### Fotos

A capa da Amazon é `https://m.media-amazon.com/images/P/{asin}.jpg`.

A foto do Mercado Livre não é buscada no site na hora de abrir a Curadoria. O anúncio manda o servidor para um captcha, e a API pública de itens responde 403. A foto vem do CSV, coluna `imagem`, gravada pelo crawler quando ele lê a vitrine. O painel só aceita URL `https://http2.mlstatic.com/D_….jpg|jpeg|webp|png`. Outro endereço é descartado.

O card da Curadoria usa essa URL direto. O card do post baixa a mesma URL. Sem `imagem`, o card do Mercado Livre fica vazio, a menos que o mesmo título exista na Amazon: aí a capa da Amazon aparece como apoio, e o texto da página lembra que a foto do anúncio depende do CSV.

### Crawler do Mercado Livre

O gerador é `~/ml-crawler/crawl_clipboard.py`, no Mac. Ele abre a lista de livros físicos em português, com frete Full e desconto de 50% a 100%, no Chrome já logado, copia o código da página e extrai os cards. A cópia anterior à coluna `imagem` está em `~/ml-crawler/crawl_clipboard.py.bak-20260929`.

Cada execução grava quatro CSVs, com `;`, aspas em todos os campos e UTF-8 com BOM:

- `~/ml-crawler/mercadolivre-livros.csv`
- `~/ml-crawler/mercadolivre_livros_AAAA-MM-DD.csv`
- `/Volumes/HD 1Tb/Vibecoding/Promo Livros/CSV Atualizado/mercadolivre-livros.csv`
- o mesmo nome com a data, na mesma pasta

Colunas: `posicao`, `titulo`, `autor`, `categoria`, `categoria_caminho`, `formato`, `preco`, `preco_de`, `menor_preco_365`, `badges`, `categoria_mais_vendido`, `asin`, `link`, `imagem`. A coluna `asin` aqui é o id `MLB…`, não um ASIN da Amazon. `menor_preco_365` sai vazio. A foto é o `img.poly-component__picture` do card; se o `src` for placeholder, vale o `data-src` ou o `srcSet`.

Quando o CSV novo cai na pasta, a Curadoria passa a usá-lo na próxima abertura da página (ou ao subir o painel) e as marcações daquela lista saem. "Importar os CSVs da pasta" faz a mesma leitura na hora.

### Links de afiliado

Amazon: a API local `amz-link-api` (contrato em `amz-link-api/API.md`). Sem `AMZ_TOKEN`, o link fica `https://www.amazon.com.br/dp/ASIN?tag=`.

Mercado Livre: `POST https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink`, o mesmo caminho do Gerador de Links (`lib/affiliate/converters.ts`). O corpo é `{ "urls": ["…"], "tag": "…" }`. A resposta usada é `urls[0].short_url`, em geral `https://meli.la/…`.

Em Configurações, cole o export JSON do Cookie-Editor (cookies de `mercadolivre.com.br` ou `mercadolibre.com`) e a tag. A sessão só vale com cookie e com o cookie `_csrf`. Na hora de converter, o painel abre `https://www.mercadolivre.com.br/afiliados/linkbuilder` e usa o `csrf-token` novo da página. A tag padrão, se o campo vier vazio, é `cpetrag1971`.

A API recusa `https://produto.mercadolivre.com.br/MLB-…` com a mensagem "URL not allowed in affiliates program". O código troca esse endereço por `https://www.mercadolivre.com.br/p/MLB{id}` antes de chamar. Um link `www.mercadolivre.com.br/…` do CSV segue como está, sem a query. Salvar as configurações converte os links dos posts que ainda não saíram. A subida do painel faz o mesmo. Se a API recusar, o endereço do produto permanece e o log registra `Link do Mercado Livre mantido` com o motivo. Cookies vencidos pedem um export novo.

## O que foi feito em 29 de setembro de 2026

A fila deixou de ser montada sozinha. O painel ganhou a Curadoria, a frase curta da legenda e a contagem de membros. Nada disso manda mensagem por conta própria: o envio continua no processo que já dispara a fila.

### Curadoria da Amazon

A fonte inicial foi o CSV `CSV Atualizado/amazon_livros_*.csv`. Cada linha mostra capa, título, categoria, preço e percentual de desconto. O checkbox é a fila. "Definir a fila" troca apenas os posts do dia que ainda estão agendados.

Código: `promo_livros/catalog.py`, `promo_livros/dashboard_curation.py`, o retorno cedo em `promo_livros/morning.py`.

No dia 29, a fila definida na mão ficou com intervalo de 17 minutos. Dois livros marcados saíram da fila porque a checagem de oferta não achou preço ao vivo: *Box Clássicos de Shakespeare* e *O Menino Maluquinho*. Os posts da manhã que já tinham saído não foram apagados.

### Frase da legenda

A linha em itálico sai de `promo_livros/blurb.py`. O prompt do `pitch` (fila antiga, com sinopse) ficou travado pelo teste e não é o caminho da Curadoria. A Curadoria usa `research`, descrito em "Resenha". O CSV não tem sinopse.

### Membros no painel

Em [painel.promolivros.org/hoje](https://painel.promolivros.org/hoje), abaixo do resumo do dia:

- **Membros líquidos:** participantes dos grupos salvos, sem administrador e sem superadmin.
- **Entradas do dia** e **saídas:** gente que entrou ou saiu desde a leitura anterior.
- **Líquido do dia:** entradas menos saídas.

A leitura usa `GET /api/{sessão}/groups/{id}/participants/v2` no WAHA. A primeira leitura de cada grupo só cria a base e não conta como entrada, porque o WhatsApp não devolve o histórico do dia. Por isso, na primeira vez, entradas, saídas e líquido ficaram em 0. O total líquido nessa leitura foi 168: Black Livros 01 com 53, 02 com 58, 03 com 57. O painel consulta de novo no máximo a cada 20 segundos. O telefone não é gravado: o sqlite guarda só um hash em `group_roster` e o movimento do dia em `group_flow`.

Código: `promo_livros/membership.py` e o bloco no topo de `promo_livros/dashboard_belt.py`.

## O que foi feito

Curadoria, em `n:\Vibecoding\Promo Livros`:

- Busca diária no Keepa, domínio 12 (Amazon.com.br). A raiz Livros foi resolvida na API: id `6740748011`, gravado no SQLite.
- Três nichos, dois livros e dois reservas cada: Ficção (`7872687011`), Não ficção / História (`7843068011`), Biografia (`7841731011`).
- Janela 08:00–22:00, três posts por hora, um nicho por vez. Às 22:00 para. O agendador é o processo `python -m promo_livros`.
- Régua de livro físico, ranking, nota, avaliações, desconto contra a média de 90 dias, menor preço histórico, tempo de rastreio, Amazon ou Buy Box. Preços em centavos.
- "Menor preço em N dias" sai do histórico do Keepa na fila automática. Na Curadoria, a frase de até 12 palavras sai da pesquisa na internet (`OpenAIBlurb.research`). Sem `OPENAI_API_KEY`, o post sai sem essa frase.
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

1. A imagem combinada de manhã (cena gerada, capa colada, faixa de preço) continua fora deste fluxo. O card da fila manual usa a capa de cada loja.
2. Deixar o site como está até haver um pedido para publicar a oferta lá.
3. A aba Mercado Livre não tem categorias de assunto: o crawler grava "Português" em todas as linhas.
4. O aviso de "menor preço em 365 dias" só existe no CSV da Amazon.

## Testes

```powershell
python -m unittest discover -s tests -v
```

Eles cobrem a query, os filtros, o texto, o SQLite, o YAML, a conexão com o WAHA e a fila de disparo. Não chamam o Keepa nem enviam mensagem.
