# Logos das lojas no card do post

## Objetivo

Cada capa do card do post ganha a logo da loja correspondente, centrada **embaixo** da capa (fora da arte do livro). A logo Black Livros continua no canto inferior direito.

Referência visual aprovada: `tmp/exemplo-card-logos-abaixo.jpg` (Amazon + ML) e `tmp/exemplo-card-logos-shopee-magalu.jpg` (Shopee + Magalu, com Magalu ~15% menor e um pouco mais baixa).

## Decisões

| Tema | Escolha |
|---|---|
| Abordagem | Estender `render_card` com lista `stores` alinhada às capas |
| Posição | Embaixo de cada capa, centrada na largura da capa |
| Escala padrão | ~55% da largura da capa |
| Magalu | ~85% da escala padrão (~46,75% da capa) e +12 px para baixo |
| Fundo das logos | Remover preto/xadrez; colar direto no bege (sem badge branco) |
| Sem `stores` | Card igual ao de hoje (só capas + Black Livros) |
| Arquivos | Copiar as 4 logos de `Logos/` para `promo_livros/assets/` |

## Fora de escopo

- Mudar texto/legenda do post
- Gerar cena com IA / mockup 3D
- Colocar logo da loja por cima da arte da capa
- Badge/pill branco atrás da logo da loja
- Trocar a logo Black Livros

## Layout

```
[ margem ]
[ capa₁ ]  gap  [ capa₂ ]  …
[ logo₁ ]       [ logo₂ ]     ← centradas sob cada capa
[ faixa Black Livros (canto inferior direito) ]
```

Constantes (alinhar ao exemplo aprovado):

- Fundo bege `(245, 241, 232)`
- Gap entre capas: 24 px
- Margem: 28 px
- Gap capa → logo da loja: 10 px
- Faixa inferior (Black Livros): 78 px (como hoje)
- Escala logo loja: `0.55` da largura da capa; Magalu `0.55 * 0.85`
- Offset vertical extra Magalu: `+12` px

## API

```python
def render_card(
    covers: list[Image.Image],
    destination: Path,
    *,
    stores: list[str] | None = None,
    logo_path: Path | None = None,
) -> None:
```

- `stores[i]` é a loja da capa `covers[i]` (`amazon` | `ml` | `shopee` | `magalu`).
- Se `stores` for `None` ou comprimento diferente de `covers`, não desenha logos de loja (comportamento atual).
- Loja desconhecida: trata como sem logo naquela capa (capa entra normal).

## Assets

Copiar para `promo_livros/assets/`:

| Loja | Origem | Destino sugerido |
|---|---|---|
| Amazon | `Logos/logo amazon.webp` | `store_amazon.webp` |
| Mercado Livre | `Logos/logo mercado livre.png` | `store_ml.png` |
| Shopee | `Logos/shopee-logo-2.webp` | `store_shopee.webp` |
| Magalu | `Logos/logo magalu.png` | `store_magalu.png` |

Preparação da logo (no código, na hora de colar):

- **Amazon:** manter tinta escura + seta laranja; descartar xadrez/cinza/branco.
- **Demais:** pixels quase pretos → transparentes; crop pelo bbox; thumbnail na escala da loja.

## Callers

Passar `stores` onde a loja já é conhecida:

- `promo_livros/catalog.py` — `publish_selection` / `_covers_for` (ordem já é por loja)
- `promo_livros/board_actions.py` — post manual (derivar de URL / `store_of`)
- `promo_livros/troca_livro.py` — ao remontar o card após troca
- `promo_livros/morning.py` / `scripts/carregar_fila.py` — se houver loja no contexto

## `extract_covers`

Hoje o recorte usa `band = 78` abaixo das capas. Com logos de loja entre capas e a faixa Black Livros, o recorte precisa **excluir** a faixa das logos da loja (altura máxima das logos + gap + offset Magalu), senão o detector de conteúdo trata logo como capa.

Reservar altura fixa da faixa de logos (ex.: baseada na escala máxima possível para a largura de capa do card) e subtrair de `bottom` junto com `band`.

Testes de `troca_livro` / board que dependem de `extract_covers` devem continuar passando com cards novos.

## Testes

- `render_card` com 2 capas + `stores=["amazon","ml"]` gera JPEG; altura maior que o card sem lojas.
- Magalu usa escala e offset distintos (assertar via imagem gerada ou helper de medição).
- Sem `stores`, geometria compatível com o card antigo (ou só Black Livros).
- `extract_covers` em card com logos de loja devolve exatamente `count` capas.
- Loja desconhecida não quebra o render.

## Critério de pronto

- Cards novos da fila/manual/troca saem com logo da loja sob cada capa.
- Black Livros permanece.
- Amazon, ML, Shopee e Magalu batem com os exemplos aprovados (Magalu menor e um pouco mais baixa).
- Recorte de capas em troca de livro continua funcionando.
