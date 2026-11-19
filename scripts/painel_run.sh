#!/bin/bash
ROOT="/Volumes/HD 1Tb/Vibecoding/Promo Livros"
cd "$ROOT" || exit 1
export PYTHONUNBUFFERED=1
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "/Volumes/HD 1Tb/Vibecoding/promo-livros-venv/bin/python" -m promo_livros.dashboard
