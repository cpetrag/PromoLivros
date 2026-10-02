#!/bin/bash
# Monta a fila do dia. Não envia WhatsApp.
# O cron do macOS não consegue abrir arquivos neste disco; o launchd do usuário chama este script.
set -u
HOME_LOG="${HOME}/Library/Logs/promo-livros-fila.log"
PROJECT="/Volumes/HD 1Tb/Vibecoding/Promo Livros"
PYTHON="/Volumes/HD 1Tb/Vibecoding/promo-livros-venv/bin/python"
LOCK="/tmp/promo-livros-fila.lock"

mkdir -p "${HOME}/Library/Logs"

if ! mkdir "${LOCK}" 2>/dev/null; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') fila ja em execucao" >> "${HOME_LOG}"
  exit 0
fi
trap 'rmdir "${LOCK}"' EXIT

if ! cd "${PROJECT}"; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') pasta do projeto inacessivel" >> "${HOME_LOG}"
  exit 1
fi
mkdir -p logs

export PYTHONPATH="."
export PYTHONUNBUFFERED=1
set -o pipefail
"${PYTHON}" scripts/fila_do_dia.py 2>&1 | tee -a logs/fila_dia.log >> "${HOME_LOG}"
status=${PIPESTATUS[0]}
echo "$(date '+%Y-%m-%d %H:%M:%S') fila_do_dia exit ${status}" >> "${HOME_LOG}"
exit "${status}"
