# Logos das lojas no card — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colocar a logo da loja centrada embaixo de cada capa no card do post, mantendo a Black Livros no canto.

**Architecture:** Estender `render_card(covers, destination, *, stores=None)` em `promo_livros/post_card.py`. Com `stores` alinhado às capas, desenha as logos (assets em `promo_livros/assets/`). Magalu usa escala 85% e +12 px. `extract_covers` tenta o layout novo (exclui faixa das logos) e cai no antigo se o contagem não bater. Callers que já sabem a loja passam `stores`.

**Tech Stack:** Python, Pillow (PIL), unittest

**Spec:** `docs/superpowers/specs/2026-11-19-logos-loja-no-card-design.md`

---

## File map

| File | Responsibility |
|---|---|
| `promo_livros/assets/store_*.{webp,png}` | Logos das 4 lojas (copiadas de `Logos/`) |
| `promo_livros/post_card.py` | `render_card` + `_store_logo` + `extract_covers` |
| `tests/test_post_card.py` | Testes do card e do recorte |
| `promo_livros/catalog.py` | Passar `stores` em `publish_selection` |
| `promo_livros/board_actions.py` | Passar `stores` no post manual |
| `promo_livros/troca_livro.py` | Passar `stores` ao remontar |
| `promo_livros/morning.py` | Passar `stores=["amazon"]` |
| `scripts/carregar_fila.py` | Passar `stores` derivados das URLs |

---

### Task 1: Copiar assets das logos

**Files:**
- Create: `promo_livros/assets/store_amazon.webp`
- Create: `promo_livros/assets/store_ml.png`
- Create: `promo_livros/assets/store_shopee.webp`
- Create: `promo_livros/assets/store_magalu.png`

- [ ] **Step 1: Copiar os arquivos**

```powershell
Copy-Item "Logos\logo amazon.webp" "promo_livros\assets\store_amazon.webp"
Copy-Item "Logos\logo mercado livre.png" "promo_livros\assets\store_ml.png"
Copy-Item "Logos\shopee-logo-2.webp" "promo_livros\assets\store_shopee.webp"
Copy-Item "Logos\logo magalu.png" "promo_livros\assets\store_magalu.png"
```

- [ ] **Step 2: Confirmar que os quatro existem**

```powershell
Get-ChildItem promo_livros\assets\store_*
```

Expected: quatro arquivos (`store_amazon.webp`, `store_ml.png`, `store_shopee.webp`, `store_magalu.png`).

- [ ] **Step 3: Commit**

```bash
git add promo_livros/assets/store_amazon.webp promo_livros/assets/store_ml.png promo_livros/assets/store_shopee.webp promo_livros/assets/store_magalu.png
git commit -m "Add store logo assets for the post card."
```

---

### Task 2: Testes de `render_card` com `stores` (TDD)

**Files:**
- Create: `tests/test_post_card.py`
- Modify: `promo_livros/post_card.py` (nas tasks seguintes)

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/test_post_card.py`:

```python
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from promo_livros.post_card import _BEIGE, extract_covers, render_card

RED, BLUE = (200, 30, 30), (30, 60, 200)


def _cover(color, size=(196, 280)):
    return Image.new("RGB", size, color)


def _non_beige_bbox(image: Image.Image):
    from PIL import ImageChops

    rgb = image.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, _BEIGE[:3])).convert("L")
    mask = diff.point(lambda value: 255 if value > 24 else 0)
    return mask.getbbox()


class RenderCardStoreLogosTests(unittest.TestCase):
    def test_without_stores_keeps_old_height_formula(self):
        with tempfile.TemporaryDirectory() as tmp:
            cover = _cover(RED)
            cover.thumbnail((280, 280), Image.Resampling.LANCZOS)
            destination = Path(tmp) / "old.jpg"
            render_card([_cover(RED)], destination)
            with Image.open(destination) as image:
                # layout antigo: cover_h + margin*2 + band
                self.assertEqual(image.height, cover.height + 28 * 2 + 78)

    def test_with_stores_makes_card_taller_than_without(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "plain.jpg"
            branded = Path(tmp) / "branded.jpg"
            render_card([_cover(RED), _cover(BLUE)], plain)
            render_card(
                [_cover(RED), _cover(BLUE)],
                branded,
                stores=["amazon", "ml"],
            )
            with Image.open(plain) as a, Image.open(branded) as b:
                self.assertGreater(b.height, a.height)

    def test_unknown_store_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "card.jpg"
            render_card([_cover(RED)], destination, stores=["loja-fantasma"])
            self.assertTrue(destination.is_file())

    def test_magalu_logo_is_smaller_and_lower_than_shopee(self):
        """Compara a faixa sob cada capa: Magalu ocupa menos e começa mais baixo."""
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "card.jpg"
            left, right = _cover(RED), _cover(BLUE)
            render_card([left, right], destination, stores=["shopee", "magalu"])
            with Image.open(destination) as image:
                rgb = image.convert("RGB")
            # Metades do card (capas centradas); olha só a faixa sob as capas.
            # margin(28) + max cover (~280) = ~308; logos começam perto daí.
            mid = rgb.width // 2
            strip_top = 28 + 240  # abaixo da menor capa possível em 2-up
            left_strip = rgb.crop((0, strip_top, mid, rgb.height - 78))
            right_strip = rgb.crop((mid, strip_top, rgb.width, rgb.height - 78))
            left_box = _non_beige_bbox(left_strip)
            right_box = _non_beige_bbox(right_strip)
            self.assertIsNotNone(left_box)
            self.assertIsNotNone(right_box)
            left_h = left_box[3] - left_box[1]
            right_h = right_box[3] - right_box[1]
            self.assertLess(right_h, left_h)
            self.assertGreater(right_box[1], left_box[1])


class ExtractCoversWithStoresTests(unittest.TestCase):
    def test_extract_covers_ignores_store_logos(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "card.jpg"
            render_card(
                [_cover(RED), _cover(BLUE)],
                card,
                stores=["amazon", "ml"],
            )
            covers = extract_covers(card, 2)
            self.assertIsNotNone(covers)
            self.assertEqual(len(covers), 2)

    def test_extract_covers_still_works_on_old_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "card.jpg"
            render_card([_cover(RED), _cover(BLUE)], card)
            covers = extract_covers(card, 2)
            self.assertIsNotNone(covers)
            self.assertEqual(len(covers), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar os testes e ver falha**

```bash
python -m unittest tests.test_post_card -v
```

Expected: FAIL — `render_card() got an unexpected keyword argument 'stores'` (ou equivalente).

- [ ] **Step 3: Commit dos testes**

```bash
git add tests/test_post_card.py
git commit -m "Add failing tests for store logos on the post card."
```

---

### Task 3: Implementar logos em `render_card`

**Files:**
- Modify: `promo_livros/post_card.py`

- [ ] **Step 1: Acrescentar constantes e helpers de logo de loja**

No topo de `promo_livros/post_card.py`, depois de `_BEIGE`:

```python
_ASSETS = Path(__file__).resolve().parent / "assets"
_STORE_LOGOS = {
    "amazon": _ASSETS / "store_amazon.webp",
    "ml": _ASSETS / "store_ml.png",
    "shopee": _ASSETS / "store_shopee.webp",
    "magalu": _ASSETS / "store_magalu.png",
}
_STORE_SCALE = 0.55
_MAGALU_SCALE = _STORE_SCALE * 0.85
_MAGALU_EXTRA_DOWN = 12
_STORE_GAP = 10
# Faixa reservada sob as capas quando há logos (gap + altura típica + folga Magalu).
_STORE_STRIP = _STORE_GAP + 56 + _MAGALU_EXTRA_DOWN
```

Adicionar helpers (antes de `_logo`):

```python
def _prepare_store_logo(path: Path, max_w: int, *, store: str) -> Image.Image:
    source = Image.open(path).convert("RGBA")
    pixels = source.load()
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue, _alpha = pixels[x, y]
            if store == "amazon":
                is_orange = red > 180 and 70 < green < 170 and blue < 90
                is_ink = max(red, green, blue) < 70
                if not (is_orange or is_ink):
                    pixels[x, y] = (0, 0, 0, 0)
            elif red <= 28 and green <= 28 and blue <= 28:
                pixels[x, y] = (0, 0, 0, 0)
    box = source.getbbox()
    if box:
        source = source.crop(box)
    source.thumbnail((max_w, max_w), Image.Resampling.LANCZOS)
    return source


def _store_marks(fitted: list[Image.Image], stores: list[str]) -> list[Image.Image | None]:
    marks: list[Image.Image | None] = []
    for image, store in zip(fitted, stores):
        path = _STORE_LOGOS.get(store)
        if path is None or not path.is_file():
            marks.append(None)
            continue
        scale = _MAGALU_SCALE if store == "magalu" else _STORE_SCALE
        marks.append(_prepare_store_logo(path, max_w=int(image.width * scale), store=store))
    return marks
```

- [ ] **Step 2: Reescrever `render_card` para aceitar `stores` e desenhar as logos**

Substituir o corpo de `render_card` por:

```python
def render_card(
    covers: list[Image.Image],
    destination: Path,
    *,
    stores: list[str] | None = None,
    logo_path: Path | None = None,
) -> None:
    if not covers or len(covers) > 3:
        raise ValueError("O card leva de 1 a 3 capas.")
    side = 280 if len(covers) < 3 else 240
    fitted = []
    for cover in covers:
        image = cover.convert("RGB")
        image.thumbnail((side, side), Image.Resampling.LANCZOS)
        fitted.append(image)
    use_stores = stores is not None and len(stores) == len(fitted)
    marks = _store_marks(fitted, stores) if use_stores else []
    gap, margin, band = 24, 28, 78
    cover_h = max(image.height for image in fitted)
    mark_h = 0
    if marks:
        mark_h = max(
            (mark.height + (_MAGALU_EXTRA_DOWN if store == "magalu" else 0))
            for mark, store in zip(marks, stores)
            if mark is not None
        ) if any(mark is not None for mark in marks) else 0
    store_band = (_STORE_GAP + mark_h) if mark_h else 0
    row_w = sum(image.width for image in fitted) + gap * (len(fitted) - 1)
    width = max(margin * 2 + row_w, 520)
    # Sem logos de loja: margem embaixo das capas (layout antigo).
    # Com logos: capa → gap → logos → faixa Black Livros.
    if store_band:
        height = margin + cover_h + store_band + band
    else:
        height = cover_h + margin * 2 + band
    canvas = Image.new("RGBA", (width, height), _BEIGE)
    cursor = (width - row_w) // 2
    for index, image in enumerate(fitted):
        top = margin + (cover_h - image.height) // 2
        canvas.paste(image.convert("RGBA"), (cursor, top))
        if store_band and index < len(marks) and marks[index] is not None:
            mark = marks[index]
            down = _MAGALU_EXTRA_DOWN if stores[index] == "magalu" else 0
            mx = cursor + (image.width - mark.width) // 2
            my = margin + cover_h + _STORE_GAP + down
            canvas.alpha_composite(mark, (mx, my))
        cursor += image.width + gap
    brand = _logo(logo_path or _LOGO, 92 if len(fitted) == 1 else 100)
    canvas.alpha_composite(brand, (canvas.width - brand.width - 18, canvas.height - brand.height - 10))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(destination, "JPEG", quality=68, optimize=True)
```

- [ ] **Step 3: Ajustar `extract_covers` para layout novo e antigo**

Substituir o cálculo de `top`/`bottom` e o fluxo de detecção para tentar os dois layouts:

```python
def extract_covers(card: Path, count: int) -> list[Image.Image] | None:
    """Recorta as capas de um card já feito por `render_card`.

    A Shopee não guarda a foto do anúncio; o card é a única cópia da capa. As capas ficam
    lado a lado sobre o bege, com 24 px entre elas, acima da faixa da logo. Cards novos
    ainda têm logos de loja sob as capas — essa faixa é excluída. Se o recorte não achar
    exatamente `count` capas, devolve None.
    """
    from PIL import ImageChops

    if count < 1 or not card.is_file():
        return None
    margin, band, gap = 28, 78, 24
    with Image.open(card) as source:
        image = source.convert("RGB")
    # Novo (com logos) primeiro; antigo depois.
    for strip in (_STORE_STRIP, 0):
        top = margin
        bottom = image.height - band - (0 if strip else margin) - strip
        if strip:
            # No layout novo não há margem inferior entre logos e a faixa Black Livros.
            bottom = image.height - band - strip
        found = _covers_in_band(image, top, bottom, gap, count)
        if found is not None:
            return found
    return None


def _covers_in_band(
    image: Image.Image, top: int, bottom: int, gap: int, count: int
) -> list[Image.Image] | None:
    from PIL import ImageChops

    if bottom - top < 40:
        return None
    area = image.crop((0, top, image.width, bottom))
    diff = ImageChops.difference(area, Image.new("RGB", area.size, _BEIGE[:3])).convert("L")
    mask = diff.point(lambda value: 255 if value > 24 else 0)
    columns = mask.resize((mask.width, 1), Image.Resampling.BOX)
    filled = [columns.getpixel((x, 0)) > 6 for x in range(columns.width)]
    runs: list[list[int]] = []
    for x, on in enumerate(filled):
        if not on:
            continue
        if runs and x - runs[-1][1] < gap // 2:
            runs[-1][1] = x
        else:
            runs.append([x, x])
    runs = [run for run in runs if run[1] - run[0] >= 20]
    if len(runs) != count:
        return None
    covers = []
    for left, right in runs:
        strip = mask.crop((left, 0, right + 1, mask.height))
        profile = strip.resize((1, strip.height), Image.Resampling.BOX)
        rows = [profile.getpixel((0, y)) > 6 for y in range(profile.height)]
        first = next((y for y, on in enumerate(rows) if on), None)
        last = next((y for y in range(len(rows) - 1, -1, -1) if rows[y]), None)
        if first is None or last is None or last - first < 20:
            return None
        covers.append(image.crop((left, top + first, right + 1, top + last + 1)))
    return covers
```

Se `_STORE_STRIP` fixo for curto/longo demais e o teste Magalu/extract falhar, ajuste `_STORE_STRIP` para ` _STORE_GAP + mark_h_max` observado (ex.: 10 + 56 + 12 = 78) até `test_extract_covers_ignores_store_logos` passar — sem mudar a API.

- [ ] **Step 4: Rodar os testes**

```bash
python -m unittest tests.test_post_card tests.test_troca_livro.ExtractCoversTests -v
```

Expected: PASS em todos.

- [ ] **Step 5: Commit**

```bash
git add promo_livros/post_card.py tests/test_post_card.py
git commit -m "Draw store logos under each cover on the post card."
```

---

### Task 4: Passar `stores` em `catalog.py`

**Files:**
- Modify: `promo_livros/catalog.py` (trecho de `publish_selection` ~1500–1510 e `_covers_for`)

- [ ] **Step 1: Fazer `_covers_for` devolver também as lojas**

Substituir `_covers_for` por:

```python
def _covers_for(
    book: CatalogBook, alt: CatalogBook | None, download, thumbnail
) -> tuple[list[Image.Image], list[str]]:
    items = [book]
    if alt is not None:
        items.append(alt)
    items.sort(key=lambda item: _STORE_ORDER.get(item.store, 9))
    covers = [_one_cover(item, download, thumbnail) for item in items]
    stores = [item.store for item in items]
    return covers, stores
```

- [ ] **Step 2: Atualizar `publish_selection` para desempacotar e passar `stores`**

Onde hoje está:

```python
prepared = [(book, alt, _covers_for(book, alt, download, thumbnail)) for book, alt in chosen]
```

trocar para o mesmo, e no loop:

```python
for index, ((book, alt, pair), clock) in enumerate(zip(prepared, clocks)):
    covers, stores = pair
    rows = _store_rows(book, alt, primary_urls[index], alt_urls[index])
    payloads = [_payload(item, url, _safe_describe(describe, item)) for item, url in rows]
    post_id = store.add_post(
        day=day,
        clock=clock,
        caption=render_caption(payloads, sign_index=index),
        image_path="",
        books=[_board_book(payload) for payload in payloads],
    )
    render_card(covers, cards_dir / f"{post_id}.jpg", stores=stores)
    for image in covers:
        image.close()
    store.set_image(post_id, f"data/cards/{post_id}.jpg")
```

Qualquer outro uso de `_covers_for` no arquivo precisa desempacotar `(covers, stores)` do mesmo jeito.

- [ ] **Step 3: Rodar testes de catálogo/fila que montam card**

```bash
python -m unittest tests.test_fila_aplicar tests.test_board -v
```

Expected: PASS (ou só falhas pré-existentes não ligadas a `stores`).

- [ ] **Step 4: Commit**

```bash
git add promo_livros/catalog.py
git commit -m "Pass store names into render_card from the catalog."
```

---

### Task 5: Passar `stores` em `board_actions`, `troca_livro`, `morning`, `carregar_fila`

**Files:**
- Modify: `promo_livros/board_actions.py`
- Modify: `promo_livros/troca_livro.py`
- Modify: `promo_livros/morning.py`
- Modify: `scripts/carregar_fila.py`

- [ ] **Step 1: `board_actions.py` — post manual e revisão**

Importar `store_of` de `promo_livros.lojas`.

Em `schedule_manual`, depois de `_amazon_first`:

```python
stores = [store_of(book) for book in books]
...
render_card(covers, destination, stores=stores)
```

Em `revise_manual` (onde baixa uma capa e chama `render_card([download_image(cover_url)], destination)`), se o post tiver livros, preferir:

```python
stores = [store_of(book) for book in books][:1] or None
render_card([download_image(cover_url)], destination, stores=stores)
```

(Se `books` não estiver no escopo, passar `stores=None` e deixar o card sem logo de loja nessa edição de capa — YAGNI.)

- [ ] **Step 2: `troca_livro.py` — uma loja por imagem de capa**

Na montagem do card:

```python
covers = [cover for item in books for cover in item.covers]
stores = [store_of(item.book) for item in books for _ in item.covers]
render_card(covers, target, stores=stores)
```

- [ ] **Step 3: `morning.py`**

```python
render_card([cover], cards_dir / f"{post_id}.jpg", stores=["amazon"])
```

- [ ] **Step 4: `scripts/carregar_fila.py`**

Importar `store_of` (ou detectar pela URL de cada livro). Ao chamar `render_card`:

```python
from promo_livros.lojas import store_of
...
render_card(covers, destination, stores=[store_of(book) for book in books])
```

- [ ] **Step 5: Rodar regressão de troca e board**

```bash
python -m unittest tests.test_troca_livro tests.test_post_card -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add promo_livros/board_actions.py promo_livros/troca_livro.py promo_livros/morning.py scripts/carregar_fila.py
git commit -m "Wire store logos through manual posts, swaps, and morning queue."
```

---

### Task 6: Verificação visual rápida

**Files:** nenhum de produção (script temporário ok em `tmp/`)

- [ ] **Step 1: Gerar um card de conferência com assets reais**

```powershell
python -c @"
from pathlib import Path
from PIL import Image
from promo_livros.post_card import render_card

out = Path('tmp/check-logos-card.jpg')
out.parent.mkdir(exist_ok=True)
covers = [
    Image.new('RGB', (200, 280), (180, 40, 40)),
    Image.new('RGB', (200, 280), (40, 80, 180)),
]
render_card(covers, out, stores=['shopee', 'magalu'])
print(out.resolve())
"@
```

- [ ] **Step 2: Abrir `tmp/check-logos-card.jpg` e conferir**

Checklist:
- Shopee sob a capa esquerda
- Magalu menor e um pouco mais baixa sob a direita
- Black Livros no canto
- Sem fundo preto/xadrez nas logos

- [ ] **Step 3: Commit final só se houver ajuste fino de constante** (`_STORE_STRIP` / escala)

Se nada mudou além do tmp, não commit de `tmp/`.

---

## Self-review (plan vs spec)

| Spec | Task |
|---|---|
| Logos sob a capa, centradas | Task 3 |
| Escala 55%; Magalu 85% +12 px | Task 3 + teste Magalu |
| Sem badge branco; limpar fundo | `_prepare_store_logo` |
| Sem `stores` = layout antigo | Task 2/3 |
| Assets em `promo_livros/assets/` | Task 1 |
| Callers catalog/board/troca/morning/carregar | Tasks 4–5 |
| `extract_covers` com logos | Task 3 |
| Testes listados na spec | Task 2 |

Sem placeholders TBD. Tipos: `stores: list[str] | None` consistente em todas as tasks.
