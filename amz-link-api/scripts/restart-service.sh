#!/bin/zsh
set -euo pipefail
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm use 24.17.0 >/dev/null
: > /tmp/amz-boot.log
pm2 restart amz-link-api >/tmp/amz-pm2-restart.txt
sleep 4
echo "---BOOT---"
cat /tmp/amz-boot.log || true
echo "---HEALTH---"
curl -sv --max-time 5 http://127.0.0.1:3070/health || true
echo
