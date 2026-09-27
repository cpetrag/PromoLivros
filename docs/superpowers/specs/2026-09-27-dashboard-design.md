# Dashboard do Promo Livros

A dashboard é a tela de operação da noite. Ela mostra a fila do dia, o estado do WhatsApp e deixa escolher os grupos que recebem o disparo. Não publica, não pula livro e não liga o envio.

## Onde abre

O processo roda no Mac, na pasta `/Volumes/HD 1Tb/Vibecoding/Promo Livros`, e escuta só em `127.0.0.1:8787`. O código não grava esse caminho: sqlite, log e `config.yaml` continuam relativos à pasta de onde o processo sobe. Essa pasta já está no volume HD 1Tb, que tem centenas de GB livres. O SSD interno está em 83% e não recebe arquivo novo deste bot.

O túnel Cloudflare `promo-livros` ganha o nome `painel.promolivros.org` apontando para a porta 8787. O painel do WAHA permanece em `esteira.promolivros.org/dashboard`. A sessão `promo-livros` do container `waha-livros` não muda de volume neste trabalho: continua em `~/waha/sessions-livros`, no SSD.

Quem abre a página passa por login. Usuário e senha vêm de `DASHBOARD_USERNAME` e `DASHBOARD_PASSWORD` no `.env`. São variáveis novas, distintas de `WAHA_DASHBOARD_USERNAME` e `WAHA_DASHBOARD_PASSWORD`. Se uma das duas estiver vazia, o processo não sobe. O cookie é httpOnly e guarda um token aleatório que vive só na memória desse processo; reiniciar pede login de novo. Login errado mostra o formulário outra vez, sem dizer qual campo falhou. Sem cookie válido, nenhuma rota responde conteúdo, inclusive a imagem do QR.

## Três páginas

A navegação é Hoje, WhatsApp e Grupos.

**Hoje** lê o dia de serviço no fuso `America/Sao_Paulo`. A grade usa os horários do `config.yaml`, que hoje são 20:00, 20:20, 20:40, 21:00, 21:20 e 21:40. Cada horário mostra nicho, título, preço e o status do livro na `daily_queue`: `ready`, `queued`, `posted` ou `skipped`, escritos na tela como pronto, na fila, publicado ou pulado. Abrir um livro mostra o texto da mensagem e uma linha por grupo da tabela `dispatches`: `na_fila`, `enviando`, `enviada`, `falhou` ou `expirada`. Se o horário ainda não gerou disparo, os grupos salvos aparecem como "ainda não entrou na fila". Se não houver linha na `daily_queue` desse dia, a página diz que a fila de hoje ainda não existe.

**WhatsApp** consulta a sessão `promo-livros` pelo cliente que já existe. Os estados na tela são conectado, QR e desconectado, os mesmos que `connection_state` devolve. O QR só aparece quando o estado é QR: o processo pede `GET /api/{sessão}/auth/qr` ao WAHA em `127.0.0.1:4443`, com `Accept: image/png`, e repassa a imagem. Se a resposta não for uma imagem, a página diz que não há QR. O navegador não chama o WAHA e não recebe `WAHA_API_KEY`. Se o WAHA não responder, a página diz isso e não mostra um QR vazio.

**Grupos** lista os grupos da sessão conectada e marca os que já estão em `whatsapp.groups`. Um grupo que está no YAML e não aparece na sessão continua na lista, marcado como fora da sessão, e só sai do arquivo se for desmarcado. Salvar reescreve só o bloco `groups` do `config.yaml`, com a mesma validação de hoje: id no formato `…@g.us`, sem repetir. O restante do arquivo, inclusive comentários, permanece. Salvar não altera `whatsapp.enabled`. Se `whatsapp.enabled` for `true` e a lista enviada vier vazia, a gravação é recusada. Se o WhatsApp não estiver conectado, a página pede para conectar e não apaga os grupos já salvos. O processo do relógio só lê a lista nova na próxima subida; a página diz isso depois de salvar.

A leitura do SQLite é somente leitura. A dashboard não grava `daily_queue`, `dispatches` nem `posts`. Se o banco estiver ocupado, a página pede para atualizar.

## Processo

Um segundo processo, `python -m promo_livros.dashboard`, sobe ao lado do agendador. Os dois não compartilham memória. A dashboard usa a biblioteca HTTP padrão do Python. Não entra framework web novo.

A montagem da grade e a edição do bloco de grupos são funções puras: recebem linhas ou o texto do YAML e devolvem o resultado, sem abrir rede.

## Fora deste trabalho

Ficam de fora: enviar agora, pular livro, segurar o disparo, editar nicho, horário ou filtro, ligar `whatsapp.enabled`, publicar no site, gerar imagem e mover o volume da sessão do WAHA para o HD de 1 TB.

## Testes

Os testes não chamam o WAHA, não abrem túnel e não mandam mensagem.

- A grade de hoje sai de linhas falsas do SQLite, inclusive o dia sem fila e o livro aberto com status por grupo.
- Salvar grupos troca só o bloco `groups` e deixa o resto do YAML igual, recusa id inválido ou repetido e recusa lista vazia quando o disparo está ligado.
- Pedido sem o cookie de sessão não recebe fila, QR nem lista de grupos.
