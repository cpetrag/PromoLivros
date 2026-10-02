import tempfile
import unittest
from pathlib import Path

from promo_livros.blurb import BlurbCache, OpenAIAuthError, OpenAIBlurb, promo_line


class _Response:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self._text = text

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._text}}]}


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.bodies: list[dict] = []

    def post(self, url: str, headers: dict, json: dict, timeout: float) -> _Response:
        del url, timeout
        self.bodies.append({"headers": headers, "json": json})
        return self.responses.pop(0)

    def close(self) -> None:
        return None


class PromoLineTests(unittest.TestCase):
    def test_keeps_a_short_invitation(self) -> None:
        line = promo_line("Entre nessa trama e descubra o segredo que ela esconde")
        self.assertEqual(line, "Entre nessa trama e descubra o segredo que ela esconde.")
        self.assertLessEqual(len(line.rstrip(".!?").split()), 12)

    def test_rejects_a_long_line_and_a_price(self) -> None:
        self.assertIsNone(promo_line("Um dois três quatro cinco seis sete oito nove dez onze doze treze."))
        self.assertIsNone(promo_line("Aproveite o desconto e leia esta história hoje."))

    def test_pitch_asks_for_twelve_words_and_stops_on_a_bad_key(self) -> None:
        session = _Session([_Response(200, "Leia e descubra o segredo que essa família esconde.")])
        writer = OpenAIBlurb("sk-test", "gpt-4.1-mini", 180, session=session)
        self.assertEqual(
            writer.pitch(title="O segredo", synopsis="Uma família guarda um segredo antigo."),
            "Leia e descubra o segredo que essa família esconde.",
        )
        prompt = session.bodies[0]["json"]["messages"][0]["content"]
        self.assertIn("12 palavras", prompt)
        self.assertIn("resenhas encontradas na internet", prompt)
        self.assertIn("nasce só do título e da sinopse", prompt)
        refused = _Session([_Response(401, "")])
        writer = OpenAIBlurb("sk-test", "gpt-4.1-mini", 180, session=refused)
        with self.assertRaises(OpenAIAuthError):
            writer.pitch(title="O segredo", synopsis="Uma família guarda um segredo antigo.")


class _JsonResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _ResearchSession:
    def __init__(self, posts: list[_JsonResponse], gets: list[_JsonResponse] | None = None) -> None:
        self.posts = list(posts)
        self.gets = list(gets or [])
        self.calls: list[tuple] = []

    def post(self, url: str, headers: dict, json: dict, timeout: float) -> _JsonResponse:
        del headers, timeout
        self.calls.append(("post", url, json))
        return self.posts.pop(0)

    def get(self, url: str, params: dict, headers: dict, timeout: float) -> _JsonResponse:
        del headers, timeout
        self.calls.append(("get", url, params))
        return self.gets.pop(0)

    def close(self) -> None:
        return None


class ResearchTests(unittest.TestCase):
    def test_research_reads_the_web_search_answer(self) -> None:
        session = _ResearchSession(
            [
                _JsonResponse(
                    200,
                    {
                        "output": [
                            {
                                "content": [
                                    {"type": "output_text", "text": "Um romance curto sobre a liberdade de um príncipe."}
                                ]
                            }
                        ]
                    },
                )
            ]
        )
        writer = OpenAIBlurb("sk-test", "gpt-4.1-mini", 180, session=session)
        line = writer.research(title="O Pequeno Príncipe", author="Antoine")
        self.assertEqual(line, "Um romance curto sobre a liberdade de um príncipe.")
        kind, url, body = session.calls[0]
        self.assertEqual(kind, "post")
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(body["tools"], [{"type": "web_search"}])
        self.assertIn("Pesquise na internet", body["input"][0]["content"])
        self.assertIn("Antoine", body["input"][1]["content"])

    def test_a_refused_key_does_not_fall_back_to_public_pages(self) -> None:
        session = _ResearchSession([_JsonResponse(401, {})])
        writer = OpenAIBlurb("sk-test", "gpt-4.1-mini", 180, session=session)
        with self.assertRaises(OpenAIAuthError):
            writer.research(title="O Pequeno Príncipe")
        self.assertEqual(session.gets, [])

    def test_when_web_search_fails_the_sentence_comes_from_public_pages(self) -> None:
        session = _ResearchSession(
            posts=[
                _JsonResponse(400, {}),
                _JsonResponse(
                    200,
                    {"choices": [{"message": {"content": "Um funcionário isolado confronta a própria miséria."}}]},
                ),
            ],
            gets=[
                _JsonResponse(
                    200,
                    {"query": {"search": [{"snippet": "Romance de <span>Dostoiévski</span> sobre um homem amargo."}]}},
                )
            ],
        )
        writer = OpenAIBlurb("sk-test", "gpt-4.1-mini", 180, session=session)
        line = writer.research(title="Memórias do subsolo")
        self.assertEqual(line, "Um funcionário isolado confronta a própria miséria.")
        self.assertEqual(session.calls[1][0], "get")
        self.assertIn("Memórias do subsolo livro", session.calls[1][2]["srsearch"])
        self.assertIn("homem amargo", session.calls[2][2]["messages"][1]["content"])
        self.assertNotIn("<span>", session.calls[2][2]["messages"][1]["content"])

    def test_cache_keeps_a_line_and_ignores_a_blank(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "blurb_cache.json"
            cache = BlurbCache(path)
            cache.put("Memórias do subsolo", "Um funcionário isolado confronta a própria miséria.")
            cache.put("   ", "Uma frase qualquer aqui.")
            cache.put("Vazio", "   ")
            reloaded = BlurbCache(path)
            self.assertEqual(
                reloaded.get("  memórias   do subsolo "),
                "Um funcionário isolado confronta a própria miséria.",
            )
            self.assertEqual(reloaded.get("Vazio"), "")


if __name__ == "__main__":
    unittest.main()
