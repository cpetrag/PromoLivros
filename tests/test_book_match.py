import unittest

from promo_livros.book_match import pair_posts, titles_match
from promo_livros.catalog import CatalogBook


def _book(asin: str, title: str, *, price: int = 1000, position: int = 1, store: str = "amazon") -> CatalogBook:
    return CatalogBook(
        asin=asin,
        position=position,
        title=title,
        author="",
        category="",
        price_cents=price,
        list_cents=None,
        low_365=False,
        url="https://example.test/" + asin,
        picked=True,
        store=store,
    )


class BookMatchTests(unittest.TestCase):
    def test_same_title_matches_and_a_kit_does_not(self) -> None:
        self.assertTrue(
            titles_match(
                "Memórias do subsolo",
                "Memórias do subsolo - Dostoiévski, Fiódor - Ciranda Cultural - Capa Mole",
            )
        )
        self.assertTrue(
            titles_match(
                "O Caibalion",
                "Livro O Caibalion: Os Três Iniciados - Camelot Editora Novo",
            )
        )
        self.assertFalse(
            titles_match(
                "Memórias do subsolo",
                "Memórias Do Subsolo + Os Irmãos Karamázov Kit Dostoiévski",
            )
        )
        self.assertFalse(
            titles_match(
                "O Pequeno Príncipe",
                "Cute & Comfy Super Special Edição 10 - Pequeno Príncipe",
            )
        )

    def test_each_post_takes_one_book_from_each_store(self) -> None:
        amazon = [
            _book("6550974119", "Dom Casmurro", price=1112, position=1),
            _book("6550974120", "Quincas Borba", price=1500, position=2),
        ]
        same = _book("MLB4493446393", "Dom Casmurro - Machado de Assis", price=1900, store="ml")
        other = _book("MLB1", "Memórias do Cárcere", price=500, store="ml", position=2)
        extra = _book("MLB2", "Capitães da Areia", price=800, store="ml", position=3)
        pairs = pair_posts(amazon, [same, other, extra], amazon, [same, other, extra])
        self.assertEqual(
            [(item.asin, alt.asin if alt else None) for item, alt in pairs],
            [
                ("6550974119", "MLB1"),
                ("6550974120", "MLB4493446393"),
                ("MLB2", None),
            ],
        )


if __name__ == "__main__":
    unittest.main()
