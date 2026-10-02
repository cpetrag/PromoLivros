#!/bin/zsh
set -euo pipefail
log=/tmp/amz-login.log
: > "$log"
nohup zsh "/Volumes/HD 1Tb/Vibecoding/Promo Livros/amz-link-api/scripts/open-login.sh" >> "$log" 2>&1 &
echo "PID $!"
