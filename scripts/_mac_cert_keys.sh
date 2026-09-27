#!/bin/bash
set -eu
python3 - <<'PY'
import json
path = "/Users/cpetrag/.cloudflared/cert.pem"
with open(path) as f:
    raw = f.read(1)
print("starts_with", raw)
with open(path) as f:
    text = f.read()
text = text.strip()
if text.startswith("{"):
    data = json.loads(text)
    print("keys", sorted(data.keys()))
else:
    print("not_json", "lines", text.count("\n") + 1)
PY
echo "--- route help ---"
/opt/homebrew/bin/cloudflared tunnel route dns --help | head -40
