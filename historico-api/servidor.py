"""Leitura do histórico de posts enviados. Não grava no banco e não faz parte do painel."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

VERSAO = "1"
MAX_IDS = 300
DIAS_PADRAO = 90
DIAS_MAXIMO = 400
FUSO = ZoneInfo("America/Sao_Paulo")
DRIVE_REMOTE = 4

log = logging.getLogger("historico")


def caminho_de_rede(path: Path) -> bool:
    """UNC, caminho POSIX de rede, ou unidade mapeada (GetDriveTypeW == DRIVE_REMOTE). O N: entra aqui."""
    text = str(path)
    if text.startswith("\\\\") or text.startswith("//"):
        return True
    if os.name != "nt":
        return False
    drive = os.path.splitdrive(text)[0]
    if not drive:
        return False
    root = drive if drive.endswith("\\") else drive + "\\"
    kind = int(__import__("ctypes").windll.kernel32.GetDriveTypeW(root))
    return kind == DRIVE_REMOTE


def uri_somente_leitura(path: Path) -> str:
    """file:N:/... sem resolve(). resolve() em unidade mapeada vira UNC e o SQLite recusa a URI."""
    if not path.is_absolute():
        path = path.absolute()
    return "file:" + str(path).replace("\\", "/") + "?mode=ro"


def abrir(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(uri_somente_leitura(path), uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def consultar(path: Path, fn):
    """Uma conexão por pedido. O with do sqlite só dá commit e não fecha."""
    conn = abrir(path)
    try:
        return fn(conn)
    finally:
        conn.close()


def id_norm(value: str) -> str:
    return value.strip().upper().replace(" ", "").replace("MLB-", "MLB")


def agora() -> datetime:
    return datetime.now(FUSO)


def hoje() -> str:
    return agora().date().isoformat()


def _norm_sql() -> str:
    return "REPLACE(UPPER(TRIM(b.product_id)), 'MLB-', 'MLB')"


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    return int(value)


def _ultimo_sent(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        """
        SELECT day, clock
        FROM scheduled_posts
        WHERE status = 'sent'
        ORDER BY day DESC, clock DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return {"day": row["day"], "clock": row["clock"]}


def saude(conn: sqlite3.Connection, db: str) -> dict:
    posts = conn.execute("SELECT COUNT(*) AS n FROM scheduled_posts WHERE status = 'sent'").fetchone()["n"]
    livros = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM scheduled_books b
        JOIN scheduled_posts p ON p.id = b.post_id
        WHERE p.status = 'sent'
        """
    ).fetchone()["n"]
    distintos = conn.execute(
        f"""
        SELECT COUNT(DISTINCT {_norm_sql()}) AS n
        FROM scheduled_books b
        JOIN scheduled_posts p ON p.id = b.post_id
        WHERE p.status = 'sent'
        """
    ).fetchone()["n"]
    return {
        "ok": True,
        "versao": VERSAO,
        "db": db,
        "ultimo_sent": _ultimo_sent(conn),
        "posts_sent": int(posts),
        "livros_sent": int(livros),
        "ids_distintos": int(distintos),
        "agora": agora().isoformat(timespec="seconds"),
    }


def _linhas(conn: sqlite3.Connection, norms: list[str], statuses: tuple[str, ...]) -> list[sqlite3.Row]:
    if not norms:
        return []
    marks = ",".join("?" for _ in norms)
    status_marks = ",".join("?" for _ in statuses)
    return conn.execute(
        f"""
        SELECT {_norm_sql()} AS id_norm, b.product_id, b.sort_order, b.price_cents,
               b.list_price_cents, b.coupon, b.title, b.url,
               p.id AS post_id, p.day, p.clock, p.status
        FROM scheduled_books b
        JOIN scheduled_posts p ON p.id = b.post_id
        WHERE p.status IN ({status_marks})
          AND {_norm_sql()} IN ({marks})
        """,
        (*statuses, *norms),
    ).fetchall()


def _ultimo(rows: list[sqlite3.Row], day: str) -> dict:
    chosen_post = max(rows, key=lambda row: (row["day"], row["clock"], int(row["post_id"])))
    in_post = [row for row in rows if int(row["post_id"]) == int(chosen_post["post_id"])]
    row = min(in_post, key=lambda item: (int(item["sort_order"]), int(item["post_id"])))
    posted = datetime.strptime(row["day"], "%Y-%m-%d").date()
    current = datetime.strptime(day, "%Y-%m-%d").date()
    return {
        "post_id": int(row["post_id"]),
        "day": row["day"],
        "clock": row["clock"],
        "dias_desde": (current - posted).days,
        "price_cents": int(row["price_cents"]),
        "list_price_cents": _int_or_none(row["list_price_cents"]),
        "coupon": row["coupon"] or "",
        "title": row["title"],
        "url": row["url"],
    }


def _menor(rows: list[sqlite3.Row]) -> dict:
    floor = min(int(row["price_cents"]) for row in rows)
    tied = [row for row in rows if int(row["price_cents"]) == floor]
    row = max(tied, key=lambda item: (item["day"], item["clock"], int(item["post_id"])))
    return {"price_cents": int(row["price_cents"]), "day": row["day"], "clock": row["clock"]}


def _agendado(rows: list[sqlite3.Row]) -> list[dict]:
    by_post: dict[int, sqlite3.Row] = {}
    for row in rows:
        post_id = int(row["post_id"])
        current = by_post.get(post_id)
        if current is None or int(row["sort_order"]) < int(current["sort_order"]):
            by_post[post_id] = row
    ordered = sorted(by_post.values(), key=lambda row: (row["day"], row["clock"], int(row["post_id"])))
    return [
        {
            "post_id": int(row["post_id"]),
            "day": row["day"],
            "clock": row["clock"],
            "price_cents": int(row["price_cents"]),
        }
        for row in ordered
    ]


def postados(conn: sqlite3.Connection, ids: list[str]) -> dict:
    day = hoje()
    start_30 = (datetime.strptime(day, "%Y-%m-%d").date() - timedelta(days=30)).isoformat()
    norms = [id_norm(item) for item in ids]
    sent = _linhas(conn, norms, ("sent",))
    scheduled = [
        row
        for row in _linhas(conn, norms, ("scheduled",))
        if row["day"] >= day
    ]
    sent_by: dict[str, list[sqlite3.Row]] = {}
    scheduled_by: dict[str, list[sqlite3.Row]] = {}
    for row in sent:
        sent_by.setdefault(row["id_norm"], []).append(row)
    for row in scheduled:
        scheduled_by.setdefault(row["id_norm"], []).append(row)
    itens = []
    for original, norm in zip(ids, norms):
        rows = sent_by.get(norm, [])
        posts = {int(row["post_id"]) for row in rows}
        recent = {int(row["post_id"]) for row in rows if row["day"] >= start_30}
        itens.append(
            {
                "id": original,
                "id_norm": norm,
                "encontrado": bool(rows),
                "ultimo": _ultimo(rows, day) if rows else None,
                "menor": _menor(rows) if rows else None,
                "vezes_total": len(posts),
                "vezes_30d": len(recent),
                "agendado": _agendado(scheduled_by.get(norm, [])),
            }
        )
    return {"hoje": day, "itens": itens}


def historico(conn: sqlite3.Connection, original: str) -> dict:
    norm = id_norm(original)
    rows = _linhas(conn, [norm], ("sent",))
    rows.sort(key=lambda row: (row["day"], row["clock"], int(row["post_id"]), int(row["sort_order"])))
    return {
        "id_norm": norm,
        "saidas": [
            {
                "post_id": int(row["post_id"]),
                "day": row["day"],
                "clock": row["clock"],
                "price_cents": int(row["price_cents"]),
                "list_price_cents": _int_or_none(row["list_price_cents"]),
                "coupon": row["coupon"] or "",
                "title": row["title"],
                "url": row["url"],
                "sort_order": int(row["sort_order"]),
            }
            for row in rows
        ],
    }


def recentes(conn: sqlite3.Connection, dias: int) -> dict:
    day = hoje()
    since = (datetime.strptime(day, "%Y-%m-%d").date() - timedelta(days=dias)).isoformat()
    rows = conn.execute(
        f"""
        SELECT id_norm, title, day, clock, price_cents
        FROM (
            SELECT {_norm_sql()} AS id_norm, b.title, p.day, p.clock, b.price_cents, p.id AS post_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY {_norm_sql()}
                       ORDER BY p.day DESC, p.clock DESC, p.id DESC
                   ) AS n
            FROM scheduled_books b
            JOIN scheduled_posts p ON p.id = b.post_id
            WHERE p.status = 'sent' AND p.day >= ?
        )
        WHERE n = 1
        ORDER BY day DESC, clock DESC, post_id DESC
        """,
        (since,),
    ).fetchall()
    return {
        "desde": since,
        "itens": [
            {
                "id_norm": row["id_norm"],
                "title": row["title"],
                "day": row["day"],
                "clock": row["clock"],
                "price_cents": int(row["price_cents"]),
            }
            for row in rows
        ],
    }


class HistoricoHandler(BaseHTTPRequestHandler):
    config: dict
    db_path: Path

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_OPTIONS(self) -> None:
        self._send(204, b"", route="OPTIONS", ids=0)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        started = time.perf_counter()
        parsed = urlparse(self.path)
        route = parsed.path
        ids = 0
        try:
            status, body, ids = self._route(method, route, parse_qs(parsed.query))
        except sqlite3.OperationalError as exc:
            status, body = 503, {"erro": "Banco ocupado. Tente de novo."}
            log.warning("banco ocupado: %s", type(exc).__name__)
        except ValueError:
            status, body = 400, {"erro": "Pedido inválido."}
        except Exception:
            log.exception("falha na rota %s", route)
            status, body = 500, {"erro": "Falha ao ler o histórico."}
        payload = b"" if status == 204 else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self._send(status, payload, route=route, ids=ids, started=started)

    def _route(self, method: str, route: str, query: dict) -> tuple[int, dict, int]:
        if route == "/saude" and method == "GET":
            return 200, consultar(self.db_path, lambda conn: saude(conn, str(self.db_path))), 0
        if not self._token_ok():
            return 401, {"erro": "Token ausente ou incorreto."}, 0
        if route == "/postados" and method == "GET":
            ids = _ids_da_query(query.get("ids", [""])[0])
            return self._postados(ids)
        if route == "/postados" and method == "POST":
            ids = _ids_do_body(self._body())
            return self._postados(ids)
        if route == "/historico" and method == "GET":
            raw = (query.get("id") or [""])[0].strip()
            if not raw:
                return 400, {"erro": "Informe o id."}, 0
            return 200, consultar(self.db_path, lambda conn: historico(conn, raw)), 1
        if route == "/recentes" and method == "GET":
            dias = _dias((query.get("dias") or [str(DIAS_PADRAO)])[0])
            return 200, consultar(self.db_path, lambda conn: recentes(conn, dias)), 0
        return 404, {"erro": "Rota não encontrada."}, 0

    def _postados(self, ids: list[str]) -> tuple[int, dict, int]:
        if not ids:
            return 400, {"erro": "Informe ao menos um id."}, 0
        if len(ids) > MAX_IDS:
            return 400, {"erro": f"No máximo {MAX_IDS} ids por chamada."}, len(ids)
        return 200, consultar(self.db_path, lambda conn: postados(conn, ids)), len(ids)

    def _token_ok(self) -> bool:
        sent = self.headers.get("X-Token", "")
        expected = str(self.config.get("token") or "")
        return bool(expected) and sent == expected

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > 65_536:
            raise ValueError("corpo")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("corpo")
        return data

    def _send(self, status: int, payload: bytes, *, route: str, ids: int, started: float | None = None) -> None:
        elapsed = 0 if started is None else int((time.perf_counter() - started) * 1000)
        log.info("rota=%s ids=%s ms=%s status=%s", route, ids, elapsed, status)
        self.send_response(status)
        origin = self.headers.get("Origin", "")
        if origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "X-Token, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        if payload:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)


def _ids_da_query(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _ids_do_body(body: dict) -> list[str]:
    ids = body.get("ids")
    if not isinstance(ids, list):
        raise ValueError("ids")
    found = []
    for item in ids:
        if not isinstance(item, str) or not item.strip():
            continue
        found.append(item.strip())
    return found


def _dias(raw: str) -> int:
    try:
        dias = int(raw)
    except ValueError as exc:
        raise ValueError("dias") from exc
    if dias < 1 or dias > DIAS_MAXIMO:
        raise ValueError("dias")
    return dias


def carregar(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    db = Path(data["db"])
    if not db.is_absolute():
        db = (path.parent / db).resolve()
    data["db"] = str(db)
    data["porta"] = int(data.get("porta") or 8791)
    data["host"] = str(data.get("host") or "127.0.0.1")
    data["token"] = str(data.get("token") or "")
    return data


def servir(config: dict) -> ThreadingHTTPServer:
    db_path = Path(config["db"])
    if caminho_de_rede(db_path):
        raise SystemExit(
            "O banco está numa pasta de rede. Este servidor só sobe na máquina que grava o arquivo, "
            "com o caminho local. Unidade mapeada e caminho UNC, inclusive o N:, ficam de fora."
        )
    if not db_path.is_file():
        raise SystemExit(f"Não achei o banco em {db_path}.")
    handler = type(
        "BoundHistoricoHandler",
        (HistoricoHandler,),
        {"config": config, "db_path": db_path},
    )
    return ThreadingHTTPServer((config["host"], int(config["porta"])), handler)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    args = sys.argv[1:] if argv is None else argv
    config_path = Path(args[args.index("--config") + 1]) if "--config" in args else Path(__file__).with_name("config.json")
    config = carregar(config_path)
    server = servir(config)
    log.info("rota=iniciar ids=0 ms=0 status=0")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
