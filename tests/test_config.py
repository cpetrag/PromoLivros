import tempfile
import unittest
from pathlib import Path

from promo_livros.config import load_config
from promo_livros.models import ConfigError

from tests.helpers import load_sample


class ConfigTests(unittest.TestCase):
    def test_loads_spec_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = load_sample(Path(folder))

        self.assertEqual(config.domain_id, 12)
        self.assertEqual(config.category_name, "Livros")
        self.assertEqual(config.filters.current_rank_lte, 20_000)
        self.assertEqual(config.filters.avg30_rank_lte, 30_000)
        self.assertEqual(config.filters.sales_rank_drops30_gte, 10)
        self.assertEqual(config.filters.current_rating_gte, 45)
        self.assertEqual(config.filters.current_review_count_gte, 100)
        self.assertEqual(config.filters.historic_low_tolerance_percent, 0)
        self.assertEqual(config.filters.min_discount_vs_avg90_percent, 20)
        self.assertEqual(config.filters.min_tracking_days, 180)
        self.assertEqual(config.schedule.search_hour, 6)
        self.assertEqual(config.schedule.posts_per_hour, 3)
        self.assertEqual([niche.key for niche in config.niches], ["ficcao", "nao_ficcao", "biografia"])
        self.assertEqual([(slot.hour, slot.minute, slot.niche_key, slot.rank) for slot in config.slots], [
            (20, 0, "ficcao", 0),
            (20, 20, "nao_ficcao", 0),
            (20, 40, "biografia", 0),
            (21, 0, "ficcao", 1),
            (21, 20, "nao_ficcao", 1),
            (21, 40, "biografia", 1),
        ])
        self.assertFalse(config.whatsapp_enabled)
        self.assertEqual(config.whatsapp_gap_seconds, 45)
        self.assertEqual(config.whatsapp_groups, ())
        self.assertEqual(config.waha_session, "promo-livros")
        self.assertEqual(config.waha_url, "http://127.0.0.1:4443")
        self.assertFalse(config.website_enabled)
        self.assertEqual(config.amz_link_api_url, "http://127.0.0.1:3070")
        self.assertEqual(config.amz_link_api_token, "")

    def test_shipped_file_loads(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config.yaml"
        config = load_config(path, {"KEEPA_API_KEY": "test-key"})
        self.assertEqual(config.domain_id, 12)
        self.assertEqual(config.category_name, "Livros")
        self.assertEqual(
            [group.name for group in config.whatsapp_groups],
            ["Black Livros 01", "Black Livros 02", "Black Livros 03"],
        )
        self.assertFalse(config.whatsapp_enabled)

    def test_rejects_other_domain_and_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.yaml"
            text = (Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8")
            path.write_text(text.replace("domain_id: 12", "domain_id: 1"), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path, {"KEEPA_API_KEY": "test-key"})

            shipped = Path(__file__).resolve().parents[1] / "config.yaml"
            with self.assertRaises(ConfigError):
                load_config(shipped, {"KEEPA_API_KEY": ""})

    def test_rejects_affiliate_tag_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ConfigError):
                load_sample(Path(folder), AMAZON_AFFILIATE_TAG="loja 20")


if __name__ == "__main__":
    unittest.main()
