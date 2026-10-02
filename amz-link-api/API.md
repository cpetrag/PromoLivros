# API de links de afiliado

Serviço interno no Mac Mini. Gera o link de associado da Amazon Brasil (longo e curto) para outros sistemas. Cada chamada manda a tag daquele canal. A tag é conferida na conta antes de encurtar.

Endereço neste Mac: `http://127.0.0.1:3070`. Fora da máquina, só por um túnel que aponte para essa porta. A API não abre na rede.

## Autenticação

Todas as rotas, exceto `GET /health`, exigem o header:

```
x-api-key: <AMZ_TOKEN>
```

`AMZ_TOKEN` está em `amz-link-api/.env`. Quem consome guarda a mesma chave no próprio ambiente. Chave ausente ou diferente responde `401`.

## O que usar na mensagem

A resposta de sucesso tem este formato:

```json
{
  "asin": "B0CP9Z56SW",
  "tag": "souleitor-20",
  "longUrl": "https://www.amazon.com.br/dp/B0CP9Z56SW?linkCode=sl2&tag=souleitor-20&ref_=as_li_ss_tl",
  "shortUrl": "https://link.amazon/abc",
  "url": "https://link.amazon/abc",
  "cached": false
}
```

Use o campo `url`. Quando o encurtamento funciona, `url` e `shortUrl` são o `link.amazon`. Quando a sessão da Amazon está caída ou o encurtador falha, `shortUrl` vem `null` e `url` é o `longUrl`, que já comissiona.

`cached: true` significa que o par `(asin, tag)` já estava no SQLite. Essa leitura não chama a Amazon.

## O mesmo do SiteStripe

Sim. A API abre a Amazon já logada e chama os mesmos endereços da barra de SiteStripe: `getStoreTagMap` para as tags e `getShortUrl` para o `link.amazon`. O link longo sai no formato do link de texto dessa barra (`linkCode=sl2`, `ref_=as_li_ss_tl`), não no formato do link de imagem. Se a sessão cair, o encurtador não responde e a API devolve esse link longo, que já leva a tag.

## Tag

- Sem `tag`, a API usa a loja principal (`AMZ_STORE_ID`, hoje `cpetrag0f7-20`).
- A tag precisa existir na conta. Tag desconhecida é `TAG_INVALIDA` e o link não é gerado.
- A Amazon aceitaria qualquer texto na query. Esta API não. A lista vem do SiteStripe e fica em cache.

### Puxar as tags disponíveis

`GET /tags` devolve a lista que já está em memória, sem chamar a Amazon:

```json
{ "tags": ["souleitor-20", "cpetrag0f7-20"] }
```

`GET /tags?atualizar=1` puxa de novo no SiteStripe (`getStoreTagMap`) e responde com a lista nova:

```json
{
  "tags": ["souleitor-20", "cpetrag0f7-20"],
  "sessionOk": true,
  "lastTagsRefresh": "2026-09-28T20:00:00.000Z",
  "atualizado": true
}
```

`atualizar=1` e `refresh=1` são o mesmo modo. Se a sessão caiu, `atualizado` vem `false` e `tags` fica com a última lista que deu certo. `POST /refresh-tags` faz a mesma atualização e devolve o estado completo.

```bash
curl -sS \
  -H "x-api-key: $AMZ_TOKEN" \
  "http://127.0.0.1:3070/tags?atualizar=1"
```

## Entrada

Vale ASIN (`B0CP9Z56SW`), URL da `amazon.com.br` (`/dp/`, `/gp/product/`, `/gp/aw/d/`) ou encurtador `amzn.to`, `link.amazon` e `a.co`. A query original é descartada. O link novo sai com a tag desta chamada.

## Rotas

| Método | Rota | Auth | Uso |
|---|---|---|---|
| GET | `/health` | não | `{ sessionOk, lastTagsRefresh, uptime }` |
| GET | `/tags` | sim | tags em cache. `?atualizar=1` puxa na Amazon agora |
| GET | `/link?url=...&tag=...` | sim | um link. `asin` no lugar de `url` também vale |
| POST | `/links` | sim | até 50 itens, resposta na mesma ordem |
| POST | `/refresh-tags` | sim | atualiza a lista de tags agora |

### Um link

```bash
curl -sS \
  -H "x-api-key: $AMZ_TOKEN" \
  "http://127.0.0.1:3070/link?url=https://www.amazon.com.br/dp/B0CP9Z56SW&tag=souleitor-20"
```

### Lote

```bash
curl -sS -X POST http://127.0.0.1:3070/links \
  -H "content-type: application/json" \
  -H "x-api-key: $AMZ_TOKEN" \
  -d '{"items":[{"url":"https://www.amazon.com.br/dp/B0CP9Z56SW","tag":"souleitor-20"}]}'
```

A resposta é um array. Item com sucesso tem o objeto do link. Item com falha tem `{ "error", "message" }` e não derruba o restante. Mais de 50 itens, JSON inválido ou `items` ausente é `400` no lote inteiro.

### Python

```python
import json
import os
import urllib.request

request = urllib.request.Request(
    "http://127.0.0.1:3070/links",
    data=json.dumps({
        "items": [
            {"url": "https://www.amazon.com.br/dp/B0CP9Z56SW", "tag": "souleitor-20"},
        ]
    }).encode(),
    headers={
        "content-type": "application/json",
        "x-api-key": os.environ["AMZ_TOKEN"],
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=180) as response:
    for item in json.load(response):
        print(item["url"])
```

O primeiro lote sem cache pode levar cerca de 1,5 s por link novo. Chamada repetida do mesmo ASIN e da mesma tag volta na hora.

## Erros

Corpo: `{ "error": "CODIGO", "message": "..." }`.

| Código | HTTP | Quando |
|---|---|---|
| `NAO_AUTORIZADO` | 401 | chave ausente ou diferente |
| `ENTRADA_INVALIDA` | 400 | query repetida, item malformado ou lote inválido |
| `TAG_INVALIDA` | 400 | tag fora da conta. No lote, o erro fica no item |
| `ASIN_NAO_ENCONTRADO` | 400 | não deu para achar o ASIN. No lote, fica no item |
| `NAO_ENCONTRADO` | 404 | rota que não existe |
| `ERRO_INTERNO` | 500 | falha inesperada. No lote, pode ficar no item |

## Promo Livros

O painel usa esta API com a tag `AMAZON_AFFILIATE_TAG` e a chave `AMZ_TOKEN` do `.env` da raiz. `AMZ_LINK_API_URL` é opcional e o padrão é `http://127.0.0.1:3070`.

Entram no lote os posts `scheduled` que ainda não têm envio `sent` nem `sending` em `board_sends`. A legenda e o `url` de cada livro são regravados. Post que já foi para um grupo, ou que está no meio de um envio, fica com o link que saiu. URL que já começa em `https://link.amazon/` não é refeita. URL que não é da Amazon fica como está.

A fila da manhã e o post manual do painel passam pela mesma API na hora de gravar. O processo de envio tenta de novo, no máximo uma vez por minuto, o que ainda estiver com link antigo.
