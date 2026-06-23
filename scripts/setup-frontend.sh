#!/usr/bin/env bash
#
# Install Node dependencies for QuantDinger-Vue (vendored under ./QuantDinger-Vue/).
#
# Usage:
#   bash scripts/setup-frontend.sh
#

set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="${FRONTEND_DIR:-$ROOT_DIR/QuantDinger-Vue}"

cd "$ROOT_DIR"

if ! command -v pnpm >/dev/null 2>&1; then
  if command -v corepack >/dev/null 2>&1; then
    corepack enable pnpm >/dev/null 2>&1 || true
  fi
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "error: pnpm is required (Node.js 18+). Install via: corepack enable pnpm" >&2
  exit 1
fi

if [ ! -f "$FRONTEND_DIR/package.json" ]; then
  echo "error: frontend source not found at $FRONTEND_DIR" >&2
  exit 1
fi

echo "Installing frontend dependencies ..."
(cd "$FRONTEND_DIR" && pnpm install)

echo "Done. Frontend source: $FRONTEND_DIR"
