#!/usr/bin/env bash
# Bring up the full JARVIS dev stack (spec §9 demo prerequisites).
# Idempotent: safe to run repeatedly. Nothing here needs an API key.
set -euo pipefail
cd "$(dirname "$0")/.."

DOCKER="/Applications/Docker.app/Contents/Resources/bin/docker"
[ -x "$DOCKER" ] || DOCKER="docker"   # fall back to PATH if Desktop moved

echo "==> Postgres + Redis (docker compose)"
"$DOCKER" compose -f infra/docker-compose.yml up -d
for i in $(seq 1 24); do
  healthy=$("$DOCKER" compose -f infra/docker-compose.yml ps --format '{{.Status}}' \
            | grep -c healthy || true)
  [ "$healthy" = "2" ] && break
  sleep 2
done
echo "    postgres/redis healthy"

echo "==> DB migrations (alembic upgrade head)"
.venv/bin/python -m alembic upgrade head >/dev/null

echo "==> Ollama (local model tier)"
if ! curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  brew services start ollama >/dev/null 2>&1 || ollama serve >/dev/null 2>&1 &
  for i in $(seq 1 15); do
    curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi
model=$(.venv/bin/python -c "from core.router.router import RouterConfig; \
print(RouterConfig.load().tiers.get('ollama_local',''))")
if ! ollama list 2>/dev/null | grep -q "${model%%:*}"; then
  echo "    pulling local model $model ..."
  ollama pull "$model" >/dev/null 2>&1 || echo "    (pull failed — remote tier still works with a key)"
fi
echo "    ollama up (model: $model)"

echo "==> API + worker"
mkdir -p .run
if ! curl -s --max-time 2 http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
  .venv/bin/python -m uvicorn core.app:app --host 127.0.0.1 --port 8000 \
    >.run/api.log 2>&1 &
  echo $! >.run/api.pid
  for i in $(seq 1 20); do
    curl -s --max-time 2 http://127.0.0.1:8000/healthz >/dev/null 2>&1 && break
    sleep 1
  done
fi
if ! pgrep -f "arq core.worker.WorkerSettings" >/dev/null 2>&1; then
  .venv/bin/python -m arq core.worker.WorkerSettings >.run/worker.log 2>&1 &
  echo $! >.run/worker.pid
fi

echo
echo "JARVIS dev stack is up:"
curl -s http://127.0.0.1:8000/healthz | sed 's/^/    health: /'
echo "    api log:    .run/api.log     (stop: scripts/dev-down.sh)"
echo "    worker log: .run/worker.log"
echo "    next: 'uv run jarvis chat' (CLI) or 'pnpm tauri dev' in desktop/ (GUI)"
