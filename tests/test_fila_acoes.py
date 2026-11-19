import tempfile
import unittest
from pathlib import Path

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.fila_acoes import executar
from promo_livros.send_schedule import parse_schedule

_DAY = "2026-09-28"


class FilaAcoesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.board = BoardStore(Path(self.folder.name) / "board.sqlite")
        self.board.save_send_schedule(parse_schedule("08:00", "22:00", "40", "45"))
        self.ids = [self._add(clock) for clock in ("20:00", "20:40", "21:20")]

    def tearDown(self) -> None:
        self.board.close()
        self.folder.cleanup()

    def _add(self, clock: str) -> int:
        return self.board.add_post(
            day=_DAY,
            clock=clock,
            caption=clock,
            image_path="",
            books=[BoardBook("Livro", "", 1000, None, None, "", "https://www.amazon.com.br/dp/857412320X", "")],
        )

    def _clocks(self) -> list[str]:
        return [post.clock for post in self.board.posts_for(_DAY)]

    def test_abrir_horario_usa_o_intervalo_da_grade_e_avisa_o_fim(self) -> None:
        answer = executar(self.board, _DAY, "09:00", "empurrar", {"id": [str(self.ids[1])]})
        self.assertEqual(answer["fora"], {"count": 1, "last": "22:00", "fit_interval": 39})
        self.assertEqual(self._clocks(), ["20:00", "20:40", "21:20"])

    def test_encaixar_e_desfazer(self) -> None:
        form = {"id": [str(self.ids[1])], "minutos": ["40"], "intervalo": ["39"]}
        answer = executar(self.board, _DAY, "09:00", "empurrar", form)
        self.assertTrue(answer["ok"])
        self.assertEqual(self._clocks(), ["20:00", "21:20", "21:59"])
        self.assertTrue(executar(self.board, _DAY, "09:00", "desfazer", {})["ok"])
        self.assertEqual(self._clocks(), ["20:00", "20:40", "21:20"])

    def test_passar_do_horario_estende_o_fim_do_dia(self) -> None:
        form = {"id": [str(self.ids[2])], "minutos": ["60"], "permitir_fora": ["1"]}
        self.assertTrue(executar(self.board, _DAY, "09:00", "empurrar", form)["ok"])
        self.assertEqual(self.board.send_end_for(_DAY, "22:00"), "22:21")

    def test_pedido_sem_id_vira_erro(self) -> None:
        self.assertEqual(executar(self.board, _DAY, "09:00", "trocar", {})["error"], "Pedido incompleto. Atualize a página.")


if __name__ == "__main__":
    unittest.main()
