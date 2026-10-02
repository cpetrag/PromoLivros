"""Lê título, preço e capa de um link avulso da Amazon ou do Mercado Livre."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

logger = logging.getLogger("promo_livros.link_offer")

_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
# Só estes domínios são buscados. Qualquer outro endereço é recusado antes da chamada.
_AMAZON_HOSTS = ("amazon.com.br", "amzn.to", "a.co", "link.amazon")
_ML_HOSTS = ("mercadolivre.com.br", "mercadolibre.com", "meli.la")
_MAX_BYTES = 3_000_000


class LinkOfferError(ValueError):
    """O link não é de loja conhecida, ou a página não trouxe preço e título."""


@dataclass(frozen=True)
class LinkOffer:
    store: str
    title: str
    price_cents: int | None
    list_cents: int | None
    cover_url: str
    url: str

    def as_dict(self) -> dict:
        return {
            "store": self.store,
            "title": self.title,
            "price": _brl_input(self.price_cents),
            "list_price": _brl_input(self.list_cents),
            "cover": self.cover_url,
            "url": self.url,
        }


def store_of(url: str) -> str:
    """Devolve "amazon", "ml" ou vazio quando o endereço não é de loja conhecida."""
    parts = urlsplit((url or "").strip())
    if parts.scheme != "https":
        return ""
    host = (parts.hostname or "").lower().removeprefix("www.")
    if _host_in(host, _AMAZON_HOSTS):
        return "amazon"
    if _host_in(host, _ML_HOSTS):
        return "ml"
    return ""


def read_offer(url: str, *, ml_cookie: str = "", fetch=None, browser=None) -> LinkOffer:
    """Uma chamada por link. Sem preço ou sem título, avisa em vez de montar post pela metade."""
    clean = (url or "").strip()
    store = store_of(clean)
    if not store:
        raise LinkOfferError("Use um link da Amazon ou do Mercado Livre.")
    reader = fetch or _get
    if store == "ml":
        offer = _read_ml(clean, reader, ml_cookie)
    else:
        offer = _read_amazon(clean, reader, browser)
    if not offer.title or offer.price_cents is None:
        raise LinkOfferError(_missing_message(store, ml_cookie))
    return offer


def _missing_message(store: str, ml_cookie: str) -> str:
    """O Mercado Livre só abre o anúncio para quem tem sessão; sem ela o aviso precisa dizer o caminho."""
    if store == "ml" and not ml_cookie:
        return "O Mercado Livre não abre o anúncio sem sessão. Cole os cookies em Configurações ou preencha à mão."
    return "A página não mostrou título e preço. Preencha à mão."


def read_offers(urls: list[str], *, ml_cookie: str = "", fetch=None, browser=None) -> list[dict]:
    """Um resultado por link preenchido, com o erro no lugar da oferta quando a leitura falha."""
    found = []
    for url in urls:
        if not (url or "").strip():
            continue
        try:
            found.append(read_offer(url, ml_cookie=ml_cookie, fetch=fetch, browser=browser))
        except LinkOfferError as exc:
            found.append(LinkOfferError(str(exc)))
    return [
        {"error": str(item)} if isinstance(item, LinkOfferError) else item.as_dict() for item in found
    ]


def _host_in(host: str, names: tuple[str, ...]) -> bool:
    return any(host == name or host.endswith("." + name) for name in names)


def _get(url: str, *, cookie: str = "") -> str:
    headers = {
        "user-agent": _BROWSER,
        "accept": "text/html,application/json,*/*",
        "accept-language": "pt-BR,pt;q=0.9",
    }
    if cookie:
        headers["cookie"] = cookie
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=25) as response:
            if store_of(response.geturl()) == "":
                raise LinkOfferError("O link saiu das lojas conhecidas.")
            return response.read(_MAX_BYTES).decode("utf-8", "replace")
    except HTTPError as exc:
        exc.read()
        raise LinkOfferError(f"A loja respondeu HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, UnicodeError) as exc:
        raise LinkOfferError("A loja não respondeu.") from exc


_ML_ID = re.compile(r"MLB-?(\d{6,14})", re.I)
_ASIN = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)", re.I)


def product_id(url: str) -> str:
    """O ASIN ou o id MLB dentro do endereço. Serve para achar o livro no CSV já importado."""
    path = urlsplit((url or "").strip()).path
    mercado = _ML_ID.search(path)
    if mercado:
        return f"MLB{mercado.group(1)}"
    amazon = _ASIN.search(path)
    return amazon.group(1).upper() if amazon else ""


def offer_from_catalog(url: str, find_book) -> dict | None:
    """O CSV do dia já tem título, preço e capa: olhar nele primeiro evita depender da loja responder."""
    from promo_livros.catalog import cover_url

    if not store_of(url):
        return None
    item = product_id(url)
    book = find_book(item) if item else None
    if book is None or not book.title or not book.price_cents:
        return None
    cover = book.image_url if book.store == "ml" else cover_url(book.asin)
    return LinkOffer(
        store=book.store,
        title=book.title,
        price_cents=book.price_cents,
        list_cents=book.list_cents,
        cover_url=cover,
        url=book.url or url.strip(),
    ).as_dict()


def _read_ml(url: str, fetch, cookie: str) -> LinkOffer:
    """A loja fecha a porta sem sessão: a API pública responde 403 e a página vem vazia."""
    item = product_id(url)
    endpoints = []
    if item:
        if cookie:
            endpoints.append((f"https://www.mercadolivre.com.br/p/api/items/{item}", cookie))
        endpoints.append((f"https://api.mercadolibre.com/items/{item}", ""))
    for endpoint, session in endpoints:
        try:
            payload = json.loads(fetch(endpoint, cookie=session) if session else fetch(endpoint))
        except (LinkOfferError, json.JSONDecodeError):
            continue
        offer = _ml_from_api(payload, url) if isinstance(payload, dict) else None
        if offer is not None:
            return offer
    try:
        page = fetch(url, cookie=cookie) if cookie else fetch(url)
    except LinkOfferError as exc:
        # A recusa da loja não é o aviso útil: quem lê precisa saber o que fazer agora.
        logger.info("Mercado Livre não entregou o anúncio %s: %s", item or url, exc)
        return LinkOffer("ml", "", None, None, "", url)
    return _ml_from_html(page, url)


def _ml_from_api(payload: dict, url: str) -> LinkOffer | None:
    from promo_livros.catalog import ml_picture

    for key in ("data", "item", "body"):
        nested = payload.get(key)
        if isinstance(nested, dict) and nested.get("title"):
            payload = nested
            break
    title = str(payload.get("title") or "").strip()
    price = _money(payload.get("price"))
    if not title or price is None:
        return None
    cover = ml_picture(payload.get("secure_thumbnail") or payload.get("thumbnail"))
    pictures = payload.get("pictures")
    if isinstance(pictures, list):
        for picture in pictures:
            if isinstance(picture, dict):
                better = ml_picture(picture.get("secure_url") or picture.get("url"))
                if better:
                    cover = better
                    break
    return LinkOffer("ml", title, price, _money(payload.get("original_price")), cover, url)


_ML_TITLE = re.compile(r'<h1[^>]*class="[^"]*ui-pdp-title[^"]*"[^>]*>(.*?)</h1>', re.S | re.I)
_ML_PRICE = re.compile(r'"price"\s*:\s*(\d+(?:\.\d+)?)')
_ML_LIST = re.compile(r'"original_price"\s*:\s*(\d+(?:\.\d+)?)')
_ML_META_PRICE = re.compile(r'itemprop="price"[^>]*content="(\d+(?:\.\d+)?)"', re.I)


def _ml_from_html(body: str, url: str) -> LinkOffer:
    from promo_livros.catalog import ml_picture

    title = _text(_first(_ML_TITLE, body)) or _meta(body, "og:title")
    price = _money(_first(_ML_PRICE, body) or _first(_ML_META_PRICE, body))
    listed = _money(_first(_ML_LIST, body))
    cover = ml_picture(_meta(body, "og:image"))
    if not cover:
        found = re.search(r"https://http2\.mlstatic\.com/D_[^\"'\s<>\\]+", body.replace("\\/", "/"))
        cover = ml_picture(found.group(0)) if found else ""
    return LinkOffer("ml", title, price, listed, cover, url)


_AMZ_TITLE = re.compile(r'<span[^>]*id="productTitle"[^>]*>(.*?)</span>', re.S | re.I)
_AMZ_OFFSCREEN = re.compile(r'class="a-offscreen">\s*R\$\s*([\d.,]+)\s*</span>', re.I)
_AMZ_WHOLE = re.compile(
    r'class="a-price-whole">\s*([\d.]+)[^<]*</span><span[^>]*class="a-price-decimal">[^<]*</span>'
    r'<span[^>]*class="a-price-fraction">\s*(\d{2})',
    re.I,
)
_AMZ_LIST = re.compile(
    r'class="a-price a-text-price"[^>]*>.*?class="a-offscreen">\s*R\$\s*([\d.,]+)', re.S | re.I
)
_AMZ_DYNAMIC = re.compile(r'data-a-dynamic-image="([^"]+)"')


def _read_amazon(url: str, fetch, browser) -> LinkOffer:
    try:
        offer = _amazon_from_html(fetch(url), url)
    except LinkOfferError:
        offer = LinkOffer("amazon", "", None, None, "", url)
    if offer.title and offer.price_cents is not None:
        return offer
    found = (browser or _amazon_with_browser)(url)
    if found is None:
        return offer
    return found


def _amazon_from_html(body: str, url: str) -> LinkOffer:
    title = _text(_first(_AMZ_TITLE, body)) or _meta(body, "og:title")
    price = _money(_first(_AMZ_OFFSCREEN, body))
    if price is None:
        whole = _AMZ_WHOLE.search(body)
        if whole:
            price = _money(f"{whole.group(1)},{whole.group(2)}")
    listed = _money(_first(_AMZ_LIST, body))
    return LinkOffer("amazon", title, price, listed, _amazon_cover(body), url)


def _amazon_cover(body: str) -> str:
    raw = _first(_AMZ_DYNAMIC, body)
    if raw:
        try:
            images = json.loads(unescape(raw))
        except json.JSONDecodeError:
            images = {}
        best = ""
        widest = 0
        for address, size in images.items() if isinstance(images, dict) else []:
            width = size[0] if isinstance(size, list) and size else 0
            if isinstance(width, int) and width > widest and _amazon_image(address):
                best, widest = address, width
        if best:
            return best
    return _amazon_image(_meta(body, "og:image"))


def _amazon_image(url: str | None) -> str:
    text = (url or "").strip()
    host = (urlsplit(text).hostname or "").lower()
    if text.startswith("https://") and (host.endswith("media-amazon.com") or host.endswith("ssl-images-amazon.com")):
        return text
    return ""


_BROWSER_READ = """
() => {
  const text = (node) => (node?.innerText || '').replace(/\\s+/g, ' ').trim();
  const money = (node) => text(node).match(/R\\$\\s*[\\d.,]+/)?.[0] || '';
  const price = money(document.querySelector('#corePrice_feature_div .a-offscreen, #corePriceDisplay_desktop_feature_div .a-offscreen, #priceblock_ourprice, #price'))
    || money(document.querySelector('.a-price .a-offscreen'));
  const listed = money(document.querySelector('.a-price.a-text-price .a-offscreen, #listPrice, .basisPrice .a-offscreen'));
  const image = document.querySelector('#landingImage, #imgBlkFront, #ebooksImgBlkFront');
  return {
    title: text(document.querySelector('#productTitle')),
    price: price,
    listed: listed,
    image: image?.getAttribute('data-old-hires') || image?.src || ''
  };
}
"""


def _amazon_with_browser(url: str) -> LinkOffer | None:
    """A Amazon costuma recusar a leitura simples. O navegador abre a página do jeito normal."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as playwright:
            chrome = playwright.chromium.launch(headless=True)
            try:
                page = chrome.new_page(locale="pt-BR", viewport={"width": 1280, "height": 900})
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_selector("#productTitle", timeout=12000)
                except Exception:
                    pass
                data = page.evaluate(_BROWSER_READ)
            finally:
                chrome.close()
    except Exception:
        logger.warning("Não consegui abrir a página da Amazon no navegador.")
        return None
    return LinkOffer(
        "amazon",
        str(data.get("title") or "").strip(),
        _money(str(data.get("price") or "").replace("R$", "")),
        _money(str(data.get("listed") or "").replace("R$", "")),
        _amazon_image(data.get("image")),
        url,
    )


def _first(pattern: re.Pattern[str], body: str) -> str:
    match = pattern.search(body)
    return match.group(1) if match else ""


def _meta(body: str, name: str) -> str:
    pattern = re.compile(
        rf'<meta[^>]*(?:property|name)="{re.escape(name)}"[^>]*content="([^"]*)"', re.I
    )
    found = _first(pattern, body)
    if found:
        return _text(found)
    pattern = re.compile(
        rf'<meta[^>]*content="([^"]*)"[^>]*(?:property|name)="{re.escape(name)}"', re.I
    )
    return _text(_first(pattern, body))


def _text(raw: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", raw or "")
    return " ".join(unescape(cleaned).split())


def _money(value: object) -> int | None:
    """Aceita 19.9 da API, "1.234,56" da página e "1234.56" do JSON."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(round(float(value) * 100)) or None
    text = str(value or "").replace("R$", "").replace("\xa0", "").strip()
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        cents = int(round(float(text) * 100))
    except ValueError:
        return None
    return cents or None


def _brl_input(cents: int | None) -> str:
    if not cents:
        return ""
    return f"{cents // 100},{cents % 100:02d}"
