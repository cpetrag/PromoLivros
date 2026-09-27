import unittest

from promo_livros.formatter import amazon_url, format_brl, format_rating, format_thousands, render_deal
from promo_livros.models import Deal


class FormatterTests(unittest.TestCase):
    def test_money_rating_and_thousands(self) -> None:
        self.assertEqual(format_brl(1_990), "R$ 19,90")
        self.assertEqual(format_brl(123_456), "R$ 1.234,56")
        self.assertEqual(format_rating(47), "4,7")
        self.assertEqual(format_rating(45), "4,5")
        self.assertEqual(format_rating(50), "5,0")
        self.assertEqual(format_thousands(1_234), "1.234")

    def test_caption_uses_whatsapp_bold_and_affiliate_tag(self) -> None:
        deal = Deal(
            asin="B00TEST123",
            title="A <B> & C",
            author="Autor",
            price_cents=1_990,
            avg90_cents=4_000,
            historic_min_cents=1_990,
            rating=47,
            review_count=1_234,
            image_url="https://m.media-amazon.com/images/I/capa.jpg",
            price_source="amazon",
        )
        rendered = render_deal(
            Deal(
                asin=deal.asin,
                title=deal.title,
                author=deal.author,
                price_cents=deal.price_cents,
                avg90_cents=deal.avg90_cents,
                historic_min_cents=deal.historic_min_cents,
                rating=deal.rating,
                review_count=deal.review_count,
                image_url=deal.image_url,
                price_source=deal.price_source,
                niche_label="Biografia",
                blurb="Conta a trajetória de alguém.",
                lowest_for_days=214,
            ),
            "loja-20",
        )
        self.assertIn("📚 *A <B> & C*", rendered.caption)
        self.assertIn("Biografia", rendered.caption)
        self.assertIn("Conta a trajetória de alguém.", rendered.caption)
        self.assertIn("R$ 19,90. Menor preço em 214 dias.", rendered.caption)
        self.assertIn("tag=loja-20", rendered.caption)
        self.assertEqual(
            amazon_url("b00test123", ""),
            "https://www.amazon.com.br/dp/B00TEST123",
        )

    def test_rejects_invalid_asin(self) -> None:
        with self.assertRaises(ValueError):
            amazon_url("não-é-asin", "loja-20")


if __name__ == "__main__":
    unittest.main()
