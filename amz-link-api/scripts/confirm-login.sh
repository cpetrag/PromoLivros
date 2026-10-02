#!/bin/zsh
set -euo pipefail
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm use 24.17.0 >/dev/null
cd "/Volumes/HD 1Tb/Vibecoding/Promo Livros/amz-link-api"

pids=$(ps aux | awk '/amz-profile/ && /MacOS\/Google Chrome for Testing / && !/Helper/ { print $2 }')
if [[ -n "$pids" ]]; then
  echo "$pids" | while read -r pid; do
    kill "$pid" || true
  done
fi

for _ in {1..20}; do
  if ! ps aux | awk '/scripts\/login.js/ && !/awk/ { found=1 } END { exit !found }'; then
    break
  fi
  sleep 0.5
done

if ps aux | awk '/scripts\/login.js/ && !/awk/ { found=1 } END { exit !found }'; then
  echo "LOGIN_STILL_OPEN"
  exit 1
fi

echo "LOGIN_CLOSED"
node scripts/check-session.js
