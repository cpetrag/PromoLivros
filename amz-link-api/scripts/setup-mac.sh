#!/bin/zsh
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm use 24.17.0

cd "/Volumes/HD 1Tb/Vibecoding/Promo Livros/amz-link-api"

echo "node $(node -v)"
echo "npm $(npm -v)"

npm install
npx playwright install chromium

if [[ ! -f .env ]]; then
  token="$(node -e 'console.log(require("crypto").randomBytes(32).toString("hex"))')"
  cat > .env << EOF
PORT=3070
HOST=127.0.0.1
AMZ_TOKEN=${token}
AMZ_STORE_ID=cpetrag0f7-20
AMZ_MARKETPLACE_ID=526970
AMZ_PROFILE_DIR=./amz-profile
HEADLESS=true
MIN_INTERVAL_MS=1500
TAGS_REFRESH_MIN=30
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF
  chmod 600 .env
  echo "ENV_CREATED token_chars=${#token}"
else
  echo "ENV_EXISTS"
fi

if ! command -v pm2 >/dev/null 2>&1; then
  npm install -g pm2
fi

mkdir -p logs
echo "PM2 $(pm2 -v)"
echo "SETUP_OK"
