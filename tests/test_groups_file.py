import unittest

from promo_livros.groups_file import (
    GroupsFileError,
    group_choices,
    replace_groups_block,
    selected_groups,
    validate_groups,
)
from promo_livros.models import WhatsAppGroup

YAML = """# topo
whatsapp:
  # não ligar daqui
  enabled: false
  gap_seconds: 45
  groups:
    - name: "Velho"
      id: "120363430990609445@g.us"
website:
  enabled: false
"""


class GroupsFileTests(unittest.TestCase):
    def test_replaces_only_the_groups_block(self) -> None:
        updated = replace_groups_block(
            YAML,
            [("Black Livros 01", "120363430990609445@g.us")],
        )
        self.assertIn("# não ligar daqui", updated)
        self.assertIn("enabled: false", updated)
        self.assertIn('name: "Black Livros 01"', updated)
        self.assertNotIn("Velho", updated)
        self.assertIn("website:", updated)

    def test_rejects_bad_id_duplicate_and_empty_when_enabled(self) -> None:
        with self.assertRaises(GroupsFileError):
            validate_groups([("A", "nao-e-grupo")], enabled=False)
        with self.assertRaises(GroupsFileError):
            validate_groups(
                [("A", "1@g.us"), ("B", "1@g.us")],
                enabled=False,
            )
        with self.assertRaises(GroupsFileError):
            validate_groups([], enabled=True)
        validate_groups([], enabled=False)

    def test_keeps_saved_group_missing_from_the_session(self) -> None:
        saved = WhatsAppGroup("Black Livros 03", "120363412365496470@g.us")
        live = WhatsAppGroup("Black Livros 01", "120363430990609445@g.us")
        choices = group_choices((live,), (saved, live))
        self.assertEqual(choices[1].chat_id, saved.chat_id)
        self.assertTrue(choices[1].missing)
        self.assertTrue(choices[1].checked)

    def test_posted_id_must_be_one_of_the_choices(self) -> None:
        choices = group_choices(
            (WhatsAppGroup("Black Livros 01", "120363430990609445@g.us"),),
            (),
        )
        picked = selected_groups(["120363430990609445@g.us"], choices)
        self.assertEqual(picked, [("Black Livros 01", "120363430990609445@g.us")])
        with self.assertRaises(GroupsFileError):
            selected_groups(["999@g.us"], choices)


if __name__ == "__main__":
    unittest.main()
