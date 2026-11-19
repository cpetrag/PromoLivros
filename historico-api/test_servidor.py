"""Testes contra uma cópia do banco, feita com backup() a partir da conexão só de leitura."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from servidor import caminho_de_rede, servir, uri_somente_leitura

LIVE = Path(r"N:\Vibecoding\Promo Livros\data\promo_livros.sqlite")
TOKEN = "teste-token"


def _backup() -> Path:
    folder = Path(tempfile.mkdtemp())
    target = folder / "copia.sqlite"
    src = sqlite3.connect(uri_somente_leitura(LIVE), uri=True, timeout=5)
    src.execute("PRAGMA query_only=ON")
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def _insert(copy: Path, product_id: str, *, day: str, clock: str, status: str, price: int, sort_order: int = 0) -> int:
    conn = sqlite3.connect(copy)
    try:
        cur = conn.execute(
            """
            INSERT INTO scheduled_posts (day, position, clock, status, caption, image_path)
            VALUES (?, 1, ?, ?, 'x', '')
            """,
            (day, clock, status),
        )
        post_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO scheduled_books (
                post_id, sort_order, title, blurb, price_cents, list_price_cents,
                discount_pct, lowest_label, url, coupon, alt_url, alt_price_cents, product_id
            ) VALUES (?, ?, 'Livro teste', '', ?, 3990, NULL, '', 'https://exemplo', '', '', NULL, ?)
            """,
            (post_id, sort_order, price, product_id),
        )
        conn.commit()
        return post_id
    finally:
        conn.close()


def _one(copy: Path, where: str) -> str:
    conn = sqlite3.connect(uri_somente_leitura(copy), uri=True, timeout=5)
    conn.execute("PRAGMA query_only=ON")
    try:
        row = conn.execute(
            f"""
            SELECT b.product_id
            FROM scheduled_books b
            JOIN scheduled_posts p ON p.id = b.post_id
            WHERE p.status = 'sent' AND {where}
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise AssertionError(where)
    return str(row[0])


class ServidorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.copy = _backup()
        cls.amazon = _one(cls.copy, "b.product_id NOT LIKE 'MLB%' AND b.product_id NOT LIKE '%.%'")
        cls.ml = _one(cls.copy, "b.product_id LIKE 'MLB%'")
        cls.shopee = _one(cls.copy, "b.product_id LIKE '%.%'")
        cls.future = _insert(cls.copy, "B00FUTURO1", day="2099-01-01", clock="18:00", status="scheduled", price=2290)
        cls.hyphen_post = _insert(cls.copy, "mlb-555000111", day="2026-11-01", clock="09:00", status="sent", price=1990)
        _insert(cls.copy, "mlb-555000111", day="2026-11-02", clock="10:00", status="sent", price=1500)
        twice = _insert(cls.copy, "B00DUPLO01", day="2026-11-03", clock="11:00", status="sent", price=3000, sort_order=0)
        conn = sqlite3.connect(cls.copy)
        conn.execute(
            """
            INSERT INTO scheduled_books (
                post_id, sort_order, title, blurb, price_cents, list_price_cents,
                discount_pct, lowest_label, url, coupon, alt_url, alt_price_cents, product_id
            ) VALUES (?, 1, 'Livro teste', '', 2800, NULL, NULL, '', 'https://exemplo', '', '', NULL, 'B00DUPLO01')
            """,
            (twice,),
        )
        conn.commit()
        conn.close()
        config = {"porta": 0, "host": "127.0.0.1", "token": TOKEN, "db": str(cls.copy)}
        cls.server = servir(config)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def _call(self, path: str, *, token: str | None = TOKEN, body: dict | None = None) -> tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        method = "POST" if body is not None else "GET"
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if token is not None:
            request.add_header("X-Token", token)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_rede_recusa_o_n(self) -> None:
        self.assertTrue(caminho_de_rede(LIVE))
        with self.assertRaises(SystemExit):
            servir({"porta": 8798, "host": "127.0.0.1", "token": TOKEN, "db": str(LIVE)})

    def test_saude_sem_token(self) -> None:
        status, payload = self._call("/saude", token=None)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertGreater(payload["posts_sent"], 0)

    def test_token_errado(self) -> None:
        status, payload = self._call(f"/postados?ids={self.amazon}", token="nao")
        self.assertEqual(status, 401)
        self.assertIn("erro", payload)

    def test_lojas_e_ausente_e_hifen(self) -> None:
        status, payload = self._call(
            "/postados",
            body={"ids": [self.amazon, "MLB-" + self.ml[3:], self.shopee, "NAOEXISTE1", "MLB-555000111"]},
        )
        self.assertEqual(status, 200)
        by_id = {item["id"]: item for item in payload["itens"]}
        self.assertTrue(by_id[self.amazon]["encontrado"])
        self.assertEqual(by_id[self.amazon]["ultimo"]["price_cents"], by_id[self.amazon]["ultimo"]["price_cents"])
        ml = by_id["MLB-" + self.ml[3:]]
        self.assertTrue(ml["encontrado"])
        self.assertEqual(ml["id_norm"], self.ml)
        self.assertTrue(by_id[self.shopee]["encontrado"])
        missing = by_id["NAOEXISTE1"]
        self.assertFalse(missing["encontrado"])
        self.assertIsNone(missing["ultimo"])
        self.assertEqual(missing["agendado"], [])
        hyphen = by_id["MLB-555000111"]
        self.assertTrue(hyphen["encontrado"])
        self.assertEqual(hyphen["id_norm"], "MLB555000111")
        self.assertEqual(hyphen["vezes_total"], 2)
        self.assertEqual(hyphen["menor"]["price_cents"], 1500)

    def test_agendado_futuro_nao_entra_no_historico(self) -> None:
        status, payload = self._call("/postados?ids=B00FUTURO1")
        self.assertEqual(status, 200)
        item = payload["itens"][0]
        self.assertFalse(item["encontrado"])
        self.assertEqual(item["agendado"][0]["post_id"], self.future)
        self.assertEqual(item["agendado"][0]["price_cents"], 2290)
        self.assertEqual(item["vezes_total"], 0)

    def test_mesmo_post_conta_uma_vez(self) -> None:
        status, payload = self._call("/postados?ids=B00DUPLO01")
        self.assertEqual(status, 200)
        self.assertEqual(payload["itens"][0]["vezes_total"], 1)

    def test_historico_de_quem_saiu_mais_de_uma_vez(self) -> None:
        status, payload = self._call("/historico?id=mlb-555000111")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload["saidas"]), 2)
        days = [item["day"] for item in payload["saidas"]]
        self.assertEqual(days, sorted(days))

    def test_recentes(self) -> None:
        status, payload = self._call("/recentes?dias=90")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload["itens"]), 3)
        self.assertIn("id_norm", payload["itens"][0])

    def test_trezentos_ids(self) -> None:
        ids = [f"B00PAD{index:05d}" for index in range(299)]
        ids.append(self.amazon)
        started = time.perf_counter()
        status, payload = self._call("/postados", body={"ids": ids})
        elapsed = time.perf_counter() - started
        print(f"TEMPO_POSTADOS_300 {elapsed:.3f}")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["itens"]), 300)
        self.assertLess(elapsed, 5)

    def test_recentes_tempo(self) -> None:
        started = time.perf_counter()
        status, _payload = self._call("/recentes?dias=90")
        elapsed = time.perf_counter() - started
        print(f"TEMPO_RECENTES_90 {elapsed:.3f}")
        self.assertEqual(status, 200)

    def test_banco_ocupado(self) -> None:
        holder = sqlite3.connect(self.copy, timeout=5)
        holder.execute("PRAGMA locking_mode=EXCLUSIVE")
        holder.execute("BEGIN EXCLUSIVE")
        try:
            status, payload = self._call(f"/postados?ids={self.amazon}")
        finally:
            holder.rollback()
            holder.close()
        self.assertEqual(status, 503)
        self.assertIn("erro", payload)


if __name__ == "__main__":
    unittest.main()
