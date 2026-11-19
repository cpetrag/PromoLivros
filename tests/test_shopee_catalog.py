import json
import re
import tempfile
import unittest
from pathlib import Path

from promo_livros.catalog import CatalogStore, catalog_kind, parse_csv, parse_rows, shopee_csv, shopee_link_id
from promo_livros.dashboard_curation import render_curation

_SHOPEE = (
    "posicao;asin;titulo;preco;preco_de;link;imagem;menor_preco_365;categoria;categoria_caminho;autor;nota;avaliacoes;vendidos;cupom;loja_nome;loja_oficial;frete_gratis;esgotado;preco_min;preco_max;preco_pix;origem\n"
    "1;482840775.41158748466;Mulheres com Deus - Devocional;R$ 19,38;R$ 39,90;https://shopee.com.br/product/482840775/41158748466;"
    "https://down-br.img.susercontent.com/file/sg-11134201-7rdxz-mc9mb2wz7xjld0;;Religião e Filosofia;Livros e Revistas > Livros > Religião e Filosofia;;5.0;88791;159275;;Online Editora;sim;;não;;;R$ 18,41;geral-vendas\n"
    "2;482840775.20697921308;Livro de colorir;R$ 9,90;;https://shopee.com.br/product/482840775/20697921308;"
    "https://exemplo.com/capa.jpg;;Livros Infantis;Livros e Revistas > Livros > Livros Infantis;;;;;;Loja;não;;não;;;;geral-vendas\n"
    "3;111111111.22222222222;Link de outro anúncio;R$ 10,00;;https://shopee.com.br/product/999999999/22222222222;;;;;;;;;;;;;;;;;x\n"
)
_ML = (
    '"posicao";"titulo";"autor";"categoria";"preco";"preco_de";"menor_preco_365";"asin";"link"\n'
    '"1";"Duna";"F";"";"R$ 30,00";"R$ 40,00";"";"MLB1234567";"https://www.mercadolivre.com.br/duna/p/MLB1234567"\n'
)


class ShopeeParseTests(unittest.TestCase):
    def test_reads_rows_and_ignores_extra_columns(self):
        books = parse_rows(parse_csv(_SHOPEE), kind="shopee")
        self.assertEqual([book.asin for book in books], ["482840775.41158748466", "482840775.20697921308"])
        first, second = books
        self.assertEqual((first.store, first.price_cents, first.list_cents), ("shopee", 1938, 3990))
        self.assertEqual(first.url, "https://shopee.com.br/product/482840775/41158748466")
        self.assertTrue(first.image_url.startswith("https://down-br.img.susercontent.com/file/"))
        self.assertEqual(second.image_url, "")
        self.assertTrue(second.kids)

    def test_kind_and_link_id(self):
        self.assertEqual(catalog_kind(parse_csv(_SHOPEE)), "shopee")
        self.assertEqual(shopee_link_id("https://shopee.com.br/Box-i.468407499.9268512424"), "468407499.9268512424")
        self.assertEqual(shopee_link_id("https://outro.com/product/1/2"), "")

    def test_folder_prefers_latest_copy(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            (root / "shopee-livros-2026-11-02.csv").write_text("x", encoding="utf-8")
            self.assertEqual(shopee_csv(root).name, "shopee-livros-2026-11-02.csv")
            (root / "shopee-livros.csv").write_text("x", encoding="utf-8")
            self.assertEqual(shopee_csv(root).name, "shopee-livros.csv")


class ShopeeStoreTests(unittest.TestCase):
    def test_each_csv_replaces_only_its_store(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace_ml(parse_csv(_ML), "ml.csv", day="2026-11-03")
            catalog.replace_shopee(parse_csv(_SHOPEE), "shopee.csv", day="2026-11-03")
            catalog.replace_ml(parse_csv(_ML), "ml.csv", day="2026-11-03")
            stores = sorted(book.store for book in catalog.ml_books())
            self.assertEqual(stores, ["ml", "shopee", "shopee"])
            self.assertEqual(catalog.reviews()[("shopee", "482840775.41158748466")].count, 88791)

    def test_marks_shopee_and_finds_it(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace_shopee(parse_csv(_SHOPEE), "shopee.csv", day="2026-11-03")
            catalog.set_ml_picked("482840775.41158748466", True, "2026-11-03")
            picked = catalog.ml_picked()
            self.assertEqual([(book.asin, book.store) for book in picked], [("482840775.41158748466", "shopee")])
            self.assertEqual(catalog.find_book("482840775.41158748466").store, "shopee")

    def test_curation_payload_has_shopee_list(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace_shopee(parse_csv(_SHOPEE), "shopee.csv", day="2026-11-03")
            shopee = catalog.ml_books()
            html = render_curation(
                shopee, source="x", folder_file="", notice=None, store="shopee", shopee_books=shopee, ml_books=[],
                reviews=catalog.reviews(),
            )
            raw = re.search(r'id="curation-data">(.*?)</script>', html, re.S).group(1)
            payload = json.loads(raw)
            self.assertEqual(payload["loja"], "shopee")
            self.assertEqual(len(payload["shopee"]), 2)
            self.assertEqual(payload["shopee"][0]["reviews"], 88791)
            self.assertIn('id="store-shopee"', html)


if __name__ == "__main__":
    unittest.main()
