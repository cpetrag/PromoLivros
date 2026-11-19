import tempfile
import unittest
from pathlib import Path

from PIL import Image

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.catalog import CatalogError, CatalogStore, parse_csv, publish_selection
from promo_livros.fila_aplicar import MemoriaPrevia, aplicar, desfazer, previa

_CSV = """posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;menor_preco_365;badges;categoria_mais_vendido;asin;link
"1";"Shakespeare";"W";"";"";"";"R$ 11,00";"R$ 20,00";"sim";"";"";"B000000001";"https://www.amazon.com.br/dp/B000000001"
"2";"Cute Bears";"A";"";"";"";"R$ 5,00";"R$ 24,00";"sim";"";"";"B000000002";"https://www.amazon.com.br/dp/B000000002"
"3";"Declínio de um Homem";"O";"";"";"";"R$ 13,00";"R$ 20,00";"sim";"";"";"B000000003";"https://www.amazon.com.br/dp/B000000003"
"""


def _download(_url: str) -> Image.Image:
    return Image.new("RGB", (40, 60), (20, 20, 20))


class PreviaAplicarTests(unittest.TestCase):
    def test_previa_bloqueia_enviado_aplicar_e_desfazer(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                catalog.replace(parse_csv(_CSV), "amazon")
                catalog.set_picked("B000000001", True, "2026-10-02")
                catalog.set_picked("B000000002", True, "2026-10-02")
                publish_selection(
                    catalog, board, "2026-10-02", "07:00", root / "cards", download=_download
                )
                sent = next(post for post in board.posts_for("2026-10-02") if "Shakespeare" in post.books[0].title)
                board.mark_sent(sent.id)
                catalog.set_picked("B000000003", True, "2026-10-02")
                memoria = MemoriaPrevia()
                payload = previa(catalog, board, "2026-10-02", "15:12", "desc", memoria)
                ids = [
                    side["id"]
                    for slot in payload["slots"]
                    for side in (slot["amazon"], slot["ml"])
                    if side
                ]
                self.assertNotIn("B000000001", ids)
                self.assertIn("B000000001", [item["id"] for item in payload["bloqueados"]])
                self.assertEqual(payload["slots"][0]["amazon"]["title"], "Cute Bears")
                antes = [post.books[0].title for post in board.posts_for("2026-10-02")]
                with self.assertRaises(CatalogError):
                    aplicar(catalog, board, "2026-10-02", "", memoria, root / "cards", download=_download)
                notice = aplicar(
                    catalog,
                    board,
                    "2026-10-02",
                    payload["previa_id"],
                    memoria,
                    root / "cards",
                    download=_download,
                )
                self.assertIn("entraram", notice)
                atuais = [post.books[0].title for post in board.posts_for("2026-10-02")]
                self.assertNotIn("Shakespeare", atuais)
                self.assertEqual(desfazer(catalog, board, "2026-10-02"), "A fila anterior voltou.")
                restaurada = [post.books[0].title for post in board.posts_for("2026-10-02")]
                self.assertEqual(restaurada, antes)
            finally:
                catalog.close()
                board.close()

    def test_shopee_da_fila_aparece_na_previa_e_continua_ao_aplicar(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                catalog.replace(parse_csv(_CSV), "amazon")
                catalog.set_picked("B000000002", True, "2026-10-02")
                shopee_post = board.add_post(
                    day="2026-10-02",
                    clock="16:00",
                    caption="shopee",
                    image_path="",
                    books=[
                        BoardBook(
                            title="Dom Casmurro",
                            blurb="",
                            price_cents=1500,
                            list_price_cents=3000,
                            discount_pct=50,
                            lowest_label="",
                            url="https://s.shopee.com.br/abc123",
                            coupon="",
                            product_id="123456789.2233445566",
                        )
                    ],
                )
                board.set_image(shopee_post, f"data/cards/{shopee_post}.jpg")
                memoria = MemoriaPrevia()
                payload = previa(catalog, board, "2026-10-02", "15:12", "mine", memoria)
                self.assertEqual(payload["imagens"], {"123456789.2233445566": f"/cards/{shopee_post}.jpg"})
                shopee = [slot["shopee"] for slot in payload["slots"] if slot["shopee"]]
                self.assertEqual([item["id"] for item in shopee], ["123456789.2233445566"])
                self.assertTrue(all(slot["ml"] is None for slot in payload["slots"] if slot["shopee"]))
                aplicar(
                    catalog,
                    board,
                    "2026-10-02",
                    payload["previa_id"],
                    memoria,
                    root / "cards",
                    download=_download,
                )
                livros = [book for post in board.posts_for("2026-10-02") for book in post.books]
                self.assertIn("https://s.shopee.com.br/abc123", [book.url for book in livros])
                self.assertIn("Cute Bears", [book.title for book in livros])
            finally:
                catalog.close()
                board.close()

    def test_aplicar_recusa_quando_a_fila_muda(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                catalog.replace(parse_csv(_CSV), "amazon")
                catalog.set_picked("B000000002", True, "2026-10-02")
                memoria = MemoriaPrevia()
                payload = previa(catalog, board, "2026-10-02", "07:00", "mine", memoria)
                board.add_post(
                    day="2026-10-02",
                    clock="08:00",
                    caption="outro",
                    image_path="",
                    books=[
                        BoardBook(
                            title="Outro",
                            blurb="",
                            price_cents=1000,
                            list_price_cents=2000,
                            discount_pct=50,
                            lowest_label="",
                            url="https://www.amazon.com.br/dp/B000000009",
                            coupon="",
                            product_id="B000000009",
                        )
                    ],
                )
                with self.assertRaises(CatalogError):
                    aplicar(
                        catalog,
                        board,
                        "2026-10-02",
                        payload["previa_id"],
                        memoria,
                        root / "cards",
                        download=_download,
                    )
            finally:
                catalog.close()
                board.close()
