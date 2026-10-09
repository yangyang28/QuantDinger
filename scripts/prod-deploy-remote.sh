#!/usr/bin/env bash
# Run on the production host (or via GitHub Actions SSH).
# Usage: ./scripts/prod-deploy-remote.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

git fetch origin
git checkout main
git pull --ff-only origin main
docker compose up -d --build backend frontend
docker compose ps
