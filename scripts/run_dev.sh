#!/usr/bin/env bash
# Development startup script (Linux / macOS)
# Usage: bash scripts/run_dev.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo ">> Running Alembic migrations..."
alembic upgrade head

echo ">> Starting dev server..."
uvicorn app.main:app --app-dir api --reload --host 0.0.0.0 --port 8000