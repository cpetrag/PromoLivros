#!/bin/zsh
export PATH="/Users/cpetrag/.nvm/versions/node/v24.17.0/bin:$PATH"
echo "--- envio ---"
pm2 show promo-livros-envio | head -n 40
echo "--- fila ---"
pm2 show promo-livros-fila | head -n 25
echo "--- web ---"
pm2 show promo-livros-web | head -n 25
echo "--- listen 8787 ---"
lsof -nP -iTCP:8787 -sTCP:LISTEN || true
echo "--- listen 4188 ---"
lsof -nP -iTCP:4188 -sTCP:LISTEN || true
