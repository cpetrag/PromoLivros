import unittest

from promo_livros.fila import (
    ItemFila,
    OpcoesFila,
    chave_obra,
    horarios_livres,
    montar_fila,
    obras_batem,
    serie_de,
)


def _item(item_id: str, title: str, store: str = "amazon", discount: int = 10, price: int = 1000, category: str = "Romance") -> ItemFila:
    return ItemFila(item_id, title, store, price, discount, category)


class HorarioTests(unittest.TestCase):
    def test_corta_no_limite_e_depois_de_agora(self) -> None:
        clocks = horarios_livres("07:00", "23:40", 25, "15:12")
        self.assertEqual(clocks[0], "15:20")
        self.assertEqual(clocks[-1], "23:15")
        self.assertEqual(len(clocks), 20)
        self.assertNotIn("23:40", clocks)
        self.assertTrue(all(clock < "23:40" for clock in clocks))

    def test_nao_gera_horario_igual_ou_depois_do_fim(self) -> None:
        clocks = horarios_livres("08:00", "22:00", 40, "21:30")
        self.assertEqual(clocks, [])
        closed = horarios_livres("08:00", "22:00", 40, "22:00")
        self.assertEqual(closed, [])


class BloqueioTests(unittest.TestCase):
    def test_enviado_sai_da_fila_e_aparece_como_bloqueado(self) -> None:
        amazon = [
            _item("B000000001", "Shakespeare"),
            _item("B000000002", "Cute Bears", discount=79),
        ]
        opcoes = OpcoesFila(
            agora="15:12",
            inicio="07:00",
            fim="23:40",
            intervalo=25,
            enviados={"B000000001": ("09:05", "12:25")},
            horarios=("15:20",),
        )
        fila = montar_fila(amazon, [], opcoes)
        self.assertEqual([slot.amazon.id for slot in fila.slots if slot.amazon], ["B000000002"])
        self.assertEqual(fila.bloqueados[0].item.id, "B000000001")
        self.assertEqual(fila.bloqueados[0].clocks, ("09:05", "12:25"))


class OrdemTests(unittest.TestCase):
    def test_minha_ordem_respeita_a_marcacao(self) -> None:
        amazon = [
            _item("B000000001", "Declínio de um Homem", discount=34),
            _item("B000000002", "Cute Bears", discount=79),
        ]
        fila = montar_fila(amazon, [], _opcoes("mine"))
        self.assertEqual([slot.amazon.title for slot in fila.slots], ["Declínio de um Homem", "Cute Bears"])

    def test_maior_desconto_poe_o_maior_na_frente(self) -> None:
        amazon = [
            _item("B000000001", "Declínio de um Homem", discount=34),
            _item("B000000002", "Cute Bears", discount=79),
        ]
        fila = montar_fila(amazon, [], _opcoes("desc"))
        self.assertEqual([slot.amazon.title for slot in fila.slots], ["Cute Bears", "Declínio de um Homem"])

    def test_intercalar_pula_a_mesma_categoria(self) -> None:
        amazon = [
            _item("B000000001", "Primeiro romance", discount=80, category="Romance"),
            _item("B000000002", "Segundo romance", discount=70, category="Romance"),
            _item("B000000003", "Um ensaio", discount=60, category="Ensaio"),
        ]
        fila = montar_fila(amazon, [], _opcoes("mix"))
        titles = [slot.amazon.title for slot in fila.slots]
        self.assertEqual(titles[0], "Primeiro romance")
        self.assertEqual(titles[1], "Um ensaio")
        self.assertEqual(titles[2], "Segundo romance")


class PareamentoTests(unittest.TestCase):
    def test_listas_de_tamanhos_diferentes_deixam_metade_vazia(self) -> None:
        amazon = [_item("B000000001", "Um"), _item("B000000002", "Dois")]
        mercado = [_item("MLB1111111", "Lá", store="ml")]
        fila = montar_fila(amazon, mercado, _opcoes("mine"))
        self.assertEqual(len(fila.slots), 2)
        self.assertEqual(fila.slots[0].ml.title, "Lá")
        self.assertIsNone(fila.slots[1].ml)
        self.assertEqual(fila.slots[1].amazon.title, "Dois")

    def test_sobras_ficam_fora_dos_horarios(self) -> None:
        amazon = [_item(f"B00000000{n}", f"Livro {n}") for n in range(3)]
        opcoes = OpcoesFila("15:00", "07:00", "23:40", 25, horarios=("15:20",))
        fila = montar_fila(amazon, [], opcoes)
        self.assertEqual(len(fila.slots), 1)
        self.assertEqual([item.title for item in fila.sobras], ["Livro 1", "Livro 2"])

    def test_reserva_entra_antes_do_resto(self) -> None:
        amazon = [
            _item("B000000001", "Novo", discount=90),
            ItemFila("B000000002", "Guardado", "amazon", 1000, 10, "Romance", reserva=True),
        ]
        fila = montar_fila(amazon, [], _opcoes("desc"))
        self.assertEqual(fila.slots[0].amazon.title, "Guardado")
        self.assertEqual(fila.slots[1].amazon.title, "Novo")


class ObraTests(unittest.TestCase):
    def test_metamorfose_box_e_edicoes_batem(self) -> None:
        chaves = [
            chave_obra("A Metamorfose de Franz Kafka - Livro Capa Dura"),
            chave_obra("A Metamorfose 2026 | Franz Kafka"),
            chave_obra("Book Charm - A Metamorfose - Livro chaveiro"),
        ]
        self.assertTrue(obras_batem(chaves[0], chaves[1]))
        self.assertTrue(obras_batem(chaves[1], chaves[2]))
        self.assertTrue(obras_batem(chaves[0], chaves[2]))

    def test_colecao_e_karamazov_batem(self) -> None:
        self.assertTrue(
            obras_batem(
                chave_obra("Coleção Primeira Biblioteca Volume 02 - Box com 10 Livrinhos"),
                chave_obra("Coleção Primeira Biblioteca Volume 02"),
            )
        )
        self.assertTrue(
            obras_batem(
                chave_obra("Os Irmãos Karamázov Dostoiévski Clássicos Literatura Russa"),
                chave_obra("Os Irmãos Karamázov Literatura Russa Dostoiévski Clássicos"),
            )
        )

    def test_stranger_things_e_serie_e_nao_a_mesma_obra(self) -> None:
        voo = "Stranger Things: O voo de Ícaro"
        diario = "Stranger Things: Diário de Will Byers"
        self.assertFalse(obras_batem(chave_obra(voo), chave_obra(diario)))
        self.assertEqual(serie_de(voo), serie_de(diario))
        self.assertEqual(serie_de(voo), "stranger things")

    def test_mesma_obra_na_fila_gera_aviso(self) -> None:
        amazon = [_item("B000000001", "Book Charm - A Metamorfose - Livro chaveiro")]
        mercado = [_item("MLB1111111", "A Metamorfose de Franz Kafka - Livro Capa Dura", store="ml")]
        fila = montar_fila(amazon, mercado, _opcoes("mine", horarios=("16:00", "16:25")))
        textos = fila.slots[0].amazon_avisos + fila.slots[0].ml_avisos
        self.assertTrue(any("aparece de novo" in texto for texto in textos))

    def test_serie_proxima_gera_aviso_de_serie(self) -> None:
        amazon = [
            _item("B000000001", "Stranger Things: O voo de Ícaro"),
            _item("B000000002", "Outro livro qualquer"),
            _item("B000000003", "Stranger Things: Diário de Will Byers"),
        ]
        fila = montar_fila(amazon, [], _opcoes("mine", horarios=("16:00", "16:25", "16:50")))
        avisos = [texto for slot in fila.slots for texto in slot.amazon_avisos]
        self.assertTrue(any(texto.startswith("mesma série") for texto in avisos))

    def test_obra_que_ja_saiu_avisa_sem_bloquear(self) -> None:
        amazon = [_item("B000000009", "A Metamorfose 2026 | Franz Kafka")]
        opcoes = OpcoesFila(
            "15:00",
            "07:00",
            "23:40",
            25,
            obras_enviadas=(("a metamorfose", "11:10"),),
            horarios=("16:00",),
        )
        fila = montar_fila(amazon, [], opcoes)
        self.assertEqual(fila.slots[0].amazon_avisos, ("mesma obra saiu 11:10",))
        self.assertEqual(fila.bloqueados, ())


def _opcoes(ordem: str, horarios: tuple[str, ...] = ("08:00", "08:25", "08:50")) -> OpcoesFila:
    return OpcoesFila("07:00", "07:00", "23:40", 25, ordem=ordem, horarios=horarios)


if __name__ == "__main__":
    unittest.main()
