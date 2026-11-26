import hashlib
import json
import unittest
from urllib.error import URLError

from promo_livros.shopee_links import (
    ShopeeLinkError,
    affiliate_url,
    is_shopee_url,
    links_de_afiliado,
    signature,
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


class ShopeeLinkTests(unittest.TestCase):
    def test_reconhece_link_longo_e_curto(self) -> None:
        self.assertTrue(
            is_shopee_url("https://shopee.com.br/livro-i.482840775.22595587888")
        )
        self.assertTrue(is_shopee_url("https://s.shopee.com.br/abc"))
        self.assertTrue(is_shopee_url("https://shope.ee/abc"))
        self.assertFalse(is_shopee_url("https://www.amazon.com.br/dp/B000000001"))

    def test_assinatura_e_o_sha256_da_concatenacao(self) -> None:
        payload = '{"query":"mutation { generateShortLink }"}'
        got = signature("18140170003", "1704067200", payload, "secret")
        expected = hashlib.sha256(
            f"18140170003{'1704067200'}{payload}secret".encode()
        ).hexdigest()
        self.assertEqual(got, expected)

    def test_affiliate_call_sends_auth_and_subid(self) -> None:
        seen = {}

        def opener(request, timeout=0):
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data.decode())
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            return _Response(
                {"data": {"generateShortLink": {"shortLink": "https://s.shopee.com.br/xyz"}}}
            )

        url = affiliate_url(
            "https://shopee.com.br/livro-i.1.2",
            app_id="18140170003",
            secret="secret",
            sub_id="promolivros",
            opener=opener,
            now=1704067200,
        )
        self.assertEqual(url, "https://s.shopee.com.br/xyz")
        self.assertIn("Credential=18140170003", seen["auth"])
        self.assertIn("Timestamp=1704067200", seen["auth"])
        self.assertIn("promolivros", seen["body"]["query"])
        self.assertIn("shopee.com.br/livro-i.1.2", seen["body"]["query"])
        self.assertEqual(seen["url"], "https://open-api.affiliate.shopee.com.br/graphql")

    def test_sem_credencial_sobe_erro(self) -> None:
        with self.assertRaises(ShopeeLinkError):
            links_de_afiliado(["https://shopee.com.br/livro-i.1.2"], app_id="", secret="x")

    def test_rede_instavel_tenta_de_novo_antes_de_falhar(self) -> None:
        attempts = {"n": 0}

        def opener(request, timeout=0):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise URLError("temporary")
            return _Response(
                {"data": {"generateShortLink": {"shortLink": "https://s.shopee.com.br/ok"}}}
            )

        url = affiliate_url(
            "https://shopee.com.br/livro-i.1.2",
            app_id="18140170003",
            secret="secret",
            opener=opener,
            now=1704067200,
            sleep=lambda _seconds: None,
        )
        self.assertEqual(url, "https://s.shopee.com.br/ok")
        self.assertEqual(attempts["n"], 3)
