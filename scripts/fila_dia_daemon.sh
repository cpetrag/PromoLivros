#!/bin/bash
# Fica no ar pelo pm2, que consegue gravar no disco. O cron do macOS não consegue.
# Na subida, depois das 5h, monta a fila se ela ainda não existe. Depois disso, todo dia às 5h.
set -u
PROJECT="/Volumes/HD 1Tb/Vibecoding/Promo Livros"
JOB="${PROJECT}/scripts/fila_dia_job.sh"

cd "${PROJECT}"
mkdir -p logs

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a logs/fila_dia.log
}

seconds_until_five() {
  /usr/bin/python3 - <<'PY'
from datetime import datetime, timedelta
now = datetime.now()
target = now.replace(hour=5, minute=0, second=5, microsecond=0)
if now >= target:
    target += timedelta(days=1)
print(int((target - now).total_seconds()))
PY
}

run_once() {
  log "iniciando montagem da fila"
  /bin/bash "${JOB}" || log "montagem terminou com erro"
}

log "agendador da fila no ar"
hour="$(date +%H)"
if [ "${hour}" -ge 5 ]; then
  run_once
fi

while true; do
  delay="$(seconds_until_five)"
  if [ "${delay}" -lt 30 ]; then
    delay=30
  fi
  sleep "${delay}"
  hour="$(date +%H)"
  minute="$(date +%M)"
  if [ "${hour}" -eq 5 ] && [ "${minute}" -lt 15 ]; then
    run_once
    sleep 3600
  fi
done
