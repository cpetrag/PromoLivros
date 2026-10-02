import json
import unittest

from promo_livros.link_offer import LinkOfferError, read_offer, read_offers, store_of

_AMAZON_PAGE = """
<html><head><meta property="og:image" content="https://m.media-amazon.com/images/I/small.jpg"></head>
<body>
<span id="productTitle">  Dom Casmurro &amp; outras hist&oacute;rias  </span>
<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">R$ 1.234,56</span></span></div>
<span class="a-price a-text-price"><span class="a-offscreen">R$ 1.999,90</span></span>
<img id="landingImage" data-a-dynamic-image="{&quot;https://m.media-amazon.com/images/I/big.jpg&quot;:[500,700],&quot;https://m.media-amazon.com/images/I/mid.jpg&quot;:[300,420]}">
</body></html>
"""

_ML_PAGE = """
<html><head>
<meta property="og:title" content="Livro Capit&atilde;es da Areia">
<meta property="og:image" content="https://http2.mlstatic.com/D_NQ_NP_2X_777.webp">
</head><body>
<h1 class="ui-pdp-title">Livro Capitães da Areia - Jorge Amado</h1>
<script>{"price":19.9,"original_price":39.9}</script>
</body></html>
"""


class StoreOfTests(unittest.TestCase):
    def test_only_the_two_stores_are_accepted(self) -> None:
        self.assertEqual(store_of("https://www.amazon.com.br/dp/6550974119"), "amazon")
        self.assertEqual(store_of("https://amzn.to/abc"), "amazon")
        self.assertEqual(store_of("https://produto.mercadolivre.com.br/MLB-1234567"), "ml")
        self.assertEqual(store_of("https://meli.la/abc"), "ml")
        self.assertEqual(store_of("https://evil.test/amazon.com.br"), "")
        self.assertEqual(store_of("http://www.amazon.com.br/dp/6550974119"), "")
        self.assertEqual(store_of("file:///etc/passwd"), "")

    def test_a_link_from_another_site_is_refused_before_any_request(self) -> None:
        def fetch(_url: str, **_kwargs):
            raise AssertionError("não deveria buscar")

        with self.assertRaises(LinkOfferError):
            read_offer("https://evil.test/produto", fetch=fetch)


class AmazonLinkTests(unittest.TestCase):
    def test_the_page_gives_title_price_list_price_and_the_widest_cover(self) -> None:
        offer = read_offer(
            "https://www.amazon.com.br/dp/6550974119",
            fetch=lambda _url, **_kwargs: _AMAZON_PAGE,
            browser=lambda _url: None,
        )
        self.assertEqual(offer.store, "amazon")
        self.assertEqual(offer.title, "Dom Casmurro & outras histórias")
        self.assertEqual(offer.price_cents, 123456)
        self.assertEqual(offer.list_cents, 199990)
        self.assertEqual(offer.cover_url, "https://m.media-amazon.com/images/I/big.jpg")
        self.assertEqual(offer.as_dict()["price"], "1234,56")

    def test_a_captcha_page_falls_back_to_the_browser(self) -> None:
        from promo_livros.link_offer import LinkOffer

        tried = []

        def browser(url: str):
            tried.append(url)
            return LinkOffer("amazon", "Quincas Borba", 1500, None, "", url)

        offer = read_offer(
            "https://www.amazon.com.br/dp/6550974119",
            fetch=lambda _url, **_kwargs: "<html><body>Digite os caracteres</body></html>",
            browser=browser,
        )
        self.assertEqual(tried, ["https://www.amazon.com.br/dp/6550974119"])
        self.assertEqual(offer.title, "Quincas Borba")
        self.assertEqual(offer.price_cents, 1500)

    def test_a_cover_outside_the_amazon_cdn_is_dropped(self) -> None:
        page = _AMAZON_PAGE.replace("https://m.media-amazon.com/images/I/big.jpg", "https://evil.test/x.jpg")
        offer = read_offer(
            "https://www.amazon.com.br/dp/6550974119",
            fetch=lambda _url, **_kwargs: page,
            browser=lambda _url: None,
        )
        self.assertEqual(offer.cover_url, "https://m.media-amazon.com/images/I/mid.jpg")


class MercadoLivreLinkTests(unittest.TestCase):
    def test_the_public_api_answers_with_the_offer(self) -> None:
        payload = {
            "title": "Livro Dom Casmurro",
            "price": 19.9,
            "original_price": 39.9,
            "secure_thumbnail": "https://http2.mlstatic.com/D_NQ_NP_123-O.jpg",
            "pictures": [{"secure_url": "https://http2.mlstatic.com/D_NQ_NP_2X_456-F.jpg"}],
        }
        asked = []

        def fetch(url: str, **_kwargs):
            asked.append(url)
            return json.dumps(payload)

        offer = read_offer("https://www.mercadolivre.com.br/p/MLB4493446393", fetch=fetch)
        self.assertEqual(asked, ["https://api.mercadolibre.com/items/MLB4493446393"])
        self.assertEqual(offer.title, "Livro Dom Casmurro")
        self.assertEqual(offer.price_cents, 1990)
        self.assertEqual(offer.list_cents, 3990)
        self.assertEqual(offer.cover_url, "https://http2.mlstatic.com/D_NQ_NP_2X_456-F.jpg")

    def test_without_the_api_the_page_is_read(self) -> None:
        def fetch(url: str, **_kwargs):
            if "api.mercadolibre.com" in url:
                raise LinkOfferError("A loja respondeu HTTP 401.")
            return _ML_PAGE

        offer = read_offer("https://produto.mercadolivre.com.br/MLB-1234567", fetch=fetch)
        self.assertEqual(offer.title, "Livro Capitães da Areia - Jorge Amado")
        self.assertEqual(offer.price_cents, 1990)
        self.assertEqual(offer.list_cents, 3990)
        self.assertEqual(offer.cover_url, "https://http2.mlstatic.com/D_NQ_NP_2X_777.webp")

    def test_with_cookies_the_signed_in_endpoint_is_asked_before_the_public_api(self) -> None:
        asked = []

        def fetch(url: str, **kwargs):
            asked.append((url, bool(kwargs.get("cookie"))))
            if url.startswith("https://www.mercadolivre.com.br/p/api/"):
                return json.dumps({"data": {"title": "Livro Memórias", "price": 31.5}})
            raise AssertionError("não deveria continuar depois da sessão")

        offer = read_offer(
            "https://www.mercadolivre.com.br/p/MLB4493446393",
            ml_cookie="ssid=abc",
            fetch=fetch,
        )
        self.assertEqual(asked, [("https://www.mercadolivre.com.br/p/api/items/MLB4493446393", True)])
        self.assertEqual(offer.title, "Livro Memórias")
        self.assertEqual(offer.price_cents, 3150)

    def test_without_cookies_the_warning_sends_the_person_to_the_settings(self) -> None:
        def fetch(_url: str, **_kwargs):
            raise LinkOfferError("A loja respondeu HTTP 403.")

        with self.assertRaises(LinkOfferError) as caught:
            read_offer("https://produto.mercadolivre.com.br/MLB-1234567", fetch=fetch)
        self.assertIn("Cole os cookies em Configurações", str(caught.exception))


class CatalogShortcutTests(unittest.TestCase):
    """O CSV do dia responde sempre; a loja, não. Por isso o catálogo vem primeiro."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        from promo_livros.catalog import CatalogStore, parse_csv

        amazon = """posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;menor_preco_365;badges;categoria_mais_vendido;asin;link
"1";"Memórias do subsolo";"Fiódor";"Literatura";"Livros";"Capa Comum";"R$ 11,12";"R$ 19,90";"sim";"";"";"6550974119";"https://www.amazon.com.br/dp/6550974119"
"""
        mercado = """posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;menor_preco_365;badges;categoria_mais_vendido;asin;link;imagem
"1";"Capitães da Areia";"Jorge Amado";"Português";"Livros";"Livro físico";"R$ 19,00";"R$ 39,00";"";"";"";"MLB5055179419";"https://produto.mercadolivre.com.br/MLB-5055179419";"https://http2.mlstatic.com/D_NQ_NP_2X_900.webp"
"""
        self._folder = tempfile.TemporaryDirectory()
        self.catalog = CatalogStore(Path(self._folder.name) / "board.sqlite")
        self.catalog.replace(parse_csv(amazon), "amazon.csv")
        self.catalog.replace_ml(parse_csv(mercado), "mercadolivre-livros.csv")

    def tearDown(self) -> None:
        self.catalog.close()
        self._folder.cleanup()

    def test_a_link_already_in_the_imported_csv_is_filled_without_asking_the_store(self) -> None:
        from promo_livros.link_offer import offer_from_catalog

        found = offer_from_catalog(
            "https://produto.mercadolivre.com.br/MLB-5055179419", self.catalog.find_book
        )
        self.assertEqual(found["store"], "ml")
        self.assertEqual(found["title"], "Capitães da Areia")
        self.assertEqual(found["price"], "19,00")
        self.assertEqual(found["list_price"], "39,00")
        self.assertEqual(found["cover"], "https://http2.mlstatic.com/D_NQ_NP_2X_900.webp")

    def test_an_amazon_link_in_the_csv_brings_the_cover_from_the_asin(self) -> None:
        from promo_livros.link_offer import offer_from_catalog

        found = offer_from_catalog("https://www.amazon.com.br/dp/6550974119", self.catalog.find_book)
        self.assertEqual(found["title"], "Memórias do subsolo")
        self.assertEqual(found["price"], "11,12")
        self.assertIn("6550974119", found["cover"])

    def test_a_link_outside_the_csv_is_left_for_the_store_to_answer(self) -> None:
        from promo_livros.link_offer import offer_from_catalog

        self.assertIsNone(
            offer_from_catalog("https://www.amazon.com.br/dp/0000000000", self.catalog.find_book)
        )
        self.assertIsNone(offer_from_catalog("https://evil.test/dp/6550974119", self.catalog.find_book))


class TwoLinksTests(unittest.TestCase):
    def test_one_link_of_each_store_becomes_two_offers(self) -> None:
        def fetch(url: str, **_kwargs):
            if "api.mercadolibre.com" in url:
                return json.dumps({"title": "Livro Gabriela", "price": 25})
            return _AMAZON_PAGE

        found = read_offers(
            [
                "https://www.amazon.com.br/dp/6550974119",
                "",
                "https://www.mercadolivre.com.br/p/MLB4493446393",
            ],
            fetch=fetch,
            browser=lambda _url: None,
        )
        self.assertEqual([item["store"] for item in found], ["amazon", "ml"])
        self.assertEqual(found[1]["price"], "25,00")

    def test_a_link_that_fails_reports_the_reason_and_the_other_one_still_comes(self) -> None:
        def fetch(url: str, **_kwargs):
            if "api.mercadolibre.com" in url:
                raise LinkOfferError("A loja respondeu HTTP 404.")
            if "mercadolivre" in url:
                return "<html><body>nada aqui</body></html>"
            return _AMAZON_PAGE

        found = read_offers(
            [
                "https://www.amazon.com.br/dp/6550974119",
                "https://produto.mercadolivre.com.br/MLB-1234567",
            ],
            fetch=fetch,
            browser=lambda _url: None,
        )
        self.assertEqual(found[0]["title"], "Dom Casmurro & outras histórias")
        self.assertIn("preencha à mão", found[1]["error"])


if __name__ == "__main__":
    unittest.main()
