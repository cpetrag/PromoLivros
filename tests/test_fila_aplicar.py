import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import Random

from PIL import Image

from promo_livros.board_store import BoardBook, BoardStore
from promo_livros.campaign_queue import CampaignQueueContext
from promo_livros.campaign_store import CampaignStore
from promo_livros.catalog import CatalogError, CatalogStore, parse_csv, publish_selection
from promo_livros.fila_aplicar import MemoriaPrevia, aplicar, desfazer, previa, reorganizar

_CSV = """posicao;titulo;autor;categoria;categoria_caminho;formato;preco;preco_de;menor_preco_365;badges;categoria_mais_vendido;asin;link
"1";"Shakespeare";"W";"";"";"";"R$ 11,00";"R$ 20,00";"sim";"";"";"B000000001";"https://www.amazon.com.br/dp/B000000001"
"2";"Cute Bears";"A";"";"";"";"R$ 5,00";"R$ 24,00";"sim";"";"";"B000000002";"https://www.amazon.com.br/dp/B000000002"
"3";"Declínio de um Homem";"O";"";"";"";"R$ 13,00";"R$ 20,00";"sim";"";"";"B000000003";"https://www.amazon.com.br/dp/B000000003"
"""


def _download(_url: str) -> Image.Image:
    return Image.new("RGB", (40, 60), (20, 20, 20))


class PreviaAplicarTests(unittest.TestCase):
    def test_previa_bloqueia_enviado_aplicar_e_desfazer(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                catalog.replace(parse_csv(_CSV), "amazon")
                catalog.set_picked("B000000001", True, "2026-10-02")
                catalog.set_picked("B000000002", True, "2026-10-02")
                publish_selection(
                    catalog, board, "2026-10-02", "07:00", root / "cards", download=_download
                )
                sent = next(post for post in board.posts_for("2026-10-02") if "Shakespeare" in post.books[0].title)
                board.mark_sent(sent.id)
                catalog.set_picked("B000000003", True, "2026-10-02")
                memoria = MemoriaPrevia()
                payload = previa(catalog, board, "2026-10-02", "15:12", "desc", memoria)
                ids = [
                    side["id"]
                    for slot in payload["slots"]
                    for side in (slot["amazon"], slot["ml"])
                    if side
                ]
                self.assertNotIn("B000000001", ids)
                self.assertIn("B000000001", [item["id"] for item in payload["bloqueados"]])
                self.assertEqual(payload["slots"][0]["amazon"]["title"], "Cute Bears")
                antes = [post.books[0].title for post in board.posts_for("2026-10-02")]
                with self.assertRaises(CatalogError):
                    aplicar(catalog, board, "2026-10-02", "", memoria, root / "cards", download=_download)
                notice = aplicar(
                    catalog,
                    board,
                    "2026-10-02",
                    payload["previa_id"],
                    memoria,
                    root / "cards",
                    download=_download,
                )
                self.assertIn("entraram", notice)
                atuais = [post.books[0].title for post in board.posts_for("2026-10-02")]
                self.assertNotIn("Shakespeare", atuais)
                self.assertEqual(desfazer(catalog, board, "2026-10-02"), "A fila anterior voltou.")
                restaurada = [post.books[0].title for post in board.posts_for("2026-10-02")]
                self.assertEqual(restaurada, antes)
            finally:
                catalog.close()
                board.close()

    def test_shopee_da_fila_aparece_na_previa_e_continua_ao_aplicar(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                catalog.replace(parse_csv(_CSV), "amazon")
                catalog.set_picked("B000000002", True, "2026-10-02")
                shopee_post = board.add_post(
                    day="2026-10-02",
                    clock="16:00",
                    caption="shopee",
                    image_path="",
                    books=[
                        BoardBook(
                            title="Dom Casmurro",
                            blurb="",
                            price_cents=1500,
                            list_price_cents=3000,
                            discount_pct=50,
                            lowest_label="",
                            url="https://s.shopee.com.br/abc123",
                            coupon="",
                            product_id="123456789.2233445566",
                        )
                    ],
                )
                board.set_image(shopee_post, f"data/cards/{shopee_post}.jpg")
                memoria = MemoriaPrevia()
                payload = previa(catalog, board, "2026-10-02", "15:12", "mine", memoria)
                self.assertEqual(payload["imagens"], {"123456789.2233445566": f"/cards/{shopee_post}.jpg"})
                shopee = [slot["shopee"] for slot in payload["slots"] if slot["shopee"]]
                self.assertEqual([item["id"] for item in shopee], ["123456789.2233445566"])
                self.assertTrue(all(slot["ml"] is None for slot in payload["slots"] if slot["shopee"]))
                aplicar(
                    catalog,
                    board,
                    "2026-10-02",
                    payload["previa_id"],
                    memoria,
                    root / "cards",
                    download=_download,
                )
                livros = [book for post in board.posts_for("2026-10-02") for book in post.books]
                self.assertIn("https://s.shopee.com.br/abc123", [book.url for book in livros])
                self.assertIn("Cute Bears", [book.title for book in livros])
            finally:
                catalog.close()
                board.close()

    def test_aplicar_recusa_quando_a_fila_muda(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                catalog.replace(parse_csv(_CSV), "amazon")
                catalog.set_picked("B000000002", True, "2026-10-02")
                memoria = MemoriaPrevia()
                payload = previa(catalog, board, "2026-10-02", "07:00", "mine", memoria)
                board.add_post(
                    day="2026-10-02",
                    clock="08:00",
                    caption="outro",
                    image_path="",
                    books=[
                        BoardBook(
                            title="Outro",
                            blurb="",
                            price_cents=1000,
                            list_price_cents=2000,
                            discount_pct=50,
                            lowest_label="",
                            url="https://www.amazon.com.br/dp/B000000009",
                            coupon="",
                            product_id="B000000009",
                        )
                    ],
                )
                with self.assertRaises(CatalogError):
                    aplicar(
                        catalog,
                        board,
                        "2026-10-02",
                        payload["previa_id"],
                        memoria,
                        root / "cards",
                        download=_download,
                    )
            finally:
                catalog.close()
                board.close()

    def test_reorganizar_passa_magalu_para_montar_fila(self) -> None:
        _MAGALU_ROW = (
            "posicao;asin;titulo;preco;preco_de;link;imagem;menor_preco_365;categoria;autor\n"
            "1;jf7k9gad9;Livro Magalu;R$ 29,90;R$ 49,90;"
            "https://www.magazineluiza.com.br/livro/p/jf7k9gad9/sku/;;;;\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = CatalogStore(root / "board.sqlite")
            board = BoardStore(root / "board.sqlite")
            try:
                catalog.replace(parse_csv(_CSV), "amazon")
                catalog.replace_magalu(parse_csv(_MAGALU_ROW), "magalu.csv")
                catalog.set_picked("B000000002", True, "2026-10-02")
                catalog.set_ml_picked("jf7k9gad9", True, "2026-10-02")
                publish_selection(
                    catalog, board, "2026-10-02", "07:00", root / "cards", download=_download
                )
                reorganizar(catalog, board, "2026-10-02", "15:12", root / "cards", download=_download)
                magalu = [
                    book
                    for post in board.posts_for("2026-10-02")
                    for book in post.books
                    if "magazineluiza" in book.url
                ]
                self.assertEqual(len(magalu), 1)
                self.assertEqual(magalu[0].title, "Livro Magalu")
            finally:
                catalog.close()
                board.close()


class ReorganizarComCampanhaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.root = Path(self._folder.name)
        path = self.root / "board.sqlite"
        self.catalog = CatalogStore(path)
        self.board = BoardStore(path)
        self.addCleanup(self.catalog.close)
        self.addCleanup(self.board.close)

    def _campaign_post(self, clock: str) -> int:
        return self.board.add_campaign_post(
            "2026-10-02",
            clock,
            campaign_id=3,
            image_id=4,
            text_id=5,
            caption="Convite",
            image_path="data/campaigns/3/a.jpg",
            locked_at="2026-10-02T08:00:00-03:00",
        )

    def _reorganize(self) -> str:
        return reorganizar(self.catalog, self.board, "2026-10-02", "15:12", self.root / "cards", download=_download)

    def _publish_books(self) -> None:
        self.catalog.replace(parse_csv(_CSV), "amazon")
        self.catalog.set_picked("B000000002", True, "2026-10-02")
        publish_selection(self.catalog, self.board, "2026-10-02", "07:00", self.root / "cards", download=_download)

    def test_reorganizar_keeps_campaign_posts_with_same_content_and_free_their_clock(self) -> None:
        self._publish_books()
        from promo_livros.fila import horarios_livres

        schedule = self.board.send_schedule()
        reserved = horarios_livres(schedule.start, schedule.end, schedule.post_interval_minutes, "15:12")[0]
        self._campaign_post(reserved)

        self._reorganize()

        posts = self.board.posts_for("2026-10-02")
        campaigns = [post for post in posts if post.post_kind == "campaign"]
        self.assertEqual(len(campaigns), 1)
        self.assertEqual(
            (campaigns[0].clock, campaigns[0].campaign_id, campaigns[0].image_id, campaigns[0].text_id),
            (reserved, 3, 4, 5),
        )
        self.assertEqual(campaigns[0].caption, "Convite")
        self.assertEqual(campaigns[0].image_path, "data/campaigns/3/a.jpg")
        book_clocks = [post.clock for post in posts if post.post_kind != "campaign"]
        self.assertNotIn(reserved, book_clocks)
        self.assertTrue(book_clocks)

    def test_only_campaign_posts_left_is_not_reported_as_window_closed(self) -> None:
        post_id = self._campaign_post("16:00")

        notice = self._reorganize()

        self.assertNotIn("janela", notice.lower())
        self.assertIn("campanha", notice.lower())
        self.assertEqual([post.id for post in self.board.posts_for("2026-10-02")], [post_id])

    def test_undo_after_reorganizar_brings_campaign_posts_back(self) -> None:
        self._publish_books()
        self._campaign_post("16:00")
        self._reorganize()

        desfazer(self.catalog, self.board, "2026-10-02")

        kinds = sorted(post.post_kind for post in self.board.posts_for("2026-10-02"))
        self.assertEqual(kinds.count("campaign"), 1)


_DAY = "2026-10-02"
_NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone(timedelta(hours=-3)))
_STAMP = "2026-10-02T09:00:00-03:00"


def _campaign_slot(clock: str) -> dict:
    return {"clock": clock, "amazon": "", "ml": "", "shopee": "", "magalu": "", "extra": "", "is_campaign": True}


class MontagemCampanhaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.root = Path(self._folder.name)
        path = self.root / "board.sqlite"
        self.catalog = CatalogStore(path)
        self.board = BoardStore(path)
        self.campaigns = CampaignStore(path)
        self.addCleanup(self.catalog.close)
        self.addCleanup(self.board.close)
        self.addCleanup(self.campaigns.close)
        self.context = CampaignQueueContext(self.campaigns, Random(7), lambda: _NOW)

    def _ready_campaign(self, name: str, images: int = 1, texts: int = 1) -> int:
        campaign_id = self.campaigns.create(name)
        for number in range(images):
            self.campaigns.add_image(campaign_id, f"data/campaigns/{campaign_id}/{number}.jpg")
        for number in range(texts):
            self.campaigns.add_text(campaign_id, f"{name} texto {number}")
        return campaign_id

    def _mount(self, slots: list[dict]) -> str:
        return publish_selection(
            self.catalog,
            self.board,
            _DAY,
            "00:00",
            self.root / "cards",
            download=_download,
            slots_fixos=slots,
            campaign_context=self.context,
        )

    def _campaign_ids(self) -> list[int | None]:
        return [post.campaign_id for post in self.board.posts_for(_DAY)]

    def test_mount_assigns_rotating_campaigns_in_order(self) -> None:
        first = self._ready_campaign("Primeira")
        second = self._ready_campaign("Segunda")
        self._mount([_campaign_slot("11:00"), _campaign_slot("10:00")])
        posts = self.board.posts_for(_DAY)
        self.assertEqual([post.clock for post in posts], ["10:00", "11:00"])
        self.assertEqual([post.campaign_id for post in posts], [first, second])
        for post in posts:
            self.assertEqual(post.post_kind, "campaign")
            self.assertEqual(post.books, ())
            self.assertEqual(post.campaign_locked_at, _STAMP)
            self.assertTrue(post.image_path.startswith(f"data/campaigns/{post.campaign_id}/"))
            self.assertIn("texto", post.caption)
            self.assertIsNotNone(post.image_id)
            self.assertIsNotNone(post.text_id)

    def test_mount_continues_rotation_after_last_used_campaign(self) -> None:
        first = self._ready_campaign("Primeira")
        second = self._ready_campaign("Segunda")
        third = self._ready_campaign("Terceira")
        sent_id = self.board.add_campaign_post(
            _DAY, "08:00", campaign_id=first, image_id=1, text_id=1, locked_at="2026-10-02T07:00:00-03:00"
        )
        self.board.mark_sent(sent_id)
        self._mount([_campaign_slot("10:00"), _campaign_slot("11:00"), _campaign_slot("12:00")])
        pending = [post for post in self.board.posts_for(_DAY) if post.clock >= "10:00"]
        self.assertEqual([post.campaign_id for post in pending], [second, third, first])

    def test_mount_again_does_not_advance_rotation_with_replaced_posts(self) -> None:
        first = self._ready_campaign("Primeira")
        second = self._ready_campaign("Segunda")
        self._ready_campaign("Terceira")
        slots = [_campaign_slot("10:00"), _campaign_slot("11:00")]
        self._mount(slots)
        self._mount(slots)
        self.assertEqual(self._campaign_ids(), [first, second])

    def test_mount_avoids_repeating_photo_and_text_for_the_same_campaign(self) -> None:
        only = self._ready_campaign("Unica", images=2, texts=2)
        self._mount([_campaign_slot("10:00"), _campaign_slot("11:00")])
        first, second = self.board.posts_for(_DAY)
        self.assertEqual((first.campaign_id, second.campaign_id), (only, only))
        self.assertNotEqual(first.image_id, second.image_id)
        self.assertNotEqual(first.text_id, second.text_id)

    def test_empty_rotating_pool_creates_empty_campaign_post_with_warning(self) -> None:
        notice = self._mount([_campaign_slot("10:00")])
        (post,) = self.board.posts_for(_DAY)
        self.assertEqual(post.post_kind, "campaign")
        self.assertIsNone(post.campaign_id)
        self.assertEqual((post.caption, post.image_path), ("", ""))
        self.assertIn("10:00: sem campanha rotativa pronta", notice)

    def test_fixed_clock_campaigns_are_not_used_by_the_rotation(self) -> None:
        fixed = self._ready_campaign("Fixa")
        self.campaigns.set_schedule(fixed, "13:00", None)
        self._mount([_campaign_slot("10:00")])
        self.assertEqual(self._campaign_ids(), [None])

    def test_book_and_campaign_slots_share_one_queue(self) -> None:
        self.catalog.replace(parse_csv(_CSV), "amazon")
        self.catalog.set_picked("B000000002", True, _DAY)
        campaign = self._ready_campaign("Primeira")
        notice = self._mount(
            [
                {"clock": "10:00", "amazon": "B000000002", "ml": "", "shopee": "", "magalu": "", "extra": ""},
                _campaign_slot("11:00"),
            ]
        )
        book_post, campaign_post = self.board.posts_for(_DAY)
        self.assertEqual(book_post.books[0].title, "Cute Bears")
        self.assertEqual(book_post.post_kind, "book")
        self.assertEqual(campaign_post.campaign_id, campaign)
        self.assertIn("1 livros e 1 campanhas entraram", notice)

    def test_campaign_slot_without_campaign_context_is_refused(self) -> None:
        with self.assertRaises(CatalogError):
            publish_selection(
                self.catalog,
                self.board,
                _DAY,
                "00:00",
                self.root / "cards",
                download=_download,
                slots_fixos=[_campaign_slot("10:00")],
            )
        self.assertEqual(self.board.posts_for(_DAY), [])

    def test_aplicar_and_desfazer_restore_campaign_posts(self) -> None:
        self.catalog.replace(parse_csv(_CSV), "amazon")
        self.catalog.set_picked("B000000002", True, _DAY)
        campaign = self._ready_campaign("Primeira")
        self._mount([_campaign_slot("10:00")])
        before = [(post.clock, post.campaign_id, post.caption) for post in self.board.posts_for(_DAY)]
        memoria = MemoriaPrevia()
        payload = previa(self.catalog, self.board, _DAY, "00:00", "mine", memoria)
        aplicar(
            self.catalog,
            self.board,
            _DAY,
            payload["previa_id"],
            memoria,
            self.root / "cards",
            download=_download,
            campaign_context=self.context,
        )
        self.assertEqual(desfazer(self.catalog, self.board, _DAY), "A fila anterior voltou.")
        restored = self.board.posts_for(_DAY)
        self.assertEqual([(post.clock, post.campaign_id, post.caption) for post in restored], before)
        self.assertEqual(restored[0].campaign_id, campaign)
        self.assertEqual(restored[0].post_kind, "campaign")
        self.assertIsNotNone(restored[0].campaign_locked_at)


if __name__ == "__main__":
    unittest.main()
