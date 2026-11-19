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

    def test_divulgador_sem_oferta_insere_segmento(self):
        raw = (
            "https://www.magazineluiza.com.br/livro/divulgador/abc/sku/"
            "?promoter_id=old&partner_id=old"
        )
        got = convert_magalu(raw, promoter_id=PROMOTER, partner_id=PARTNER)
        self.assertTrue(got.ok)
        self.assertEqual(got.tipo, "divulgador")
        parts = urlsplit(got.link_convertido)
        self.assertIn("/divulgador/oferta/abc/sku", parts.path)
        qs = parse_qs(parts.query)
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
        seen = []
        def opener(request, timeout=0):
            seen.append(request)
            return FakeResp()
        raw = "https://divulgador.magalu.com/r/xyz"
        got = convert_magalu(raw, promoter_id=PROMOTER, partner_id=PARTNER, opener=opener)
        self.assertEqual(len(seen), 1)
        user_agent = seen[0].get_header("User-agent", seen[0].get_header("User-Agent"))
        self.assertTrue(user_agent)
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