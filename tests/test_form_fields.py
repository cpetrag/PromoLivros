import unittest

from promo_livros.form_fields import first_field, raw_field


class FormFieldTests(unittest.TestCase):
    def test_first_field_strips_and_defaults_to_empty(self) -> None:
        form = {"nome": ["  Terror  ", "outro"]}
        self.assertEqual(first_field(form, "nome"), "Terror")
        self.assertEqual(first_field(form, "falta"), "")

    def test_raw_field_keeps_spacing(self) -> None:
        form = {"corpo": ["  Linha\n"]}
        self.assertEqual(raw_field(form, "corpo"), "  Linha\n")
        self.assertEqual(raw_field(form, "falta"), "")


if __name__ == "__main__":
    unittest.main()
