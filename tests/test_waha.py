import unittest

from promo_livros.waha import WahaClient, WahaError


class _Response:
    def __init__(
        self,
        status_code: int,
        payload: object,
        text: str | None = None,
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"
        self.text = text if text is not None else ""
        self.headers = headers or {}

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Http:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict | None, dict]] = []

    def request(self, method: str, url: str, headers: dict, json: dict | None, timeout: float) -> _Response:
        del timeout
        self.calls.append((method, url, json, headers))
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

    def test_send_jpeg_posts_the_card_bytes(self) -> None:
        http = _Http([_Response(200, {"id": "ABC"})])
        client = WahaClient("http://127.0.0.1:4443", "", "promo-livros", http=http)

        self.assertEqual(client.send_jpeg("120363430990609445@g.us", "texto", b"jpeg"), "ABC")
        body = http.calls[0][2]
        assert body is not None
        self.assertEqual(body["file"]["data"], "anBlZw==")
        self.assertNotIn("url", body["file"])

    def test_unpaired_session_is_retryable(self) -> None:
        http = _Http([_Response(422, {"message": "session is not working"}, text="session is not working")])
        client = WahaClient("http://127.0.0.1:3000", "", "esteira", http=http)

        with self.assertRaises(WahaError) as caught:
            client.send("120363430990609445@g.us", "oi", None)

        self.assertTrue(caught.exception.session_down)

    def test_probe_session_raises_when_waha_refuses(self) -> None:
        http = _Http([_Response(500, {})])
        client = WahaClient("http://127.0.0.1:4443", "chave", "promo-livros", http=http)
        with self.assertRaises(WahaError):
            client.probe_session()

    def test_fetch_qr_png_returns_image_bytes(self) -> None:
        response = _Response(200, {})
        response.content = b"\x89PNG\r\n"
        response.headers = {"content-type": "image/png"}
        http = _Http([response])
        client = WahaClient("http://127.0.0.1:4443", "chave", "promo-livros", http=http)

        self.assertEqual(client.fetch_qr_png(), b"\x89PNG\r\n")
        self.assertIn("/api/promo-livros/auth/qr", http.calls[0][1])
        recorded_headers = http.calls[0][3]
        self.assertEqual(recorded_headers.get("accept"), "image/png")
        self.assertEqual(recorded_headers.get("x-api-key"), "chave")

    def test_fetch_qr_png_rejects_json(self) -> None:
        response = _Response(200, {"status": "WORKING"})
        response.headers = {"content-type": "application/json"}
        http = _Http([response])
        client = WahaClient("http://127.0.0.1:4443", "", "promo-livros", http=http)
        with self.assertRaises(WahaError):
            client.fetch_qr_png()
        recorded_headers = http.calls[0][3]
        self.assertNotIn("x-api-key", recorded_headers)

    def test_begin_pairing_restarts_the_session(self) -> None:
        http = _Http([_Response(201, {"status": "STARTING"})])
        client = WahaClient("http://127.0.0.1:4443", "chave", "promo-livros", http=http)
        client.begin_pairing()
        self.assertEqual(http.calls[0][0], "POST")
        self.assertTrue(http.calls[0][1].endswith("/api/sessions/promo-livros/restart"))

    def test_group_participants_keep_role_and_skip_blanks(self) -> None:
        http = _Http([
            _Response(200, [
                {"id": "1@c.us", "role": "participant"},
                {"id": "2@c.us", "role": "admin"},
                {"id": "", "role": "participant"},
                {"role": "superadmin"},
            ]),
        ])
        client = WahaClient("http://127.0.0.1:4443", "chave", "promo-livros", http=http)
        self.assertEqual(
            client.group_participants("120363430990609445@g.us"),
            [("1@c.us", "participant"), ("2@c.us", "admin")],
        )
        self.assertIn("/participants/v2", http.calls[0][1])

if __name__ == "__main__":
    unittest.main()
