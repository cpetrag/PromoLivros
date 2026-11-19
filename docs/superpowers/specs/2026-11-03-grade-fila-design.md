# Grade da fila na /hoje — Etapa 1

## Objetivo

Organizar a fila agendada de hoje sem recarregar a página: ver a fila inteira de uma vez, trocar posts de lugar, mandar um post direto para um horário e mexer nos horários em lote.

Fora desta etapa:

- Etapa 2: trocar só um livro entre dois posts (regera card e legenda dos dois).
- Etapa 3: a mesma grade na curadoria, editando o rascunho antes de aplicar.

## Tela

A `/hoje` ganha um seletor **Lista | Grade** no topo da fila. A escolha fica no `localStorage`. A lista atual não muda.

Na grade, cada post agendado é uma linha:

| Horário | Amazon | Mercado Livre ou Shopee | ⋯ |
|---|---|---|---|

- Cada célula de loja mostra miniatura, título em uma linha, preço e desconto. A célula da segunda loja traz a etiqueta "Mercado Livre" ou "Shopee". Post com uma loja só deixa a outra célula vazia.
- A loja de cada livro do post sai do link: Mercado Livre pelo `MLB`, Shopee por `is_shopee_product`, o resto é Amazon.
- A miniatura é o card do post (`/cards/{id}.jpg`). Quando a imagem falha, a célula mostra um retângulo neutro em vez do ícone quebrado.
- Posts enviados, pulados ou com falha ficam recolhidos acima da linha "agora", em um `<details>` com a contagem.
- Arrastar a linha pela alça ⠿ move o post para aquele ponto. Mesma regra de hoje: os horários ficam e cada post assume o horário da nova posição (`board_store.reorder`).

## Ações do menu ⋯

**Mover para…** abre a lista de horários livres e ocupados de hoje que ainda não passaram e estão dentro da janela.

- Horário livre: o post vai para ele.
- Horário ocupado: duas opções.
  - **Trocar com o post das HH:MM**: os dois trocam de horário.
  - **Entrar antes dele**: o post assume esse horário. O que estava lá e os seguintes descem uma posição, cada um assumindo o horário do próximo, até chegar ao lugar de onde o post saiu. Se o post vier de depois, o efeito é o mesmo de arrastar.

**Empurrar daqui em diante**: campo de minutos com sinal (−60 a +180). Soma o valor a este post e a todos os agendados depois dele.

**Abrir horário aqui**: empurra este post e os seguintes em um intervalo da grade (`post_interval_minutes`). O horário dele fica vazio.

**Reespaçar daqui em diante**: campo de intervalo em minutos (5 a 180). Mantém o horário deste post e coloca cada seguinte N minutos depois do anterior.

## Limites

- Só posts com `status = 'scheduled'` do dia mudam. Enviados, pulados e com falha não se mexem.
- Nenhum horário pode ficar igual ou antes de agora.
- Dois posts agendados não podem ter o mesmo horário.
- Fim da janela (`send_schedule().end`). Quando uma ação deixaria posts depois do fim, o servidor não grava nada e devolve:
  - quantos posts passariam e o horário do último;
  - o intervalo que faria tudo caber entre o primeiro horário afetado e o fim, arredondado para baixo, se ele for de pelo menos 5 minutos.

  A tela mostra um diálogo com três botões:
  1. **Encaixar com intervalo de N min**: aplica a ação e reespaça os afetados com esse intervalo.
  2. **Passar do horário de envio**: confirmação explícita. Aplica com os horários depois do fim e marca a ação com `permitir_fora=1`.
  3. **Cancelar**.

  O botão 1 só aparece quando o intervalo calculado é de pelo menos 5 minutos.
- O envio só dispara post com horário antes do fim (`clock < end`). Quando o botão 2 é usado, o servidor grava em `board_settings` a chave `send_end_extra:<dia>` com o último horário + 1 minuto. `board_send` passa a usar o maior entre o fim da regra e essa extensão do dia. A extensão vale só para aquele dia.
- "Fora da janela" é horário igual ou depois do fim (`clock >= end`), igual à regra do envio.
- Horário depois de 23:59 nunca é aceito, nem com confirmação.

## Servidor

Novas operações em `BoardStore`. Cada uma roda em uma transação, relê os posts agendados dentro do lock e recusa se algum id citado não estiver mais agendado.

| Método | Faz |
|---|---|
| `swap_clocks(day, a, b)` | troca horário e posição de dois posts |
| `insert_before(day, post_id, target_id)` | move o post para o horário do alvo, deslocando o trecho entre eles |
| `move_to_clock(day, post_id, clock)` | põe o post num horário livre |
| `shift_from(day, post_id, minutes)` | soma minutos a este e aos seguintes |
| `respace_from(day, post_id, interval)` | reespaça este e os seguintes |

A validação dos limites fica numa função pura em `promo_livros/fila_horarios.py`. Ela recebe a lista atual `(id, clock)`, a mudança proposta e os limites (agora, fim, `permitir_fora`), e devolve os novos horários ou o motivo da recusa com a sugestão de intervalo. O `BoardStore` só grava o que essa função aprovou. Assim, a regra de horário é testada sem SQLite.

Endpoints novos, todos `POST` com formulário e resposta JSON:

| Rota | Campos |
|---|---|
| `/hoje/trocar` | `id`, `com` |
| `/hoje/antes` | `id`, `de` |
| `/hoje/horario` | `id`, `clock` |
| `/hoje/empurrar` | `id`, `minutos`, `permitir_fora`, `intervalo` |
| `/hoje/reespacar` | `id`, `intervalo`, `permitir_fora` |
| `/hoje/horarios/desfazer` | nenhum |

Resposta de sucesso: `{"ok": true, "message": "...", "undo": "<token>"}`. Recusa por limite: `{"ok": false, "fora": {"count": 2, "last": "22:40", "fit_interval": 25}}`. Outro erro: `{"ok": false, "error": "..."}`. Depois do sucesso, a tela chama `/hoje/parcial` e troca só os fragmentos, como já faz.

"Abrir horário aqui" é `/hoje/empurrar` com `minutos` igual ao intervalo da grade.

Quando `intervalo` vem preenchido em `/hoje/empurrar`, a ação empurra e depois reespaça os afetados com esse intervalo (botão "Encaixar").

## Desfazer

Antes de gravar, cada ação guarda `(id, clock, position)` dos posts agendados do dia em `board_settings` com a chave `clock_undo`, junto com o horário em que foi salvo. `/hoje/horarios/desfazer` restaura esse retrato se:

- for o mesmo dia;
- tiver menos de 10 minutos;
- todos os ids ainda estiverem agendados.

Senão, recusa com mensagem. A tela mostra "Desfazer" no aviso por 8 segundos.

## Concorrência com o envio

O envio marca posts como enviados em outro processo. Toda operação relê o estado dentro do lock e da transação. Se um post citado acabou de sair, a resposta é `{"ok": false, "error": "O post das HH:MM acabou de sair."}` e a tela atualiza a grade.

## Testes

- `tests/test_fila_horarios.py`: troca; inserir antes vindo de cima e de baixo; empurrar positivo e negativo; reespaçar; recusa por passado, por colisão e por fim da janela com sugestão de intervalo; sugestão ausente abaixo de 5 minutos; `permitir_fora`; teto de 23:59.
- `tests/test_board.py`: cada método novo grava o resultado da função pura e recusa id que não está mais agendado.
- `tests/test_dashboard_http.py`: cada rota responde JSON nos três formatos e exige login.
