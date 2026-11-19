import unittest

from promo_livros.fila_horarios import Limites, antes, empurrar, no_horario, reespacar, trocar

_FILA = [(1, "10:00"), (2, "10:40"), (3, "11:20"), (4, "12:00")]
_LIVRE = Limites(agora="09:00", fim="22:00")


class TrocarTests(unittest.TestCase):
    def test_troca_os_dois_horarios(self) -> None:
        result = trocar(_FILA, 1, 3, _LIVRE)
        self.assertTrue(result.ok)
        self.assertEqual(result.clocks, {1: "11:20", 3: "10:00"})

    def test_post_que_saiu_e_recusado(self) -> None:
        result = trocar(_FILA, 1, 9, _LIVRE)
        self.assertEqual(result.erro, "Esse post não está mais na fila.")

    def test_nao_poe_post_no_passado(self) -> None:
        result = trocar([(1, "08:30"), (2, "10:00")], 1, 2, _LIVRE)
        self.assertIn("já passou", result.erro)


class AntesTests(unittest.TestCase):
    def test_vindo_de_baixo_assume_o_horario_do_alvo(self) -> None:
        result = antes(_FILA, 4, 2, _LIVRE)
        self.assertEqual(result.clocks, {4: "10:40", 2: "11:20", 3: "12:00"})

    def test_vindo_de_cima_fica_logo_antes_do_alvo(self) -> None:
        result = antes(_FILA, 1, 4, _LIVRE)
        self.assertEqual(result.clocks, {2: "10:00", 3: "10:40", 1: "11:20"})


class NoHorarioTests(unittest.TestCase):
    def test_vai_para_horario_livre(self) -> None:
        self.assertEqual(no_horario(_FILA, 2, "15:00", _LIVRE).clocks, {2: "15:00"})

    def test_horario_ocupado_e_recusado(self) -> None:
        self.assertIn("11:20", no_horario(_FILA, 2, "11:20", _LIVRE).erro)

    def test_horario_fora_da_janela_e_recusado(self) -> None:
        result = no_horario(_FILA, 2, "22:00", _LIVRE)
        self.assertIsNotNone(result.fora)


class EmpurrarTests(unittest.TestCase):
    def test_soma_minutos_a_este_e_aos_seguintes(self) -> None:
        result = empurrar(_FILA, 2, 20, _LIVRE)
        self.assertEqual(result.clocks, {2: "11:00", 3: "11:40", 4: "12:20"})

    def test_volta_minutos_sem_passar_do_anterior(self) -> None:
        self.assertEqual(empurrar(_FILA, 3, -20, _LIVRE).clocks, {3: "11:00", 4: "11:40"})
        self.assertIn("10:40", empurrar(_FILA, 3, -40, _LIVRE).erro)

    def test_nao_empurra_para_o_passado(self) -> None:
        result = empurrar(_FILA, 1, -60, _LIVRE)
        self.assertIn("já passou", result.erro)

    def test_minutos_fora_do_limite(self) -> None:
        self.assertTrue(empurrar(_FILA, 1, 181, _LIVRE).erro)
        self.assertTrue(empurrar(_FILA, 1, -61, _LIVRE).erro)

    def test_passar_do_fim_sugere_intervalo(self) -> None:
        fila = [(1, "20:00"), (2, "20:40"), (3, "21:20")]
        result = empurrar(fila, 1, 40, _LIVRE)
        self.assertFalse(result.ok)
        self.assertEqual(result.fora.count, 1)
        self.assertEqual(result.fora.last, "22:00")
        self.assertEqual(result.fora.fit_interval, 39)

    def test_sem_sugestao_abaixo_de_cinco_minutos(self) -> None:
        fila = [(1, "21:40"), (2, "21:50"), (3, "21:55")]
        self.assertIsNone(empurrar(fila, 1, 15, _LIVRE).fora.fit_interval)

    def test_encaixar_reespaca_com_o_intervalo(self) -> None:
        fila = [(1, "20:00"), (2, "20:40"), (3, "21:20")]
        result = empurrar(fila, 1, 40, _LIVRE, intervalo=39)
        self.assertTrue(result.ok)
        self.assertEqual(result.clocks, {1: "20:40", 2: "21:19", 3: "21:58"})

    def test_permitir_fora_aceita_depois_do_fim(self) -> None:
        fila = [(1, "21:20")]
        limites = Limites(agora="09:00", fim="22:00", permitir_fora=True)
        self.assertEqual(empurrar(fila, 1, 60, limites).clocks, {1: "22:20"})

    def test_meia_noite_nunca(self) -> None:
        limites = Limites(agora="09:00", fim="22:00", permitir_fora=True)
        self.assertIn("meia-noite", empurrar([(1, "23:30")], 1, 40, limites).erro)


class ReespacarTests(unittest.TestCase):
    def test_mantem_este_e_espaca_os_seguintes(self) -> None:
        result = reespacar(_FILA, 2, 30, _LIVRE)
        self.assertEqual(result.clocks, {3: "11:10", 4: "11:40"})

    def test_intervalo_fora_do_limite(self) -> None:
        self.assertTrue(reespacar(_FILA, 2, 4, _LIVRE).erro)
        self.assertTrue(reespacar(_FILA, 2, 181, _LIVRE).erro)

    def test_passar_do_fim_sugere_intervalo(self) -> None:
        fila = [(1, "21:00"), (2, "21:10"), (3, "21:20")]
        result = reespacar(fila, 1, 40, _LIVRE)
        self.assertEqual(result.fora.count, 1)
        self.assertEqual(result.fora.last, "22:20")
        self.assertEqual(result.fora.fit_interval, 29)


if __name__ == "__main__":
    unittest.main()
