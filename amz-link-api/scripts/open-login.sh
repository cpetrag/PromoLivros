#!/bin/zsh
set -euo pipefail
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm use 24.17.0
cd "/Volumes/HD 1Tb/Vibecoding/Promo Livros/amz-link-api"
exec npm run login
