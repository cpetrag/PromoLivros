import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from promo_livros.catalog import (
    CatalogStore,
    catalog_kind,
    magalu_csv,
    parse_csv,
    parse_rows,
)
from promo_livros.board_store import BoardStore
from promo_livros.dashboard_curation import render_curation
from promo_livros.fila_aplicar import MemoriaPrevia, previa
from promo_livros.lojas import store_of
from promo_livros.post_copy import render_caption

_MAGALU = (
    "posicao;asin;titulo;preco;preco_de;link;imagem;menor_preco_365;categoria;autor\n"
    "1;jf7k9gad9;Livro Magalu Teste;R$ 29,90;R$ 49,90;"
    "https://www.magazineluiza.com.br/livro-foo/p/jf7k9gad9/sku123/;"
    "https://cdn.exemplo/capa.jpg;sim;Ficção;Autor\n"
    "2;abc12345;Segundo Magalu;R$ 19,90;;"
    "https://www.magazineluiza.com.br/livro/p/abc12345/sku/;;;;\n"
    "3;wrongid;Ignorado;R$ 10,00;;https://www.magazineluiza.com.br/livro/p/othercode/sku/;;;;\n"
)
_ML = (
    '"posicao";"titulo";"autor";"categoria";"preco";"preco_de";"menor_preco_365";"asin";"link"\n'
    '"1";"Duna";"F";"";"R$ 30,00";"R$ 40,00";"";"MLB1234567";"https://www.mercadolivre.com.br/duna/p/MLB1234567"\n'
)
_SHOPEE = (
    "posicao;asin;titulo;preco;preco_de;link;imagem;menor_preco_365;categoria;autor\n"
    "1;482840775.41158748466;Livro Shopee;R$ 19,38;;https://shopee.com.br/product/482840775/41158748466;;;;\n"
)


class MagaluParseTests(unittest.TestCase):
    def test_keeps_only_matching_asin_and_link(self):
        books = parse_rows(parse_csv(_MAGALU), kind="magalu")
        self.assertEqual([book.asin for book in books], ["jf7k9gad9", "abc12345"])
        book = books[0]
        self.assertEqual(book.store, "magalu")
        self.assertEqual(book.price_cents, 2990)
        self.assertEqual(book.list_cents, 4990)
        self.assertIn("/p/jf7k9gad9/", book.url)
        self.assertTrue(book.low_365)

    def test_catalog_kind_magalu(self):
        self.assertEqual(catalog_kind(parse_csv(_MAGALU)), "magalu")

    def test_folder_prefers_fixed_name(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            (root / "magalu-livros-2026-11-02.csv").write_text("x", encoding="utf-8")
            self.assertEqual(magalu_csv(root).name, "magalu-livros-2026-11-02.csv")
            (root / "magalu-livros.csv").write_text("x", encoding="utf-8")
            self.assertEqual(magalu_csv(root).name, "magalu-livros.csv")


class MagaluStoreTests(unittest.TestCase):
    def test_replace_keeps_ml_and_shopee_rows(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace_ml(parse_csv(_ML), "ml.csv", day="2026-11-03")
            catalog.replace_shopee(parse_csv(_SHOPEE), "shopee.csv", day="2026-11-03")
            catalog.replace_magalu(parse_csv(_MAGALU), "magalu.csv", day="2026-11-03")
            stores = sorted(book.store for book in catalog.ml_books())
            self.assertEqual(stores, ["magalu", "magalu", "ml", "shopee"])

    def test_marks_magalu_and_finds_it(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace_magalu(parse_csv(_MAGALU), "magalu.csv", day="2026-11-03")
            catalog.set_ml_picked("jf7k9gad9", True, "2026-11-03")
            picked = catalog.ml_picked()
            self.assertEqual([(book.asin, book.store) for book in picked], [("jf7k9gad9", "magalu")])
            found = catalog.find_book("jf7k9gad9")
            self.assertIsNotNone(found)
            self.assertEqual(found.store, "magalu")

    def test_move_pick_and_ml_image_keep_lowercase_id(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace_magalu(parse_csv(_MAGALU), "magalu.csv", day="2026-11-03")
            catalog.set_ml_picked("jf7k9gad9", True, "2026-11-03")
            catalog.set_ml_picked("abc12345", True, "2026-11-03")
            self.assertEqual(catalog.ml_image("JF7K9GAD9"), "https://cdn.exemplo/capa.jpg")
            self.assertTrue(catalog.move_pick("JF7K9GAD9", "magalu", 1))
            order = [book.asin for book in catalog.ml_picked()]
            self.assertEqual(order, ["abc12345", "jf7k9gad9"])


class MagaluCurationTests(unittest.TestCase):
    def test_previa_inclui_magalu_marcado(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            board = BoardStore(Path(folder) / "b.sqlite")
            try:
                catalog.replace_magalu(parse_csv(_MAGALU), "magalu.csv", day="2026-11-03")
                catalog.set_ml_picked("jf7k9gad9", True, "2026-11-03")
                payload = previa(catalog, board, "2026-11-03", "09:00", "mine", MemoriaPrevia())
                magalu = [slot["magalu"] for slot in payload["slots"] if slot.get("magalu")]
                self.assertEqual([item["id"] for item in magalu], ["jf7k9gad9"])
            finally:
                catalog.close()
                board.close()

    def test_post_copy_labels_magalu_link(self):
        caption = render_caption(
            [
                {
                    "title": "Livro",
                    "blurb": "",
                    "price_cents": 2990,
                    "list_price_cents": 4990,
                    "discount_pct": 40,
                    "lowest_label": "",
                    "coupon": "",
                    "url": "https://www.magazineluiza.com.br/livro/p/jf7k9gad9/sku/",
                }
            ],
            sign_index=0,
        )
        self.assertIn("Magazine Luiza:", caption)
        self.assertNotIn("🔗 Amazon:", caption)

    def test_curation_payload_has_magalu_list(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace_magalu(parse_csv(_MAGALU), "magalu.csv", day="2026-11-03")
            magalu = [book for book in catalog.ml_books() if book.store == "magalu"]
            html = render_curation(
                magalu,
                source="x",
                folder_file="",
                notice=None,
                store="magalu",
                magalu_books=magalu,
                ml_books=[],
                shopee_books=[],
            )
            raw = re.search(r'id="curation-data">(.*?)</script>', html, re.S).group(1)
            payload = json.loads(raw)
            self.assertEqual(payload["loja"], "magalu")
            self.assertEqual(len(payload["magalu"]), 2)
            self.assertIn('id="store-magalu"', html)


class LojasMagaluTests(unittest.TestCase):
    def test_store_of_magalu_url(self):
        book = SimpleNamespace(
            product_id="jf7k9gad9",
            url="https://www.magazineluiza.com.br/livro-foo/p/jf7k9gad9/sku123/",
        )
        self.assertEqual(store_of(book), "magalu")


if __name__ == "__main__":
    unittest.main()