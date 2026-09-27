import unittest
from datetime import timedelta

from promo_livros.filters import evaluate_product, historic_min_from_csv
from promo_livros.models import PRICE_AMAZON, PRICE_BUY_BOX_SHIPPING, LastPost

from tests.helpers import NOW, filter_settings, make_product


def evaluate(product: dict, **settings):
    return evaluate_product(
        product,
        filter_settings(**settings),
        expected_product_type=0,
        now=NOW,
        last_post=None,
    )


class FilterTests(unittest.TestCase):
    def test_accepts_amazon_offer_at_historic_low(self) -> None:
        result = evaluate(make_product())
        self.assertTrue(result.accepted)
        assert result.deal is not None
        self.assertEqual(result.deal.price_source, "amazon")
        self.assertEqual(result.deal.price_cents, 2_000)
        self.assertEqual(result.deal.author, "Patrick Rothfuss")
        self.assertEqual(result.deal.image_url, "https://m.media-amazon.com/images/I/capa.jpg")
        self.assertFalse(result.is_repost)

    def test_rating_fails_before_price(self) -> None:
        product = make_product()
        product["stats"]["current"][16] = 40
        product["stats"]["current"][PRICE_AMAZON] = 9_000
        result = evaluate(product)
        self.assertEqual(result.reason, "rating")

    def test_rejects_third_party_only(self) -> None:
        product = make_product(availabilityAmazon=-1)
        result = evaluate(product)
        self.assertEqual(result.reason, "third_party")

    def test_uses_buy_box_when_amazon_is_absent(self) -> None:
        product = make_product(availabilityAmazon=-1)
        product["stats"]["current"][PRICE_BUY_BOX_SHIPPING] = 1_500
        product["stats"]["avg90"][PRICE_BUY_BOX_SHIPPING] = 3_000
        product["stats"]["min"][PRICE_BUY_BOX_SHIPPING] = [1_000, 1_500]
        result = evaluate(product)
        self.assertTrue(result.accepted)
        assert result.deal is not None
        self.assertEqual(result.deal.price_source, "buy_box")
        self.assertEqual(result.deal.price_cents, 1_500)

    def test_buy_box_rescues_amazon_that_is_not_the_low(self) -> None:
        product = make_product()
        product["stats"]["current"][PRICE_AMAZON] = 3_000
        product["stats"]["current"][PRICE_BUY_BOX_SHIPPING] = 1_000
        product["stats"]["avg90"][PRICE_BUY_BOX_SHIPPING] = 2_000
        product["stats"]["min"][PRICE_BUY_BOX_SHIPPING] = [1_000, 1_000]
        result = evaluate(product)
        self.assertTrue(result.accepted)
        assert result.deal is not None
        self.assertEqual(result.deal.price_source, "buy_box")

    def test_historic_low_and_tolerance(self) -> None:
        product = make_product()
        product["stats"]["current"][PRICE_AMAZON] = 2_500
        rejected = evaluate(product)
        self.assertEqual(rejected.reason, "historic_low")

        accepted = evaluate(product, historic_low_tolerance_percent=25)
        self.assertTrue(accepted.accepted)

    def test_discount_boundary(self) -> None:
        product = make_product()
        product["stats"]["current"][PRICE_AMAZON] = 8_000
        product["stats"]["avg90"][PRICE_AMAZON] = 10_000
        product["stats"]["min"][PRICE_AMAZON] = [1, 8_000]
        self.assertTrue(evaluate(product).accepted)

        product["stats"]["current"][PRICE_AMAZON] = 8_001
        product["stats"]["min"][PRICE_AMAZON] = [1, 8_001]
        self.assertEqual(evaluate(product).reason, "discount")

    def test_tracking_and_repost_window(self) -> None:
        from promo_livros.keepa_time import keepa_minutes

        recent = make_product(trackingSince=keepa_minutes(NOW - timedelta(days=10)))
        self.assertEqual(evaluate(recent).reason, "tracking")

        same_price = LastPost("B00TEST123", "O Nome do Vento", 2_000, NOW - timedelta(days=2))
        skipped = evaluate_product(
            make_product(),
            filter_settings(),
            expected_product_type=0,
            now=NOW,
            last_post=same_price,
        )
        self.assertEqual(skipped.reason, "already_posted")

        lower = LastPost("B00TEST123", "O Nome do Vento", 2_500, NOW - timedelta(days=2))
        product = make_product()
        repost = evaluate_product(
            product,
            filter_settings(),
            expected_product_type=0,
            now=NOW,
            last_post=lower,
        )
        self.assertTrue(repost.accepted)
        self.assertTrue(repost.is_repost)

        old = LastPost("B00TEST123", "O Nome do Vento", 1_000, NOW - timedelta(days=40))
        again = evaluate_product(
            make_product(),
            filter_settings(),
            expected_product_type=0,
            now=NOW,
            last_post=old,
        )
        self.assertTrue(again.accepted)
        self.assertFalse(again.is_repost)

    def test_csv_fallback_when_stats_min_is_empty(self) -> None:
        product = make_product()
        product["stats"]["min"] = [None] * 19
        product["csv"] = [None] * 19
        product["csv"][PRICE_AMAZON] = [10, 5_000, 20, 2_000, 30, -1]
        result = evaluate(product)
        self.assertTrue(result.accepted)
        assert result.deal is not None
        self.assertEqual(result.deal.historic_min_cents, 2_000)

    def test_buy_box_history_includes_shipping(self) -> None:
        history = [10, 1_000, 200, 20, 900, 0, 30, 800, 300]
        self.assertEqual(
            historic_min_from_csv([None] * 18 + [history], PRICE_BUY_BOX_SHIPPING, with_shipping=True),
            900,
        )


if __name__ == "__main__":
    unittest.main()
