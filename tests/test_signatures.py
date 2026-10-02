import unittest

from promo_livros.signatures import apply_signature, parse_block


class SignatureTests(unittest.TestCase):
    def test_split_keeps_the_text_and_drops_empty_pieces(self) -> None:
        block = "  Livros com até 60% off: https://link.amazon/B01bzXpmN  |  \n | Kindle Unlimited | "
        self.assertEqual(
            parse_block(block),
            [
                "Livros com até 60% off: https://link.amazon/B01bzXpmN",
                "Kindle Unlimited",
            ],
        )

    def test_replaces_the_old_signature_line(self) -> None:
        caption = "📖 *Livro*\n\n🔗 https://amazon.com/dp/1\n\nℹ️ Oferta: https://link.amazon/B01bzXpmN"
        updated = apply_signature(caption, "Nova linha")
        self.assertTrue(updated.endswith("Nova linha"))
        self.assertNotIn("Oferta:", updated)
        self.assertIn("🔗 https://amazon.com/dp/1", updated)

    def test_appends_when_the_caption_has_no_signature(self) -> None:
        self.assertEqual(apply_signature("*Livro*", "Rodapé"), "*Livro*\n\nRodapé")
