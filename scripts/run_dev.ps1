# Development startup script (Windows PowerShell)
# Usage: .\scripts\run_dev.ps1

$ErrorActionPreference = "Stop"

Write-Host ">> Running Alembic migrations..." -ForegroundColor Cyan
alembic upgrade head

Write-Host ">> Starting dev server..." -ForegroundColor Cyan
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
