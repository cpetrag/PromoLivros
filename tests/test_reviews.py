import json
import re
import tempfile
import unittest
from pathlib import Path

from promo_livros.catalog import CatalogStore, Reviews, parse_csv, parse_reviews
from promo_livros.dashboard_curation import render_curation

_HEAD = '"posicao";"titulo";"autor";"categoria";"categoria_caminho";"formato";"preco";"preco_de";"menor_preco_365";"badges";"categoria_mais_vendido";"asin";"link";"avaliacoes";"nota"\n'
_CSV = (
    _HEAD
    + '"1";"Duna";"F";"";"";"";"R$ 11,00";"R$ 20,00";"sim";"";"";"B000000001";"https://www.amazon.com.br/dp/B000000001";"5368";"4.8"\n'
    + '"2";"Sem nota";"A";"";"";"";"R$ 5,00";"R$ 24,00";"sim";"";"";"B000000002";"https://www.amazon.com.br/dp/B000000002";"";""\n'
)


class ParseReviewsTests(unittest.TestCase):
    def test_reads_count_rating_and_sold(self):
        self.assertEqual(parse_reviews({"avaliacoes": "5.368", "nota": "4,8"}), Reviews(5368, 4.8, None))
        self.assertEqual(parse_reviews({"nota": "4.6", "vendidos": "1000"}), Reviews(None, 4.6, 1000))

    def test_out_of_range_or_empty_is_none(self):
        self.assertIsNone(parse_reviews({"avaliacoes": "", "nota": "9"}))
        self.assertIsNone(parse_reviews({"avaliacoes": "abc", "nota": "x"}))
        self.assertIsNone(parse_reviews({}))


class CatalogReviewsTests(unittest.TestCase):
    def test_import_saves_and_old_csv_clears(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace(parse_csv(_CSV), "amazon")
            self.assertEqual(catalog.reviews(), {("amazon", "B000000001"): Reviews(5368, 4.8, None)})
            without = "\n".join(line.rsplit(";", 2)[0] for line in _CSV.strip().splitlines())
            catalog.replace(parse_csv(without), "amazon")
            self.assertEqual(catalog.reviews(), {})

    def test_curation_payload_carries_reviews(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            catalog = CatalogStore(Path(folder) / "c.sqlite")
            catalog.replace(parse_csv(_CSV), "amazon")
            html = render_curation(
                catalog.books(), source="x", folder_file="", notice=None, reviews=catalog.reviews()
            )
            raw = re.search(r'id="curation-data">(.*?)</script>', html, re.S).group(1)
            books = {book["asin"]: book for book in json.loads(raw)["amazon"]}
            self.assertEqual(books["B000000001"]["reviews"], 5368)
            self.assertEqual(books["B000000001"]["rating"], 4.8)
            self.assertNotIn("reviews", books["B000000002"])


if __name__ == "__main__":
    unittest.main()
