# amz-link-api

API interna que gera links de afiliado da Amazon Brasil (longo e curto `link.amazon`) para outros sistemas. Cada sistema manda a própria tag. A tag é conferida na lista da conta antes de gerar o link.

O encurtamento usa a sessão de Associado já aberta num Chromium persistente. As chamadas do SiteStripe rodam dentro dessa página. A senha não entra no código: o login, inclusive o 2FA, é manual.

Produção prevista: Mac Mini, Node 20+, PM2, SQLite e Cloudflare Tunnel. Instale as dependências **no Mac Mini**. O módulo do SQLite é nativo e não serve se for copiado de outro sistema.

## Instalação

```bash
cd amz-link-api
node -v   # 20 ou mais novo
npm install
npx playwright install chromium
cp .env.example .env
```

Gere a chave da API e cole em `AMZ_TOKEN`:

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

`AMZ_TOKEN` autentica quem chama a API. `AMZ_STORE_ID` é a loja principal da conta e também a tag usada quando o cliente não manda `tag`. As outras tags (WhatsApp, site, Telegram) precisam existir nessa conta de Associado.

O servidor escuta em `127.0.0.1`. Quem está fora chega pelo túnel.

## Primeiro login

O perfil do navegador só pode estar aberto num processo. Se o serviço já estiver no ar, pare antes.

```bash
pm2 stop amz-link-api
npm run login
```

Abre uma janela na Amazon. Entre na conta de Associado, conclua o 2FA e feche a janela (ou pressione Enter no terminal). O perfil fica em `amz-profile/`.

Suba de novo:

```bash
mkdir -p logs
pm2 start ecosystem.config.cjs
pm2 save
```

`GET /health` sem chave. `sessionOk: true` significa que o SiteStripe respondeu. Se cair, o Telegram avisa para rodar `npm run login` de novo. Enquanto isso a API continua devolvendo o link longo, que já comissiona.

Uma instância só. Dois processos no mesmo perfil derrubam o Chromium.

## Cloudflare Tunnel

No `config.yml` do `cloudflared`, aponte o hostname para a porta local:

```yaml
ingress:
  - hostname: links.seudominio.com
    service: http://127.0.0.1:3070
  - service: http_status:404
```

```bash
cloudflared tunnel route dns <TUNNEL> links.seudominio.com
```

O túnel não adiciona a chave. Cada sistema guarda o `AMZ_TOKEN` e a tag dele.

O contrato para quem consome está em [API.md](API.md).

## API

Header em todas as rotas, exceto `/health`:

```
x-api-key: <AMZ_TOKEN>
```

| Método | Rota | Uso |
|---|---|---|
| GET | `/health` | `{ sessionOk, lastTagsRefresh, uptime }` |
| GET | `/tags` | tags válidas da conta. `?atualizar=1` puxa a lista na Amazon agora |
| GET | `/link?url=...&tag=...` | um link; aceita `asin` no lugar de `url` |
| POST | `/links` | até 50 itens, na mesma ordem |
| POST | `/refresh-tags` | força a lista de tags |

O campo `url` é o que os outros sistemas devem usar. Se o encurtamento falhar, `shortUrl` vem `null` e `url` é o link longo com a tag certa.

Erros: `{ "error": "CODIGO", "message": "..." }`. `TAG_INVALIDA` e `ASIN_NAO_ENCONTRADO` são 400. Chave errada é 401. No lote, o erro fica dentro do item e o restante segue.

Entradas aceitas: ASIN, URL `amazon.com.br` (`/dp/`, `/gp/product/`, `/gp/aw/d/`) e encurtadores `amzn.to`, `link.amazon`, `a.co`. A query original é descartada.

### curl

```bash
curl -sS \
  -H "x-api-key: $AMZ_TOKEN" \
  "http://127.0.0.1:3070/link?url=https://www.amazon.com.br/dp/B0CP9Z56SW&tag=babypoupe-20"
```

```bash
curl -sS -X POST http://127.0.0.1:3070/links \
  -H "content-type: application/json" \
  -H "x-api-key: $AMZ_TOKEN" \
  -d '{"items":[{"url":"https://www.amazon.com.br/dp/B0CP9Z56SW","tag":"babypoupe-20"}]}'
```

### Node

```js
const response = await fetch(
  'http://127.0.0.1:3070/link?url=' + encodeURIComponent(productUrl) + '&tag=babypoupe-20',
  { headers: { 'x-api-key': process.env.AMZ_TOKEN } },
);
const link = await response.json();
console.log(link.url);
```

### Python

```python
import json
import os
import urllib.parse
import urllib.request

query = urllib.parse.urlencode({
    "url": "https://www.amazon.com.br/dp/B0CP9Z56SW",
    "tag": "babypoupe-20",
})
request = urllib.request.Request(
    f"http://127.0.0.1:3070/link?{query}",
    headers={"x-api-key": os.environ["AMZ_TOKEN"]},
)
with urllib.request.urlopen(request, timeout=30) as response:
    print(json.load(response)["url"])
```

## Operação

- Cache em `data/links.sqlite`, chave `(asin, tag)`. A segunda chamada igual não vai à Amazon e soma `hits`.
- A fila espera `MIN_INTERVAL_MS` entre um `getShortUrl` e o próximo. Leitura de cache não entra na fila.
- A lista de tags atualiza na subida e a cada `TAGS_REFRESH_MIN` minutos. A última lista fica no SQLite: se reiniciar deslogado, a validação continua.
- A página da Amazon recarrega a cada 6 horas. Se o Chromium morrer, a próxima requisição abre de novo.
- Log de cada geração: `asin`, `tag`, `cached`, `result` (`short` ou `fallback`) e `ms`.
- Testes: `npm test`.

Os caminhos `/associates/sitestripe/*` são internos da Amazon e podem mudar. Essa dependência está em `src/amazon.js`. O navegador está em `src/launcher.js`.
