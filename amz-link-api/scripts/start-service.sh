#!/bin/zsh
set -euo pipefail
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm use 24.17.0 >/dev/null
cd "/Volumes/HD 1Tb/Vibecoding/Promo Livros/amz-link-api"
pm2 start ecosystem.config.cjs
pm2 save
for _ in {1..20}; do
  if curl -sf http://127.0.0.1:3070/health; then
    echo
    exit 0
  fi
  sleep 1
done
echo "HEALTH_TIMEOUT"
pm2 logs amz-link-api --nostream --lines 40
exit 1
