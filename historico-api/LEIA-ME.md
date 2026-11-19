# Histórico de posts

Servidor só de leitura. Responde o que já saiu no WhatsApp, quando e por quanto. Não grava no banco e não faz parte do painel.

Escuta em `127.0.0.1:8791`. A porta 8787 fica com o painel (`painel.promolivros.org`). O token está em `config.json`, no campo `token`.

O banco no config é o caminho local do Mac:

`/Volumes/HD 1Tb/Vibecoding/Promo Livros/data/promo_livros.sqlite`

Se o caminho for de rede, inclusive o `N:`, o processo recusa a subir.

## Iniciar, parar e log

No Mac, na pasta do projeto:

```bash
pm2 start /bin/bash --name promo-livros-historico -- "/Volumes/HD 1Tb/Vibecoding/Promo Livros/scripts/historico_run.sh"
pm2 save
```

```bash
pm2 stop promo-livros-historico
```

```bash
pm2 logs promo-livros-historico
```

O `pm2` chama o bash por causa do espaço em `HD 1Tb`, o mesmo motivo do painel.

## Túnel

A regra já está em `~/.cloudflared/promo-livros.yml`, antes do 404, e o processo `promo-livros-tunnel` foi reiniciado:

```yaml
- hostname: historico.promolivros.org
  service: http://127.0.0.1:8791
```

O certificado do `cloudflared` neste Mac só cria DNS na zona `macmini-capture.cc`, então o nome `historico.promolivros.org` ainda não existe. No painel da zona `promolivros.org`, o CNAME é:

`historico` → `569e5fde-a230-46e3-ae6a-a8538a3555eb.cfargotunnel.com` (proxied)

Apague também o registro criado por engano em outra zona: `historico.promolivros.org.macmini-capture.cc`. Ele aponta para o túnel `mac-capture`, não para este serviço.

A extensão manda o header `X-Token` com o valor de `config.json`. Sem esse header, `/postados`, `/historico` e `/recentes` respondem 401. `/saude` é aberto.
