import unittest
from types import SimpleNamespace

from promo_livros.fila import ItemFila, item_de_livro
from promo_livros.fila_aplicar import _item_json


class StoreLinkTest(unittest.TestCase):
    def test_queue_item_carries_store_url(self) -> None:
        book = SimpleNamespace(asin="8501401382", title="Trono de vidro", store="amazon", price_cents=3455,
                               list_cents=6990, url="https://www.amazon.com.br/dp/8501401382")
        payload = _item_json(item_de_livro(book), ())
        self.assertEqual(payload["url"], "https://www.amazon.com.br/dp/8501401382")

    def test_url_does_not_change_item_identity(self) -> None:
        first = ItemFila("MLB1", "Livro", "ml", url="https://www.mercadolivre.com.br/a/p/MLB1")
        second = ItemFila("MLB1", "Livro", "ml")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
