#!/usr/bin/env bash
# Development startup script (Linux / macOS)
# Usage: bash scripts/run_dev.sh

set -euo pipefail

echo ">> Running Alembic migrations..."
alembic upgrade head

echo ">> Starting dev server..."
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
