import tempfile
import unittest
from pathlib import Path

from PIL import Image

from promo_livros.board_store import BoardStore
from promo_livros.catalog import CatalogError, CatalogStore
from promo_livros.dashboard_curation import render_curation
from promo_livros.fila_aplicar import MemoriaPrevia, aplicar
from promo_livros.fila_csv import _FORMATOS_LINK, parse_fila_csv, previa_do_csv

_HEADER = (
    "horario;asin;titulo;preco;preco_de;menor_preco_365;cupom;"
    "asin_ml;titulo_ml;preco_ml;preco_de_ml;menor_preco_365_ml;cupom_ml;link_ml"
)

_HEADER_3 = (
    "horario;asin;titulo;preco;preco_de;menor_preco_365;cupom;"
    "asin_ml;titulo_ml;preco_ml;preco_de_ml;menor_preco_365_ml;cupom_ml;imagem_ml;link_ml;"
    "asin_shopee;titulo_shopee;preco_shopee;preco_de_shopee;menor_preco_365_shopee;"
    "cupom_shopee;imagem_shopee;link_shopee"
)

_SHOPEE_LINK = (
    "https://shopee.com.br/Grandes-Obras-de-Julio-Verne-Box-com-3-Livros-i.482840775.22595587888"
)
_SHOPEE_IMG = "https://down-br.img.susercontent.com/file/sg-11134201-7qvd9-lg5gd41l2bsz35"

_LINK = "https://www.mercadolivre.com.br/capitaes-da-areia/p/MLB9990001111"
_MAGALU_LINK = "https://www.magazineluiza.com.br/livro-foo/p/jf7k9gad9/sku123/"

_FILA = f"""{_HEADER}
10:15;B000000001;Shakespeare;R$ 11,00;R$ 20,00;sim;Cupom: GILDO10;MLB1111111;Capitães da Areia;R$ 19,00;R$ 39,00;nao;;{_LINK}?matt_tool=1
11:00;https://www.amazon.com.br/dp/B000000002;Cute Bears;R$ 5,00;R$ 24,00;Menor preço em 365 dias;;;;;;
"""


def _download(_url: str) -> Image.Image:
    return Image.new("RGB", (40, 60), (20, 20, 20))


class FilaCsvTests(unittest.TestCase):
    def test_campanha_row_parses_without_books(self) -> None:
        # Colunas de livro vêm preenchidas de propósito: na linha campanha elas são ignoradas.
        text = f"{_HEADER}\n10:00;Campanha;lixo;R$ abc;;;;MLB1;x;y;;;;nao-e-link\n"
        rows = parse_fila_csv(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["clock"], "10:00")
        self.assertTrue(rows[0]["is_campaign"])
        self.assertIsNone(rows[0]["amazon"])
        self.assertIsNone(rows[0]["ml"])
        self.assertEqual(rows.avisos, [])
        self.assertEqual(rows.rejeitados, [])

    def test_book_and_campanha_in_same_csv(self) -> None:
        text = f"{_FILA}12:00;CAMPANHA;;;;;;;;;;;;\n"
        rows = parse_fila_csv(text)
        by_clock = {item["clock"]: item for item in rows}
        self.assertFalse(by_clock["10:15"].get("is_campaign", False))
        self.assertTrue(by_clock["12:00"]["is_campaign"])
        self.assertEqual(by_clock["10:15"]["amazon"]["asin"], "B000000001")

    def test_campanha_sem_horario_e_horario_repetido_sao_recusados(self) -> None:
        with self.assertRaises(CatalogError) as sem_hora:
            parse_fila_csv(f"{_HEADER}\n;campanha;;;;;;;;;;;;\n")
        self.assertIn("horário", str(sem_hora.exception))
        with self.assertRaises(CatalogError) as repetido:
            parse_fila_csv(f"{_HEADER}\n10:00;campanha;;;;;;;;;;;;\n10:00;campanha;;;;;;;;;;;;\n")
        self.assertIn("aparece de novo", str(repetido.exception))

    def test_previa_campanha_sem_passos_de_keepa_ou_resenha(self) -> None:
        text = f"{_HEADER}\n10:15;campanha;;;;;;;;;;;;\n11:00;B000000002;Cute Bears;R$ 5,00;;sim;;;;;;;;\n"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", text, MemoriaPrevia())
                campanha, livro = payload["slots"]
                self.assertTrue(campanha["is_campaign"])
                self.assertEqual(campanha["label"], "Campanha (rodízio)")
                self.assertIsNone(campanha["amazon"])
                self.assertFalse(livro["is_campaign"])
                self.assertTrue(payload["slots_ids"][0]["is_campaign"])
                self.assertEqual([b["asin"] for b in payload["livros"]], ["B000000002"])
                self.assertTrue(all(step["asin"] in {"B000000002", ""} for step in payload["passos"]))
                self.assertEqual(payload["passos"][-1]["kind"], "gravar")
            finally:
                catalog.close()
                board.close()

    def test_so_campanha_gera_previa_e_sobrevive_ao_gravar(self) -> None:
        from promo_livros.fila_csv import ImportacaoFila, avancar

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                payload = previa_do_csv(
                    catalog, board, "2026-10-03", "09:00", "22:00",
                    f"{_HEADER}\n10:15;campanha;;;;;;;;;;;;\n", MemoriaPrevia(),
                )
                job = ImportacaoFila(payload)
                gravados = []
                while not job.done and not job.error:
                    avancar(
                        job,
                        resolve_amazon=lambda urls: urls,
                        resolve_ml=lambda urls: urls,
                        describe=lambda title, author="": "x",
                        gravar=lambda atual: gravados.append(atual) or "ok",
                    )
                self.assertEqual(len(gravados), 1)
                self.assertTrue(gravados[0].slots_ids[0]["is_campaign"])
            finally:
                catalog.close()
                board.close()

    def test_colunas_ml_com_link_magalu_vai_para_store_magalu(self) -> None:
        text = (
            f"{_HEADER}\n"
            "10:15;B000000001;Amazon;R$ 10,00;;nao;;"
            f"jf7k9gad9;Livro Magalu;R$ 29,90;R$ 49,90;nao;;{_MAGALU_LINK}\n"
        )
        rows = parse_fila_csv(text)
        self.assertIsNone(rows[0]["ml"])
        magalu = rows[0]["magalu"]
        self.assertIsNotNone(magalu)
        self.assertEqual(magalu["store"], "magalu")
        self.assertEqual(magalu["asin"], "jf7k9gad9")
        self.assertEqual(magalu["title"], "Livro Magalu")
        self.assertEqual(magalu["price_cents"], 2990)
        self.assertEqual(magalu["url"], _MAGALU_LINK)
        self.assertEqual(rows[0]["amazon"]["asin"], "B000000001")

    def test_colunas_magalu_proprias_viram_oferta_magalu(self) -> None:
        link = "https://www.magazineluiza.com.br/livro-glee-o-inicio/p/088682900/li/lljl/"
        image = "https://a-static.mlcdn.com.br/600x600/livro-glee-o-inicio/magazineluiza/088682900/354223.jpg"
        text = (
            f"{_HEADER};asin_magalu;titulo_magalu;preco_magalu;preco_de_magalu;"
            "menor_preco_365_magalu;cupom_magalu;imagem_magalu;link_magalu\n"
            "13:40;B000000001;Amazon;R$ 10,00;;nao;;;;;;;;;"
            f"088682900;Livro - Glee: O início;R$ 9,89;R$ 49,90;nao;;{image};{link}\n"
        )
        rows = parse_fila_csv(text)
        magalu = rows[0]["magalu"]
        self.assertIsNotNone(magalu)
        self.assertEqual(magalu["store"], "magalu")
        self.assertEqual(magalu["asin"], "088682900")
        self.assertEqual(magalu["price_cents"], 989)
        self.assertEqual(magalu["url"], link)
        self.assertEqual(magalu["image_url"], image)
        self.assertIsNone(rows[0]["ml"])

    def test_codigo_magalu_com_10_chars_nao_e_confundido_com_asin(self) -> None:
        # IDs Magalu como bejk8f8a32 têm o mesmo formato [A-Z0-9]{10} do ASIN Amazon.
        link = "https://www.magazineluiza.com.br/livro-colecao/p/bejk8f8a32/li/lifs/"
        text = (
            f"{_HEADER};asin_magalu;titulo_magalu;preco_magalu;preco_de_magalu;"
            "menor_preco_365_magalu;cupom_magalu;imagem_magalu;link_magalu\n"
            "10:30;8501922382;Kit thrillers;R$ 57,14;R$ 109,90;sim;;;;;;;;;"
            f"bejk8f8a32;Mulheres notáveis;R$ 59,42;R$ 142,90;nao;;"
            f"https://a-static.mlcdn.com.br/img.jpg;{link}\n"
        )
        rows = parse_fila_csv(text)
        self.assertEqual(rows[0]["amazon"]["asin"], "8501922382")
        magalu = rows[0]["magalu"]
        self.assertIsNotNone(magalu)
        self.assertEqual(magalu["store"], "magalu")
        self.assertEqual(magalu["asin"], "bejk8f8a32")
        self.assertEqual(magalu["url"], link)

    def test_link_magalu_de_outro_produto_recusa_a_linha(self) -> None:
        text = (
            f"{_HEADER};asin_magalu;titulo_magalu;preco_magalu;preco_de_magalu;"
            "menor_preco_365_magalu;cupom_magalu;imagem_magalu;link_magalu\n"
            "13:40;B000000001;Amazon;R$ 10,00;;nao;;;;;;;;;"
            "088682900;Glee;R$ 9,89;;nao;;;https://www.magazineluiza.com.br/outro/p/999999999/\n"
        )
        with self.assertRaises(CatalogError) as trocada:
            parse_fila_csv(text)
        self.assertIn("asin_magalu", str(trocada.exception))

    def test_colunas_ml_mercado_livre_continua_store_ml(self) -> None:
        rows = parse_fila_csv("\ufeff" + _FILA)
        mercado = rows[0]["ml"]
        self.assertIsNone(rows[0]["magalu"])
        self.assertEqual(mercado["store"], "ml")
        self.assertEqual(mercado["asin"], "MLB1111111")

    def test_previa_csv_magalu_no_slot_e_passos(self) -> None:
        text = (
            f"{_HEADER}\n"
            "10:15;B000000001;Amazon;R$ 10,00;;nao;;"
            f"jf7k9gad9;Livro Magalu;R$ 29,90;;nao;;{_MAGALU_LINK}\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                memoria = MemoriaPrevia()
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", text, memoria)
                slot = payload["slots"][0]
                self.assertIsNone(slot["ml"])
                self.assertEqual(slot["magalu"]["title"], "Livro Magalu")
                self.assertEqual(payload["slots_ids"][0]["magalu"], "jf7k9gad9")
                stores = {book["store"] for book in payload["livros"]}
                self.assertEqual(stores, {"amazon", "magalu"})
                labels = " ".join(step["label"] for step in payload["passos"])
                self.assertIn("Magazine Luiza", labels)
            finally:
                catalog.close()
                board.close()

    def test_le_o_post_inteiro_e_a_pagina_mostra_o_formato(self) -> None:
        rows = parse_fila_csv("\ufeff" + _FILA)
        amazon = rows[0]["amazon"]
        mercado = rows[0]["ml"]
        self.assertEqual(rows[0]["clock"], "10:15")
        self.assertEqual(amazon["asin"], "B000000001")
        self.assertEqual(amazon["title"], "Shakespeare")
        self.assertEqual(amazon["price_cents"], 1100)
        self.assertTrue(amazon["low_365"])
        self.assertEqual(amazon["coupon"], "Cupom: GILDO10")
        self.assertEqual(mercado["asin"], "MLB1111111")
        self.assertEqual(mercado["url"], _LINK)
        self.assertEqual(mercado["title"], "Capitães da Areia")
        self.assertEqual(rows[1]["amazon"]["asin"], "B000000002")
        self.assertTrue(rows[1]["amazon"]["low_365"])
        self.assertIsNone(rows[1]["ml"])
        self.assertEqual(rows.avisos, [])
        self.assertEqual(rows.rejeitados, [])
        page = render_curation([], source="", folder_file="", notice=None)
        self.assertIn("Importar fila", page)
        self.assertIn("Substitui a fila de hoje", page)
        self.assertIn('id="fila-csv"', page)
        self.assertIn("Links do Mercado Livre que ficaram de fora", page)
        self.assertIn("Resolver", page)

    def test_recusa_coluna_trocada_horario_repetido_e_arquivo_vazio(self) -> None:
        with self.assertRaises(CatalogError) as trocada:
            parse_fila_csv(f"{_HEADER}\n10:00;MLB1111111;Livro;R$ 10,00;;nao;;;;;;\n")
        self.assertIn("asin_ml", str(trocada.exception))
        with self.assertRaises(CatalogError) as repetido:
            parse_fila_csv(
                f"{_HEADER}\n"
                "10:00;B000000001;Um;R$ 10,00;;nao;;;;;;\n"
                "10:00;B000000002;Dois;R$ 10,00;;nao;;;;;;\n"
            )
        self.assertIn("aparece de novo", str(repetido.exception))
        with self.assertRaises(CatalogError) as vazio:
            parse_fila_csv(f"{_HEADER}\n")
        self.assertIn("nenhum horário", str(vazio.exception))
        with self.assertRaises(CatalogError) as sem_titulo:
            parse_fila_csv(f"{_HEADER}\n10:00;B000000001;;R$ 10,00;;nao;;;;;;\n")
        self.assertIn("título", str(sem_titulo.exception))
        with self.assertRaises(CatalogError) as sem_link:
            parse_fila_csv(f"{_HEADER}\n10:00;;;;;;;MLB1111111;Livro;R$ 10,00;;nao;;\n")
        self.assertIn("link_ml inválido", str(sem_link.exception))
        self.assertIn("nome-do-livro/p/MLB", str(sem_link.exception))
        self.assertIn("produto.mercadolivre.com.br", str(sem_link.exception))
        with self.assertRaises(CatalogError) as curto:
            parse_fila_csv(
                f"{_HEADER}\n"
                "10:00;;;;;;;MLB1111111;Livro;R$ 10,00;;nao;;https://www.mercadolivre.com.br/p/MLB1111111\n"
            )
        self.assertIn("link_ml inválido", str(curto.exception))
        self.assertIn("nome-do-livro/p/MLB", str(curto.exception))
        self.assertIn("produto.mercadolivre.com.br", str(curto.exception))

    def test_link_ml_aceita_catalogo_anuncio_e_pagina_antiga(self) -> None:
        catalogo = "https://www.mercadolivre.com.br/eu-escolhi-viver-citadel/p/MLB19274569"
        anuncio = (
            "https://produto.mercadolivre.com.br/"
            "MLB-5936587644-kit-1-livro-para-colorir-infantil-educativo--36-canetinhas-_JM"
        )
        trocado = "https://produto.mercadolivre.com.br/MLB-1111111111-qualquer-coisa-_JM"
        antigo = (
            "https://www.mercadolivre.com.br/"
            "kit-2-livros-o-principe-maquiavel--o-caibalion-originais/up/MLBU4696027055"
        )
        convertido = (
            "https://produto.mercadolivre.com.br/"
            "MLB-5055179419-kit-2-livros-o-principe-maquiavel--o-caibalion-originais-_JM"
        )
        nu = "https://www.mercadolivre.com.br/p/MLB5055179419"

        def linha(clock: str, asin: str, titulo: str, asin_ml: str, titulo_ml: str, link: str) -> str:
            return (
                f"{clock};{asin};{titulo};R$ 10,00;;nao;;"
                f"{asin_ml};{titulo_ml};R$ 20,00;;nao;;{link}"
            )

        rows = parse_fila_csv(
            "\n".join(
                (
                    _HEADER,
                    linha("10:00", "B000000001", "Eu escolhi", "MLB3842786765", "Eu escolhi viver", catalogo),
                    linha("10:15", "B000000002", "Colorir", "MLB5936587644", "Kit colorir", anuncio),
                    linha("10:30", "B000000003", "Codigo trocado", "MLB5936587644", "Outro codigo", trocado),
                    linha("10:45", "B000000004", "Kit dois", "MLB5055179419", "Kit 2 livros", antigo),
                    linha("11:00", "B000000005", "Sem nome", "MLB5055179419", "Sem nome", nu),
                    linha("11:15", "B000000006", "Sem link", "MLB1111111", "Sem link", ""),
                    "11:30;B000000007;So Amazon;R$ 10,00;;nao;;;;;;;",
                )
            )
        )
        por_hora = {item["clock"]: item for item in rows}
        self.assertEqual(por_hora["10:00"]["ml"]["asin"], "MLB3842786765")
        self.assertEqual(por_hora["10:00"]["ml"]["url"], catalogo)
        self.assertEqual(por_hora["10:15"]["ml"]["url"], anuncio)
        self.assertNotIn("10:30", por_hora)
        self.assertEqual(rows.rejeitados[0], (
            "Linha 4: link_ml inválido para MLB5936587644: "
            f"{trocado}. O número depois de MLB- precisa ser o do asin_ml. "
            "Formatos aceitos: https://www.mercadolivre.com.br/nome-do-livro/p/MLB123 "
            "ou https://produto.mercadolivre.com.br/MLB-123-nome-do-livro-_JM."
        ))
        self.assertEqual(por_hora["10:45"]["ml"]["asin"], "MLB5055179419")
        self.assertEqual(por_hora["10:45"]["ml"]["url"], convertido)
        self.assertIsNone(por_hora["11:00"]["ml"])
        self.assertEqual(por_hora["11:00"]["amazon"]["asin"], "B000000005")
        self.assertIsNone(por_hora["11:15"]["ml"])
        self.assertEqual(por_hora["11:15"]["amazon"]["asin"], "B000000006")
        self.assertIsNotNone(por_hora["11:30"]["amazon"])
        self.assertIsNone(por_hora["11:30"]["ml"])
        self.assertEqual(
            rows.avisos,
            [
                f"Linha 6: link_ml inválido para MLB5055179419: {nu}. {_FORMATOS_LINK}",
                f"Linha 7: link_ml inválido para MLB1111111: . {_FORMATOS_LINK}",
            ],
        )
        self.assertTrue(all("11:30" not in aviso for aviso in rows.avisos))

    def test_le_amazon_e_shopee_na_mesma_linha(self) -> None:
        text = (
            f"{_HEADER_3}\n"
            "08:00;6550971292;Vidas secas;R$ 8,36;;nao;;;;;;;;;;"
            f"482840775.22595587888;Grandes Obras de Júlio Verne | Box com 3 Livros;"
            f"R$ 59,90;R$ 69,90;nao;;{_SHOPEE_IMG};{_SHOPEE_LINK}\n"
        )
        rows = parse_fila_csv(text)
        self.assertEqual(rows[0]["clock"], "08:00")
        self.assertEqual(rows[0]["amazon"]["asin"], "6550971292")
        self.assertIsNone(rows[0]["ml"])
        shopee = rows[0]["shopee"]
        self.assertEqual(shopee["asin"], "482840775.22595587888")
        self.assertEqual(shopee["title"], "Grandes Obras de Júlio Verne | Box com 3 Livros")
        self.assertEqual(shopee["price_cents"], 5990)
        self.assertEqual(shopee["list_cents"], 6990)
        self.assertEqual(shopee["url"], _SHOPEE_LINK)
        self.assertEqual(shopee["image_url"], _SHOPEE_IMG)
        self.assertEqual(shopee["store"], "shopee")

    def test_recusa_as_tres_lojas_na_mesma_linha(self) -> None:
        with self.assertRaises(CatalogError) as erro:
            parse_fila_csv(
                f"{_HEADER_3}\n"
                "08:00;B000000001;Um;R$ 10,00;;nao;;MLB1111111;Dois;R$ 20,00;;nao;;"
                f";{_LINK};482840775.22595587888;Tres;R$ 30,00;;nao;;{_SHOPEE_IMG};{_SHOPEE_LINK}\n"
            )
        self.assertIn("duas ofertas", str(erro.exception))

    def test_aplicar_poe_a_shopee_no_post(self) -> None:
        text = (
            f"{_HEADER_3}\n"
            "10:15;B000000001;Shakespeare;R$ 11,00;R$ 20,00;sim;;;;;;;;;;"
            f"482840775.22595587888;Box Verne;R$ 59,90;R$ 69,90;nao;;{_SHOPEE_IMG};{_SHOPEE_LINK}\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                memoria = MemoriaPrevia()
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", text, memoria)
                self.assertEqual(payload["slots"][0]["shopee"]["title"], "Box Verne")
                self.assertIsNone(payload["slots"][0]["ml"])

                def resolve_urls(urls: list[str]) -> list[str]:
                    return [f"{url}?tag=promo" if url else "" for url in urls]

                def resolve_shopee(urls: list[str]) -> list[str]:
                    return ["https://s.shopee.com.br/promo" if url else "" for url in urls]

                aplicar(
                    catalog,
                    board,
                    "2026-10-03",
                    payload["previa_id"],
                    memoria,
                    root / "cards",
                    download=_download,
                    resolve_urls=resolve_urls,
                    resolve_shopee=resolve_shopee,
                    describe=lambda title, author="": "Resenha curta.",
                )
                posts = board.posts_for("2026-10-03")
                self.assertEqual(len(posts[0].books), 2)
                ids = {book.product_id: book for book in posts[0].books}
                self.assertIn("B000000001", ids)
                self.assertIn("482840775.22595587888", ids)
                self.assertEqual(ids["482840775.22595587888"].url, "https://s.shopee.com.br/promo")
                self.assertIn("Shopee:", posts[0].caption)
            finally:
                catalog.close()
                board.close()

    def test_aplicar_usa_o_csv_e_so_entao_converte_link_e_resenha(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            chamadas: list[str] = []
            try:
                memoria = MemoriaPrevia()
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", _FILA, memoria)
                self.assertEqual(payload["origem"], "csv")
                self.assertEqual(payload["slots"][0]["clock"], "10:15")
                self.assertEqual(payload["slots"][0]["amazon"]["title"], "Shakespeare")
                self.assertEqual(payload["livros"][0]["coupon"], "Cupom: GILDO10")
                self.assertNotIn("Resenha", str(payload))

                def describe(title: str, author: str = "") -> str:
                    chamadas.append(title)
                    return "Resenha curta deste livro."

                def resolve_urls(urls: list[str]) -> list[str]:
                    return [f"{url}?tag=promo" if url else "" for url in urls]

                notice = aplicar(
                    catalog,
                    board,
                    "2026-10-03",
                    payload["previa_id"],
                    memoria,
                    root / "cards",
                    download=_download,
                    resolve_urls=resolve_urls,
                    describe=describe,
                )
                self.assertIn("entraram", notice)
                posts = board.posts_for("2026-10-03")
                self.assertEqual([post.clock for post in posts], ["10:15", "11:00"])
                livro = next(book for book in posts[0].books if book.product_id == "B000000001")
                self.assertEqual(livro.title, "Shakespeare")
                self.assertEqual(livro.coupon, "Cupom: GILDO10")
                self.assertEqual(livro.lowest_label, "Menor preço em 365 dias.")
                self.assertIn("tag=promo", livro.url)
                self.assertIn("Resenha curta", livro.blurb)
                self.assertIn("Shakespeare", chamadas)
            finally:
                catalog.close()
                board.close()

    def test_horario_passado_fica_de_fora_e_o_resto_segue(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                memoria = MemoriaPrevia()
                arquivo = (
                    f"{_HEADER}\n"
                    "08:00;B000000001;Shakespeare;R$ 11,00;;sim;;;;;;\n"
                    "10:15;B000000002;Cute Bears;R$ 5,00;;sim;;;;;;\n"
                )
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", arquivo, memoria)
                self.assertEqual(payload["pulados"], ["08:00 já passou"])
                self.assertEqual([slot["clock"] for slot in payload["slots"]], ["10:15"])
                self.assertEqual(payload["slots"][0]["amazon"]["title"], "Cute Bears")
                with self.assertRaises(CatalogError) as passou:
                    previa_do_csv(
                        catalog,
                        board,
                        "2026-10-03",
                        "11:00",
                        "22:00",
                        f"{_HEADER}\n08:00;B000000001;Shakespeare;R$ 11,00;;sim;;;;;;\n",
                        memoria,
                    )
                self.assertIn("já passaram", str(passou.exception))
                with self.assertRaises(CatalogError) as fora:
                    previa_do_csv(
                        catalog,
                        board,
                        "2026-10-03",
                        "09:00",
                        "10:00",
                        f"{_HEADER}\n10:15;B000000001;Shakespeare;R$ 11,00;;sim;;;;;;\n",
                        memoria,
                    )
                self.assertIn("fora da janela", str(fora.exception))
            finally:
                catalog.close()
                board.close()

    def test_capa_do_catalogo_entra_quando_o_csv_nao_traz_a_foto(self) -> None:
        from promo_livros.catalog import parse_csv

        picture = "https://http2.mlstatic.com/D_Q_NP_2X_719889-MLB110799756479_042026-E.webp"
        header = (
            "posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;"
            "menor_preco_365;badges;categoria_mais_vendido;asin;link;imagem\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                catalog.replace_ml(
                    parse_csv(
                        header
                        + f'"1";"Capitães";"Jorge";"Livros";"Livros";"Livro";"R$ 19,00";"";"";"";"";"MLB1111111";"https://www.mercadolivre.com.br/p/MLB1111111";"{picture}"\n'
                    ),
                    "mercadolivre-livros.csv",
                )
                arquivo = (
                    f"{_HEADER}\n"
                    "10:15;B000000001;Shakespeare;R$ 11,00;;sim;;MLB1111111;Capitães da Areia;R$ 19,00;;nao;;"
                    "https://www.mercadolivre.com.br/capitaes/p/MLB9990001111\n"
                    "11:00;;;;;;;MLB2222222;Sem foto;R$ 10,00;;nao;;"
                    "https://www.mercadolivre.com.br/sem-foto/p/MLB8880002222\n"
                )
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", arquivo, MemoriaPrevia())
                capas = {item["asin"]: item["image_url"] for item in payload["livros"]}
                self.assertEqual(capas["MLB1111111"], picture)
                self.assertEqual(capas["MLB2222222"], "")
                self.assertEqual(payload["sem_foto"], 1)
            finally:
                catalog.close()
                board.close()

    def test_os_passos_convertem_link_e_resenha_antes_de_substituir(self) -> None:
        from promo_livros.fila_csv import ImportacaoFila, avancar

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                memoria = MemoriaPrevia()
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", _FILA, memoria)
                job = ImportacaoFila(payload)
                vistos: list[str] = []

                def resolve(urls: list[str]) -> list[str]:
                    vistos.append("link")
                    return [f"{urls[0]}?tag=promo"]

                def describe(title: str, author: str = "") -> str:
                    vistos.append("resenha")
                    return "Resenha curta."

                def gravar(atual) -> str:
                    livro = atual.livros["B000000001"]
                    self.assertEqual(livro["blurb"], "Resenha curta.")
                    self.assertIn("tag=promo", livro["url_final"])
                    vistos.append("gravar")
                    return "A fila foi substituída."

                while not job.done and not job.error:
                    avancar(job, resolve_amazon=resolve, resolve_ml=resolve, describe=describe, gravar=gravar)
                self.assertTrue(job.done)
                self.assertEqual(job.message, "A fila foi substituída.")
                self.assertEqual(vistos.count("link"), 3)
                self.assertEqual(vistos.count("resenha"), 3)
                self.assertEqual(vistos[-1], "gravar")
                self.assertTrue(any(item["label"].startswith("Importando livro da Amazon") for item in job.passos))
                self.assertTrue(any(item["label"].startswith("Importando livro do Mercado Livre") for item in job.passos))
                self.assertEqual(job.passos[-1]["label"], "Substituindo a fila de hoje")
                self.assertTrue(all(item["state"] == "ok" for item in job.passos))
            finally:
                catalog.close()
                board.close()

    def test_link_quebrado_do_mercado_livre_sai_e_a_fila_segue(self) -> None:
        from promo_livros.fila_csv import ImportacaoFila, avancar

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                memoria = MemoriaPrevia()
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", _FILA, memoria)
                job = ImportacaoFila(payload)
                gravados = []

                def resolve_amazon(urls: list[str]) -> list[str]:
                    return [f"{urls[0]}?tag=promo"]

                def resolve_ml(urls: list[str]) -> list[str]:
                    raise RuntimeError("URL not allowed in affiliates program")

                def describe(title: str, author: str = "") -> str:
                    del title, author
                    return "Resenha curta."

                def gravar(atual) -> str:
                    gravados.append(atual)
                    return "A fila foi substituída."

                while not job.done and not job.error:
                    avancar(
                        job,
                        resolve_amazon=resolve_amazon,
                        resolve_ml=resolve_ml,
                        describe=describe,
                        gravar=gravar,
                    )
                self.assertTrue(job.done)
                self.assertFalse(job.aguardando)
                self.assertEqual(len(gravados), 1)
                salvo = gravados[0]
                self.assertNotIn("MLB1111111", salvo.livros)
                self.assertIn("B000000001", salvo.livros)
                self.assertIn("B000000002", salvo.livros)
                self.assertEqual(salvo.slots_ids[0]["amazon"], "B000000001")
                self.assertEqual(salvo.slots_ids[0]["ml"], "")
                self.assertEqual(job.visao()["quebrados"][0]["titulo"], "Capitães da Areia")
                self.assertIn("URL not allowed", job.visao()["quebrados"][0]["motivo"])
                self.assertIn("Ficaram de fora: Capitães da Areia.", job.message)
            finally:
                catalog.close()
                board.close()

    def test_converter_magalu_grava_url_final_encurtada(self) -> None:
        from promo_livros.fila_csv import ImportacaoFila, avancar

        text = (
            f"{_HEADER}\n"
            "10:15;B000000001;Amazon;R$ 10,00;;nao;;"
            f"jf7k9gad9;Livro Magalu;R$ 29,90;;nao;;{_MAGALU_LINK}\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", text, MemoriaPrevia())
                job = ImportacaoFila(payload)
                short = "https://aqui.descontos.ai/abc123"

                def resolve_magalu(urls: list[str]) -> list[str]:
                    return [short if url else "" for url in urls]

                def resolve_amazon(urls: list[str]) -> list[str]:
                    return [f"{urls[0]}?tag=promo"]

                def gravar(atual) -> str:
                    return "ok"

                while not job.done and not job.error:
                    avancar(
                        job,
                        resolve_amazon=resolve_amazon,
                        resolve_ml=lambda urls: urls,
                        resolve_magalu=resolve_magalu,
                        describe=lambda title, author="": "",
                        gravar=gravar,
                    )
                self.assertEqual(job.livros["jf7k9gad9"]["url_final"], short)
                self.assertTrue(job.done)
            finally:
                catalog.close()
                board.close()

    def test_converter_magalu_falha_deixa_oferta_de_fora(self) -> None:
        from promo_livros.fila_csv import ImportacaoFila, LinkQuebrado, avancar

        text = (
            f"{_HEADER}\n"
            "10:15;B000000001;Amazon;R$ 10,00;;nao;;"
            f"jf7k9gad9;Livro Magalu;R$ 29,90;;nao;;{_MAGALU_LINK}\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", text, MemoriaPrevia())
                job = ImportacaoFila(payload)

                def resolve_magalu(_urls: list[str]) -> list[str]:
                    raise LinkQuebrado("O Aqui não encurtou o link.")

                def gravar(atual) -> str:
                    return "ok"

                while not job.done and not job.error:
                    avancar(
                        job,
                        resolve_amazon=lambda urls: [f"{urls[0]}?tag=promo"],
                        resolve_ml=lambda urls: urls,
                        resolve_magalu=resolve_magalu,
                        describe=lambda title, author="": "",
                        gravar=gravar,
                    )
                self.assertNotIn("jf7k9gad9", job.livros)
                self.assertEqual(job.slots_ids[0]["magalu"], "")
                quebrados = job.visao()["quebrados"]
                self.assertEqual(len(quebrados), 1)
                self.assertEqual(quebrados[0]["titulo"], "Livro Magalu")
            finally:
                catalog.close()
                board.close()

    def test_magalu_encurtamento_nao_chama_aqui_nas_outras_lojas(self) -> None:
        from unittest.mock import MagicMock, patch

        from promo_livros.fila_csv import ImportacaoFila, LinkQuebrado, avancar
        from promo_livros.magalu_links import MagaluConvertResult

        def resolve_magalu(urls: list[str]) -> list[str]:
            from promo_livros.aqui_links import create_short_link
            from promo_livros.magalu_links import convert_magalu

            out: list[str] = []
            for url in urls:
                got = convert_magalu(url, promoter_id="promo", partner_id="partner")
                if not got.ok:
                    raise LinkQuebrado(got.erro or "falhou")
                out.append(
                    create_short_link(
                        got.link_convertido,
                        api_key="aqui_key",
                        base_url="https://aqui.descontos.ai",
                    )
                )
            return out

        converted = (
            "https://www.magazineluiza.com.br/foo/divulgador/oferta/jf7k9gad9/?"
            "promoter_id=promo&partner_id=partner"
        )
        mock_convert = MagicMock(
            return_value=MagaluConvertResult(converted, "produto", True, ""),
        )
        mock_aqui = MagicMock(return_value="https://aqui.descontos.ai/xyz")

        text_magalu = (
            f"{_HEADER}\n"
            "10:15;B000000001;Amazon;R$ 10,00;;nao;;"
            f"jf7k9gad9;Livro Magalu;R$ 29,90;;nao;;{_MAGALU_LINK}\n"
        )
        text_sem_magalu = (
            f"{_HEADER_3}\n"
            "10:15;B000000001;Amazon;R$ 10,00;;nao;;;;;;;;;;"
            f"482840775.22595587888;Box;R$ 59,90;;nao;;{_SHOPEE_IMG};{_SHOPEE_LINK}\n"
        )

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                with patch("promo_livros.magalu_links.convert_magalu", mock_convert):
                    with patch("promo_livros.aqui_links.create_short_link", mock_aqui):
                        payload = previa_do_csv(
                            catalog, board, "2026-10-03", "09:00", "22:00", text_magalu, MemoriaPrevia()
                        )
                        job = ImportacaoFila(payload)
                        while not job.done and not job.error:
                            avancar(
                                job,
                                resolve_amazon=lambda urls: [f"{urls[0]}?tag=promo"],
                                resolve_ml=lambda urls: urls,
                                resolve_shopee=lambda urls: ["https://s.shopee.com.br/x"],
                                resolve_magalu=resolve_magalu,
                                describe=lambda title, author="": "",
                                gravar=lambda _atual: "ok",
                            )
                self.assertEqual(mock_convert.call_count, 1)
                self.assertEqual(mock_aqui.call_count, 1)
                self.assertEqual(job.livros["jf7k9gad9"]["url_final"], "https://aqui.descontos.ai/xyz")

                mock_convert.reset_mock()
                mock_aqui.reset_mock()
                with patch("promo_livros.magalu_links.convert_magalu", mock_convert):
                    with patch("promo_livros.aqui_links.create_short_link", mock_aqui):
                        payload = previa_do_csv(
                            catalog, board, "2026-10-03", "09:00", "22:00", text_sem_magalu, MemoriaPrevia()
                        )
                        job = ImportacaoFila(payload)
                        while not job.done and not job.error:
                            avancar(
                                job,
                                resolve_amazon=lambda urls: [f"{urls[0]}?tag=promo"],
                                resolve_ml=lambda urls: urls,
                                resolve_shopee=lambda urls: ["https://s.shopee.com.br/x"],
                                resolve_magalu=resolve_magalu,
                                describe=lambda title, author="": "",
                                gravar=lambda _atual: "ok",
                            )
                self.assertEqual(mock_convert.call_count, 0)
                self.assertEqual(mock_aqui.call_count, 0)
            finally:
                catalog.close()
                board.close()


_HEADER_EXTRA = (
    _HEADER + ";asin_2;titulo_2;preco_2;preco_de_2;menor_preco_365_2;cupom_2;imagem_2;link_2"
)


def _linha_extra(values: dict[str, str]) -> str:
    names = _HEADER_EXTRA.split(";")
    return ";".join(values.get(name, "") for name in names)


class MesmaLojaTests(unittest.TestCase):
    def test_duas_amazons_no_mesmo_horario_entram_no_post(self) -> None:
        text = _HEADER_EXTRA + "\n" + _linha_extra({
            "horario": "10:15",
            "asin": "B000000001",
            "titulo": "Shakespeare",
            "preco": "R$ 11,00",
            "preco_de": "R$ 20,00",
            "menor_preco_365": "sim",
            "asin_2": "B000000002",
            "titulo_2": "Cute Bears",
            "preco_2": "R$ 5,00",
            "preco_de_2": "R$ 24,00",
            "menor_preco_365_2": "sim",
        }) + "\n"
        rows = parse_fila_csv(text)
        self.assertEqual(rows[0]["amazon"]["asin"], "B000000001")
        self.assertEqual(rows[0]["extra"]["asin"], "B000000002")
        self.assertEqual(rows[0]["extra"]["store"], "amazon")
        self.assertIsNone(rows[0]["ml"])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                memoria = MemoriaPrevia()
                payload = previa_do_csv(catalog, board, "2026-10-03", "09:00", "22:00", text, memoria)
                self.assertEqual(payload["slots_ids"][0]["amazon"], "B000000001")
                self.assertEqual(payload["slots_ids"][0]["extra"], "B000000002")
                aplicar(
                    catalog,
                    board,
                    "2026-10-03",
                    payload["previa_id"],
                    memoria,
                    root / "cards",
                    download=_download,
                    resolve_urls=lambda urls: [f"{url}?tag=promo" if url else "" for url in urls],
                    describe=lambda title, author="": "Resenha curta.",
                )
                books = board.posts_for("2026-10-03")[0].books
                self.assertEqual([book.product_id for book in books], ["B000000001", "B000000002"])
                self.assertIn("Amazon:", board.posts_for("2026-10-03")[0].caption)
                self.assertIn("Cute Bears", board.posts_for("2026-10-03")[0].caption)
            finally:
                catalog.close()
                board.close()

    def test_segunda_oferta_sozinha_nao_exige_a_primeira(self) -> None:
        text = _HEADER_EXTRA + "\n" + _linha_extra({
            "horario": "10:15",
            "asin_2": "B000000009",
            "titulo_2": "Sozinho",
            "preco_2": "R$ 9,00",
            "menor_preco_365_2": "nao",
        }) + "\n"
        rows = parse_fila_csv(text)
        self.assertEqual(rows[0]["extra"]["asin"], "B000000009")
        self.assertIsNone(rows[0]["amazon"])

    def test_tres_ofertas_continuam_recusadas(self) -> None:
        with self.assertRaises(CatalogError) as erro:
            parse_fila_csv(
                _HEADER_EXTRA + "\n" + _linha_extra({
                    "horario": "10:15",
                    "asin": "B000000001",
                    "titulo": "Um",
                    "preco": "R$ 10,00",
                    "menor_preco_365": "nao",
                    "asin_ml": "MLB1111111",
                    "titulo_ml": "Dois",
                    "preco_ml": "R$ 20,00",
                    "menor_preco_365_ml": "nao",
                    "link_ml": _LINK,
                    "asin_2": "B000000003",
                    "titulo_2": "Tres",
                    "preco_2": "R$ 30,00",
                    "menor_preco_365_2": "nao",
                }) + "\n"
            )
        self.assertIn("duas ofertas", str(erro.exception))

    def test_a_pagina_explica_a_coluna_opcional(self) -> None:
        page = render_curation([], source="", folder_file="", notice=None)
        self.assertIn("asin_2", page)
        self.assertIn("mesma loja", page)
