import tempfile
import unittest
from pathlib import Path

from promo_livros.board_store import BoardStore
from promo_livros.catalog import CatalogError, CatalogStore, parse_csv
from promo_livros.fila import ItemFila, OpcoesFila, com_ordem_manual, montar_fila
from promo_livros.fila_aplicar import (
    MemoriaPrevia,
    limpar_ordem_manual,
    ordem_manual,
    previa,
    salvar_ordem_manual,
)

DAY = "2026-11-03"
_CSV = """posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;menor_preco_365;badges;categoria_mais_vendido;asin;link
"1";"Primeiro";"W";"";"";"";"R$ 11,00";"R$ 20,00";"sim";"";"";"B000000001";"https://www.amazon.com.br/dp/B000000001"
"2";"Segundo";"A";"";"";"";"R$ 5,00";"R$ 24,00";"sim";"";"";"B000000002";"https://www.amazon.com.br/dp/B000000002"
"3";"Terceiro";"O";"";"";"";"R$ 13,00";"R$ 20,00";"sim";"";"";"B000000003";"https://www.amazon.com.br/dp/B000000003"
"""


def _item(item_id, store="amazon"):
    return ItemFila(id=item_id, title=f"Livro {item_id}", store=store, price_cents=1000)


class ComOrdemManualTests(unittest.TestCase):
    def test_listed_follow_list_and_new_ones_go_last(self):
        items = [_item("A"), _item("B"), _item("C"), _item("D")]
        self.assertEqual([item.id for item in com_ordem_manual(items, ("c", "A"))], ["C", "A", "B", "D"])

    def test_second_column_mixes_ml_and_shopee_in_any_order(self):
        opcoes = OpcoesFila(
            agora="08:00", inicio="09:00", fim="12:00", intervalo=60,
            ordem_manual=((), ("123456.7890123", "MLB1")),
        )
        fila = montar_fila([], [_item("MLB1", "ml")], opcoes, shopee=[_item("123456.7890123", "shopee")])
        self.assertEqual(fila.slots[0].shopee.id, "123456.7890123")
        self.assertIsNone(fila.slots[0].ml)
        self.assertEqual(fila.slots[1].ml.id, "MLB1")


class SalvarOrdemManualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.board = BoardStore(root / "board.sqlite")
        self.catalog = CatalogStore(root / "board.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def test_saves_per_day_and_dedupes(self):
        salvar_ordem_manual(self.board, DAY, ["B000000002", "b000000002", "B000000001"], ["MLB1"])
        self.assertEqual(ordem_manual(self.board, DAY), (("B000000002", "B000000001"), ("MLB1",)))
        self.assertIsNone(ordem_manual(self.board, "2026-11-04"))
        limpar_ordem_manual(self.board)
        self.assertIsNone(ordem_manual(self.board, DAY))

    def test_rejects_bad_ids(self):
        with self.assertRaises(CatalogError):
            salvar_ordem_manual(self.board, DAY, ["<script>"], [])
        self.assertIsNone(ordem_manual(self.board, DAY))

    def test_preview_uses_manual_order_only_in_mine(self):
        self.catalog.replace(parse_csv(_CSV), "amazon")
        for asin in ("B000000001", "B000000002", "B000000003"):
            self.catalog.set_picked(asin, True, DAY)
        salvar_ordem_manual(self.board, DAY, ["B000000003", "B000000001"], [])
        payload = previa(self.catalog, self.board, DAY, "07:00", "mine", MemoriaPrevia())
        order = [slot["amazon"]["id"] for slot in payload["slots"] if slot["amazon"]]
        self.assertEqual(order[:3], ["B000000003", "B000000001", "B000000002"])
        self.assertTrue(payload["manual"])
        desc = previa(self.catalog, self.board, DAY, "07:00", "desc", MemoriaPrevia())
        self.assertFalse(desc["manual"])


if __name__ == "__main__":
    unittest.main()
