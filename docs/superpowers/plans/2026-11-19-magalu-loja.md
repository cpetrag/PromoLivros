# Magazine Luiza — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Incluir Magazine Luiza como segunda loja (como a Shopee) e, no CSV da fila, monetizar o link Magalu e encurtar só essa URL no Aqui.

**Architecture:** Magalu vive em `ml_books` com `store=magalu`, detectada por host/path. `magalu_links.py` reescreve afiliado sem API Magalu. `aqui_links.py` chama `POST /api/v1/links` e grava `shortUrl`. No aplicar do CSV da fila, falha Magalu/Aqui = `LinkQuebrado` (oferta fora). Curadoria/`publish_selection` ainda não convertem/encurtam Magalu neste ciclo.

**Tech Stack:** Python 3.12, `urllib`, SQLite, unittest, dashboard `http.server` existente.

Spec: `docs/superpowers/specs/2026-11-19-magalu-loja-design.md`.

## Global Constraints

- Amazon continua o lado principal; Magalu divide a 2ª metade com ML e Shopee.
- Máximo 2 ofertas por post/linha.
- Só Magalu usa o Aqui; só no passo `link` do CSV da fila.
- Credenciais só via `.env` (`MAGALU_PROMOTER_ID`, `MAGALU_PARTNER_ID`, `AQUI_API_KEY`, `AQUI_BASE_URL`).
- Textos de UI em português do Brasil; nomes de código em inglês nos módulos novos (`magalu_links`, `aqui_links`).
- Não inventar parâmetros Magalu além de `promoter_id`, `partner_id`, `seller_id`.

## Arquivos

| Arquivo | Responsabilidade |
|---|---|
| Criar `promo_livros/magalu_links.py` | Hosts, id, rewrite afiliado, redirect |
| Criar `promo_livros/aqui_links.py` | Cliente HTTP do encurtador |
| Criar `tests/test_magalu_links.py` | Conversão Magalu |
| Criar `tests/test_aqui_links.py` | Cliente Aqui |
| Criar `tests/test_magalu_catalog.py` | Import/catálogo Magalu |
| Modificar `promo_livros/models.py` | Campos Magalu/Aqui em `AppConfig` |
| Modificar `promo_livros/config.py` | Ler env Magalu/Aqui |
| Modificar `.env.example` | Novas variáveis |
| Modificar `promo_livros/lojas.py` | `store_of` + `STORE_ORDER` |
| Modificar `promo_livros/catalog.py` | `replace_magalu`, parse, CSV folder |
| Modificar `promo_livros/fila.py` | `SlotFila.magalu`, `montar_fila` |
| Modificar `promo_livros/fila_csv.py` | Detectar Magalu nas colunas `_ml`; converter+encurtar |
| Modificar `promo_livros/dashboard.py` / `dashboard_curation.py` / `dashboard_grid.py` / `post_copy.py` / `price_log.py` | Aba, labels, wiring |
| Estender `tests/test_fila.py`, `tests/test_fila_csv.py`, `tests/test_config.py`, `tests/test_dashboard_grid.py` | Contratos |

---

### Task 1: `magalu_links` — detecção e rewrite

**Files:** Create `promo_livros/magalu_links.py`, `tests/test_magalu_links.py`

**Interfaces — Produces:**

```python
@dataclass(frozen=True)
class MagaluConvertResult:
    link_convertido: str
    tipo: str  # produto | divulgador | generico | redirect_resolvido
    ok: bool
    erro: str = ""

def is_magalu_url(url: str) -> bool: ...
def magalu_product_id(url: str) -> str: ...  # codigo do /p/{codigo}/ ou ""
def convert_magalu(
    url: str,
    *,
    promoter_id: str,
    partner_id: str,
    opener=urlopen,  # injetável nos testes
) -> MagaluConvertResult: ...
```

Hosts (hostname contém): `magazineluiza`, `magazinevoce`, `divulgador.magalu`, `influenciadormagalu`, `magalu.com`.

- [ ] **Step 1: Escrever testes que falham**

```python
# tests/test_magalu_links.py
import unittest
from urllib.parse import parse_qs, urlsplit
from promo_livros.magalu_links import convert_magalu, is_magalu_url, magalu_product_id

PROMOTER = "promoter-test"
PARTNER = "partner-test"

class MagaluLinksTests(unittest.TestCase):
    def test_hosts(self):
        self.assertTrue(is_magalu_url("https://www.magazineluiza.com.br/livro/p/abc123/sku/"))
        self.assertTrue(is_magalu_url("https://www.magazinevoce.com.br/x"))
        self.assertTrue(is_magalu_url("https://divulgador.magalu.com/r/xyz"))
        self.assertFalse(is_magalu_url("https://www.amazon.com.br/dp/B000000001"))

    def test_product_id_from_p_path(self):
        self.assertEqual(
            magalu_product_id("https://www.magazineluiza.com.br/livro-foo/p/jf7k9gad9/sku123/"),
            "jf7k9gad9",
        )

    def test_produto_p_vira_divulgador_oferta(self):
        raw = "https://www.magazineluiza.com.br/livro-foo/p/jf7k9gad9/sku123/"
        got = convert_magalu(raw, promoter_id=PROMOTER, partner_id=PARTNER)
        self.assertTrue(got.ok)
        self.assertEqual(got.tipo, "produto")
        parts = urlsplit(got.link_convertido)
        self.assertIn("/divulgador/oferta/jf7k9gad9/sku123", parts.path)
        self.assertNotIn("/p/", parts.path)
        qs = parse_qs(parts.query)
        self.assertEqual(qs["promoter_id"], [PROMOTER])
        self.assertEqual(qs["partner_id"], [PARTNER])

    def test_preserva_seller_id(self):
        raw = "https://www.magazineluiza.com.br/livro/p/abc/sku/?seller_id=999"
        got = convert_magalu(raw, promoter_id=PROMOTER, partner_id=PARTNER)
        self.assertEqual(parse_qs(urlsplit(got.link_convertido).query)["seller_id"], ["999"])

    def test_ja_divulgador_normaliza_e_sobrescreve_ids(self):
        raw = (
            "https://www.magazineluiza.com.br/livro/divulgador/oferta/abc/sku/"
            "?promoter_id=old&partner_id=old"
        )
        got = convert_magalu(raw, promoter_id=PROMOTER, partner_id=PARTNER)
        self.assertTrue(got.ok)
        self.assertEqual(got.tipo, "divulgador")
        qs = parse_qs(urlsplit(got.link_convertido).query)
        self.assertEqual(qs["promoter_id"], [PROMOTER])
        self.assertEqual(qs["partner_id"], [PARTNER])

    def test_generico_so_query(self):
        raw = "https://www.magazineluiza.com.br/busca/livro/"
        got = convert_magalu(raw, promoter_id=PROMOTER, partner_id=PARTNER)
        self.assertTrue(got.ok)
        self.assertEqual(got.tipo, "generico")
        qs = parse_qs(urlsplit(got.link_convertido).query)
        self.assertEqual(qs["promoter_id"], [PROMOTER])

    def test_redirect_divulgador_magalu(self):
        final = "https://www.magazineluiza.com.br/livro/p/abc/sku/"
        class FakeResp:
            def geturl(self):
                return final
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return b""
        def opener(request, timeout=0):
            return FakeResp()
        raw = "https://divulgador.magalu.com/r/xyz"
        got = convert_magalu(raw, promoter_id=PROMOTER, partner_id=PARTNER, opener=opener)
        self.assertTrue(got.ok)
        self.assertEqual(got.tipo, "redirect_resolvido")
        self.assertIn("/divulgador/oferta/abc/", got.link_convertido)

    def test_url_invalida_ok_false(self):
        got = convert_magalu("not-a-url", promoter_id=PROMOTER, partner_id=PARTNER)
        self.assertFalse(got.ok)
        self.assertEqual(got.link_convertido, "not-a-url")

    def test_nao_magalu_ok_false(self):
        raw = "https://www.amazon.com.br/dp/B000000001"
        got = convert_magalu(raw, promoter_id=PROMOTER, partner_id=PARTNER)
        self.assertFalse(got.ok)
        self.assertEqual(got.link_convertido, raw)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_magalu_links.py -q`  
Expected: FAIL (import / módulo ausente)

- [ ] **Step 3: Implementar `promo_livros/magalu_links.py`**

Regras na ordem do spec: redirect `divulgador.magalu.com` → `/p/` → path com `divulgador` → genérico. Usar `urllib.parse` para path/query. Em redirect, `Request` + `opener` e `geturl()` (ou header Location seguido manualmente se o opener de teste devolver URL final). Sem API Magalu. Sem inventar query keys.

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_magalu_links.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add promo_livros/magalu_links.py tests/test_magalu_links.py
git commit -m "Add Magalu affiliate URL rewrite without Magalu API."
```

---

### Task 2: Cliente Aqui

**Files:** Create `promo_livros/aqui_links.py`, `tests/test_aqui_links.py`

**Interfaces — Produces:**

```python
class AquiLinkError(Exception):
    """O encurtador Aqui não devolveu shortUrl."""

def create_short_link(
    url: str,
    *,
    api_key: str,
    base_url: str = "https://aqui.descontos.ai",
    title: str = "",
    opener=urlopen,
    timeout: float = 20,
) -> str:
    """POST /api/v1/links; devolve shortUrl."""
```

- [ ] **Step 1: Testes**

```python
# tests/test_aqui_links.py
import json
import unittest
from promo_livros.aqui_links import AquiLinkError, create_short_link

class _Response:
    def __init__(self, payload: dict, status: int = 201):
        self.payload = payload
        self.status = status
    def read(self):
        return json.dumps(self.payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

class AquiLinksTests(unittest.TestCase):
    def test_create_returns_short_url(self):
        seen = {}
        def opener(request, timeout=0):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data.decode())
            return _Response({
                "id": "1",
                "slug": "tv-55",
                "shortUrl": "https://aqui.descontos.ai/tv-55",
                "url": seen["body"]["url"],
            })
        got = create_short_link(
            "https://www.magazineluiza.com.br/x/divulgador/oferta/a/b/",
            api_key="aqui_testkey",
            title="Livro",
            opener=opener,
        )
        self.assertEqual(got, "https://aqui.descontos.ai/tv-55")
        self.assertEqual(seen["url"], "https://aqui.descontos.ai/api/v1/links")
        self.assertEqual(seen["auth"], "Bearer aqui_testkey")
        self.assertEqual(seen["body"]["url"].startswith("https://"), True)
        self.assertEqual(seen["body"]["title"], "Livro")

    def test_sem_api_key_erro(self):
        with self.assertRaises(AquiLinkError):
            create_short_link("https://exemplo.com", api_key="")

    def test_sem_short_url_erro(self):
        def opener(request, timeout=0):
            return _Response({"url": "https://destino"}, status=201)
        with self.assertRaises(AquiLinkError):
            create_short_link("https://exemplo.com", api_key="aqui_x", opener=opener)
```

- [ ] **Step 2:** `python -m pytest tests/test_aqui_links.py -q` → FAIL  
- [ ] **Step 3:** Implementar com `Request`, `Authorization: Bearer`, `Content-Type: application/json`, ler JSON, exigir `shortUrl`. Em HTTP ≠ 201 ou JSON sem `shortUrl`, levantar `AquiLinkError` com mensagem curta.  
- [ ] **Step 4:** PASS  
- [ ] **Step 5:** Commit `Add Aqui short-link client for Magalu URLs.`

---

### Task 3: Config e `.env.example`

**Files:** Modify `promo_livros/models.py`, `promo_livros/config.py`, `.env.example`; Test `tests/test_config.py`

**Interfaces — Produces (campos novos em `AppConfig`):**

```python
magalu_promoter_id: str
magalu_partner_id: str
aqui_api_key: str
aqui_base_url: str  # default https://aqui.descontos.ai, sem barra final
```

- [ ] **Step 1:** Em `tests/test_config.py`, adicionar:

```python
def test_loads_magalu_and_aqui_from_env(self) -> None:
    # montar environ de teste com:
    # MAGALU_PROMOTER_ID, MAGALU_PARTNER_ID, AQUI_API_KEY, AQUI_BASE_URL
    # assert nos quatro campos; AQUI_BASE_URL sem barra final
```

Defaults: strings vazias para ids/key; `aqui_base_url` default `https://aqui.descontos.ai`. Validar `AQUI_BASE_URL` como http(s) (mesmo padrão de `_amz_link_api_url`).

- [ ] **Step 2:** FAIL (campos inexistentes)  
- [ ] **Step 3:** Atualizar `AppConfig`, `_build`, `.env.example` com:

```env
MAGALU_PROMOTER_ID=
MAGALU_PARTNER_ID=
AQUI_API_KEY=
AQUI_BASE_URL=https://aqui.descontos.ai
```

- [ ] **Step 4:** PASS (`tests/test_config.py`)  
- [ ] **Step 5:** Commit `Load Magalu and Aqui credentials from environment.`

---

### Task 4: `lojas` + catálogo Magalu

**Files:** Modify `promo_livros/lojas.py`, `promo_livros/catalog.py`; Create `tests/test_magalu_catalog.py`; touch `tests/test_dashboard_grid.py` se `store_of` local divergir

**Interfaces:**

- `STORE_ORDER = {"amazon": 0, "ml": 1, "shopee": 2, "magalu": 3}`
- `store_of`: Magalu antes de ML/Amazon (`is_magalu_url` ou `magalu_product_id` no `product_id` quando URL Magalu)
- `CatalogStore.replace_magalu(rows, source, *, day=None) -> int` via `_replace_second("magalu", …)`
- `_replace_second` meta key: `magalu_source` (estender o `if store == "ml" else …`)
- `_second_store_of` / `_in_second_store`: incluir Magalu (id = `magalu_product_id` ou código do CSV; se id não bastar sozinho, URL no row decide na parse)
- `parse_rows(..., kind="magalu")`: exige `asin` = product id Magalu **e** `link` Magalu; URL final = link limpo do CSV (ainda sem afiliado/Aqui)
- `catalog_kind`: contar Magalu quando `is_magalu_url(link)` ou id Magalu conhecido
- `magalu_csv(folder) -> Path | None`: `magalu-livros.csv` / `magalu-livros-*.csv` / `magalu_livros_*.csv` (espelho `shopee_csv`)
- Qualquer `store in {"ml", "shopee"}` que trate segunda loja passa a incluir `"magalu"` (caixa, queue, picks)

**Id Magalu no CSV de catálogo:** coluna `asin` = código `/p/{codigo}/` (minúsculas preservadas ou normalizadas de forma estável — documentar no teste). Regex sugerida após extrair do link: código não-vazio do path; para CSV sem padrão MLB/Shopee/ASIN, aceitar se `is_magalu_url(link)` e `asin == magalu_product_id(link)` (ou asin igual ao código).

- [ ] **Step 1:** Testes em `tests/test_magalu_catalog.py` espelhando `test_shopee_catalog.py` (parse, `catalog_kind`, `magalu_csv`, `replace_magalu` mantém linhas ML/Shopee).  
- [ ] **Step 2:** FAIL  
- [ ] **Step 3:** Implementar  
- [ ] **Step 4:** PASS + `tests/test_dashboard_grid.py` se necessário (`store_of` Magalu)  
- [ ] **Step 5:** Commit `Add Magalu catalog import beside ML and Shopee.`

---

### Task 5: `montar_fila` com Magalu

**Files:** Modify `promo_livros/fila.py`; Test `tests/test_fila.py` (e `tests/test_ordem_manual.py` se quebrar)

**Interfaces:**

```python
@dataclass(frozen=True)
class SlotFila:
    ...
    magalu: ItemFila | None = None
    magalu_avisos: tuple[str, ...] = ()

def montar_fila(amazon, mercado, opcoes, shopee=None, magalu=None) -> FilaMontada:
    # segunda lista = mercado + shopee + magalu
    # _da_loja(..., "magalu")
```

Docstring: Magalu também divide a segunda metade.

- [ ] **Step 1:** Em `tests/test_fila.py`, caso: Amazon+ML no slot 0, Amazon+Magalu no slot 1 (ou ML/Shopee/Magalu intercalados por índice).  
- [ ] **Step 2:** FAIL  
- [ ] **Step 3:** Implementar; atualizar `_avisos` / consumidores de `SlotFila` que listam lojas (`fila_aplicar`, `catalog.publish_selection`, grade) para ler `slot.magalu`.  
- [ ] **Step 4:** PASS  
- [ ] **Step 5:** Commit `Let Magalu share the second half of queue slots.`

---

### Task 6: CSV da fila — detectar Magalu nas colunas `_ml`

**Files:** Modify `promo_livros/fila_csv.py`; Test `tests/test_fila_csv.py`

**Comportamento:**

1. Ao ler campos `_ml` (`asin_ml`, `link_ml`, …), se `is_magalu_url(link_ml)` **ou** o código/link for Magalu → anúncio com `store="magalu"` (não `"ml"`).
2. `_encaixar` ganha ramo `magalu`.
3. Linha parseada inclui chave `"magalu"` além de `ml`/`shopee`.
4. `_loja_do_texto` / `_codigo` / `_link_magalu` (novo) validam URL Magalu; mensagem com formatos Magalu.
5. `_passos` / `_nome_loja` / `_store_of`: incluir `magalu` → “Magazine Luiza”.
6. Sem conversão Aqui ainda nesta task — só parse/prévia com `store=magalu` e URL crua do CSV.

Ordem de detecção em `_ml`: Magalu → senão ML atual. Shopee continua em colunas `_shopee` se existirem.

- [ ] **Step 1:** Teste: CSV com `link_ml` Magalu + Amazon → prévia/`parse_fila_csv` com `store=magalu`. Teste: ML clássico continua `ml`.  
- [ ] **Step 2:** FAIL  
- [ ] **Step 3:** Implementar  
- [ ] **Step 4:** PASS  
- [ ] **Step 5:** Commit `Detect Magalu offers in fila CSV _ml columns.`

---

### Task 7: Converter + encurtar Magalu no aplicar CSV

**Files:** Modify `promo_livros/fila_csv.py`, `promo_livros/dashboard.py` (wiring `resolve_magalu`); Test `tests/test_fila_csv.py`

**Interfaces:**

```python
def _converter(..., resolve_shopee=None, resolve_magalu=None) -> None:
    if book.get("store") == "magalu":
        _converter_magalu(book, chave, resolve_magalu)
        return

def _converter_magalu(book, chave, resolve_magalu) -> None:
    # resolve_magalu([chave]) -> [shortUrl]
    # falha -> LinkQuebrado
```

`resolve_magalu` no dashboard (só CSV):

```python
def resolve_magalu(urls: list[str]) -> list[str]:
    from promo_livros.magalu_links import convert_magalu
    from promo_livros.aqui_links import create_short_link, AquiLinkError
    # para cada url: convert_magalu(...); se not ok -> raise LinkQuebrado
    # create_short_link(link_convertido, api_key=config.aqui_api_key, base_url=config.aqui_base_url, title=...)
    # AquiLinkError / credenciais vazias -> LinkQuebrado
```

`avancar` / `resolver_links`: passar `resolve_magalu`; incluir `magalu` no conjunto de stores que convertem com falha dura (`{"ml", "shopee", "magalu"}`).

Testes com doubles (sem rede):

- Magalu ok → `url_final` = shortUrl fake  
- Magalu convert fail → ignorado / `LinkQuebrado`  
- Aqui fail → ignorado  
- Shopee/Amazon no mesmo job **não** chamam Aqui (mock conta chamadas)

- [ ] **Step 1:** Testes com `resolve_magalu` injetado  
- [ ] **Step 2:** FAIL  
- [ ] **Step 3:** Implementar conversão + wiring  
- [ ] **Step 4:** PASS  
- [ ] **Step 5:** Commit `Shorten monetized Magalu links via Aqui on fila CSV apply.`

---

### Task 8: Curadoria UI + copy + price_log

**Files:** Modify `promo_livros/dashboard_curation.py`, `promo_livros/dashboard.py`, `promo_livros/dashboard_grid.py`, `promo_livros/post_copy.py`, `promo_livros/price_log.py` (e qualquer label “Mercado Livre ou Shopee” → incluir Magalu)

**Comportamento:**

- Aba Magazine Luiza; import `replace_magalu` / `magalu_csv` / stamp `magalu_source_stamp`
- Grade: tag Magalu; `store_of` reconhece Magalu
- `post_copy`: tratar URL Magalu (não como Amazon); texto de loja “Magazine Luiza” se já houver padrão por loja
- `price_log.STORES`: incluir `"magalu"` se a tupla listar segundas lojas
- **Não** ligar `resolve_magalu` em `publish_selection` neste ciclo (URL do catálogo)

- [ ] **Step 1:** Testes de grid/label existentes + um assert Magalu; smoke de import se houver teste de dashboard  
- [ ] **Step 2–4:** Implementar até PASS  
- [ ] **Step 5:** Commit `Show Magalu in curation, grid, and post copy.`

---

### Task 9: Verificação final

- [ ] Rodar: `python -m pytest tests/test_magalu_links.py tests/test_aqui_links.py tests/test_magalu_catalog.py tests/test_fila.py tests/test_fila_csv.py tests/test_config.py tests/test_dashboard_grid.py -q`  
- [ ] Grep rápido: nenhum `promoter_id`/`partner_id`/`aqui_` hardcoded com segredo real  
- [ ] Confirmar spec: Curadoria sem Aqui; CSV com Aqui; só Magalu no Aqui  
- [ ] Commit do spec se ainda estiver untracked: `docs/superpowers/specs/2026-11-19-magalu-loja-design.md`  
- [ ] Commit deste plano se ainda não versionado

---

## Spec coverage (self-review)

| Requisito do spec | Task |
|---|---|
| Magalu 2ª metade como Shopee | 4, 5, 8 |
| `magalu_links` rewrite + redirect | 1 |
| Cliente Aqui `shortUrl` | 2, 7 |
| Env Magalu/Aqui | 3 |
| Catálogo `replace_magalu` / CSV folder | 4 |
| Colunas `_ml` reutilizadas | 6 |
| Converter+encurtar só CSV fila | 7 |
| Falha = Magalu fora | 7 |
| Amazon/ML/Shopee sem Aqui | 7 |
| Curadoria sem convert/encurtar Magalu | 8 (explícito) |
| UI / post_copy / labels | 8 |
| Testes | 1–8 |

## Placeholder scan

Sem TBD / “similar to Task N” sem código. Interfaces e testes principais estão inline nas Tasks 1–2; Tasks 4–8 referenciam padrões Shopee já no repo com mudanças nomeadas.
