#!/bin/bash
ROOT="/Volumes/HD 1Tb/Vibecoding/Promo Livros"
cd "$ROOT" || exit 1
export PYTHONUNBUFFERED=1
exec "/Volumes/HD 1Tb/Vibecoding/promo-livros-venv/bin/python" \
  "$ROOT/historico-api/servidor.py" \
  --config "$ROOT/historico-api/config.json"
