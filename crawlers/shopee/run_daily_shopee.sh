#!/bin/bash
# Chamado pelo launchd (com.cpetrag.shopee-livros) às 05:40, depois do coletor do ML.
set -u
NODE_BIN="$HOME/.nvm/versions/node/v24.17.0/bin"
export PATH="$NODE_BIN:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
cd "$HOME/shopee-crawler" || exit 1
mkdir -p logs
STAMP=$(date +%Y-%m-%d)
LOG="logs/shopee-${STAMP}.log"
{
  echo "START $(date '+%Y-%m-%dT%H:%M:%S%z')"
  node shopee-livros.mjs
  EC=$?
  echo "END $(date '+%Y-%m-%dT%H:%M:%S%z') exit=$EC"
} >> "$LOG" 2>&1
# Mantém 30 dias de logs.
find logs -name 'shopee-*' -mtime +30 -delete 2>/dev/null
exit "${EC:-1}"
