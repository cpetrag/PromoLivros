"""Abre a Curadoria logado e pede as capas em paralelo, como o navegador. Não imprime segredos."""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path

from dotenv import dotenv_values

BASE = "http://127.0.0.1:8787"


def main() -> None:
    env = dotenv_values(Path(".env"))
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = urllib.parse.urlencode(
        {"username": env.get("DASHBOARD_USERNAME", ""), "password": env.get("DASHBOARD_PASSWORD", "")}
    ).encode()
    opener.open(urllib.request.Request(f"{BASE}/login", data=body), timeout=20).read()
    print("logged_in", any(cookie.name == "promo_livros_session" for cookie in jar))

    started = time.monotonic()
    page = opener.open(f"{BASE}/curadoria", timeout=60).read().decode("utf-8", "replace")
    print(f"curadoria bytes={len(page)} t={time.monotonic() - started:.2f}s")
    covers = sorted(set(re.findall(r"/curadoria/capa/[A-Z0-9]+\.jpg", page)))[:60]
    print("covers", len(covers))

    def fetch(path: str) -> str:
        begin = time.monotonic()
        try:
            with opener.open(f"{BASE}{path}", timeout=30) as response:
                response.read()
                return f"{response.status} {time.monotonic() - begin:.2f}"
        except Exception as exc:
            return f"ERR {type(exc).__name__} {time.monotonic() - begin:.2f}"

    with ThreadPoolExecutor(max_workers=24) as pool:
        probe = pool.submit(fetch, "/hoje")
        results = list(pool.map(fetch, covers))
    codes: dict[str, int] = {}
    for line in results:
        codes[line.split()[0]] = codes.get(line.split()[0], 0) + 1
    print("covers_codes", codes)
    print("slowest", sorted(results, key=lambda line: float(line.split()[-1]))[-5:])
    print("hoje_during_covers", probe.result())


if __name__ == "__main__":
    main()
