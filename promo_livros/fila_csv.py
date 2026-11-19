"""CSV da fila: o arquivo já traz o post. Aplicar só converte o link e pede a resenha."""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import replace

from urllib.parse import unquote

from promo_livros.catalog import CatalogBook, CatalogError, _ASIN, _ML_ID, _cents, ml_picture
from promo_livros.fila import Bloqueado, FilaMontada, SlotFila, _CLOCK, _avisos, item_de_livro, produto_de_url
from promo_livros.fila_aplicar import _enviados, _guardar_previa
from promo_livros.magalu_links import is_magalu_url, magalu_product_id
from promo_livros.ml_links import clean_product_url
from promo_livros.shopee_links import SHOPEE_ID, is_shopee_url

_MAX_LINHAS = 60
_COLUNAS = (
    "horario",
    "asin",
    "titulo",
    "preco",
    "preco_de",
    "menor_preco_365",
    "cupom",
    "asin_ml",
    "titulo_ml",
    "preco_ml",
    "preco_de_ml",
    "menor_preco_365_ml",
    "cupom_ml",
    "link_ml",
)

# Catálogo traz o nome e, depois de /p/, o código do catálogo — pode ser outro número que o asin_ml.
_LINK_CATALOGO = re.compile(r"https://www\.mercadolivre\.com\.br/[a-z0-9-]+/p/MLB\d+")
# Anúncio fora do catálogo. O número depois de MLB- é o do próprio anúncio.
_LINK_ANUNCIO = re.compile(r"https://produto\.mercadolivre\.com\.br/MLB-(\d+)-[a-z0-9-]+-_JM")
# Página antiga /up/MLBU. O nome fica no caminho; o número usado é o do asin_ml.
_LINK_ANTIGO = re.compile(r"https://www\.mercadolivre\.com\.br/([a-z0-9-]+)/up/MLBU\d+")
_FORMATOS_LINK = (
    "Formatos aceitos: https://www.mercadolivre.com.br/nome-do-livro/p/MLB123 "
    "ou https://produto.mercadolivre.com.br/MLB-123-nome-do-livro-_JM."
)
_LINK_SHOPEE_ITEM = re.compile(
    r"https://shopee\.com\.br/.+-i\.(\d+)\.(\d+)(?:\?|$)",
    re.IGNORECASE,
)
_LINK_SHOPEE_PRODUCT = re.compile(
    r"https://shopee\.com\.br/product/(\d+)/(\d+)(?:\?|$)",
    re.IGNORECASE,
)
_FORMATOS_SHOPEE = (
    "Formatos aceitos: https://shopee.com.br/nome-do-livro-i.123.456 "
    "ou https://shopee.com.br/product/123/456."
)
_FORMATOS_MAGALU = (
    "Formatos aceitos: https://www.magazineluiza.com.br/livro/p/{codigo}/ "
    "ou link Magazine Luiza com /p/{codigo}/."
)


def parse_fila_csv(text: str) -> list[dict]:
    """Lê um horário por linha, com até duas lojas: Amazon, Mercado Livre, Magazine Luiza e/ou Shopee."""
    sample = text.lstrip("\ufeff").strip()
    if not sample:
        raise CatalogError("O CSV da fila está vazio.")
    first = sample.splitlines()[0]
    if ";" not in first:
        raise CatalogError("O CSV da fila usa ponto e vírgula.")
    reader = csv.DictReader(io.StringIO(sample), delimiter=";")
    header = {_fold(name) for name in (reader.fieldnames or []) if name and name.strip()}
    missing = [name for name in _COLUNAS if name not in header]
    if missing:
        raise CatalogError("Faltam colunas no CSV da fila: " + ", ".join(missing) + ".")
    rows: list[dict] = []
    errors: list[str] = []
    avisos: list[str] = []
    rejeitados: list[str] = []
    clocks: dict[str, int] = {}
    vistos: dict[str, int] = {}
    for index, raw in enumerate(reader, start=2):
        row = {_fold(key): (value or "").strip() for key, value in raw.items() if key}
        clock = row.get("horario") or ""
        amazon = _anuncio(row, "amazon", index, errors, avisos, rejeitados)
        segundo = _anuncio(row, "ml", index, errors, avisos, rejeitados)
        mercado = magalu = None
        if segundo is not None:
            if segundo.get("store") == "magalu":
                magalu = segundo
            else:
                mercado = segundo
        magalu_proprio = _anuncio(row, "magalu", index, errors, avisos, rejeitados)
        if magalu_proprio is not None:
            if magalu is not None:
                errors.append(f"Linha {index}: a Magazine Luiza veio nas colunas _ml e _magalu; use só uma.")
            magalu = magalu_proprio
        shopee = _anuncio(row, "shopee", index, errors, avisos, rejeitados)
        extra = _segunda_oferta(row, index, errors, avisos, rejeitados)
        if (
            not clock
            and amazon is None
            and mercado is None
            and magalu is None
            and shopee is None
            and extra is None
            and not _ja_reclamou(errors, index)
        ):
            continue
        if not clock:
            errors.append(f"Linha {index}: falta o horário.")
            continue
        if _CLOCK.fullmatch(clock) is None:
            errors.append(f"Linha {index}: horário {clock} precisa ser HH:MM, como 08:00.")
            continue
        if clock in clocks:
            errors.append(f"O horário {clock} aparece de novo na linha {index}.")
        else:
            clocks[clock] = index
        if _ja_reclamou(rejeitados, index):
            continue
        filled = [item for item in (amazon, mercado, magalu, shopee, extra) if item is not None]
        if len(filled) > 2:
            errors.append(f"Linha {index}: o post aceita no máximo duas ofertas.")
            continue
        if not filled:
            if not _ja_reclamou(errors, index) and not _ja_reclamou(avisos, index):
                errors.append(
                    f"Linha {index}: falta o anúncio da Amazon, do Mercado Livre, da Magazine Luiza ou da Shopee."
                )
            continue
        for item in filled:
            code = item["asin"]
            if code in vistos:
                errors.append(f"{code} aparece de novo na linha {index}.")
            else:
                vistos[code] = index
        rows.append(
            {
                "linha": str(index),
                "clock": clock,
                "amazon": amazon,
                "ml": mercado,
                "magalu": magalu,
                "shopee": shopee,
                "extra": extra,
            }
        )
        if len(rows) > _MAX_LINHAS:
            raise CatalogError(f"A fila aceita no máximo {_MAX_LINHAS} horários.")
    if errors:
        raise CatalogError(" ".join(errors[:8]))
    if not rows:
        if rejeitados:
            raise CatalogError(" ".join(rejeitados[:8]))
        if avisos:
            raise CatalogError(" ".join(avisos[:8]))
        raise CatalogError("O CSV da fila não tem nenhum horário.")
    rows.sort(key=lambda item: item["clock"])
    return _Lidas(rows, avisos, rejeitados)


def previa_do_csv(catalog, board, day: str, agora: str, fim: str, text: str, memoria) -> dict:
    """Monta a prévia com o que veio no arquivo. Aplicar converte o link e pede a resenha."""
    linhas = parse_fila_csv(text)
    avisos = list(getattr(linhas, "avisos", ()))
    rejeitados = list(getattr(linhas, "rejeitados", ()))
    if _CLOCK.fullmatch(agora) is None or _CLOCK.fullmatch(fim) is None:
        raise CatalogError("A janela de envio está com horário inválido.")
    enviados, obras = _enviados(catalog, board, day)
    errors: list[str] = []
    pulados: list[str] = []
    slots: list[SlotFila] = []
    bloqueados = []
    livros: list[dict] = []
    for linha in linhas:
        clock = linha["clock"]
        numero = linha["linha"]
        if clock <= agora:
            pulados.append(f"{clock} já passou")
            continue
        if clock >= fim:
            errors.append(f"Linha {numero}: {clock} fica fora da janela, que termina às {fim}.")
            continue
        ofertas = []
        for bruto in (linha["amazon"], linha["ml"], linha.get("magalu"), linha["shopee"], linha.get("extra")):
            book = _com_capa(catalog, _livro(bruto))
            if book is None:
                continue
            if book.asin.upper() in enviados:
                pulados.append(f"{clock} · {book.title} já tinha saído")
                bloqueados.append(item_de_livro(book))
                continue
            ofertas.append(book)
        if not ofertas:
            continue
        amazon, mercado, shopee, magalu, extra = _encaixar(ofertas)
        for book in ofertas:
            livros.append(_publico(book))
        slots.append(
            SlotFila(
                clock,
                item_de_livro(amazon) if amazon is not None else None,
                item_de_livro(mercado) if mercado is not None else None,
                shopee=item_de_livro(shopee) if shopee is not None else None,
                magalu=item_de_livro(magalu) if magalu is not None else None,
                extra=item_de_livro(extra) if extra is not None else None,
            )
        )
    if errors:
        raise CatalogError(" ".join(errors[:8]))
    if not slots:
        if pulados and all(item.endswith("já passou") for item in pulados):
            raise CatalogError("Os horários desse arquivo já passaram.")
        raise CatalogError("Nenhum horário para aplicar. Os livros dessa lista já saíram.")
    fila = FilaMontada(
        _avisos(tuple(slots), obras),
        tuple(Bloqueado(item, tuple(enviados.get(item.id.upper(), ()))) for item in bloqueados),
        (),
        tuple(slot.clock for slot in slots),
    )
    payload = _guardar_previa(fila, catalog, board, day, memoria)
    payload["origem"] = "csv"
    payload["livros"] = livros
    payload["pulados"] = pulados
    payload["avisos"] = avisos
    payload["rejeitados"] = rejeitados
    payload["sem_foto"] = sum(
        1 for item in livros if item.get("store") == "ml" and not ml_picture(item.get("image_url"))
    )
    payload["passos"] = _passos(livros)
    payload["message"] = f"{len(slots)} horários lidos. Revise e aplique."
    return payload


def _passos(livros: list[dict]) -> list[dict]:
    passos = []
    nomes = {"ml": "do Mercado Livre", "shopee": "da Shopee", "magalu": "da Magazine Luiza"}
    for book in livros:
        loja = nomes.get(book.get("store") or "", "da Amazon")
        titulo = book.get("title") or book.get("asin") or ""
        for kind, label in (
            ("livro", f"Importando livro {loja} · {titulo}"),
            ("link", f"Convertendo link {loja} · {titulo}"),
            ("resenha", f"Gerando resenha · {titulo}"),
        ):
            passos.append({"kind": kind, "asin": book["asin"], "label": label, "state": "wait"})
    passos.append({"kind": "gravar", "asin": "", "label": "Substituindo a fila de hoje", "state": "wait"})
    return passos


class LinkQuebrado(Exception):
    """O anúncio do Mercado Livre não virou link de afiliado."""


class ImportacaoFila:
    """Uma importação em andamento. Cada avanço faz um passo e devolve o modal."""

    def __init__(self, payload: dict) -> None:
        import secrets

        self.id = secrets.token_urlsafe(8)
        self.pulados = list(payload.get("pulados") or [])
        self.avisos = list(payload.get("avisos") or [])
        self.rejeitados = list(payload.get("rejeitados") or [])
        self.sem_foto = int(payload.get("sem_foto") or 0)
        self.passos = [dict(item) for item in payload["passos"]]
        self.livros = {item["asin"]: dict(item) for item in payload["livros"]}
        self.slots_ids = list(payload["slots_ids"])
        self.cursor = 0
        self.done = False
        self.aguardando = False
        self.ignorados: list[dict] = []
        self.message = ""
        self.error = ""

    def visao(self) -> dict:
        return {
            "job": self.id,
            "pulados": self.pulados,
            "avisos": self.avisos,
            "rejeitados": self.rejeitados,
            "sem_foto": self.sem_foto,
            "livros": len(self.livros),
            "passos": [
                {
                    "label": f"{item['label']} — {item['detail']}" if item.get("detail") else item["label"],
                    "state": item["state"],
                }
                for item in self.passos
            ],
            "quebrados": self.ignorados or _quebrados(self),
            "aguardando": self.aguardando,
            "done": self.done,
            "message": self.message,
            "falha": self.error,
        }


def avancar(
    job: ImportacaoFila,
    *,
    resolve_amazon,
    resolve_ml,
    describe,
    gravar,
    resolve_shopee=None,
    resolve_magalu=None,
) -> dict:
    """Executa o próximo passo. Link e resenha acontecem aqui; gravar troca a fila."""
    if job.done or job.error:
        return job.visao()
    step = job.passos[job.cursor]
    step["state"] = "run"
    try:
        if step["kind"] == "link":
            _converter(job.livros[step["asin"]], resolve_amazon, resolve_ml, resolve_shopee, resolve_magalu)
        elif step["kind"] == "resenha":
            book = job.livros[step["asin"]]
            try:
                book["blurb"] = (describe(book["title"], book.get("author") or "") or "").strip()
            except Exception:
                book["blurb"] = ""
        elif step["kind"] == "gravar":
            _tirar_ignorados(job)
            if not job.slots_ids:
                job.message = "Nenhum horário entrou. Os links do Mercado Livre não viraram afiliado."
            else:
                job.message = gravar(job)
                if job.ignorados:
                    nomes = ", ".join(item["titulo"] for item in job.ignorados)
                    job.message = f"{job.message} Ficaram de fora: {nomes}."
            job.done = True
    except LinkQuebrado as exc:
        step["state"] = "erro"
        step["detail"] = str(exc)
        book = job.livros.get(step["asin"])
        if book is not None:
            book["link_erro"] = str(exc)
            book["ignorado"] = True
        asin = step["asin"]
        job.cursor += 1
        while job.cursor < len(job.passos) and job.passos[job.cursor].get("asin") == asin:
            job.passos[job.cursor]["state"] = "pulado"
            job.passos[job.cursor]["detail"] = "ficou de fora"
            job.cursor += 1
        return job.visao()
    except Exception as exc:
        step["state"] = "erro"
        job.error = str(exc)
        return job.visao()
    step["state"] = "ok"
    step["detail"] = ""
    job.cursor += 1
    if job.cursor >= len(job.passos):
        job.done = True
    return job.visao()


def resolver_links(
    job: ImportacaoFila,
    *,
    resolve_amazon,
    resolve_ml,
    resolve_shopee=None,
    resolve_magalu=None,
) -> dict:
    """Tenta de novo os anúncios cujo link de afiliado não saiu."""
    if job.done or job.error:
        return job.visao()
    for step in job.passos:
        if step["kind"] != "link" or step["state"] != "erro":
            continue
        book = job.livros.get(step["asin"])
        if book is None or book.get("store") not in {"ml", "shopee", "magalu"}:
            continue
        try:
            _converter(book, resolve_amazon, resolve_ml, resolve_shopee, resolve_magalu)
        except LinkQuebrado as exc:
            step["detail"] = str(exc)
            book["link_erro"] = str(exc)
            continue
        step["state"] = "ok"
        step["detail"] = ""
    job.aguardando = bool(_quebrados(job))
    return job.visao()


def _tirar_ignorados(job: ImportacaoFila) -> None:
    """O anúncio cujo link não virou afiliado sai do horário. O outro lado do post fica."""
    ids = [asin for asin, book in job.livros.items() if book.get("ignorado")]
    for asin in ids:
        book = job.livros.pop(asin)
        job.ignorados.append(
            {
                "asin": asin,
                "titulo": book.get("title") or asin,
                "url": book.get("url_chave") or book.get("url") or "",
                "motivo": book.get("link_erro") or "O Mercado Livre não gerou o link de afiliado.",
            }
        )
    slots = []
    for slot in job.slots_ids:
        amazon = "" if slot.get("amazon") in ids else slot.get("amazon") or ""
        mercado = "" if slot.get("ml") in ids else slot.get("ml") or ""
        shopee = "" if slot.get("shopee") in ids else slot.get("shopee") or ""
        magalu = "" if slot.get("magalu") in ids else slot.get("magalu") or ""
        extra = "" if slot.get("extra") in ids else slot.get("extra") or ""
        if amazon or mercado or shopee or magalu or extra:
            slots.append(
                {
                    "clock": slot["clock"],
                    "amazon": amazon,
                    "ml": mercado,
                    "shopee": shopee,
                    "magalu": magalu,
                    "extra": extra,
                }
            )
    job.slots_ids = slots


def _quebrados(job: ImportacaoFila) -> list[dict]:
    itens = []
    for book in job.livros.values():
        motivo = book.get("link_erro") or ""
        if book.get("store") not in {"ml", "shopee", "magalu"} or not motivo:
            continue
        itens.append(
            {
                "asin": book.get("asin") or "",
                "titulo": book.get("title") or book.get("asin") or "",
                "url": book.get("url_chave") or book.get("url") or "",
                "motivo": motivo,
            }
        )
    return itens


def _com_capa(catalog, book: CatalogBook | None) -> CatalogBook | None:
    """O CSV da fila pode vir sem foto. A capa já salva no catálogo entra no card."""
    if book is None or book.store != "ml" or ml_picture(book.image_url):
        return book
    stored = ml_picture(catalog.ml_image(book.asin)) if hasattr(catalog, "ml_image") else ""
    if not stored:
        return book
    return replace(book, image_url=stored)


def _converter(book: dict, resolve_amazon, resolve_ml, resolve_shopee=None, resolve_magalu=None) -> None:
    from promo_livros.ml_links import clean_product_url

    raw = book.get("url") or ""
    # Magalu precisa da query (seller_id). clean_product_url é só do ML.
    if book.get("store") == "magalu":
        chave = raw.strip()
        book["url_chave"] = chave
        _converter_magalu(book, chave, resolve_magalu)
        return
    chave = clean_product_url(raw) or raw
    book["url_chave"] = chave
    if book.get("store") == "ml":
        _converter_ml(book, chave, resolve_ml)
        return
    if book.get("store") == "shopee":
        _converter_shopee(book, chave, resolve_shopee)
        return
    if resolve_amazon is None or not chave:
        book["url_final"] = chave
        return
    try:
        got = resolve_amazon([chave])
    except Exception:
        got = None
    if isinstance(got, list) and len(got) == 1 and got[0]:
        book["url_final"] = got[0]
    else:
        book["url_final"] = chave


def _converter_ml(book: dict, chave: str, resolve_ml) -> None:
    if resolve_ml is None or not chave:
        raise LinkQuebrado("Falta o link do Mercado Livre.")
    try:
        got = resolve_ml([chave])
    except LinkQuebrado:
        raise
    except Exception as exc:
        texto = " ".join(str(exc).split())
        raise LinkQuebrado(texto[:180] or "O Mercado Livre não gerou o link de afiliado.") from exc
    final = got[0].strip() if isinstance(got, list) and len(got) == 1 and isinstance(got[0], str) else ""
    if not _virou_afiliado(final, chave):
        raise LinkQuebrado("O Mercado Livre não gerou o link de afiliado.")
    book["url_final"] = final
    book.pop("link_erro", None)


def _converter_magalu(book: dict, chave: str, resolve_magalu) -> None:
    if resolve_magalu is None or not chave:
        raise LinkQuebrado("Falta o link da Magazine Luiza.")
    try:
        got = resolve_magalu([chave])
    except LinkQuebrado:
        raise
    except Exception as exc:
        texto = " ".join(str(exc).split())
        raise LinkQuebrado(texto[:180] or "A Magazine Luiza não gerou o link de afiliado.") from exc
    final = got[0].strip() if isinstance(got, list) and len(got) == 1 and isinstance(got[0], str) else ""
    if not final.startswith("https://"):
        raise LinkQuebrado("A Magazine Luiza não gerou o link de afiliado.")
    book["url_final"] = final
    book.pop("link_erro", None)


def _converter_shopee(book: dict, chave: str, resolve_shopee) -> None:
    if resolve_shopee is None or not chave:
        raise LinkQuebrado("Falta o link da Shopee.")
    try:
        got = resolve_shopee([chave])
    except LinkQuebrado:
        raise
    except Exception as exc:
        texto = " ".join(str(exc).split())
        raise LinkQuebrado(texto[:180] or "A Shopee não gerou o link de afiliado.") from exc
    final = got[0].strip() if isinstance(got, list) and len(got) == 1 and isinstance(got[0], str) else ""
    if not _virou_afiliado(final, chave) and not is_shopee_url(final):
        raise LinkQuebrado("A Shopee não gerou o link de afiliado.")
    if not final.startswith("https://"):
        raise LinkQuebrado("A Shopee não gerou o link de afiliado.")
    book["url_final"] = final
    book.pop("link_erro", None)


def _virou_afiliado(final: str, chave: str) -> bool:
    got = final.strip()
    if not got.startswith("https://"):
        return False
    host = got.split("/", 3)[2].lower()
    if host == "meli.la" or host.endswith(".meli.la"):
        return True
    return got.rstrip("/") != chave.strip().rstrip("/")


def livros_da_previa(payload: dict) -> list[CatalogBook]:
    """Reconstrói os livros gravados na prévia do CSV. O catálogo não entra nessa lista."""
    books = []
    for item in payload.get("livros") or []:
        books.append(
            CatalogBook(
                asin=str(item["asin"]),
                position=0,
                title=str(item["title"]),
                author=str(item.get("author") or ""),
                category="",
                price_cents=item.get("price_cents"),
                list_cents=item.get("list_cents"),
                low_365=bool(item.get("low_365")),
                url=str(item.get("url") or ""),
                picked=True,
                store=_store_of(item),
                image_url=str(item.get("image_url") or ""),
                coupon=str(item.get("coupon") or ""),
            )
        )
    return books


class _Lidas(list):
    """Linhas lidas, com avisos de link e linhas recusadas pelo código do anúncio."""

    avisos: list[str]
    rejeitados: list[str]

    def __init__(self, rows: list[dict], avisos: list[str], rejeitados: list[str]) -> None:
        super().__init__(rows)
        self.avisos = avisos
        self.rejeitados = rejeitados


def _encaixar(
    ofertas: list[CatalogBook],
) -> tuple[CatalogBook | None, CatalogBook | None, CatalogBook | None, CatalogBook | None, CatalogBook | None]:
    """A primeira oferta de cada loja ocupa o lugar dela. A segunda da mesma loja vai em extra."""
    amazon = mercado = shopee = magalu = extra = None
    for book in ofertas:
        if book.store == "amazon" and amazon is None:
            amazon = book
        elif book.store == "ml" and mercado is None:
            mercado = book
        elif book.store == "shopee" and shopee is None:
            shopee = book
        elif book.store == "magalu" and magalu is None:
            magalu = book
        else:
            extra = book
    return amazon, mercado, shopee, magalu, extra


def _segunda_oferta(
    row: dict[str, str],
    linha: int,
    errors: list[str],
    avisos: list[str],
    rejeitados: list[str],
) -> dict | None:
    """Colunas opcionais asin_2, titulo_2, preco_2 e link_2. A loja sai do código."""
    raw = row.get("asin_2") or ""
    title = row.get("titulo_2") or ""
    price_text = row.get("preco_2") or ""
    list_text = row.get("preco_de_2") or ""
    badge = row.get("menor_preco_365_2") or ""
    coupon = row.get("cupom_2") or ""
    image = row.get("imagem_2") or ""
    link = row.get("link_2") or ""
    if not any((raw, title, price_text, list_text, badge, coupon, link, image)):
        return None
    loja = _loja_do_texto(raw)
    if not loja:
        errors.append(f"Linha {linha}: não reconheci a segunda oferta {raw or 'sem código'}.")
        return None
    code = _codigo(raw, loja=loja, linha=linha, errors=errors)
    if not code:
        return None
    if loja == "ml":
        link_ok = _link_ml(link, code, linha, avisos, rejeitados, campo="link_2")
        if link_ok is None:
            return None
    elif loja == "magalu":
        link_ok = _link_magalu(link, code, linha, avisos, rejeitados, campo="link_2")
        if link_ok is None:
            return None
    elif loja == "shopee":
        link_ok = _link_shopee(link, code, linha, avisos, rejeitados, campo="link_2")
        if link_ok is None:
            return None
    else:
        link_ok = ""
    if not title:
        errors.append(f"Linha {linha}: falta o título de {code}.")
    price = _cents(price_text)
    if not price_text:
        errors.append(f"Linha {linha}: falta o preço de {code}.")
    elif price is None:
        errors.append(f"Linha {linha}: não entendi o preço de {code}.")
    listed = _cents(list_text) if list_text else None
    if list_text and listed is None:
        errors.append(f"Linha {linha}: não entendi o preço antigo de {code}.")
    return {
        "asin": code,
        "title": title,
        "author": row.get("autor_2") or "",
        "price_cents": price,
        "list_cents": listed,
        "low_365": _badge(badge),
        "url": _url(raw, code) if loja == "amazon" else link_ok,
        "store": loja,
        "image_url": image,
        "coupon": coupon,
    }


def _loja_do_texto(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if is_magalu_url(text):
        return "magalu"
    compact = text.replace(" ", "")
    if SHOPEE_ID.fullmatch(compact) or _ids_do_link_shopee(text):
        return "shopee"
    code = text.upper().replace(" ", "")
    found = produto_de_url(text)
    if _ML_ID.fullmatch(code) or _ML_ID.fullmatch(found):
        return "ml"
    if _ASIN.fullmatch(code) or _ASIN.fullmatch(found):
        return "amazon"
    linked = magalu_product_id(text)
    if linked:
        return "magalu"
    if compact and _ML_ID.fullmatch(code) is None and _ASIN.fullmatch(code) is None:
        return "magalu"
    return ""


def _anuncio(
    row: dict[str, str],
    loja: str,
    linha: int,
    errors: list[str],
    avisos: list[str],
    rejeitados: list[str],
) -> dict | None:
    suffix = {"ml": "_ml", "shopee": "_shopee", "magalu": "_magalu"}.get(loja, "")
    raw = row.get(f"asin{suffix}") or ("" if suffix else row.get(f"link{suffix}") or "")
    title = row.get(f"titulo{suffix}") or ""
    author = row.get(f"autor{suffix}") or ""
    price_text = row.get(f"preco{suffix}") or ""
    list_text = row.get(f"preco_de{suffix}") or ""
    badge = row.get(f"menor_preco_365{suffix}") or ""
    coupon = row.get(f"cupom{suffix}") or ""
    image = row.get(f"imagem{suffix}") or "" if suffix else ""
    link = row.get(f"link{suffix}") or "" if suffix else ""
    if not any((raw, title, price_text, list_text, badge, coupon, link, image)):
        return None
    effective = "magalu" if loja == "ml" and _ml_e_magalu(raw, link) else loja
    code = _codigo(raw, loja=effective, linha=linha, errors=errors) if raw else ""
    if not code and effective == "magalu" and link.strip():
        code = magalu_product_id(link) or ""
    if not code:
        if raw or title or price_text or (suffix and link):
            if not _ja_reclamou(errors, linha):
                errors.append(f"Linha {linha}: falta o código ou o link da {_nome_loja(effective)}.")
        return None
    if effective == "magalu":
        link_ok = _link_magalu(link, code, linha, avisos, rejeitados, campo=f"link{suffix}")
        if link_ok is None:
            return None
    elif loja == "ml":
        link_ok = _link_ml(link, code, linha, avisos, rejeitados)
        if link_ok is None:
            return None
    elif loja == "shopee":
        link_ok = _link_shopee(link, code, linha, avisos, rejeitados)
        if link_ok is None:
            return None
    else:
        link_ok = ""
    if not title:
        errors.append(f"Linha {linha}: falta o título de {code}.")
    price = _cents(price_text)
    if not price_text:
        errors.append(f"Linha {linha}: falta o preço de {code}.")
    elif price is None:
        errors.append(f"Linha {linha}: não entendi o preço de {code}.")
    listed = _cents(list_text) if list_text else None
    if list_text and listed is None:
        errors.append(f"Linha {linha}: não entendi o preço antigo de {code}.")
    return {
        "asin": code,
        "title": title,
        "author": author,
        "price_cents": price,
        "list_cents": listed,
        "low_365": _badge(badge),
        "url": _url(raw, code) if loja == "amazon" else link_ok,
        "store": effective,
        "image_url": image if suffix else "",
        "coupon": coupon,
    }


def _livro(item: dict | None) -> CatalogBook | None:
    if item is None or item.get("price_cents") is None or not item.get("title"):
        return None
    return CatalogBook(
        asin=item["asin"],
        position=0,
        title=item["title"],
        author=item.get("author") or "",
        category="",
        price_cents=item["price_cents"],
        list_cents=item.get("list_cents"),
        low_365=bool(item.get("low_365")),
        url=item.get("url") or "",
        picked=True,
        store=_store_of(item),
        image_url=item.get("image_url") or "",
        coupon=item.get("coupon") or "",
    )


def _publico(book: CatalogBook) -> dict:
    return {
        "asin": book.asin,
        "title": book.title,
        "author": book.author,
        "price_cents": book.price_cents,
        "list_cents": book.list_cents,
        "low_365": book.low_365,
        "url": book.url,
        "store": book.store,
        "image_url": book.image_url,
        "coupon": book.coupon,
    }


def _store_of(item: dict) -> str:
    store = item.get("store") or "amazon"
    return store if store in {"amazon", "ml", "shopee", "magalu"} else "amazon"


def _nome_loja(loja: str) -> str:
    return {"ml": "Mercado Livre", "shopee": "Shopee", "magalu": "Magazine Luiza"}.get(loja, "Amazon")


def _ml_e_magalu(raw: str, link: str) -> bool:
    """Nas colunas _ml, Magalu tem prioridade sobre o Mercado Livre."""
    if is_magalu_url(link) or is_magalu_url(raw):
        return True
    text = (raw or "").strip()
    if text:
        upper = text.upper().replace(" ", "")
        if _ML_ID.fullmatch(upper) or _ASIN.fullmatch(upper) or SHOPEE_ID.fullmatch(text.replace(" ", "")):
            return False
        linked = magalu_product_id(link)
        if linked and linked.casefold() == text.casefold():
            return True
    return bool(magalu_product_id(link))


def _link_shopee(
    raw: str,
    code: str,
    linha: int,
    avisos: list[str],
    rejeitados: list[str],
    campo: str = "link_shopee",
) -> str | None:
    original = raw.strip()
    text = unquote(original.split("?")[0]).rstrip("/")
    found = _ids_do_link_shopee(text)
    if found == code:
        return original.split("?")[0]
    if found:
        rejeitados.append(
            f"Linha {linha}: {campo} inválido para {code}: {original}. "
            f"O shopid.itemid do link precisa ser o do asin_shopee. {_FORMATOS_SHOPEE}"
        )
        return None
    avisos.append(f"Linha {linha}: {campo} inválido para {code}: {original}. {_FORMATOS_SHOPEE}")
    return None


def _ids_do_link_shopee(url: str) -> str:
    text = unquote((url or "").strip())
    match = _LINK_SHOPEE_ITEM.search(text) or _LINK_SHOPEE_PRODUCT.search(text)
    if not match:
        return ""
    return f"{match.group(1)}.{match.group(2)}"


def _link_magalu(
    raw: str,
    code: str,
    linha: int,
    avisos: list[str],
    rejeitados: list[str],
    campo: str = "link_ml",
) -> str | None:
    """O endereço sai do link_ml, link_magalu ou link_2. None pula a Magazine Luiza; código trocado recusa a linha."""
    original = raw.strip()
    if not original:
        avisos.append(f"Linha {linha}: {campo} inválido para {code}: . {_FORMATOS_MAGALU}")
        return None
    if not is_magalu_url(original):
        avisos.append(f"Linha {linha}: {campo} inválido para {code}: {original}. {_FORMATOS_MAGALU}")
        return None
    found = magalu_product_id(original)
    if found and found.casefold() == code.casefold():
        return original.split("?")[0]
    if found:
        rejeitados.append(
            f"Linha {linha}: {campo} inválido para {code}: {original}. "
            f"O código depois de /p/ precisa ser o do {campo.replace('link', 'asin', 1)}. {_FORMATOS_MAGALU}"
        )
        return None
    avisos.append(f"Linha {linha}: {campo} inválido para {code}: {original}. {_FORMATOS_MAGALU}")
    return None


def _link_ml(
    raw: str,
    code: str,
    linha: int,
    avisos: list[str],
    rejeitados: list[str],
    campo: str = "link_ml",
) -> str | None:
    """O endereço sai do link_ml. None pula o Mercado Livre; código trocado recusa a linha."""
    original = raw.strip()
    text = clean_product_url(original).rstrip("/")
    antigo = _LINK_ANTIGO.fullmatch(text)
    if antigo and code.startswith("MLB") and code[3:].isdigit():
        text = f"https://produto.mercadolivre.com.br/MLB-{code[3:]}-{antigo.group(1)}-_JM"
    if _LINK_CATALOGO.fullmatch(text):
        return text
    anuncio = _LINK_ANUNCIO.fullmatch(text)
    if anuncio:
        if code.startswith("MLB") and anuncio.group(1) == code[3:]:
            return text
        rejeitados.append(
            f"Linha {linha}: {campo} inválido para {code}: {original}. "
            f"O número depois de MLB- precisa ser o do asin_ml. {_FORMATOS_LINK}"
        )
        return None
    avisos.append(f"Linha {linha}: {campo} inválido para {code}: {original}. {_FORMATOS_LINK}")
    return None


def _url(raw: str, code: str) -> str:
    text = raw.strip()
    if text.casefold().startswith("http"):
        return text
    return f"https://www.amazon.com.br/dp/{code}"


def _badge(value: str) -> bool:
    folded = _fold(value)
    return folded in {"sim", "s", "1"} or ("365" in folded and "menor" in folded)


def _codigo(value: str, *, loja: str, linha: int, errors: list[str]) -> str:
    text = value.strip()
    if not text:
        return ""
    if loja == "shopee":
        shopee = text.replace(" ", "")
        if SHOPEE_ID.fullmatch(shopee):
            return shopee
        found = _ids_do_link_shopee(text)
        if found:
            return found
        errors.append(f"Linha {linha}: não reconheci o anúncio {text}.")
        return ""
    if loja == "magalu":
        stripped = text.strip()
        from_url = magalu_product_id(text) if is_magalu_url(text) else ""
        if from_url:
            return from_url
        if stripped:
            upper = stripped.upper().replace(" ", "")
            if _ML_ID.fullmatch(upper):
                errors.append(f"Linha {linha}: {stripped} é do Mercado Livre e vai nas colunas _ml com link MLB.")
                return ""
            if _ASIN.fullmatch(upper):
                errors.append(f"Linha {linha}: {stripped} é da Amazon e vai na coluna asin.")
                return ""
            return stripped
        errors.append(f"Linha {linha}: não reconheci o anúncio {text}.")
        return ""
    code = text.upper().replace(" ", "")
    found = produto_de_url(text)
    mercado = code if _ML_ID.fullmatch(code) else ""
    if not mercado and _ML_ID.fullmatch(found):
        mercado = found
    amazon = "" if mercado else (code if _ASIN.fullmatch(code) else "")
    if not mercado and not amazon and _ASIN.fullmatch(found):
        amazon = found
    if loja == "ml" and mercado:
        return mercado
    if loja == "amazon" and amazon:
        return amazon
    if loja == "amazon" and mercado:
        errors.append(f"Linha {linha}: {mercado} é do Mercado Livre e vai na coluna asin_ml.")
        return ""
    if loja == "ml" and amazon:
        errors.append(f"Linha {linha}: {amazon} é da Amazon e vai na coluna asin.")
        return ""
    errors.append(f"Linha {linha}: não reconheci o anúncio {text}.")
    return ""


def _ja_reclamou(errors: list[str], linha: int) -> bool:
    prefixo = f"Linha {linha}:"
    return any(item.startswith(prefixo) for item in errors)


def _fold(name: str) -> str:
    normalized = unicodedata.normalize("NFD", name.strip())
    stripped = "".join(char for char in normalized if not unicodedata.combining(char))
    return stripped.casefold()
