#!/usr/bin/env bash
#
# Clone QuantDinger-Vue into ./QuantDinger-Vue/ and install Node dependencies.
# The directory is gitignored; safe to re-run (skips clone when already present).
#
# Usage:
#   bash scripts/setup-frontend.sh
#

set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="${FRONTEND_DIR:-$ROOT_DIR/QuantDinger-Vue}"
REPO_URL="${QUANTDINGER_VUE_REPO:-https://github.com/brokermr810/QuantDinger-Vue.git}"

cd "$ROOT_DIR"

if ! command -v git >/dev/null 2>&1; then
  echo "error: git is required" >&2
  exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  if command -v corepack >/dev/null 2>&1; then
    corepack enable pnpm >/dev/null 2>&1 || true
  fi
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "error: pnpm is required (Node.js 18+). Install via: corepack enable pnpm" >&2
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/.git" ]; then
  echo "Cloning QuantDinger-Vue into $FRONTEND_DIR ..."
  git clone "$REPO_URL" "$FRONTEND_DIR"
else
  echo "QuantDinger-Vue already present at $FRONTEND_DIR"
fi

echo "Installing frontend dependencies ..."
(cd "$FRONTEND_DIR" && pnpm install)

echo "Done. Frontend source: $FRONTEND_DIR"
