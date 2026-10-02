import tempfile
import unittest
from pathlib import Path

from PIL import Image

from promo_livros.board_store import BoardStore
from promo_livros.day_cut import clocks, from_keepa, passes, post_sizes, rank_passers, take_with_infantil_cap
from promo_livros.send_schedule import plan_day_clocks
from promo_livros.morning import begin_day, finish_day, write_board


def _product(price: int, avg90: int, low: int, rank: int) -> dict:
    return {
        "asin": "B000",
        "stats": {
            "current": [price, -1, -1, rank],
            "avg90": [avg90],
            "minInInterval": [[0, low]],
        },
    }


class CutTests(unittest.TestCase):
    def test_rejects_junk_and_a_small_drop(self) -> None:
        row = {"asin": "B000", "titulo": "Livro de colorir", "preco": "10", "preco_de": "40", "desconto_pct": "75", "url": "https://example"}
        item = from_keepa(row, _product(1000, 2000, 1000, 100), 1)
        self.assertFalse(passes(item))
        plain = from_keepa({**row, "titulo": "Dom Casmurro"}, _product(1000, 2000, 1000, 100), 3)
        self.assertTrue(passes(plain))
        weak = from_keepa({**row, "titulo": "Dom Casmurro"}, _product(1900, 2000, 1900, 100), 2)
        self.assertFalse(passes(weak))

    def test_ranks_by_place_and_drop(self) -> None:
        first = from_keepa(
            {"asin": "A", "titulo": "Primeiro", "preco": "10", "preco_de": "40", "desconto_pct": "75", "url": "u"},
            _product(1000, 2000, 1000, 100),
            1,
        )
        second = from_keepa(
            {"asin": "B", "titulo": "Segundo", "preco": "10", "preco_de": "80", "desconto_pct": "80", "url": "u"},
            _product(1000, 5000, 1000, 100),
            40,
        )
        ranked = rank_passers([second, first])
        self.assertEqual(ranked[0]["asin"], "A")

    def test_infantil_stays_under_a_tenth_of_the_day(self) -> None:
        kids = {
            "asin": "K",
            "titulo": "Turma da Mônica",
            "categoria": "Infantil e infantojuvenil",
            "lugar_vitrine": 1,
            "queda_vs_media": 40,
        }
        adult = {
            "asin": "A",
            "titulo": "Dom Casmurro",
            "categoria": "Literatura e Ficção",
            "lugar_vitrine": 30,
            "queda_vs_media": 20,
        }
        ranked = [{**kids, "asin": f"K{index}"} for index in range(8)]
        ranked.extend({**adult, "asin": f"A{index}"} for index in range(12))
        picked = take_with_infantil_cap(ranked, 10)
        infantil = [item for item in picked if "Infantil" in item["categoria"]]
        self.assertEqual(len(picked), 10)
        self.assertEqual(len(infantil), 1)

    def test_category_comes_from_the_keepa_tree(self) -> None:
        product = _product(1000, 2000, 1000, 100)
        product["categoryTree"] = [
            {"name": "Livros"},
            {"name": "Infantil e infantojuvenil"},
        ]
        item = from_keepa(
            {"asin": "B000", "titulo": "O Pequeno Príncipe", "preco": "10", "preco_de": "40", "desconto_pct": "75", "url": "u"},
            product,
            1,
        )
        self.assertEqual(item["categoria"], "Infantil e infantojuvenil")

    def test_one_book_per_post_up_to_five_an_hour(self) -> None:
        self.assertEqual(post_sizes(36), [1] * 36)
        self.assertEqual(post_sizes(80), [1] * 60)
        times = plan_day_clocks("08:00", 36)
        self.assertEqual(times[0], "08:00")
        self.assertEqual(times[1], "08:20")
        self.assertEqual(times[-1], "19:40")
        full = plan_day_clocks("08:00", 80)
        self.assertEqual(len(full), 60)
        self.assertEqual(full[1], "08:12")
        self.assertEqual(full[-1], "19:48")

    def test_a_single_leftover_still_gets_a_post(self) -> None:
        self.assertEqual(post_sizes(1), [1])
        self.assertEqual(clocks(1), ["08:00"])

    def test_window_and_interval_belong_to_the_saved_schedule(self) -> None:
        from promo_livros.send_schedule import parse_schedule, slot_clocks, write_group_gap

        schedule = parse_schedule("09:00", "12:00", "60", "30")
        self.assertEqual(slot_clocks(schedule), ["09:00", "10:00", "11:00"])
        with self.assertRaises(ValueError):
            parse_schedule("08:00", "22:00", "5", "45")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.yaml"
            path.write_text("whatsapp:\n  enabled: false\n  gap_seconds: 45\nwebsite:\n  enabled: false\n", encoding="utf-8")
            write_group_gap(path, 30)
            text = path.read_text(encoding="utf-8")
            self.assertIn("gap_seconds: 30", text)
            self.assertEqual(text.count("enabled: false"), 2)
            store = BoardStore(Path(folder) / "board.sqlite")
            store.save_send_schedule(schedule)
            store.add_post(
                day="2026-09-28",
                clock="08:00",
                caption="a",
                image_path="",
                books=[_book("A")],
            )
            store.add_post(
                day="2026-09-28",
                clock="08:40",
                caption="b",
                image_path="",
                books=[_book("B")],
            )
            self.assertEqual(store.retime_day("2026-09-28", slot_clocks(schedule)), 2)
            self.assertEqual([post.clock for post in store.posts_for("2026-09-28")], ["09:00", "10:00"])
            store.close()

    def test_repack_keeps_missed_posts_on_the_clocks_still_ahead(self) -> None:
        from promo_livros.send_schedule import parse_schedule, repack_clocks

        schedule = parse_schedule("08:00", "22:00", "40", "45")
        clocks, late = repack_clocks(schedule, "09:17", 21)
        self.assertEqual(clocks[0], "09:20")
        self.assertEqual(clocks[18], "21:20")
        self.assertEqual(late, 2)
        self.assertEqual(clocks[19:], ["22:00", "22:40"])
        early, none_late = repack_clocks(schedule, "07:00", 2)
        self.assertEqual(early, ["08:00", "08:40"])
        self.assertEqual(none_late, 0)
        closed, left = repack_clocks(schedule, "22:00", 3)
        self.assertEqual(closed, [])
        self.assertEqual(left, 3)


class IntervalSaveTests(unittest.TestCase):
    def test_saving_intervals_keeps_the_clocks_already_on_the_queue(self) -> None:
        from promo_livros.dashboard import apply_interval_save
        from promo_livros.send_schedule import parse_schedule

        with tempfile.TemporaryDirectory() as folder:
            store = BoardStore(Path(folder) / "board.sqlite")
            store.add_post(
                day="2026-09-28",
                clock="16:40",
                caption="tarde",
                image_path="",
                books=[_book("Tarde")],
            )
            store.add_post(
                day="2026-09-28",
                clock="17:20",
                caption="noite",
                image_path="",
                books=[_book("Noite")],
            )
            notice = apply_interval_save(store, "2026-09-28", parse_schedule("08:00", "23:40", "40", "45"))
            self.assertEqual([post.clock for post in store.posts_for("2026-09-28")], ["16:40", "17:20"])
            self.assertEqual(store.send_schedule().end, "23:40")
            self.assertIn("continuam nos horários atuais", notice)
            store.close()


class MorningGuardTests(unittest.TestCase):
    def test_skips_a_finished_day_and_retries_a_broken_one(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = BoardStore(Path(folder) / "board.sqlite")
            self.assertEqual(begin_day(store, "2026-09-28"), "build")
            store.add_post(
                day="2026-09-28",
                clock="08:00",
                caption="parcial",
                image_path="",
                books=[_book("Parcial")],
            )
            self.assertEqual(begin_day(store, "2026-09-28"), "build")
            self.assertEqual(store.posts_for("2026-09-28"), [])
            store.add_post(
                day="2026-09-28",
                clock="08:00",
                caption="pronto",
                image_path="",
                books=[_book("Pronto")],
            )
            finish_day(store)
            self.assertEqual(begin_day(store, "2026-09-28"), "skip")
            self.assertEqual(len(store.posts_for("2026-09-28")), 1)
            store.put_setting("fila_preview", "2026-09-28")
            self.assertEqual(begin_day(store, "2026-09-28"), "replace")
            self.assertEqual(len(store.posts_for("2026-09-28")), 1)
            store.close()

    def test_writes_one_book_per_post_with_a_different_signature(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = BoardStore(root / "board.sqlite")
            books = [_page("Um"), _page("Dois")]
            written = write_board(store, "2026-09-28", books, root / "cards", download=_png)
            self.assertEqual(written, 2)
            posts = store.posts_for("2026-09-28")
            self.assertEqual([post.clock for post in posts], ["08:00", "14:00"])
            self.assertEqual(len(posts[0].books), 1)
            self.assertEqual(len(posts[1].books), 1)
            self.assertIn("https://link.amazon/B01bzXpmN", posts[0].caption)
            self.assertIn("https://link.amazon/A0g7KCGdE", posts[1].caption)
            self.assertTrue((root / "cards" / f"{posts[0].id}.jpg").is_file())
            store.close()


def _book(title: str):
    from promo_livros.board_store import BoardBook

    return BoardBook(title, "", 1000, 2000, 50, "Menor preço em 120 dias.", "https://example", "")


def _page(title: str) -> dict:
    return {
        "asin": title,
        "titulo": title,
        "pagina_titulo": title,
        "sinopse": f"Este livro se chama {title} e conta uma história longa o bastante.",
        "preco": 39.9,
        "preco_de": 80,
        "off_pagina": 50,
        "url": "https://www.amazon.com.br/dp/X?tag=souleitor-20",
        "cupom": ["cupom 20% : 20LEITURA. Válido na sua primeira compra"],
        "capa": "http://example/capa.jpg",
    }


def _png(_url: str) -> Image.Image:
    return Image.new("RGB", (40, 60), "blue")


if __name__ == "__main__":
    unittest.main()
