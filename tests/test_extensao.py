import tempfile
import unittest
from pathlib import Path

from PIL import Image

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.catalog import CatalogError, CatalogStore, parse_csv
from promo_livros.extensao import atender
from promo_livros.fila_aplicar import MemoriaPrevia, aplicar


def _download(_url: str) -> Image.Image:
    return Image.new("RGB", (40, 60), (20, 20, 20))


def _livro(**extra):
    base = {
        "id": "B000000009",
        "title": "Dom Casmurro",
        "price": "R$ 19,90",
        "list_price": "R$ 40,00",
        "url": "https://www.amazon.com.br/dp/B000000009",
        "image": "https://m.media-amazon.com/images/I/exemplo.jpg",
        "author": "Machado",
        "category": "Romance",
    }
    base.update(extra)
    return base


class CaixaTests(unittest.TestCase):
    def test_a_caixa_nao_entra_na_fila_ate_aplicar(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            memoria = MemoriaPrevia()
            try:
                token = board.setting("extension_token") or ""
                status, created = atender(
                    "POST",
                    "/extensao/livro",
                    {},
                    _livro(),
                    "Bearer vai-ser-criado",
                    catalog=catalog,
                    board=board,
                    day="2026-10-02",
                    agora="15:12",
                    memoria=memoria,
                    cards_dir=root / "cards",
                    resolve_urls=None,
                    resolve_ml=None,
                    thumbnail=lambda _item: "",
                    describe=None,
                )
                self.assertEqual(status, 401)
                token = board.setting("extension_token")
                status, created = atender(
                    "POST",
                    "/extensao/livro",
                    {},
                    _livro(),
                    f"Bearer {token}",
                    catalog=catalog,
                    board=board,
                    day="2026-10-02",
                    agora="15:12",
                    memoria=memoria,
                    cards_dir=root / "cards",
                    resolve_urls=None,
                    resolve_ml=None,
                    thumbnail=lambda _item: "",
                    describe=None,
                )
                self.assertEqual(status, 200, created)
                self.assertEqual(created["place"]["kind"], "fila")
                amazon, mercado = catalog.queue_for("2026-10-02")
                self.assertEqual(amazon, [])
                self.assertEqual(mercado, [])
                notice = aplicar(
                    catalog,
                    board,
                    "2026-10-02",
                    created["plan"]["previa_id"],
                    memoria,
                    root / "cards",
                    download=_download,
                )
                self.assertIn("entraram na fila", notice)
                self.assertEqual(catalog.caixa(), ([], []))
                self.assertEqual(len(board.posts_for("2026-10-02")), 1)
            finally:
                catalog.close()
                board.close()

    def test_soltar_deixa_no_catalogo_e_o_csv_preserva_a_caixa(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            try:
                catalog.guardar_na_caixa(
                    product_id="MLB1234567",
                    title="A metamorfose",
                    price_cents=2500,
                    list_cents=5000,
                    url="https://www.mercadolivre.com.br/p/MLB1234567",
                    image_url="https://http2.mlstatic.com/D_exemplo.jpg",
                    author="",
                    category="Livros",
                    day="2026-10-02",
                )
                catalog.soltar_caixa({"MLB1234567"})
                book = catalog.find_book("MLB1234567")
                self.assertIsNotNone(book)
                self.assertEqual(book.pick_state, "")
                self.assertFalse(book.picked)
                catalog.guardar_na_caixa(
                    product_id="B000000008",
                    title="Fora do csv",
                    price_cents=1000,
                    list_cents=None,
                    url="https://www.amazon.com.br/dp/B000000008",
                    image_url="",
                    author="",
                    category="",
                    day="2026-10-02",
                )
                catalog.replace(
                    parse_csv(
                        "posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;menor_preco_365;badges;categoria_mais_vendido;asin;link\n"
                        '"1";"Outro";"A";"";"";"";"R$ 10,00";"R$ 20,00";"sim";"";"";"B000000001";"https://www.amazon.com.br/dp/B000000001"\n'
                    ),
                    "arquivo",
                )
                self.assertIsNotNone(catalog.find_book("B000000008"))
                self.assertEqual(catalog.find_book("B000000008").pick_state, "caixa")
            finally:
                catalog.close()

    def test_enviado_hoje_nao_volta_para_a_caixa(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            try:
                catalog.guardar_na_caixa(
                    product_id="B000000009",
                    title="Dom Casmurro",
                    price_cents=1990,
                    list_cents=4000,
                    url="https://www.amazon.com.br/dp/B000000009",
                    image_url="",
                    author="",
                    category="",
                    day="2026-10-02",
                )
                catalog.mark_enviado("B000000009", "2026-10-02")
                with self.assertRaises(CatalogError):
                    catalog.guardar_na_caixa(
                        product_id="B000000009",
                        title="Dom Casmurro",
                        price_cents=1990,
                        list_cents=4000,
                        url="https://www.amazon.com.br/dp/B000000009",
                        image_url="",
                        author="",
                        category="",
                        day="2026-10-02",
                    )
            finally:
                catalog.close()

    def test_a_extensao_substitui_so_o_horario_que_ainda_vai_sair(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            board = BoardStore(Path(folder) / "board.sqlite")
            try:
                book = BoardBook(
                    "Dom Casmurro",
                    "",
                    1990,
                    None,
                    None,
                    "",
                    "https://www.amazon.com.br/dp/B000000009",
                    "",
                )
                past = board.add_post(
                    day="2026-10-02",
                    clock="10:00",
                    caption="já passou",
                    image_path="",
                    books=[book],
                )
                board.add_post(
                    day="2026-10-02",
                    clock="20:00",
                    caption="ainda vai",
                    image_path="",
                    books=[book],
                )
                board.replace_scheduled_after("2026-10-02", "15:12")
                remaining = board.posts_for("2026-10-02")
                self.assertEqual([post.id for post in remaining], [past])
                replaced = [post for post in board.day_feed("2026-10-02") if post.status == "replaced"]
                self.assertEqual([post.clock for post in replaced], ["20:00"])
            finally:
                board.close()
