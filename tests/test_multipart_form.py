import unittest

from promo_livros.multipart_form import parse_multipart

BOUNDARY = "----promoBoundary42"


def _body(parts: list[tuple[str, str | None, bytes]]) -> bytes:
    chunks = []
    for name, filename, data in parts:
        disposition = f'form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        chunks.append(
            f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
            + data
            + b"\r\n"
        )
    return b"".join(chunks) + f"--{BOUNDARY}--\r\n".encode()


class MultipartTests(unittest.TestCase):
    def test_fields_and_binary_files(self) -> None:
        binary = bytes(range(256)) * 4 + b"\r\n--not-the-boundary\r\n"
        body = _body([
            ("acao", None, "enviar".encode()),
            ("fotos", "a.png", binary),
            ("fotos", "b.jpg", b"segunda"),
            ("fotos", "", b""),
        ])
        fields, files = parse_multipart(f"multipart/form-data; boundary={BOUNDARY}", body)
        self.assertEqual(fields, {"acao": ["enviar"]})
        self.assertEqual(files["fotos"], [binary, b"segunda"])

    def test_quoted_boundary(self) -> None:
        body = _body([("fotos", "a.jpg", b"x")])
        _fields, files = parse_multipart(f'multipart/form-data; boundary="{BOUNDARY}"', body)
        self.assertEqual(files["fotos"], [b"x"])

    def test_other_content_types_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_multipart("application/x-www-form-urlencoded", b"a=1")
        with self.assertRaises(ValueError):
            parse_multipart("multipart/form-data", b"")
        with self.assertRaises(ValueError):
            parse_multipart(f"multipart/form-datax; boundary={BOUNDARY}", _body([("fotos", "a.jpg", b"x")]))

    def test_boundary_must_be_a_parameter(self) -> None:
        with self.assertRaises(ValueError):
            parse_multipart("multipart/form-data; xboundary=abc", b"")

    def test_boundary_text_inside_content_is_kept(self) -> None:
        body = (
            b"--xyz\r\n"
            b'Content-Disposition: form-data; name="fotos"; filename="a.jpg"\r\n\r\n'
            b"AA--xyzBB\r\n"
            b"--xyz--\r\n"
        )
        _fields, files = parse_multipart("multipart/form-data; boundary=xyz", body)
        self.assertEqual(files["fotos"], [b"AA--xyzBB"])
