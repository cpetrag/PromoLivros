#!/bin/bash
cd "/Volumes/HD 1Tb/Vibecoding/Promo Livros" || exit 1
for f in scripts/*.sh; do
  [ "$f" = "scripts/_diag_mac.sh" ] && continue
  if grep -q $'\r' "$f"; then
    tr -d '\r' < "$f" > "$f.tmp" && cat "$f.tmp" > "$f" && rm -f "$f.tmp"
    echo "corrigido $f"
  fi
done
file scripts/painel_run.sh
for d in "$HOME"/.nvm/versions/node/*/bin; do export PATH="$d:/opt/homebrew/bin:$PATH"; done
pm2 restart promo-livros-painel >/dev/null
sleep 8
pm2 describe promo-livros-painel 2>&1 | grep -E " status | uptime "
curl -s -o /dev/null -w "http %{http_code}\n" http://127.0.0.1:8787/curadoria
