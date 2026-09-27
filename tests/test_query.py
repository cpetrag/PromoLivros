import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from promo_livros.keepa_client import (
    _result_present,
    build_finder_queries,
    find_root_category,
    merge_asins,
)
from promo_livros.keepa_time import tracking_since_lte
from promo_livros.models import KeepaError

from tests.helpers import NOW, load_sample


class QueryTests(unittest.TestCase):
    def test_default_queries_use_documented_field_names(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = load_sample(Path(folder))
        queries = build_finder_queries(config, 555, NOW)
        self.assertEqual([query.name for query in queries], ["amazon", "buy_box"])

        amazon = queries[0].selection
        buy_box = queries[1].selection
        self.assertEqual(amazon["rootCategory"], [555])
        self.assertEqual(amazon["productType"], 0)
        self.assertEqual(amazon["current_SALES_gte"], 1)
        self.assertEqual(amazon["current_SALES_lte"], 20_000)
        self.assertEqual(amazon["avg30_SALES_gte"], 1)
        self.assertEqual(amazon["avg30_SALES_lte"], 30_000)
        self.assertEqual(amazon["salesRankDrops30_gte"], 10)
        self.assertEqual(amazon["current_RATING_gte"], 45)
        self.assertEqual(amazon["current_COUNT_REVIEWS_gte"], 100)
        self.assertEqual(amazon["trackingSince_lte"], tracking_since_lte(NOW, 180))
        self.assertEqual(amazon["sort"], [["current_SALES", "asc"]])
        self.assertEqual(amazon["perPage"], 50)
        self.assertEqual(amazon["page"], 0)
        self.assertEqual(amazon["availabilityAmazon"], [0])
        self.assertEqual(amazon["current_AMAZON_gte"], 1)
        self.assertEqual(amazon["deltaPercent90_AMAZON_gte"], 20)
        self.assertIs(amazon["isLowest_AMAZON"], True)
        self.assertNotIn("isLowest_BUY_BOX_SHIPPING", amazon)
        self.assertNotIn("singleVariation", amazon)

        self.assertEqual(buy_box["current_BUY_BOX_SHIPPING_gte"], 1)
        self.assertEqual(buy_box["deltaPercent90_BUY_BOX_SHIPPING_gte"], 20)
        self.assertIs(buy_box["isLowest_BUY_BOX_SHIPPING"], True)
        self.assertNotIn("isLowest_AMAZON", buy_box)
        self.assertNotIn("availabilityAmazon", buy_box)
        self.assertNotIn("categories_include", amazon)

    def test_niche_ids_are_capped_at_finder_limit(self) -> None:
        from promo_livros.keepa_client import category_include_ids

        with tempfile.TemporaryDirectory() as folder:
            config = load_sample(Path(folder))
        include = category_include_ids(10, list(range(100)))
        self.assertEqual(len(include), 50)
        self.assertEqual(include[0], 10)
        amazon = build_finder_queries(config, 555, NOW, category_ids=include)[0].selection
        self.assertEqual(amazon["categories_include"], include)

    def test_tolerance_drops_exact_lowest_flag(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = load_sample(Path(folder))
        relaxed = replace(config, filters=replace(config.filters, historic_low_tolerance_percent=5))
        amazon = build_finder_queries(relaxed, 555, NOW)[0].selection
        self.assertNotIn("isLowest_AMAZON", amazon)
        self.assertEqual(amazon["deltaPercent90_AMAZON_gte"], 20)

    def test_page_size_respects_api_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = load_sample(Path(folder))
        small = replace(config, max_asins_per_run=10)
        large = replace(config, max_asins_per_run=80)
        self.assertEqual(build_finder_queries(small, 1, NOW)[0].selection["perPage"], 50)
        self.assertEqual(build_finder_queries(large, 1, NOW)[0].selection["perPage"], 80)

    def test_merge_prioritizes_amazon_and_caps(self) -> None:
        selected, dropped = merge_asins([["A", "B"], ["B", "C", "D"]], limit=3)
        self.assertEqual(selected, ["A", "B", "C"])
        self.assertEqual(dropped, 1)


class ResponseTests(unittest.TestCase):
    def test_partial_batch_still_counts_as_a_result(self) -> None:
        self.assertTrue(_result_present("/product", {"products": [{"asin": "B00TEST123"}], "error": {"message": "um asin falhou"}}))
        self.assertFalse(_result_present("/product", {"error": {"message": "You are out of tokens."}}))
        self.assertTrue(_result_present("/query", {"asinList": []}))


class CategoryTests(unittest.TestCase):
    def test_picks_root_named_livros(self) -> None:
        categories = {
            "10": {"catId": 10, "name": "Eletrônicos", "parent": 0},
            "20": {"catId": 20, "name": "Livros", "parent": 0},
            "21": {"catId": 21, "name": "Literatura", "parent": 20},
        }
        self.assertEqual(find_root_category(categories, "livros"), 20)

    def test_unknown_name_lists_what_the_api_returned(self) -> None:
        categories = {"10": {"catId": 10, "name": "Eletrônicos", "parent": 0}}
        with self.assertRaises(KeepaError) as caught:
            find_root_category(categories, "Livros")
        self.assertIn("Eletrônicos", str(caught.exception))

    def test_ambiguous_root_is_an_error(self) -> None:
        categories = {
            "1": {"catId": 1, "name": "Livros", "parent": 0},
            "2": {"catId": 2, "name": "Livros", "parent": 0},
        }
        with self.assertRaises(KeepaError):
            find_root_category(categories, "Livros")


if __name__ == "__main__":
    unittest.main()
