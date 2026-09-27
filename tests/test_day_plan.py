import tempfile
import unittest
from pathlib import Path

from promo_livros.blurb import one_sentence
from promo_livros.curation import prepare_day, publish_slot, should_prepare_today
from promo_livros.keepa_time import keepa_minutes
from promo_livros.models import PRICE_AMAZON, QueuedPost
from promo_livros.price_history import days_as_lowest, price_points
from promo_livros.selection import deals_from_products, offer_still_holds
from promo_livros.storage import Storage
from promo_livros.synopsis import extract_synopsis

from tests.helpers import NOW, filter_settings, load_sample, make_product


class PriceHistoryTests(unittest.TestCase):
    def test_counts_days_since_a_cheaper_price_ended(self) -> None:
        now_minutes = keepa_minutes(NOW)
        day = 24 * 60
        csv = [None] * 4
        csv[PRICE_AMAZON] = [now_minutes - 10 * day, 1_000, now_minutes - 4 * day, 2_500]
        points = price_points(csv, PRICE_AMAZON, with_shipping=False)
        self.assertEqual(days_as_lowest(points, 2_500, now_minutes), 4)

    def test_full_history_when_nothing_was_cheaper(self) -> None:
        now_minutes = keepa_minutes(NOW)
        day = 24 * 60
        points = [(now_minutes - 10 * day, 2_500)]
        self.assertEqual(days_as_lowest(points, 2_500, now_minutes), 10)

    def test_zero_when_the_latest_price_is_still_cheaper(self) -> None:
        now_minutes = keepa_minutes(NOW)
        points = [(now_minutes - 100, 1_000)]
        self.assertEqual(days_as_lowest(points, 2_500, now_minutes), 0)


class BlurbTests(unittest.TestCase):
    def test_keeps_the_first_sentence_inside_the_limit(self) -> None:
        text = one_sentence("Conta a história de Ana. O resto não entra.", 180)
        self.assertEqual(text, "Conta a história de Ana.")

    def test_empty_text_is_absent(self) -> None:
        self.assertIsNone(one_sentence("   ", 180))


class SynopsisTests(unittest.TestCase):
    def test_strips_html(self) -> None:
        self.assertEqual(extract_synopsis({"description": "<p>Olá&nbsp;mundo.</p>"}), "Olá mundo.")


class SelectionTests(unittest.TestCase):
    def test_skips_a_book_already_chosen_for_another_niche(self) -> None:
        product = make_product(description="Uma história.")
        deals = deals_from_products(
            [product],
            filter_settings(),
            expected_product_type=0,
            now=NOW,
            last_posts={},
            excluded={product["asin"]},
            limit=2,
        )
        self.assertEqual(deals, [])

    def test_price_rise_drops_the_morning_offer(self) -> None:
        product = make_product()
        product["stats"]["current"][PRICE_AMAZON] = 2_500
        product["stats"]["min"][PRICE_AMAZON] = [1_000, 2_500]
        product["stats"]["avg90"][PRICE_AMAZON] = 4_000
        self.assertIsNone(
            offer_still_holds(product, 2_000, filter_settings(), expected_product_type=0, now=NOW)
        )


class _FakeKeepa:
    def __init__(self, products: dict[str, dict], asins_by_category: dict[int, list[str]]) -> None:
        self._products = products
        self._asins_by_category = asins_by_category

    def balance_is_fresh(self) -> bool:
        return True

    def subcategory_ids(self, category_id: int) -> list[int]:
        return []

    def finder(self, selection: dict) -> tuple[list[str], int]:
        category_id = selection["categories_include"][0]
        asins = self._asins_by_category[category_id]
        return list(asins), len(asins)

    def products(self, asins: list[str]) -> list[dict]:
        return [self._products[asin] for asin in asins if asin in self._products]


class _FakeBlurb:
    def summarize(self, *, title: str, author: str, niche_label: str, rating: int, review_count: int, synopsis: str) -> str:
        del author, niche_label, rating, review_count, synopsis
        return f"Sobre {title}."


class CurationTests(unittest.TestCase):
    def test_morning_queue_does_not_repeat_asin_across_niches(self) -> None:
        shared = "B00SHARE01"
        products = {
            "B00TEST001": make_product(asin="B00TEST001", title="Ficção um", description="Uma história de ficção."),
            shared: make_product(asin=shared, title="Repetido", description="Aparece em dois nichos."),
            "B00TEST002": make_product(asin="B00TEST002", title="História", description="Um fato histórico."),
            "B00TEST003": make_product(asin="B00TEST003", title="Biografia", description="A vida de alguém."),
        }
        client = _FakeKeepa(
            products,
            {
                7872687011: ["B00TEST001", shared],
                7843068011: [shared, "B00TEST002"],
                7841731011: ["B00TEST003"],
            },
        )
        with tempfile.TemporaryDirectory() as folder:
            config = load_sample(Path(folder))
            storage = Storage(Path(folder) / "promo.sqlite")
            storage.save_category(12, "Livros", 6740748011, NOW)
            rows = prepare_day(config, client, storage, _FakeBlurb(), NOW, dry_run=False, refresh_category=False)
            stored = storage.queue_for_niche("2026-09-25", "nao_ficcao")
            storage.close()

        asins = [row.asin for row in rows]
        self.assertEqual(asins.count(shared), 1)
        self.assertIn("B00TEST002", asins)
        self.assertEqual(stored[0].blurb, "Sobre História.")
        self.assertTrue(should_prepare_today(config, NOW, has_queue=False))
        self.assertFalse(should_prepare_today(config, NOW, has_queue=True))

    def test_evening_slot_uses_the_reserve_when_the_price_rises(self) -> None:
        primary = make_product(asin="B00TEST001")
        primary["stats"]["current"][PRICE_AMAZON] = 2_500
        primary["stats"]["min"][PRICE_AMAZON] = [1_000, 2_500]
        primary["stats"]["avg90"][PRICE_AMAZON] = 4_000
        reserve = make_product(asin="B00TEST002", title="Reserva", description="A reserva.")
        client = _FakeKeepa(
            {"B00TEST001": primary, "B00TEST002": reserve},
            {},
        )
        with tempfile.TemporaryDirectory() as folder:
            config = load_sample(Path(folder))
            storage = Storage(Path(folder) / "promo.sqlite")
            self.assertTrue(storage.replace_queue("2026-09-25", [
                _row("B00TEST001", position=0),
                _row("B00TEST002", position=2, title="Reserva"),
            ]))
            outcome = publish_slot(
                config, client, storage, "ficcao", 0, NOW, dry_run=False
            )
            niche_rows = storage.queue_for_niche("2026-09-25", "ficcao")
            posted = storage.last_post("B00TEST002")
            blocked = storage.replace_queue("2026-09-25", [])
            storage.close()

        self.assertEqual(outcome, "posted")
        self.assertEqual(niche_rows[0].status, "skipped")
        self.assertEqual(niche_rows[1].status, "posted")
        self.assertIsNotNone(posted)
        self.assertFalse(blocked)


def _row(asin: str, *, position: int, title: str = "Livro") -> QueuedPost:
    return QueuedPost(
        day="2026-09-25",
        niche_key="ficcao",
        position=position,
        asin=asin,
        title=title,
        author="Autor",
        niche_label="Ficção",
        price_cents=2_000,
        avg90_cents=4_000,
        historic_min_cents=2_000,
        rating=47,
        review_count=1_500,
        image_url=None,
        price_source="amazon",
        synopsis="Texto.",
        lowest_for_days=30,
        blurb="Uma frase.",
        status="ready",
    )


if __name__ == "__main__":
    unittest.main()
