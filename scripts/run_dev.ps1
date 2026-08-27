# Development startup script (Windows PowerShell)
# Usage: .\scripts\run_dev.ps1

$ErrorActionPreference = "Stop"

$apiDir = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $apiDir
Set-Location $repoRoot

Write-Host ">> Running Alembic migrations..." -ForegroundColor Cyan
alembic upgrade head

Write-Host ">> Starting dev server..." -ForegroundColor Cyan
uvicorn app.main:app --app-dir api --reload --host 0.0.0.0 --port 8000