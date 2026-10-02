#!/bin/zsh
set -euo pipefail
pid=$(ps aux | awk '/amz-link-api\/src\/server.js/ && !/awk/ { print $2; exit }')
echo "PID=$pid"
lsof -nP -p "$pid" > /tmp/amz-fds.txt
echo "FD_LINES=$(wc -l < /tmp/amz-fds.txt)"
grep TCP /tmp/amz-fds.txt || echo NO_TCP
echo "---ENV---"
grep -E '^(HOST|PORT|HEADLESS|AMZ_STORE_ID|AMZ_MARKETPLACE_ID)=' "/Volumes/HD 1Tb/Vibecoding/Promo Livros/amz-link-api/.env" | od -c | head -40
