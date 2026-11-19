import io
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from PIL import Image

from promo_livros.campaign_images import (
    MAX_PIXELS,
    MAX_SIDE,
    MAX_UPLOAD_BYTES,
    ImageUploadError,
    read_image,
    remove_campaign_dir,
    remove_image,
    save_upload,
)


def _encoded(fmt: str, size: tuple[int, int] = (40, 30), **options) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, fmt, **options)
    return buffer.getvalue()


def _image_bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt)
    return buffer.getvalue()


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _huge_grayscale_png(width: int, height: int) -> bytes:
    """PNG enorme em pixels e pequeno em bytes, sem passar pelo Pillow."""
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    compressor = zlib.compressobj(9)
    row = b"\x00" * (width + 1)
    pixels = b"".join(compressor.compress(row) for _ in range(height)) + compressor.flush()
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", pixels)
        + _png_chunk(b"IEND", b"")
    )


class SaveUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_png_becomes_jpeg_in_the_campaign_folder(self) -> None:
        relative = save_upload(self.root, 3, _encoded("PNG"))
        self.assertTrue(relative.startswith("data/campaigns/3/"))
        self.assertTrue(relative.endswith(".jpg"))
        with Image.open(self.root / relative) as saved:
            self.assertEqual(saved.format, "JPEG")

    def test_webp_is_accepted(self) -> None:
        relative = save_upload(self.root, 3, _encoded("WEBP"))
        self.assertIsNotNone(read_image(self.root, relative))

    def test_large_image_is_reduced(self) -> None:
        relative = save_upload(self.root, 3, _encoded("PNG", (MAX_SIDE + 904, 100)))
        with Image.open(self.root / relative) as saved:
            self.assertEqual(saved.width, MAX_SIDE)

    def test_exif_is_dropped(self) -> None:
        exif = Image.Exif()
        exif[0x010F] = "Camera"
        relative = save_upload(self.root, 3, _encoded("JPEG", exif=exif))
        with Image.open(self.root / relative) as saved:
            self.assertNotIn("exif", saved.info)

    def test_refused_files(self) -> None:
        with self.assertRaises(ImageUploadError):
            save_upload(self.root, 3, b"")
        with self.assertRaises(ImageUploadError):
            save_upload(self.root, 3, b"not an image")
        with self.assertRaises(ImageUploadError):
            save_upload(self.root, 3, _encoded("GIF"))
        with self.assertRaises(ImageUploadError):
            save_upload(self.root, 3, b"x" * (MAX_UPLOAD_BYTES + 1))
        self.assertFalse((self.root / "data" / "campaigns" / "3").exists())

    def test_png_with_broken_checksum_is_refused(self) -> None:
        header = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
        pixels = zlib.compress(b"".join(b"\x00" + b"\x10\x20\x30" * 4 for _ in range(4)))
        broken_idat = _png_chunk(b"IDAT", pixels)[:-4] + b"\x00\x00\x00\x00"
        payload = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + broken_idat + _png_chunk(b"IEND", b"")
        with self.assertRaisesRegex(ImageUploadError, "não é uma foto JPEG, PNG ou WebP"):
            save_upload(self.root, 3, payload)
        self.assertFalse((self.root / "data" / "campaigns" / "3").exists())

    def test_truncated_and_odd_decoder_errors_are_refused(self) -> None:
        for error in (SyntaxError("broken"), ValueError("bad"), EOFError(), struct.error("short")):
            with self.subTest(error=type(error).__name__), mock.patch(
                "promo_livros.campaign_images.Image.open", side_effect=error
            ), self.assertRaises(ImageUploadError):
                save_upload(self.root, 3, _encoded("PNG"))

    def test_wrong_format_gets_the_friendly_message(self) -> None:
        with self.assertRaisesRegex(ImageUploadError, "Use foto JPEG, PNG ou WebP."):
            save_upload(self.root, 3, _encoded("GIF"))

    def test_decompression_bomb_is_refused(self) -> None:
        payload = _huge_grayscale_png(10000, 5000)
        self.assertGreater(10000 * 5000, MAX_PIXELS)
        self.assertLess(len(payload), MAX_UPLOAD_BYTES)
        with self.assertRaisesRegex(ImageUploadError, "resolução grande demais"):
            save_upload(self.root, 3, payload)
        self.assertFalse((self.root / "data" / "campaigns" / "3").exists())

    def test_exif_rotation_is_applied(self) -> None:
        exif = Image.Exif()
        exif[0x0112] = 6
        relative = save_upload(self.root, 3, _encoded("JPEG", (60, 30), exif=exif))
        with Image.open(self.root / relative) as saved:
            self.assertEqual(saved.size, (30, 60))

    def test_rotated_large_image_stays_within_max_side(self) -> None:
        exif = Image.Exif()
        exif[0x0112] = 6
        relative = save_upload(self.root, 3, _encoded("JPEG", (MAX_SIDE + 904, 100), exif=exif))
        with Image.open(self.root / relative) as saved:
            self.assertLessEqual(max(saved.size), MAX_SIDE)
            self.assertGreater(saved.height, saved.width)

    def test_sixteen_bit_is_scaled_to_eight_bit(self) -> None:
        relative = save_upload(self.root, 3, _image_bytes(Image.new("I;16", (20, 20), 30000)))
        with Image.open(self.root / relative) as saved:
            red, green, blue = saved.getpixel((10, 10))
        for channel in (red, green, blue):
            self.assertAlmostEqual(channel, 117, delta=2)

    def test_transparency_becomes_white(self) -> None:
        relative = save_upload(self.root, 3, _image_bytes(Image.new("RGBA", (20, 20), (0, 0, 0, 0))))
        with Image.open(self.root / relative) as saved:
            for channel in saved.getpixel((10, 10)):
                self.assertGreaterEqual(channel, 250)

    def test_icc_profile_is_kept(self) -> None:
        profile = b"fake-icc-profile"
        buffer = io.BytesIO()
        Image.new("RGB", (20, 20), (10, 120, 200)).save(buffer, "PNG", icc_profile=profile)
        relative = save_upload(self.root, 3, buffer.getvalue())
        with Image.open(self.root / relative) as saved:
            self.assertEqual(saved.info.get("icc_profile"), profile)


class ReadImageTests(unittest.TestCase):
    def test_only_reads_inside_the_campaign_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cards = root / "data" / "cards"
            cards.mkdir(parents=True)
            (cards / "1.jpg").write_bytes(b"card")
            self.assertIsNone(read_image(root, "data/cards/1.jpg"))
            self.assertIsNone(read_image(root, "data/campaigns/../cards/1.jpg"))
            self.assertIsNone(read_image(root, "data/campaigns/1/missing.jpg"))

    def test_remove_image_and_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            relative = save_upload(root, 4, _encoded("PNG"))
            remove_image(root, relative)
            self.assertIsNone(read_image(root, relative))
            save_upload(root, 4, _encoded("PNG"))
            remove_campaign_dir(root, 4)
            self.assertFalse((root / "data" / "campaigns" / "4").exists())

    def test_only_campaign_jpeg_files_are_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            campaign = root / "data" / "campaigns" / "1"
            (campaign / "nested").mkdir(parents=True)
            (campaign / "notes.txt").write_bytes(b"text")
            (campaign / "nested" / "deep.jpg").write_bytes(b"deep")
            (root / "data" / "campaigns" / "loose.jpg").write_bytes(b"loose")
            self.assertIsNone(read_image(root, "data/campaigns/1"))
            self.assertIsNone(read_image(root, "data/campaigns/1/nested"))
            self.assertIsNone(read_image(root, "data/campaigns/1/notes.txt"))
            self.assertIsNone(read_image(root, "data/campaigns/1/nested/deep.jpg"))
            self.assertIsNone(read_image(root, "data/campaigns/loose.jpg"))
            remove_image(root, "data/campaigns/1/nested")
            remove_image(root, "data/campaigns/1/notes.txt")
            self.assertTrue((campaign / "nested").is_dir())
            self.assertTrue((campaign / "notes.txt").is_file())

    def test_missing_campaign_dir_is_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertNoLogs("promo_livros.campaign_images"):
                remove_campaign_dir(Path(folder), 99)

    def test_failed_removal_is_logged(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            save_upload(root, 5, _encoded("PNG"))
            with mock.patch("os.unlink", side_effect=PermissionError("locked")):
                with self.assertLogs("promo_livros.campaign_images", level="WARNING") as captured:
                    remove_campaign_dir(root, 5)
            self.assertIn("PermissionError", captured.output[0])
            remove_campaign_dir(root, 5)
            self.assertFalse((root / "data" / "campaigns" / "5").exists())
