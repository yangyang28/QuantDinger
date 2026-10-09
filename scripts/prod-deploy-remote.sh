#!/usr/bin/env bash
# Run on the production host (or via GitHub Actions SSH).
# Usage: ./scripts/prod-deploy-remote.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f docker-compose.ghcr.yml ]]; then
  COMPOSE=(docker compose -f docker-compose.ghcr.yml)
elif [[ -f docker-compose.yml ]]; then
  COMPOSE=(docker compose -f docker-compose.yml)
else
  echo "error: no compose file in $ROOT" >&2
  exit 1
fi

"${COMPOSE[@]}" pull backend frontend
"${COMPOSE[@]}" up -d --no-deps backend frontend
"${COMPOSE[@]}" ps
