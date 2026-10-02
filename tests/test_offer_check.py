import unittest

from promo_livros.offer_check import asin_in, judge


class OfferCheckTests(unittest.TestCase):
    def test_reads_an_asin_from_an_amazon_url(self) -> None:
        self.assertEqual(asin_in("https://www.amazon.com.br/dp/857412320X?tag=x"), "857412320X")
        self.assertIsNone(asin_in("https://link.amazon/abc"))

    def test_flags_a_different_price_and_a_missing_product(self) -> None:
        changed, cents = judge({"asin": "857412320X", "stats": {"current": [6490]}}, 5991)
        self.assertEqual((changed, cents), ("price", 6490))
        gone, _cents = judge(
            {"asin": "857412320X", "availabilityAmazon": -1, "stats": {"current": [-1]}},
            5991,
        )
        self.assertEqual(gone, "unavailable")
        broken, _cents = judge(None, 1000)
        self.assertEqual(broken, "broken")


if __name__ == "__main__":
    unittest.main()
