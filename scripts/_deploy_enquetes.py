"""Sobe o painel, o envio e o webhook das enquetes. Não imprime segredos."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/Volumes/HD 1Tb/Vibecoding/Promo Livros")
PYTHON = Path("/Volumes/HD 1Tb/Vibecoding/promo-livros-venv/bin/python")
PM2 = "/Users/cpetrag/.nvm/versions/node/v24.17.0/bin/pm2"
NODE_BIN = "/Users/cpetrag/.nvm/versions/node/v24.17.0/bin"
LOG = ROOT / "data" / "dashboard.log"
WEBHOOK = "http://127.0.0.1:8787/whatsapp/webhook"
EVENTS = ["poll.vote", "poll.vote.failed", "message"]


def env_value(name: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def listener_pid() -> int | None:
    result = subprocess.run(
        ["lsof", "-nP", "-iTCP:8787", "-sTCP:LISTEN", "-t"],
        check=False,
        capture_output=True,
        text=True,
    )
    pids = [int(item) for item in result.stdout.split() if item.isdigit()]
    return pids[0] if pids else None


def restart_dashboard() -> int:
    previous = listener_pid()
    if previous:
        os.kill(previous, signal.SIGTERM)
        for _ in range(30):
            if listener_pid() is None:
                break
            time.sleep(0.2)
        else:
            os.kill(previous, signal.SIGKILL)
            time.sleep(0.5)
    with LOG.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [str(PYTHON), "-m", "promo_livros.dashboard"],
            cwd=ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    for _ in range(40):
        time.sleep(0.25)
        pid = listener_pid()
        if pid:
            print(f"painel pid {pid}")
            return pid
    raise SystemExit(f"O painel não escutou na 8787. Processo {process.pid}.")


def restart_envio() -> None:
    env = os.environ.copy()
    env["PATH"] = NODE_BIN + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [PM2, "restart", "promo-livros-envio", "--update-env"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        print(result.stderr[-500:])
        raise SystemExit("Não reiniciei o promo-livros-envio.")
    print("envio reiniciado")


def waha(method: str, path: str, key: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:4443" + path,
        data=data,
        method=method,
        headers={"accept": "application/json", "X-Api-Key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8") or "{}")
    if not isinstance(payload, dict):
        raise SystemExit("O WAHA não devolveu um objeto.")
    return payload


def configure_webhook(key: str, session: str) -> None:
    current = waha("GET", f"/api/sessions/{session}", key)
    config = current.get("config") if isinstance(current.get("config"), dict) else {}
    webhooks = config.get("webhooks") if isinstance(config.get("webhooks"), list) else []
    kept = [
        item
        for item in webhooks
        if not (isinstance(item, dict) and item.get("url") == WEBHOOK)
    ]
    kept.append(
        {
            "url": WEBHOOK,
            "events": EVENTS,
            "customHeaders": [{"name": "X-Api-Key", "value": key}],
        }
    )
    config = {**config, "webhooks": kept}
    print(f"sessão antes: {current.get('status')}")
    updated = waha("PUT", f"/api/sessions/{session}", key, {"config": config})
    print(f"sessão depois do update: {updated.get('status')}")
    deadline = time.time() + 90
    status = str(updated.get("status") or "")
    while time.time() < deadline:
        status = str(waha("GET", f"/api/sessions/{session}", key).get("status") or "")
        print(f"sessão: {status}")
        if status == "WORKING":
            return
        if status == "SCAN_QR_CODE":
            raise SystemExit("A sessão pediu QR. O pareamento caiu.")
        time.sleep(3)
    raise SystemExit(f"A sessão não voltou a WORKING. Último estado: {status}")


def main() -> None:
    restart_dashboard()
    restart_envio()
    key = env_value("WAHA_API_KEY")
    session = env_value("WAHA_SESSION") or "promo-livros"
    if not key:
        raise SystemExit("WAHA_API_KEY vazia. O webhook não foi configurado.")
    configure_webhook(key, session)
    request = urllib.request.Request("http://127.0.0.1:8787/enquetes")
    with urllib.request.urlopen(request, timeout=8) as response:
        html = response.read(400).decode("utf-8", "replace")
        print(f"painel /enquetes HTTP {response.status}")
    if "Entrar" not in html and "Enquetes" not in html:
        raise SystemExit("O painel respondeu sem a tela esperada.")
    print("deploy ok")


if __name__ == "__main__":
    main()
