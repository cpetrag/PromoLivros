#!/bin/bash
cd "/Volumes/HD 1Tb/Vibecoding/Promo Livros" || exit 1
export PYTHONUNBUFFERED=1
exec "/Volumes/HD 1Tb/Vibecoding/promo-livros-venv/bin/python" scripts/enviar_fila.py
