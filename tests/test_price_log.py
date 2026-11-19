import json
import re
import tempfile
import unittest
from pathlib import Path

from promo_livros.catalog import CatalogError, CatalogStore, parse_csv
from promo_livros.dashboard_curation import render_curation
from promo_livros.price_log import PriceLow, PricePoint, lowest_since, parse_history_csv

_ML_HEAD = '"posicao";"titulo";"autor";"categoria";"preco";"preco_de";"menor_preco_365";"asin";"link"\n'


def _ml_csv(price: str) -> str:
    return _ML_HEAD + f'"1";"Duna";"F";"";"{price}";"R$ 40,00";"";"MLB1234567";"https://www.mercadolivre.com.br/duna/p/MLB1234567"\n'


class LowestSinceTests(unittest.TestCase):
    def test_needs_seven_days_of_history(self):
        self.assertIsNone(lowest_since(1000, 1200, "2026-11-01", "2026-11-03"))

    def test_ties_or_beats_the_previous_minimum(self):
        self.assertEqual(lowest_since(1000, 1000, "2026-10-01", "2026-11-03", 1300), PriceLow(33, 1000, True))
        self.assertEqual(lowest_since(1100, 1000, "2026-10-01", "2026-11-03", 1300), PriceLow(33, 1000, False))
        self.assertFalse(lowest_since(1000, 1000, "2026-10-01", "2026-11-03", 1000).lowest)

    def test_caps_at_one_year(self):
        self.assertEqual(lowest_since(900, 1000, "2024-01-01", "2026-11-03").days, 365)


class PriceHistoryStoreTests(unittest.TestCase):
    def test_ml_import_records_price_and_keeps_day_minimum(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace_ml(parse_csv(_ml_csv("R$ 30,00")), "ml.csv", day="2026-10-20")
            catalog.replace_ml(parse_csv(_ml_csv("R$ 25,00")), "ml.csv", day="2026-10-20")
            catalog.replace_ml(parse_csv(_ml_csv("R$ 35,00")), "ml.csv", day="2026-10-20")
            catalog.replace_ml(parse_csv(_ml_csv("R$ 32,00")), "ml.csv", day="2026-10-25")
            lows = catalog.price_lows("ml", {"MLB1234567": 2500}, today="2026-11-03")
            self.assertEqual(lows["MLB1234567"], PriceLow(14, 2500, True))
            self.assertFalse(catalog.price_lows("ml", {"MLB1234567": 2600}, today="2026-11-03")["MLB1234567"].lowest)

    def test_price_that_never_moved_is_not_a_low(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            for day in ("2026-10-01", "2026-10-15"):
                catalog.replace_ml(parse_csv(_ml_csv("R$ 30,00")), "ml.csv", day=day)
            low = catalog.price_lows("ml", {"MLB1234567": 3000}, today="2026-11-03")["MLB1234567"]
            self.assertEqual((low.days, low.lowest), (33, False))

    def test_external_points_feed_shopee(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            saved = catalog.record_price_points(
                [
                    PricePoint("shopee", "468407499.9268512424", "2026-10-01", 13000),
                    PricePoint("shopee", "nao-e-id", "2026-10-01", 100),
                ]
            )
            self.assertEqual(saved, 1)
            low = catalog.price_lows("shopee", {"468407499.9268512424": 12341}, today="2026-11-03")
            self.assertTrue(low["468407499.9268512424"].lowest)

    def test_curation_shows_ml_low_chip_data(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace_ml(parse_csv(_ml_csv("R$ 30,00")), "ml.csv", day="2026-10-01")
            catalog.replace_ml(parse_csv(_ml_csv("R$ 28,00")), "ml.csv", day="2026-10-02")
            books = catalog.ml_books()
            lows = catalog.price_lows("ml", {book.asin: 2000 for book in books}, today="2026-11-03")
            html = render_curation(books, source="x", folder_file="", notice=None, store="ml", ml_lows=lows)
            raw = re.search(r'id="curation-data">(.*?)</script>', html, re.S).group(1)
            book = json.loads(raw)["ml"][0]
            self.assertEqual((book["historyDays"], book["lowDays"]), (33, 33))


class ParseHistoryCsvTests(unittest.TestCase):
    def test_reads_valid_rows(self):
        text = "loja;id;data;preco;preco_de\nshopee;468407499.9268512424;2026-10-01;R$ 123,41;\nml;mlb1234567;2026-10-02;10,90;29,90\n"
        self.assertEqual(
            parse_history_csv(text),
            [
                PricePoint("shopee", "468407499.9268512424", "2026-10-01", 12341, None),
                PricePoint("ml", "MLB1234567", "2026-10-02", 1090, 2990),
            ],
        )

    def test_rejects_bad_rows_with_line_number(self):
        text = "loja;id;data;preco;preco_de\namazon;B000000001;2026-10-01;10,00;\nshopee;1.2;01/10/2026;10,00;\n"
        with self.assertRaises(CatalogError) as caught:
            parse_history_csv(text)
        self.assertIn("Linha 2", str(caught.exception))
        self.assertIn("Linha 3", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
