import json
import unittest

from promo_livros.ml_links import (
    MlLinkError,
    affiliate_url,
    apply_ml_links,
    links_de_afiliado,
    session_from_export,
    session_ready,
    thumbnail_url,
)
from promo_livros.post_copy import render_caption

_JSON = json.dumps(
    [
        {"name": "NID", "value": "google", "domain": ".google.com"},
        {"name": "_csrf", "value": "tok en", "domain": ".mercadolivre.com.br"},
        {"name": "ssid", "value": "abc", "domain": ".mercadolivre.com.br"},
    ]
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


class MercadoLivreLinkTests(unittest.TestCase):
    def test_cookie_editor_json_keeps_mercado_livre_and_the_csrf(self) -> None:
        cookie, csrf = session_from_export(_JSON)
        self.assertEqual(csrf, "tok en")
        self.assertIn("_csrf=tok en", cookie)
        self.assertIn("ssid=abc", cookie)
        self.assertNotIn("google", cookie)
        self.assertTrue(session_ready(_JSON))

    def test_header_string_and_netscape_find_the_csrf(self) -> None:
        cookie, csrf = session_from_export("_csrf=abc; ssid=zzz")
        self.assertEqual(csrf, "abc")
        self.assertIn("ssid=zzz", cookie)
        netscape = ".mercadolivre.com.br\tTRUE\t/\tTRUE\t0\t_csrf\ttoken\n"
        self.assertEqual(session_from_export(netscape)[1], "token")
        self.assertFalse(session_ready(""))

    def test_affiliate_call_sends_cookie_csrf_and_tag(self) -> None:
        seen = {}

        def opener(request, timeout=0):
            seen["csrf"] = request.get_header("X-csrf-token")
            seen["cookie"] = request.get_header("Cookie")
            seen["body"] = json.loads(request.data.decode())
            seen["timeout"] = timeout
            return _Response({"urls": [{"short_url": "https://meli.la/abc"}]})

        url = affiliate_url(
            "https://www.mercadolivre.com.br/livro/p/MLB1?pdp_filters=discount",
            cookie="_csrf=tok; ssid=abc",
            csrf="tok",
            tag="cpetrag1971",
            opener=opener,
        )
        self.assertEqual(url, "https://meli.la/abc")
        self.assertEqual(seen["csrf"], "tok")
        self.assertIn("ssid=abc", seen["cookie"])
        self.assertEqual(seen["body"]["tag"], "cpetrag1971")
        self.assertEqual(seen["body"]["urls"], ["https://www.mercadolivre.com.br/livro/p/MLB1"])
        self.assertNotIn("pdp_filters", seen["body"]["urls"][0])

    def test_produto_address_is_sent_as_a_public_listing(self) -> None:
        seen = {}

        def opener(request, timeout=0):
            del timeout
            seen["body"] = json.loads(request.data.decode())
            return _Response({"urls": [{"short_url": "https://meli.la/ok"}]})

        url = affiliate_url(
            "https://produto.mercadolivre.com.br/MLB-43543757",
            cookie="_csrf=tok; ssid=abc",
            csrf="tok",
            tag="promolivros",
            opener=opener,
        )
        self.assertEqual(url, "https://meli.la/ok")
        self.assertEqual(seen["body"]["urls"], ["https://www.mercadolivre.com.br/p/MLB43543757"])

    def test_a_refused_listing_keeps_the_reason(self) -> None:
        def opener(request, timeout=0):
            del request, timeout
            return _Response({"urls": [{"message": "URL not allowed in affiliates program", "status": "error"}]})

        with self.assertRaises(MlLinkError) as caught:
            affiliate_url(
                "https://www.mercadolivre.com.br/p/MLB1",
                cookie="_csrf=tok; ssid=abc",
                csrf="tok",
                tag="promolivros",
                opener=opener,
            )
        self.assertIn("URL not allowed", str(caught.exception))

    def test_sem_sessao_o_link_de_afiliado_explica_o_erro(self) -> None:
        with self.assertRaises(MlLinkError) as caught:
            links_de_afiliado(["https://www.mercadolivre.com.br/livro/p/MLB1111111"], "", "cpetrag1971")
        self.assertIn("sessão", str(caught.exception))

    def test_without_session_the_product_url_stays(self) -> None:
        original = "https://produto.mercadolivre.com.br/MLB-1"
        self.assertEqual(apply_ml_links([original], "", "cpetrag1971"), [original])

    def test_caption_labels_the_second_store(self) -> None:
        caption = render_caption(
            [
                {
                    "title": "Memórias do subsolo",
                    "blurb": "",
                    "price_cents": 1112,
                    "list_price_cents": 1990,
                    "discount_pct": 44,
                    "lowest_label": "Menor preço em 365 dias.",
                    "coupon": "",
                    "url": "https://www.amazon.com.br/dp/6550974119",
                    "alt_url": "https://meli.la/abc",
                    "alt_title": "Memórias Do Subsolo Dostoiévski Literatura Russa Impactante",
                    "alt_price_cents": 1900,
                    "alt_list_price_cents": 3900,
                    "alt_discount_pct": 51.3,
                }
            ]
        )
        self.assertIn("📖 *Memórias do subsolo*", caption)
        self.assertIn("🔗 Amazon: https://www.amazon.com.br/dp/6550974119", caption)
        self.assertIn("📖 *Memórias Do Subsolo Dostoiévski Literatura Russa Impactante*", caption)
        self.assertIn("💲 R$ 19,00, (51% de desconto)", caption)
        self.assertIn("🔗 Mercado Livre: https://meli.la/abc", caption)
        self.assertLess(caption.index("*Memórias do subsolo*"), caption.index("Literatura Russa"))

    def test_session_page_provides_the_cover_when_the_api_refuses(self) -> None:
        from urllib.error import URLError

        html = '<meta property="og:image" content="https://http2.mlstatic.com/D_NQ_NP_2X_1-MLA1_112025-F.webp">'

        class Page:
            def read(self) -> bytes:
                return html.encode()

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> bool:
                return False

        def opener(request, timeout=0):
            if "api.mercadolibre.com" in request.full_url:
                raise URLError("recusado")
            self.assertIn("p/api/items/MLB4493446393", request.full_url)
            self.assertIn("_csrf=tok", request.get_header("Cookie"))
            self.assertGreater(timeout, 0)
            return Page()

        url = thumbnail_url("MLB4493446393", opener=opener, cookie="_csrf=tok")
        self.assertEqual(url, "https://http2.mlstatic.com/D_NQ_NP_2X_1-MLA1_112025-F.webp")


if __name__ == "__main__":
    unittest.main()
