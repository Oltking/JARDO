#!/usr/bin/env bash
# Stop the Jardo dev stack started by dev-up.sh. Leaves Docker volumes intact.
set -uo pipefail
cd "$(dirname "$0")/.."

for name in api worker; do
  if [ -f ".run/$name.pid" ]; then
    kill "$(cat ".run/$name.pid")" 2>/dev/null && echo "stopped $name"
    rm -f ".run/$name.pid"
  fi
done
pkill -f "arq core.worker.WorkerSettings" 2>/dev/null || true
pkill -f "uvicorn core.app:app" 2>/dev/null || true

DOCKER="/Applications/Docker.app/Contents/Resources/bin/docker"
[ -x "$DOCKER" ] || DOCKER="docker"
if [ "${1:-}" = "--all" ]; then
  "$DOCKER" compose -f infra/docker-compose.yml down
  echo "stopped postgres/redis (volumes kept)"
else
  echo "left postgres/redis running (use --all to stop them too)"
fi
