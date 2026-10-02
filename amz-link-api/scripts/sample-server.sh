#!/bin/zsh
set -euo pipefail
pid=$(ps aux | awk '/amz-link-api\/src\/server.js/ && !/awk/ { print $2; exit }')
echo "PID=$pid"
sample "$pid" 1 -file /tmp/amz-sample.txt >/tmp/amz-sample-status.txt 2>&1 || true
echo "SAMPLE_DONE"
# keep the report short
awk 'NR<=60 { print }' /tmp/amz-sample.txt
