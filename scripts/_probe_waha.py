"""Probe local WAHA OpenAPI. Prints paths only, never secrets."""
from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


INTERESTING = {
    "/api/sendPoll",
    "/api/sendPollVote",
    "/api/{session}/chats/{chatId}/messages/{messageId}/pin",
    "/api/{session}/chats/{chatId}/messages/{messageId}/unpin",
}
SCHEMA_NAMES = {
    "MessagePoll",
    "MessagePollRequest",
    "PinMessageRequest",
    "PollVote",
    "PollVotePayload",
    "WAHAWebhookPollVote",
    "WAHAWebhookPollVoteFailed",
    "WebhookConfig",
}


def dump_openapi(env: dict[str, str]) -> None:
    key = env.get("WAHA_API_KEY", "")
    user = env.get("WAHA_DASHBOARD_USERNAME", "")
    password = env.get("WAHA_DASHBOARD_PASSWORD", "")
    auth = base64.b64encode(f"{user}:{password}".encode()).decode() if user else ""
    headers = {
        "accept": "application/json",
        "X-Api-Key": key,
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"Basic {auth}",
    }
    ctx = ssl._create_unverified_context()
    request = urllib.request.Request("https://esteira.promolivros.org/-json", headers=headers)
    with urllib.request.urlopen(request, timeout=60, context=ctx) as response:
        spec = json.load(response)
    needles = ("poll", "pin", "unpin", "webhook")
    paths = spec.get("paths", {})
    print("--- paths ---")
    for path, methods in paths.items():
        blob = path.lower() + " " + " ".join(methods).lower()
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            blob += " " + str(operation.get("operationId", "")).lower()
            blob += " " + str(operation.get("summary", "")).lower()
        if any(needle in blob for needle in needles):
            print(path, ",".join(methods))
    schemas = spec.get("components", {}).get("schemas", {})
    print("--- schemas ---")
    for name in schemas:
        if any(needle in name.lower() for needle in needles):
            print(name)
    print("--- operations ---")
    for path, methods in paths.items():
        if path not in INTERESTING:
            continue
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            kept = {
                "summary": operation.get("summary"),
                "description": operation.get("description"),
                "operationId": operation.get("operationId"),
                "requestBody": operation.get("requestBody"),
                "responses": {
                    code: {"description": body.get("description")}
                    for code, body in (operation.get("responses") or {}).items()
                    if isinstance(body, dict)
                },
            }
            extra = {key: value for key, value in operation.items() if str(key).startswith("x-")}
            print(method.upper(), path)
            print(json.dumps({"kept": kept, "extra": extra}, ensure_ascii=False, indent=2)[:6000])
    print("--- named schemas ---")
    for name in SCHEMA_NAMES:
        print(name)
        print(json.dumps(schemas.get(name), ensure_ascii=False, indent=2)[:4000])
    raw = json.dumps(spec, ensure_ascii=False)
    print("--- plus contexts ---")
    lower = raw.lower()
    start = 0
    seen = 0
    while seen < 12:
        index = lower.find("plus", start)
        if index < 0:
            break
        print(raw[max(0, index - 180): index + 180].replace("\n", " "))
        print("---")
        start = index + 4
        seen += 1
    destination = schemas.get("MessageDestination")
    print("--- MessageDestination ---")
    print(json.dumps(destination, ensure_ascii=False, indent=2)[:2000])


def main() -> None:
    env = load_env()
    key = env.get("WAHA_API_KEY", "")
    user = env.get("WAHA_DASHBOARD_USERNAME", "")
    password = env.get("WAHA_DASHBOARD_PASSWORD", "")
    print("key_len", len(key), "user_set", bool(user), "url", env.get("WAHA_URL"))
    base = "https://esteira.promolivros.org"
    paths = [
        "/api/server/version",
        "/api/version",
        "/api/server/environment",
        "/api/sessions/promo-livros",
        "/",
        "/swagger",
        "/api/docs",
        "/api/docs-json",
        "/-json",
        "/swagger.json",
        "/api/swagger.json",
        "/openapi.json",
    ]
    ctx = ssl._create_unverified_context()
    auth = base64.b64encode(f"{user}:{password}".encode()).decode() if user else ""
    for path in paths:
        headers = {
            "accept": "application/json, text/html",
            "X-Api-Key": key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
        if auth:
            headers["Authorization"] = f"Basic {auth}"
        request = urllib.request.Request(base + path, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=25, context=ctx) as response:
                body = response.read(160)
                print(response.status, path, response.headers.get("content-type"), body[:100])
        except urllib.error.HTTPError as exc:
            snippet = exc.read(120).decode("utf-8", "replace").replace("\n", " ")
            print(exc.code, path, snippet[:100])
        except Exception as exc:
            print(type(exc).__name__, path, str(exc)[:120])


if __name__ == "__main__":
    dump_openapi(load_env())
