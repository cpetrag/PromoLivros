#!/bin/bash
set -e
export PATH="/Users/cpetrag/.nvm/versions/node/v24.17.0/bin:$PATH"
ROOT="/Volumes/HD 1Tb/Vibecoding/Promo Livros"
PY="/Volumes/HD 1Tb/Vibecoding/promo-livros-venv/bin/python"
cd "$ROOT"
"$PY" - <<'PY'
from pathlib import Path
from dotenv import dotenv_values
v = dotenv_values(Path(".env"))
print("keys", len(v))
print("has_keepa", "KEEPA_API_KEY" in v)
print("has_magalu", "MAGALU_PROMOTER_ID" in v)
print("has_aqui", "AQUI_BASE_URL" in v)
print("aqui_base", v.get("AQUI_BASE_URL", ""))
PY
pm2 restart promo-livros-painel
sleep 5
curl -s -o /dev/null -w "curadoria %{http_code}\n" http://127.0.0.1:8787/curadoria
curl -s -o /dev/null -w "hoje %{http_code}\n" http://127.0.0.1:8787/hoje
echo "--- error log ---"
tail -n 20 /Users/cpetrag/.pm2/logs/promo-livros-painel-error.log || true