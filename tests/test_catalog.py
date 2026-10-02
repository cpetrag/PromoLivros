import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image

from promo_livros.board_store import BoardStore
from promo_livros.catalog import (
    CatalogError,
    CatalogStore,
    cached_ml_cover,
    capture_clock,
    fill_blurbs,
    parse_csv,
    publish_selection,
)
from promo_livros.dashboard_curation import render_curation

_CSV = """posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;menor_preco_365;badges;categoria_mais_vendido;asin;link
"1";"Memórias do subsolo";"Fiódor";"Literatura Clássica";"Livros > Literatura e Ficção";"Capa Comum";"R$ 11,12";"R$ 19,90";"sim";"Menor preço em 365 dias";"";"6550974119";"https://www.amazon.com.br/dp/6550974119"
"2";"O Pequeno Príncipe";"Antoine";"Fantasia";"Livros > Infantil > Fantasia";"Capa Comum";"R$ 9,37";"R$ 19,90";"sim";"Oferta";"";"6598849306";"https://www.amazon.com.br/dp/6598849306"
"3";"Tao te Ching";"Lao Tzu";"Literatura e Ficção";"Livros > Literatura e Ficção";"Capa Comum";"R$ 8,91";"R$ 21,99";"nao";"Oferta";"";"6558882094";"https://www.amazon.com.br/dp/6558882094"
"""


class CatalogTests(unittest.TestCase):
    def test_a_new_csv_drops_the_pick_and_the_page_can_filter_the_badge(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = CatalogStore(Path(folder) / "board.sqlite")
            store.replace(parse_csv(_CSV), "amazon_livros_2026-09-29.csv")
            store.set_picked("6558882094", True)
            store.replace(parse_csv(_CSV), "de novo")
            self.assertEqual(store.picked(), [])
            kept = [book for book in store.books() if book.asin == "6558882094"]
            self.assertEqual(kept[0].category, "Literatura e Ficção")
            self.assertFalse(kept[0].low_365)
            page = render_curation(store.books(), source="de novo", folder_file="amazon_livros_2026-09-29.csv", notice=None)
            self.assertIn("Só menor preço em 365 dias", page)
            self.assertIn(">Lista</button>", page)
            self.assertIn("Minutos entre posts", page)
            self.assertIn('class="pick"', page)
            self.assertIn("Memórias do subsolo", page)
            self.assertIn("R$ 11,12", page)
            self.assertIn("−44%", page)
            self.assertIn('data-low="0"', page)
            store.close()

    def test_a_new_day_drops_the_marks_and_the_same_day_keeps_them(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = CatalogStore(Path(folder) / "board.sqlite")
            try:
                store.replace(parse_csv(_CSV), "amazon")
                store.set_picked("6550974119", True)
                self.assertEqual(store.begin_day("2026-09-30"), 1)
                self.assertEqual(store.picked_total(), 0)
                store.set_picked("6550974119", True)
                self.assertEqual(store.begin_day("2026-09-30"), 0)
                self.assertEqual([book.asin for book in store.picked()], ["6550974119"])
                self.assertEqual(store.begin_day("2026-10-01"), 1)
                self.assertEqual(store.picked(), [])
                store.replace(parse_csv(_CSV), "amazon")
                store.set_picked("6550974119", True)
                self.assertGreater(store.annotate_kids(parse_csv(_CSV)), 0)
                self.assertEqual([book.asin for book in store.picked()], ["6550974119"])
                by_asin = {book.asin: book.kids for book in store.books()}
                self.assertTrue(by_asin["6598849306"])
                self.assertFalse(by_asin["6550974119"])
            finally:
                store.close()

    def test_the_queue_follows_the_order_the_books_were_marked(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            catalog.replace(parse_csv(_CSV), "arquivo")
            # O segundo livro do CSV é marcado primeiro: a fila segue o clique, não a posição.
            catalog.set_picked("6598849306", True)
            catalog.set_picked("6550974119", True)

            def download(_url: str) -> Image.Image:
                return Image.new("RGB", (40, 60), (20, 20, 20))

            notice = publish_selection(
                catalog,
                board,
                "2026-09-29",
                "07:00",
                root / "cards",
                download=download,
            )
            posts = board.posts_for("2026-09-29")
            self.assertEqual([post.books[0].title for post in posts], ["O Pequeno Príncipe", "Memórias do subsolo"])
            self.assertIn("2 livros entraram", notice)
            self.assertTrue((root / "cards" / f"{posts[0].id}.jpg").is_file())
            catalog.close()
            board.close()

    def test_moving_a_pick_changes_which_books_share_a_post(self) -> None:
        ml = """posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;menor_preco_365;badges;categoria_mais_vendido;asin;link
"1";"Capitães da Areia";"Jorge Amado";"Português";"Livros";"Livro físico";"R$ 19,00";"R$ 39,00";"";"";"";"MLB1111111";"https://produto.mercadolivre.com.br/MLB-1111111"
"2";"Gabriela";"Jorge Amado";"Português";"Livros";"Livro físico";"R$ 25,00";"R$ 40,00";"";"";"";"MLB2222222";"https://produto.mercadolivre.com.br/MLB-2222222"
"""
        from promo_livros.pick_plan import plan_rows

        with tempfile.TemporaryDirectory() as folder:
            catalog = CatalogStore(Path(folder) / "board.sqlite")
            try:
                catalog.replace(parse_csv(_CSV), "amazon")
                catalog.replace_ml(parse_csv(ml), "mercadolivre-livros.csv")
                catalog.set_picked("6550974119", True)
                catalog.set_picked("6598849306", True)
                catalog.set_ml_picked("MLB1111111", True)
                catalog.set_ml_picked("MLB2222222", True)
                clocks = ["08:00", "08:40"]
                rows = plan_rows(catalog.picked(), catalog.ml_picked(), clocks)
                self.assertEqual(
                    [(row["amazon"]["title"], row["ml"]["title"]) for row in rows],
                    [
                        ("Memórias do subsolo", "Capitães da Areia"),
                        ("O Pequeno Príncipe", "Gabriela"),
                    ],
                )
                self.assertTrue(catalog.move_pick("MLB2222222", "ml", -1))
                moved = plan_rows(catalog.picked(), catalog.ml_picked(), clocks)
                self.assertEqual(
                    [(row["amazon"]["title"], row["ml"]["title"]) for row in moved],
                    [
                        ("Memórias do subsolo", "Gabriela"),
                        ("O Pequeno Príncipe", "Capitães da Areia"),
                    ],
                )
                self.assertFalse(catalog.move_pick("MLB2222222", "ml", -1))
            finally:
                catalog.close()

    def test_a_matching_mercado_livre_listing_adds_the_second_link(self) -> None:
        ml = """posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;menor_preco_365;badges;categoria_mais_vendido;asin;link
"1";"Memórias do subsolo - Dostoiévski";"Fiódor";"Português";"Livros";"Livro físico";"R$ 19,00";"R$ 39,00";"";"52% OFF";"";"MLB4493446393";"https://www.mercadolivre.com.br/memorias/p/MLB4493446393?pdp_filters=discount"
"2";"Outro livro só de lá";"";"Português";"Livros";"Livro físico";"R$ 10,00";"R$ 20,00";"";"50% OFF";"";"MLB12345678";"https://produto.mercadolivre.com.br/MLB-12345678"
"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            catalog.replace(parse_csv(_CSV), "amazon")
            catalog.replace_ml(parse_csv(ml), "mercadolivre-livros.csv")
            catalog.set_picked("6550974119", True)
            catalog.set_ml_picked("MLB12345678", True)
            page = render_curation(
                catalog.books(),
                source="amazon",
                folder_file="amazon.csv",
                notice=None,
                store="amazon",
                peers={"6550974119": "Existe no Mercado Livre · R$ 19,00"},
                marked=catalog.picked_total(),
            )
            self.assertIn("Mercado Livre", page)
            self.assertIn("Existe no Mercado Livre", page)
            self.assertEqual(catalog.picked_total(), 2)

            def download(_url: str) -> Image.Image:
                return Image.new("RGB", (40, 60), (20, 20, 20))

            def resolve_ml(urls: list[str]) -> list[str]:
                return ["https://meli.la/" + url.rsplit("/", 1)[-1] for url in urls]

            def describe(title: str, author: str) -> str:
                return "Um clássico sobre a consciência de um homem isolado."

            publish_selection(
                catalog,
                board,
                "2026-09-29",
                "07:00",
                root / "cards",
                download=download,
                resolve_ml=resolve_ml,
                thumbnail=lambda _item: None,
                describe=describe,
            )
            posts = board.posts_for("2026-09-29")
            self.assertEqual(len(posts), 1)
            first = posts[0]
            self.assertEqual(
                [book.title for book in first.books],
                ["Memórias do subsolo", "Outro livro só de lá"],
            )
            self.assertIn("🔗 Amazon:", first.caption)
            self.assertIn("🔗 Mercado Livre:", first.caption)
            self.assertIn("https://meli.la/MLB-12345678", first.caption)
            self.assertNotIn("Memórias do subsolo - Dostoiévski", first.caption)
            self.assertNotIn("4493446393", first.caption)
            self.assertNotIn("pdp_filters", first.caption)
            review = "ℹ️ _Um clássico sobre a consciência de um homem isolado._"
            self.assertEqual(first.caption.count(review), 2)
            catalog.close()
            board.close()

    def test_a_later_review_fills_the_caption_of_an_unsent_post(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                catalog.replace(parse_csv(_CSV), "arquivo")
                catalog.set_picked("6550974119", True)

                def download(_url: str) -> Image.Image:
                    return Image.new("RGB", (40, 60), (20, 20, 20))

                publish_selection(catalog, board, "2026-09-29", "07:00", root / "cards", download=download)
                before = board.posts_for("2026-09-29")[0]
                self.assertNotIn("Um homem isolado", before.caption)
                filled = fill_blurbs(board, lambda title, author: "Um homem isolado encara a própria consciência.")
                self.assertEqual(filled, 1)
                after = board.posts_for("2026-09-29")[0]
                self.assertIn("ℹ️ _Um homem isolado encara a própria consciência._", after.caption)
                self.assertEqual(fill_blurbs(board, lambda title, author: "Outra frase que não deve entrar."), 0)
            finally:
                catalog.close()
                board.close()

    def test_empty_selection_does_not_raise_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            catalog.replace(parse_csv(_CSV), "arquivo")
            with self.assertRaises(CatalogError):
                publish_selection(catalog, board, "2026-09-29", "07:00", root / "cards")
            catalog.close()
            board.close()


class MercadoLivreCoverTests(unittest.TestCase):
    def test_card_uses_the_amazon_cover_until_the_session_exists(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            catalog = CatalogStore(Path(folder) / "board.sqlite")
            catalog.replace_ml(
                parse_csv(
                    "posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;menor_preco_365;badges;categoria_mais_vendido;asin;link\n"
                    '"1";"Memórias do subsolo";"";"";"";"";"R$ 19,00";"";"";"";"";"MLB4493446393";"https://produto.mercadolivre.com.br/MLB-4493446393"\n'
                ),
                "mercadolivre-livros.csv",
            )
            book = catalog.ml_books()[0]
            page = render_curation(
                [book],
                source="ml",
                folder_file="mercadolivre-livros.csv",
                notice=None,
                store="ml",
                covers={book.asin: "https://m.media-amazon.com/images/P/6550974119.jpg"},
            )
            self.assertIn("https://m.media-amazon.com/images/P/6550974119.jpg", page)
            self.assertNotIn(f'src="/curadoria/capa/{book.asin}.jpg"', page)
            self.assertIn("Configurações", page)
            catalog.close()

    def test_a_missing_cover_is_not_saved(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("promo_livros.catalog.thumbnail_url", return_value=None):
                with self.assertRaises(CatalogError):
                    cached_ml_cover(root, "MLB4493446393")
            self.assertEqual(list(root.glob("*.jpg")), [])

    def test_the_csv_picture_is_the_cover_and_a_foreign_url_is_dropped(self) -> None:
        header = (
            "posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;"
            "menor_preco_365;badges;categoria_mais_vendido;asin;link;imagem\n"
        )
        picture = "https://http2.mlstatic.com/D_Q_NP_2X_719889-MLB110799756479_042026-E.webp"
        rows = (
            header
            + f'"1";"Dom Casmurro";"";"";"";"";"R$ 19,00";"R$ 39,00";"";"";"";"MLB4493446393";"https://produto.mercadolivre.com.br/MLB-4493446393";"{picture}"\n'
            + '"2";"Outro";"";"";"";"";"R$ 9,00";"";"";"";"";"MLB12345678";"https://produto.mercadolivre.com.br/MLB-12345678";"https://evil.test/x.jpg"\n'
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            try:
                catalog.replace_ml(parse_csv(rows), "mercadolivre-livros.csv")
                books = {book.asin: book for book in catalog.ml_books()}
                self.assertEqual(books["MLB4493446393"].image_url, picture)
                self.assertEqual(books["MLB12345678"].image_url, "")
                self.assertEqual(catalog.ml_image("MLB4493446393"), picture)
                page = render_curation(
                    list(books.values()),
                    source="ml",
                    folder_file="mercadolivre-livros.csv",
                    notice=None,
                    store="ml",
                )
                self.assertIn(f'src="{picture}"', page)
                self.assertNotIn("evil.test", page)

                seen = []

                def download(url: str) -> Image.Image:
                    seen.append(url)
                    return Image.new("RGB", (40, 60), (20, 20, 20))

                with patch("promo_livros.catalog.thumbnail_url", return_value=None):
                    payload = cached_ml_cover(root / "covers", "MLB4493446393", download, image_url=picture)
                self.assertTrue(payload)
                self.assertEqual(seen, [picture])
            finally:
                catalog.close()


class CurationFilterTests(unittest.TestCase):
    def test_cards_carry_the_numbers_the_sort_needs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            catalog = CatalogStore(Path(folder) / "board.sqlite")
            try:
                catalog.replace(parse_csv(_CSV), "amazon")
                page = render_curation(
                    catalog.books(),
                    source="amazon",
                    folder_file="amazon.csv",
                    notice=None,
                )
            finally:
                catalog.close()
        self.assertIn('id="sort-by"', page)
        self.assertIn('value="discount">Maior desconto', page)
        self.assertIn('value="price-asc">Menor preço', page)
        self.assertIn('id="min-discount"', page)
        self.assertIn('id="max-price"', page)
        self.assertIn('id="only-picked"', page)
        self.assertIn('id="hide-kids"', page)
        self.assertIn('data-kids="1"', page)
        self.assertIn('data-kids="0"', page)
        self.assertIn('href="https://www.amazon.com.br/dp/6550974119"', page)
        self.assertIn(">Ver produto</a>", page)
        self.assertIn('data-price="1112"', page)
        self.assertIn('data-discount="44"', page)
        self.assertIn('data-savings="878"', page)
        self.assertIn('data-pos="1"', page)
        self.assertIn('<option value="Literatura Clássica">Literatura Clássica (1)</option>', page)


class CaptureClockTests(unittest.TestCase):
    """O código procura um meta do crawler na pasta pessoal; aqui ela aponta para a pasta do teste."""

    def setUp(self) -> None:
        self._home = tempfile.TemporaryDirectory()
        patcher = patch("promo_livros.catalog.Path.home", return_value=Path(self._home.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._home.cleanup)

    def test_the_crawler_clock_wins_over_the_file_time(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            csv_path = root / "amazon_livros_2026-09-29.csv"
            csv_path.write_text("asin\n", encoding="utf-8")
            moment = datetime(2026, 9, 29, 12, 0, tzinfo=ZoneInfo("UTC"))
            os.utime(csv_path, (moment.timestamp(), moment.timestamp()))
            (root / "amazon-livros-1000-meta.json").write_text(
                '{"finished_utc": "2026-09-29T10:49:51+00:00",'
                ' "source_rich_reuse": "/tmp/amazon_livros_2026-09-29.csv"}',
                encoding="utf-8",
            )
            (root / "outro-meta.json").write_text(
                '{"finished_utc": "2026-01-01T00:00:00+00:00", "csv": "/tmp/outro.csv"}',
                encoding="utf-8",
            )
            self.assertEqual(capture_clock(csv_path), "29/09/2026 às 07:49")

    def test_without_a_meta_the_file_time_is_the_capture(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "mercadolivre-livros.csv"
            csv_path.write_text("asin\n", encoding="utf-8")
            moment = datetime(2026, 9, 29, 20, 6, tzinfo=ZoneInfo("America/Sao_Paulo"))
            os.utime(csv_path, (moment.timestamp(), moment.timestamp()))
            self.assertEqual(capture_clock(csv_path), "29/09/2026 às 20:06")

    def test_the_page_shows_the_capture_next_to_the_file(self) -> None:
        page = render_curation(
            [],
            source="amazon.csv",
            folder_file="amazon_livros_2026-09-29.csv",
            notice=None,
            captured="29/09/2026 às 07:49",
        )
        self.assertIn('class="captured">Capturado em 29/09/2026 às 07:49</span>', page)
        self.assertIn("Na pasta: amazon_livros_2026-09-29.csv", page)


if __name__ == "__main__":
    unittest.main()
