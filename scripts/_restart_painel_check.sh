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
def filled(key):
    return bool((v.get(key) or "").strip())
print("dotenv_ok", True)
print("MAGALU_PROMOTER_ID", "SET" if filled("MAGALU_PROMOTER_ID") else "EMPTY")
print("MAGALU_PARTNER_ID", "SET" if filled("MAGALU_PARTNER_ID") else "EMPTY")
print("AQUI_API_KEY", "SET" if filled("AQUI_API_KEY") else "EMPTY")
print("AQUI_BASE_URL", (v.get("AQUI_BASE_URL") or "").strip() or "EMPTY")
PY
pm2 restart promo-livros-painel
sleep 5
curl -s -o /dev/null -w "curadoria %{http_code}\n" http://127.0.0.1:8787/curadoria
curl -s -o /dev/null -w "hoje %{http_code}\n" http://127.0.0.1:8787/hoje
"$PY" - <<'PY'
from promo_livros.config import load_config
from pathlib import Path
cfg = load_config(Path("config.yaml"))
print("config_ok", True)
print("cfg_magalu_promoter", "SET" if cfg.magalu_promoter_id else "EMPTY")
print("cfg_magalu_partner", "SET" if cfg.magalu_partner_id else "EMPTY")
print("cfg_aqui_key", "SET" if cfg.aqui_api_key else "EMPTY")
print("cfg_aqui_base", cfg.aqui_base_url)
from promo_livros import magalu_links, aqui_links
print("imports_ok", True)
PY
echo "--- error tail ---"
tail -n 12 /Users/cpetrag/.pm2/logs/promo-livros-painel-error.log || true