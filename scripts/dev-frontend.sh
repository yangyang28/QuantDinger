#!/usr/bin/env bash
#
# Local UI development with Vite hot reload (:8000).
# Starts postgres, redis, and backend via Docker; runs pnpm dev in QuantDinger-Vue.
#
# Usage:
#   bash scripts/dev-frontend.sh
#
# Prerequisites:
#   - Docker & Docker Compose
#   - Node.js 18+ and pnpm
#   - backend_api_python/.env (copy from env.example if missing)
#

set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="${FRONTEND_DIR:-$ROOT_DIR/QuantDinger-Vue}"
BACKEND_ENV="$ROOT_DIR/backend_api_python/.env"
HEALTH_URL="${QUANTDINGER_HEALTH_URL:-http://127.0.0.1:5000/api/health}"
MAX_WAIT="${QUANTDINGER_BACKEND_WAIT_SEC:-120}"

cd "$ROOT_DIR"

if [ ! -f "$BACKEND_ENV" ]; then
  echo "error: $BACKEND_ENV not found." >&2
  echo "  cp backend_api_python/env.example backend_api_python/.env" >&2
  echo "  Then edit SECRET_KEY, ADMIN_USER, ADMIN_PASSWORD, etc." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is required" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "error: docker compose is required" >&2
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/.git" ] || [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  bash "$ROOT_DIR/scripts/setup-frontend.sh"
fi

echo "Starting backend stack (postgres, redis, backend) ..."
"${COMPOSE_CMD[@]}" up -d postgres redis backend

echo "Waiting for backend at $HEALTH_URL (up to ${MAX_WAIT}s) ..."
deadline=$((SECONDS + MAX_WAIT))
until curl -sf "$HEALTH_URL" >/dev/null 2>&1; do
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "error: backend did not become healthy in time." >&2
    echo "  ${COMPOSE_CMD[*]} logs -f backend" >&2
    exit 1
  fi
  sleep 2
done

echo "Backend is ready."
echo "Starting Vite dev server at http://localhost:8000 (API proxied to :5000) ..."
cd "$FRONTEND_DIR"
exec pnpm dev
