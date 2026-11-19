import unittest

import requests

from promo_livros.campaign_copy import MAX_GENERATED_TEXTS, MIN_GENERATED_TEXTS, generate_campaign_texts
from promo_livros.campaign_store import MAX_TEXT_LENGTH, CampaignError


class FakeResponse:
    def __init__(self, content: str | None = None, status_code: int = 200, body: object = None) -> None:
        self.status_code = status_code
        self._body = body if body is not None else {"choices": [{"message": {"content": content}}]}

    def json(self) -> object:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeSession:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _generate(session: FakeSession, count: int = 3) -> list[str]:
    return generate_campaign_texts(
        api_key="sk-test",
        model="gpt-4o-mini",
        campaign_name="Grupo X",
        count=count,
        session=session,
    )


class GenerateCampaignTextsTests(unittest.TestCase):
    def test_generate_splits_lines(self) -> None:
        session = FakeSession(FakeResponse("Hook um.\nHook dois.\nHook três."))
        self.assertEqual(_generate(session), ["Hook um.", "Hook dois.", "Hook três."])

    def test_sends_key_model_and_campaign_name_to_chat_completions(self) -> None:
        session = FakeSession(FakeResponse("A.\nB.\nC."))
        _generate(session)
        call = session.calls[0]
        self.assertEqual(call["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(call["json"]["model"], "gpt-4o-mini")
        self.assertIn("Grupo X", call["json"]["messages"][1]["content"])
        self.assertIn("3", call["json"]["messages"][1]["content"])

    def test_strips_numbering_bullets_and_blank_lines(self) -> None:
        session = FakeSession(FakeResponse("1. Um texto.\n\n2) Outro texto.\n- Terceiro texto.\n  \n"))
        self.assertEqual(_generate(session), ["Um texto.", "Outro texto.", "Terceiro texto."])

    def test_keeps_only_the_requested_count(self) -> None:
        session = FakeSession(FakeResponse("A1.\nB2.\nC3.\nD4.\nE5."))
        self.assertEqual(len(_generate(session, count=3)), 3)

    def test_clamps_count_between_three_and_ten(self) -> None:
        lines = "\n".join(f"Texto {number}." for number in range(20))
        low = FakeSession(FakeResponse(lines))
        self.assertEqual(len(_generate(low, count=0)), MIN_GENERATED_TEXTS)
        high = FakeSession(FakeResponse(lines))
        self.assertEqual(len(_generate(high, count=99)), MAX_GENERATED_TEXTS)
        self.assertIn(str(MAX_GENERATED_TEXTS), high.calls[0]["json"]["messages"][1]["content"])

    def test_drops_lines_over_the_whatsapp_caption_limit(self) -> None:
        session = FakeSession(FakeResponse("Curto.\n" + "x" * (MAX_TEXT_LENGTH + 1) + "\n" + "y" * MAX_TEXT_LENGTH))
        texts = _generate(session)
        self.assertEqual([len(text) for text in texts], [6, MAX_TEXT_LENGTH])

    def test_empty_answer_is_an_error(self) -> None:
        with self.assertRaises(CampaignError):
            _generate(FakeSession(FakeResponse("  \n ")))

    def test_http_failure_is_an_error_without_leaking_the_key(self) -> None:
        with self.assertRaises(CampaignError) as raised:
            _generate(FakeSession(FakeResponse(status_code=500, body={})))
        self.assertNotIn("sk-test", str(raised.exception))

    def test_refused_key_has_its_own_message(self) -> None:
        with self.assertRaises(CampaignError) as raised:
            _generate(FakeSession(FakeResponse(status_code=401, body={})))
        self.assertIn("chave", str(raised.exception).lower())

    def test_network_failure_is_an_error(self) -> None:
        with self.assertRaises(CampaignError):
            _generate(FakeSession(requests.ConnectionError("sk-test boom")))

    def test_invalid_json_is_an_error(self) -> None:
        with self.assertRaises(CampaignError):
            _generate(FakeSession(FakeResponse(body=ValueError("bad"))))

    def test_missing_key_is_an_error_before_any_request(self) -> None:
        session = FakeSession(FakeResponse("A.\nB.\nC."))
        with self.assertRaises(CampaignError):
            generate_campaign_texts(api_key="  ", model="m", campaign_name="X", count=3, session=session)
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
