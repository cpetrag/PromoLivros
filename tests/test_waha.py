import unittest

from promo_livros.waha import WahaClient, WahaError


class _Response:
    def __init__(self, status_code: int, payload: object, text: str | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"
        self.text = text if text is not None else ""

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Http:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, url: str, headers: dict, json: dict | None, timeout: float) -> _Response:
        del headers, timeout
        self.calls.append((method, url, json))
        return self.responses.pop(0)


class WahaClientTests(unittest.TestCase):
    def test_working_session_is_connected(self) -> None:
        http = _Http([_Response(200, {"status": "WORKING"})])
        client = WahaClient("http://127.0.0.1:3000", "", "esteira", http=http)

        self.assertEqual(client.connection_state(), "connected")
        self.assertIn("/api/sessions/esteira", http.calls[0][1])

    def test_send_image_uses_the_cover_url_and_caption(self) -> None:
        http = _Http([_Response(200, {"id": {"_serialized": "true_1@g.us_ABC"}})])
        client = WahaClient("http://127.0.0.1:3000/", "", "esteira", http=http)

        message_id = client.send("120363430990609445@g.us", "R$ 11,12", "https://exemplo/capa.jpg")

        self.assertEqual(message_id, "true_1@g.us_ABC")
        body = http.calls[0][2]
        assert body is not None
        self.assertEqual(body["session"], "esteira")
        self.assertEqual(body["chatId"], "120363430990609445@g.us")
        self.assertEqual(body["caption"], "R$ 11,12")
        self.assertEqual(body["file"]["url"], "https://exemplo/capa.jpg")
        self.assertTrue(http.calls[0][1].endswith("/api/sendImage"))

    def test_unpaired_session_is_retryable(self) -> None:
        http = _Http([_Response(422, {"message": "session is not working"}, text="session is not working")])
        client = WahaClient("http://127.0.0.1:3000", "", "esteira", http=http)

        with self.assertRaises(WahaError) as caught:
            client.send("120363430990609445@g.us", "oi", None)

        self.assertTrue(caught.exception.session_down)


if __name__ == "__main__":
    unittest.main()
