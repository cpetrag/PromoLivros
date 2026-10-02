import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from promo_livros.amz_links import (
    AmzLinkClient,
    AmzLinkError,
    LinkResult,
    apply_affiliate_links,
    needs_affiliate_link,
)
from promo_livros.board_actions import schedule_manual
from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.morning import write_board
from promo_livros.refresh_links import refresh_unsent_links


class NeedsLinkTests(unittest.TestCase):
    def test_regenerates_amazon_and_foreign_shorteners(self) -> None:
        self.assertTrue(needs_affiliate_link("https://www.amazon.com.br/dp/857412320X?tag=souleitor-20"))
        self.assertTrue(needs_affiliate_link("https://amzn.to/abc"))
        self.assertTrue(needs_affiliate_link("https://a.co/d/xyz"))
        self.assertFalse(needs_affiliate_link("https://link.amazon/ja-pronto"))
        self.assertFalse(needs_affiliate_link("https://example.com/livro"))


class ClientTests(unittest.TestCase):
    def test_posts_batches_of_fifty_and_keeps_item_errors(self) -> None:
        handler = _handler()
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            client = AmzLinkClient(f"http://127.0.0.1:{port}", "segredo", timeout=5)
            pairs = [(f"https://www.amazon.com.br/dp/B00TEST{i:03d}", "souleitor-20") for i in range(51)]
            pairs[2] = ("https://www.amazon.com.br/ruim", "souleitor-20")
            results = client.links(pairs)
        finally:
            server.shutdown()
        self.assertEqual(handler.sizes, [50, 1])
        self.assertEqual(handler.keys, ["segredo", "segredo"])
        self.assertEqual(results[0].url, "https://link.amazon/0")
        self.assertEqual(results[2].error, "ASIN_NAO_ENCONTRADO")
        self.assertIsNone(results[2].url)
        self.assertEqual(len(results), 51)

    def test_rejects_an_unauthorized_response(self) -> None:
        handler = _handler(status=401)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            client = AmzLinkClient(f"http://127.0.0.1:{port}", "errada", timeout=5)
            with self.assertRaises(AmzLinkError):
                client.links([("https://www.amazon.com.br/dp/857412320X", "souleitor-20")])
        finally:
            server.shutdown()


class RefreshTests(unittest.TestCase):
    def test_rewrites_only_posts_that_have_not_been_sent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = BoardStore(Path(folder) / "board.sqlite")
            pending = _add(store, "08:00", "Pendente", "https://www.amazon.com.br/dp/857412320X?tag=antiga")
            sent = _add(store, "08:40", "Enviado", "https://www.amazon.com.br/dp/8535902775?tag=antiga")
            sending = _add(store, "09:20", "Enviando", "https://amzn.to/abc123")
            other = _add(store, "10:00", "Outro", "https://example.com/livro")
            ready = _add(store, "10:40", "Pronto", "https://link.amazon/ja-pronto")
            store.claim_group_send(sent, "111@g.us", "Grupo", "2026-09-28T10:00:00")
            store.finish_group_send(sent, "111@g.us", "m1", "2026-09-28T10:00:01")
            store.claim_group_send(sending, "111@g.us", "Grupo", "2026-09-28T10:01:00")
            client = _FakeClient()
            changed = refresh_unsent_links(store, client, "souleitor-20")
            self.assertEqual(changed, 1)
            self.assertEqual([pair[0] for pair in client.pairs], ["https://www.amazon.com.br/dp/857412320X?tag=antiga"])
            posts = {post.books[0].title: post for post in store.unsent_posts()}
            self.assertEqual(posts["Pendente"].books[0].url, "https://link.amazon/857412320X")
            self.assertIn("https://link.amazon/857412320X", posts["Pendente"].caption)
            self.assertNotIn("Enviado", posts)
            self.assertNotIn("Enviando", posts)
            sent_row = store.posts_for("2026-09-28")
            by_title = {post.books[0].title: post for post in sent_row}
            self.assertTrue(by_title["Enviado"].books[0].url.endswith("tag=antiga"))
            self.assertEqual(by_title["Enviando"].books[0].url, "https://amzn.to/abc123")
            self.assertEqual(posts["Outro"].books[0].url, "https://example.com/livro")
            self.assertEqual(posts["Pronto"].books[0].url, "https://link.amazon/ja-pronto")
            self.assertEqual(other, posts["Outro"].id)
            self.assertEqual(ready, posts["Pronto"].id)
            store.close()

    def test_keeps_the_old_url_when_one_item_fails(self) -> None:
        urls = [
            "https://www.amazon.com.br/dp/857412320X",
            "https://www.amazon.com.br/ruim",
            "https://link.amazon/ok",
        ]
        updated = apply_affiliate_links(urls, _FakeClient(), "souleitor-20")
        self.assertEqual(
            updated,
            ["https://link.amazon/857412320X", "https://www.amazon.com.br/ruim", "https://link.amazon/ok"],
        )


class CreationTests(unittest.TestCase):
    def test_write_board_stores_the_resolved_url(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = BoardStore(root / "board.sqlite")
            books = [
                {
                    "asin": "857412320X",
                    "titulo": "Gildo",
                    "preco": 39.9,
                    "url": "https://www.amazon.com.br/dp/857412320X?tag=antiga",
                    "capa": "http://example/capa.jpg",
                    "sinopse": "",
                    "cupom": [],
                }
            ]
            written = write_board(
                store,
                "2026-09-28",
                books,
                root / "cards",
                download=lambda _url: Image.new("RGB", (20, 30), "red"),
                resolve_urls=lambda urls: ["https://link.amazon/novo" for _url in urls],
            )
            self.assertEqual(written, 1)
            post = store.posts_for("2026-09-28")[0]
            self.assertEqual(post.books[0].url, "https://link.amazon/novo")
            self.assertIn("https://link.amazon/novo", post.caption)
            store.close()

    def test_manual_post_stores_the_resolved_url(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = BoardStore(root / "board.sqlite")
            form = {
                "clock": ["21:00"],
                "title": ["Gildo"],
                "price": ["39,90"],
                "url": ["https://www.amazon.com.br/dp/857412320X"],
                "cover": ["http://example/capa.jpg"],
            }
            with patch(
                "promo_livros.board_actions.download_image",
                return_value=Image.new("RGB", (20, 30), "red"),
            ):
                notice = schedule_manual(
                    store,
                    "2026-09-28",
                    form,
                    root / "cards",
                    resolve_urls=lambda urls: ["https://link.amazon/manual"],
                )
            self.assertIsNone(notice)
            post = store.posts_for("2026-09-28")[0]
            self.assertEqual(post.books[0].url, "https://link.amazon/manual")
            self.assertIn("https://link.amazon/manual", post.caption)
            store.close()


class _FakeClient:
    def __init__(self) -> None:
        self.pairs: list[tuple[str, str]] = []

    def links(self, pairs: list[tuple[str, str]]) -> list[LinkResult]:
        self.pairs.extend(pairs)
        results = []
        for url, _tag in pairs:
            if "ruim" in url:
                results.append(LinkResult(url=None, error="ASIN_NAO_ENCONTRADO"))
            else:
                asin = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
                results.append(LinkResult(url=f"https://link.amazon/{asin}", error=None))
        return results


def _handler(status: int = 200):
    class Handler(BaseHTTPRequestHandler):
        sizes: list[int] = []
        keys: list[str] = []

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            self.sizes.append(len(body["items"]))
            self.keys.append(self.headers.get("x-api-key", ""))
            if status != 200:
                payload = json.dumps({"error": "NAO_AUTORIZADO", "message": "não"}).encode()
                self.send_response(status)
            else:
                payload = json.dumps(
                    [
                        {"error": "ASIN_NAO_ENCONTRADO", "message": "sem asin"}
                        if "ruim" in item["url"]
                        else {
                            "asin": "B00TEST123",
                            "tag": item["tag"],
                            "longUrl": "https://www.amazon.com.br/dp/B00TEST123?linkCode=sl2&tag=souleitor-20&ref_=as_li_ss_tl",
                            "shortUrl": f"https://link.amazon/{index}",
                            "url": f"https://link.amazon/{index}",
                            "cached": False,
                        }
                        for index, item in enumerate(body["items"])
                    ]
                ).encode()
                self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args) -> None:
            return

    Handler.sizes = []
    Handler.keys = []
    return Handler


def _add(store: BoardStore, clock: str, title: str, url: str) -> int:
    return store.add_post(
        day="2026-09-28",
        clock=clock,
        caption=title,
        image_path="",
        books=[BoardBook(title, "", 1000, None, None, "", url, "")],
    )


if __name__ == "__main__":
    unittest.main()
