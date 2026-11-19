import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from promo_livros.post_card import _BEIGE, extract_covers, render_card

RED, BLUE = (200, 30, 30), (30, 60, 200)


def _cover(color, size=(196, 280)):
    return Image.new("RGB", size, color)


def _non_beige_bbox(image: Image.Image):
    from PIL import ImageChops

    rgb = image.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, _BEIGE[:3])).convert("L")
    mask = diff.point(lambda value: 255 if value > 24 else 0)
    return mask.getbbox()


class RenderCardStoreLogosTests(unittest.TestCase):
    def test_without_stores_keeps_old_height_formula(self):
        with tempfile.TemporaryDirectory() as tmp:
            cover = _cover(RED)
            cover.thumbnail((280, 280), Image.Resampling.LANCZOS)
            destination = Path(tmp) / "old.jpg"
            render_card([_cover(RED)], destination)
            with Image.open(destination) as image:
                # layout antigo: cover_h + margin*2 + band
                self.assertEqual(image.height, cover.height + 28 * 2 + 78)

    def test_with_stores_makes_card_taller_than_without(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "plain.jpg"
            branded = Path(tmp) / "branded.jpg"
            render_card([_cover(RED), _cover(BLUE)], plain)
            render_card(
                [_cover(RED), _cover(BLUE)],
                branded,
                stores=["amazon", "ml"],
            )
            with Image.open(plain) as a, Image.open(branded) as b:
                self.assertGreater(b.height, a.height)

    def test_unknown_store_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "card.jpg"
            render_card([_cover(RED)], destination, stores=["loja-fantasma"])
            self.assertTrue(destination.is_file())

    def test_magalu_logo_is_smaller_and_lower_than_shopee(self):
        """Compara a faixa sob cada capa: Magalu ocupa menos e começa mais baixo."""
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "card.jpg"
            left, right = _cover(RED), _cover(BLUE)
            render_card([left, right], destination, stores=["shopee", "magalu"])
            with Image.open(destination) as image:
                rgb = image.convert("RGB")
            mid = rgb.width // 2
            strip_top = 28 + 280
            left_strip = rgb.crop((0, strip_top, mid, rgb.height - 78))
            right_strip = rgb.crop((mid, strip_top, rgb.width, rgb.height - 78))
            left_box = _non_beige_bbox(left_strip)
            right_box = _non_beige_bbox(right_strip)
            self.assertIsNotNone(left_box)
            self.assertIsNotNone(right_box)
            left_h = left_box[3] - left_box[1]
            right_h = right_box[3] - right_box[1]
            self.assertLess(right_h, left_h)
            self.assertGreater(right_box[1], left_box[1])


class DownloadImageTests(unittest.TestCase):
    def _response(self, status: int):
        from io import BytesIO
        from types import SimpleNamespace

        buffer = BytesIO()
        Image.new("RGB", (10, 10), RED).save(buffer, "JPEG")

        def raise_for_status():
            if status >= 400:
                raise OSError(str(status))

        return SimpleNamespace(status_code=status, content=buffer.getvalue(), raise_for_status=raise_for_status)

    def test_magalu_403_tries_again_with_the_store_referer(self):
        from promo_livros.post_card import download_image

        calls, waits = [], []
        replies = [self._response(403), self._response(200)]

        def get(url, timeout, headers):
            calls.append(headers)
            return replies.pop(0)

        image = download_image("https://a-static.mlcdn.com.br/600x600/x/magazineluiza/1/a.jpg", get=get, sleep=waits.append)
        self.assertEqual(image.size, (10, 10))
        self.assertEqual(len(calls), 2)
        self.assertEqual(waits, [1.0])
        self.assertEqual(calls[0]["Referer"], "https://www.magazineluiza.com.br/")

    def test_gives_up_after_the_last_attempt(self):
        from promo_livros.post_card import download_image

        def get(url, timeout, headers):
            return self._response(403)

        waits = []
        with self.assertRaises(OSError):
            download_image("https://m.media-amazon.com/images/P/x.jpg", get=get, sleep=waits.append)
        self.assertEqual(waits, [1.0, 3.0])


class RenderCardSmallCoverTests(unittest.TestCase):
    def test_small_cover_is_enlarged_to_match_the_others(self):
        """Miniatura de 70 px não pode virar um selo ao lado de uma capa de 280 px."""
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "card.jpg"
            render_card([_cover(RED, (600, 900)), _cover(BLUE, (70, 70))], destination)
            covers = extract_covers(destination, 2)
            self.assertIsNotNone(covers)
            self.assertGreaterEqual(covers[1].height, 270)


class ExtractCoversWithStoresTests(unittest.TestCase):
    def test_extract_covers_ignores_store_logos(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "card.jpg"
            render_card(
                [_cover(RED), _cover(BLUE)],
                card,
                stores=["amazon", "ml"],
            )
            covers = extract_covers(card, 2)
            self.assertIsNotNone(covers)
            self.assertEqual(len(covers), 2)
            self.assertEqual([cover.height for cover in covers], [280, 280])

    def test_extract_covers_still_works_on_old_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "card.jpg"
            render_card([_cover(RED), _cover(BLUE)], card)
            covers = extract_covers(card, 2)
            self.assertIsNotNone(covers)
            self.assertEqual(len(covers), 2)
            self.assertEqual([cover.height for cover in covers], [280, 280])


if __name__ == "__main__":
    unittest.main()