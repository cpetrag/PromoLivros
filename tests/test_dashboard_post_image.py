import tempfile
import unittest
from pathlib import Path

from promo_livros.dashboard import resolve_post_image_file


class ResolvePostImageFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.root = Path(self._folder.name)
        self.cards = self.root / "data" / "cards"
        self.cards.mkdir(parents=True)
        (self.cards / "1.jpg").write_bytes(b"card")
        campaign_dir = self.root / "data" / "campaigns" / "7"
        campaign_dir.mkdir(parents=True)
        (campaign_dir / "a.jpg").write_bytes(b"campaign")
        (self.root / "secret.jpg").write_bytes(b"secret")

    def test_serves_book_card_from_cards_folder(self) -> None:
        found = resolve_post_image_file(str(self.cards / "1.jpg"), self.cards, self.root)

        self.assertEqual(found.read_bytes(), b"card")

    def test_serves_campaign_photo_stored_as_relative_path(self) -> None:
        found = resolve_post_image_file("data/campaigns/7/a.jpg", self.cards, self.root)

        self.assertIsNotNone(found)
        self.assertEqual(found.read_bytes(), b"campaign")

    def test_missing_campaign_photo_is_not_found(self) -> None:
        self.assertIsNone(resolve_post_image_file("data/campaigns/7/gone.jpg", self.cards, self.root))

    def test_paths_outside_the_two_folders_are_refused(self) -> None:
        for raw in (
            "data/campaigns/../../secret.jpg",
            "data/campaigns/7/../../../secret.jpg",
            str(self.root / "secret.jpg"),
            "secret.jpg",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(resolve_post_image_file(raw, self.cards, self.root))


if __name__ == "__main__":
    unittest.main()
