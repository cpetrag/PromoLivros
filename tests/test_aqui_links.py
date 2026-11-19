import json
import unittest
from promo_livros.aqui_links import AquiLinkError, create_short_link

class _Response:
    def __init__(self, payload: dict, status: int = 201):
        self.payload = payload
        self.status = status
    def read(self):
        return json.dumps(self.payload).encode()
    def getcode(self):
        return self.status
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
