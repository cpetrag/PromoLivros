# Migração WAHA (Docker) → zapo-js (Node, sem container)

Documento técnico da troca feita no Promo Livros em 25 out 2026. Serve de roteiro para repetir a migração em outro sistema que hoje fala com o WAHA.

## 1. Motivo e decisão

- O WAHA (imagem `devlikeapro/waha`, motor GOWS/whatsmeow) disparou o aviso "uso de ferramenta não autorizada" no número. O aparelho aparecia como navegador Ubuntu/Linux.
- A API oficial ficou descartada. O whatsapp-web.js também, por ser instável e pesado.
- A escolha foi o [zapo-js](https://zapo.to), em Node puro, sem container. Ele se apresenta como WhatsApp Web de verdade: Chrome no sistema real do Mac, telemetria WAM simulada e presença invisível ao conectar.
- **Regra da migração:** não mexer na lógica do sistema (fila, horários, enquetes, painel). A solução foi uma **ponte** (`zapo-bridge/`) que fala o mesmo subconjunto da API HTTP e o mesmo formato de webhook do WAHA. O cliente Python (`promo_livros/waha.py`) não mudou; só o `WAHA_URL` no `.env` mudou.

```
Antes:  Python ──HTTP──> WAHA (Docker, :4443) ──> WhatsApp
                 <──webhook── WAHA

Depois: Python ──HTTP──> zapo-bridge (Node/PM2, :4450) ──> WhatsApp
                 <──webhook── zapo-bridge
```

## 2. Estrutura da ponte

```
zapo-bridge/
  package.json            ESM ("type": "module"), node >= 20.9, scripts start/test
  ecosystem.config.cjs    PM2, 1 instância (duas conexões na mesma sessão se derrubam)
  .env / .env.example     porta, webhook, caminho do SQLite, navegador, nível de log
  src/
    config.js             lê .env da ponte e depois o .env do projeto (WAHA_API_KEY/WAHA_SESSION)
    log.js                log JSON + adaptador para o Logger do zapo
    errors.js             erros HTTP (422 "not working" = sessão caída)
    jid.js                @c.us <-> @s.whatsapp.net, id no formato WAHA
    media.js              base64/URL -> JPEG + largura/altura (sharp)
    poll-store.js         SQLite próprio com as opções de cada enquete enviada
    webhook.js            POST para o painel, fila única, retry com backoff
    whatsapp.js           WaClient, estados, reconexão, eventos, envio
    server.js             rotas express compatíveis com WAHA
  test/                   node --test (26 testes)
  data/                   zapo.sqlite (credenciais/sinal) + bridge.sqlite (enquetes), modo 700
  logs/                   saída do PM2
```

### Dependências (versões fixas)

| Pacote | Versão | Uso |
| --- | --- | --- |
| `zapo-js` | 1.10.0 | cliente WhatsApp |
| `@zapo-js/store-sqlite` | 1.3.0 | persistência (auth, sinal, mensagens, caches) |
| `@zapo-js/wam` | 0.1.1 | telemetria WAM simulada (parece WhatsApp Web real) |
| `@zapo-js/media-utils` | 1.0.0 | thumbnail de imagem (sharp) |
| `sharp`, `file-type` | 0.35.5 / 22.2.0 | imagem e detecção de mimetype |
| `better-sqlite3` | 13.0.3 | SQLite (store do zapo e tabela de enquetes) |
| `ws` | 8.22.0 | WebSocket |
| `qrcode` | 1.5.4 | QR em PNG |
| `express`, `dotenv` | 5.3.0 / 18.0.9 | HTTP e .env |

`sharp` e `better-sqlite3` são nativos: rode `npm ci` **na máquina que vai executar**. Um `node_modules` instalado no Windows não funciona no Mac.

## 3. Configuração (`.env`)

| Variável | Padrão | Observação |
| --- | --- | --- |
| `WAHA_API_KEY` | — | obrigatória; a mesma do Python, lida do `.env` do projeto |
| `WAHA_SESSION` | `promo-livros` | nome da sessão; `^[A-Za-z0-9_-]{1,64}$` |
| `BRIDGE_HOST` | `127.0.0.1` | só localhost |
| `BRIDGE_PORT` | `4450` | 4443/4444 estavam presas pelo Docker Desktop |
| `BRIDGE_WEBHOOK_URL` | `http://127.0.0.1:8787/whatsapp/webhook` | votos e comandos vão para cá |
| `BRIDGE_DB_PATH` | `data/zapo.sqlite` | relativo à pasta da ponte |
| `BRIDGE_DEVICE_BROWSER` | `chrome` | chrome, firefox, safari, edge, opera |
| `BRIDGE_LOG_LEVEL` | `info` | trace..error |

Sem `WAHA_API_KEY` a ponte não sobe. Nenhum segredo fica no código.

## 4. Montagem do cliente zapo

```js
const sqlite = createSqliteStore({
  path: config.dbPath,
  // o segredo da enquete precisa sobreviver a restarts para os votos serem decifrados
  cacheTtlMs: { messageSecretMs: 45 * 24 * 60 * 60 * 1000 },
});
const store = createStore({
  backends: { sqlite },
  providers: {            // com backends, TODOS os providers precisam ser declarados
    auth: 'sqlite', signal: 'sqlite', preKey: 'sqlite', session: 'sqlite',
    identity: 'sqlite', senderKey: 'sqlite', appState: 'sqlite', privacyToken: 'sqlite',
    messages: 'sqlite', threads: 'sqlite', contacts: 'sqlite',
  },
  cacheProviders: { messageSecret: 'sqlite', deviceList: 'sqlite', groupMetadata: 'sqlite' },
});

new WaClient({
  store,
  sessionId: config.session,
  deviceBrowser: 'Chrome',          // SO = o real do processo (Mac OS no Mac)
  recoverFromClientTooOld: true,    // em 405 busca a versão atual do WA Web e reconecta
  markOnlineOnConnect: false,       // bot não aparece "online"
  plugins: [wamPlugin()],
  media: { processor: createMediaProcessor(), generateThumbnail: true, generateProbe: false },
}, logger);
```

- `generateProbe: false`: o probe usa ffprobe, desnecessário para imagem. Largura e altura vêm do sharp em `media.js`.
- `messageSecret` em SQLite é essencial. No padrão (memória) os votos de enquetes enviadas antes de um restart ficam ilegíveis.

## 5. Ciclo da sessão e reconexão

O zapo **não reconecta sozinho**. A ponte controla isso e mapeia os estados para os do WAHA, que o Python já entende:

| Evento zapo | Status WAHA | `connection_state()` no Python |
| --- | --- | --- |
| `connect()` chamado | `STARTING` | `starting` |
| `auth_qr {qr}` | `SCAN_QR_CODE` | `qr` |
| `auth_paired` | `STARTING` | `starting` |
| `connection {status:'open'}` | `WORKING` | `connected` |
| `close` por motivo fatal / `isLogout` | `FAILED` | `disconnected` |
| `close` com `client_disconnected` (nós) | `STOPPED` | `disconnected` |
| `close` sem estar pareado (QR expirou) | `STOPPED` | `disconnected` |
| `close` comum | `STARTING` + reconexão | `starting` |

- **Motivos fatais** (não reconecta, espera ação humana): `stream_error_replaced`, `stream_error_device_removed`, `stream_error_force_logout`, `failure_not_authorized`, `failure_banned`, `failure_locked`, `failure_client_too_old`, `failure_bad_user_agent`, `primary_identity_key_change`.
- **Backoff:** `min(5 min, 2 s × 2^tentativa)`; zera ao abrir.
- `restart` (usado pelo "parear" do painel) faz `disconnect()` e depois `connect()` **sem aguardar**. Durante o pareamento o `connect()` só termina quando o QR é lido, e o painel precisa da resposta HTTP antes disso.
- Desligamento (SIGINT/SIGTERM) usa `disconnect()`, nunca `logout()`: o pareamento continua valendo no próximo boot.
- `mex_notification` com `kind: 'message_capping'` é logado como `warn`. É o aviso de cota de mensagens do WhatsApp.

## 6. Contrato HTTP (subconjunto do WAHA)

Todas as rotas exigem o cabeçalho `x-api-key`, comparado por sha256 + `timingSafeEqual`. Só `/health` é aberta.

| Método e rota | Corpo / retorno |
| --- | --- |
| `GET /health` | `{status, uptime}` |
| `GET /api/sessions/{s}` | `{name, status, me:{id}, engine:{engine:'ZAPO'}}` |
| `POST /api/sessions/{s}/start` | inicia em segundo plano |
| `POST /api/sessions/{s}/restart` | desconecta e reconecta (gera QR novo se não pareado) |
| `POST /api/sessions/{s}/stop` | desconecta mantendo credenciais |
| `PUT /api/sessions/{s}` | **501** "not implemented": o webhook vem do `.env` |
| `GET /api/{s}/auth/qr` | `image/png`; 422 JSON se não houver QR |
| `GET /api/{s}/groups` | `[{id:'...@g.us', name}]` (cache de 60 s) |
| `GET /api/{s}/groups/{chatId}/participants/v2` | `[{id, role}]`, role = participant/admin/superadmin |
| `GET /api/{s}/lids` | `[{lid:'...@lid', pn:'...@c.us'}]`, montado a partir dos participantes dos grupos |
| `POST /api/sendText` | `{session, chatId, text}` → `{id, key}` |
| `POST /api/sendImage` | `{session, chatId, caption, file:{mimetype, filename, url \| data(base64)}}` |
| `POST /api/sendPoll` | `{session, chatId, poll:{name, options, multipleAnswers}}` |
| `POST /api/{s}/chats/{chatId}/messages/{msgId}/pin` | `{duration}` em segundos (1..2592000) |
| `POST /api/{s}/chats/{chatId}/messages/{msgId}/unpin` | sem corpo |

### Erros (o Python decide pelo status e pelo texto)

| Situação | HTTP | Efeito no `WahaClient` |
| --- | --- | --- |
| Sessão não está `WORKING` | 422 + "Session status is not working" | `session_down=True` → reagenda |
| Sem chave ou chave errada | 401 | `session_down=True` |
| Entrada inválida / imagem ilegível | 400 | erro comum |
| Sessão com outro nome | 404 | erro comum |
| `PUT` de sessão | 501 + "not implemented" | `unsupported=True` |

### Validação de entrada

- `chatId`: `^[0-9A-Za-z.:_-]{1,64}@(c.us|s.whatsapp.net|g.us|lid)$`
- `messageId`: aceita o id puro ou o formato WAHA `true_<chat>_<id>[_<participante>]`; o id precisa casar com `^[A-Za-z0-9]{6,64}$`
- Texto/legenda: até 65 536 caracteres. Enquete: nome até 255; 2 a 12 opções, cada uma até 100, sem repetir.
- Imagem: até 8 MB, `http(s)` ou base64 válido, download com timeout de 20 s. Sempre convertida para JPEG, com rotação EXIF aplicada.
- Corpo JSON até 12 MB.

## 7. Conversões de formato

**JID:** o WAHA e o Python usam `@c.us`; o zapo usa `@s.whatsapp.net`.

- Saída (`toWahaJid`): `5511...@s.whatsapp.net` → `5511...@c.us`; remove o sufixo de aparelho (`5511...:12@...`). `@g.us` e `@lid` passam iguais.
- Entrada (`toZapoJid`): `@c.us` → `@s.whatsapp.net`.

**Id de mensagem:** a ponte devolve `true_<chat>_<stanzaId>`, o mesmo formato do WAHA. Assim ids antigos e novos convivem no banco. O Python compara ids pelo último token hexadecimal (`[0-9A-F]*[A-F][0-9A-F]{9,}`), e o webhook de voto usa exatamente a mesma string devolvida no envio.

**Enquete:** `multipleAnswers: true` → `selectableCount: 0` (no WhatsApp, 0 = várias respostas); `false` → `1`.

**Fixar:** `{type:'pin', target:{remoteJid, id, fromMe:true}, durationSecs}`. Sem `durationSecs` o pin não aparece nos outros aparelhos.

## 8. Webhook (ponte → painel)

Formato WAHA: `{id, event, session, payload}`, com cabeçalho `x-api-key`. A entrega é em **fila única** (a ordem dos votos importa), com timeout de 10 s e 3 novas tentativas (1 s, 3 s, 9 s) em erro de rede ou 5xx. Resposta 4xx = rejeição definitiva, sem nova tentativa.

| Evento zapo | `event` | `id` (dedupe) | `payload` |
| --- | --- | --- | --- |
| `message` em grupo, com texto | `message` | `msg_<id>` | `{id, timestamp, from:grupo, participant, fromMe, body}` |
| `message_addon` `poll_vote` resolvido | `poll.vote` | `vote_<id>` | `{vote:{id, from, fromMe, selectedOptions:[nomes], timestamp(ms)}, poll:{id, to}}` |
| voto que não deu para resolver | `poll.vote.failed` | `vote_<id>` | `{vote:{id, from}, poll:{id}}` |

- Texto da mensagem: `conversation ?? extendedTextMessage.text ?? imageMessage.caption`.
- `timestamp` do voto: `pollVote.senderTimestampMs`, em **milissegundos**. O painel já aceitava ms (`timestamp > 10_000_000_000`), e com ms dois votos no mesmo segundo não se anulam.

### Resolução do voto (dupla garantia)

1. O zapo decifra o voto com o `messageSecret` guardado e devolve `selectedOptionNames`.
2. Se vier `null`, a ponte usa a própria tabela `sent_polls` (`bridge.sqlite`): compara o `sha256(nome da opção)` com `pollVote.selectedOptions`. A retenção é de 60 dias.
3. Se nenhum dos dois resolver, emite `poll.vote.failed`. Falha de decifração no zapo só aparece no log em nível debug, sem evento próprio.

## 9. Testes

- **Ponte (`npm test`, 26 testes):** conversão de JID e ids; tabela de enquetes (hash); webhook (formato, retry 5xx, desistência em 4xx); estados e reconexão; voto com e sem nomes do zapo; mensagem de grupo; grupos, participantes e lids; pin com id WAHA; rotas HTTP (chave, 422 "not working", base64 com medidas, validação de enquete, 501 no PUT, QR ausente).
- **Smoke real:** ponte com o zapo de verdade, sem parear. Conecta no `wss://web.whatsapp.com` e devolve o QR em PNG.
- **Compatibilidade:** o próprio `WahaClient` do Python contra a ponte: `connection_state`, `fetch_qr_png`, envio com sessão caída (`session_down=True`), `begin_pairing`, `list_groups`, `lid_links`. O webhook do painel aceitou um evento com a chave.

## 10. Implantação no Mac (feita)

```bash
cd "/Volumes/HD 1Tb/Vibecoding/Promo Livros/zapo-bridge"
rm -rf node_modules && npm ci          # binários nativos do macOS
npm test
pm2 start ecosystem.config.cjs && pm2 save
```

1. `.env` do projeto: `WAHA_URL=http://127.0.0.1:4450`, com backup em `.env.bak-waha-<data>`.
2. `chmod 700 data` e `chmod 600 data/*`. O código também cria a pasta com modo 700.
3. Reiniciar os processos Python que leem o `.env` só na subida: `pm2 restart promo-livros-envio` e o painel.
4. O painel passou para o PM2 (`promo-livros-painel`) com o script de entrada `scripts/painel_run.sh`, que usa o Python do venv.
5. Túnel Cloudflare: removida a regra `esteira.promolivros.org → :4443`, que expunha o WAHA. Backup em `~/.cloudflared/promo-livros.yml.bak-<data>`; depois, `pm2 restart promo-livros-tunnel`.
6. Pareamento pelo QR do painel. Status `WORKING` às 17:27.

Processos finais no PM2: `zapo-bridge`, `promo-livros-envio`, `promo-livros-fila`, `promo-livros-painel`, `promo-livros-tunnel`, `promo-livros-web`.

## 11. Armadilhas encontradas

| Problema | Causa | Solução |
| --- | --- | --- |
| Porta 4443/4444 ocupada sem WAHA respondendo | Docker Desktop travado (API 500) continua segurando as portas publicadas | ponte na 4450 e `WAHA_URL` apontando para ela |
| `docker ps` trava | daemon do Docker quebrado | não depender do Docker; parar o container quando ele voltar |
| PM2 com `/bin/bash: /Volumes/HD: No such file` | PM2 quebra o caminho do interpretador no espaço ("HD 1Tb") | `pm2 start /bin/bash -- "<script>.sh"`, com um script de entrada que faz `cd` e `exec` |
| Processo Python continua no endereço antigo | `load_dotenv` não sobrescreve variável já carregada; config lida na subida | reiniciar os processos depois de mudar o `.env` |
| `sharp`/`better-sqlite3` falham no Mac | `node_modules` instalado no Windows (pasta compartilhada) | `rm -rf node_modules && npm ci` no Mac |
| Comandos via `ssh` quebrando | aspas do PowerShell e `\r` do Windows | mandar o script por stdin: `Get-Content -Raw x.sh \| ssh mac "tr -d '\r' \| bash"` |
| Votos ilegíveis após restart | `messageSecret` em memória (padrão) | `cacheProviders.messageSecret: 'sqlite'` + TTL longo |
| Painel travado esperando o restart | `connect()` só termina após ler o QR | `restart` dispara o connect em segundo plano |

## 12. O que fica diferente do WAHA

- Não há painel web próprio nem Swagger. O QR é servido pela API e mostrado no painel do sistema.
- O webhook não é configurável via API (`PUT /api/sessions` → 501). Ele vem de `BRIDGE_WEBHOOK_URL`.
- Enquetes enviadas pelo WAHA antes da troca não recebem mais votos: o segredo delas ficou no WAHA.
- Só existe uma sessão por processo. Para outro número, suba outra instância com outra porta, outra `WAHA_SESSION` e outro `BRIDGE_DB_PATH`. Nunca rode duas instâncias na mesma sessão: elas se derrubam com `stream_error_replaced`.

## 13. Voltar atrás

1. `pm2 stop zapo-bridge`.
2. Restaurar `WAHA_URL=http://127.0.0.1:4443` (ou o backup `.env.bak-waha-*`).
3. Subir o `waha-livros` (`waha/docker-compose.yml`) e reiniciar `promo-livros-envio` e `promo-livros-painel`.
4. Se precisar do painel do WAHA, restaurar o backup do túnel.

## 14. Checklist para outro sistema

1. Listar as chamadas que o sistema faz ao WAHA (rotas, corpos, campos lidos da resposta) e os eventos de webhook que ele consome. Comparar com as seções 6 e 8; o que faltar, implementar em `server.js`/`whatsapp.js`.
2. Conferir como o cliente detecta "sessão caída" (status/texto) e como compara ids de mensagem; manter o formato `true_<chat>_<id>` se ele depender disso.
3. Copiar `zapo-bridge/`, ajustar `.env` (porta livre, `WAHA_SESSION`, `BRIDGE_WEBHOOK_URL`, `BRIDGE_DB_PATH` no disco desejado).
4. `npm ci` e `npm test` na máquina de destino.
5. Rodar o cliente real do sistema contra a ponte antes de trocar o `WAHA_URL` de produção (smoke com QR, envio com sessão caída, grupos).
6. Trocar `WAHA_URL`, reiniciar os processos que leem o `.env`, parear pelo QR.
7. Desligar o WAHA antigo e remover rotas públicas que apontavam para ele.
