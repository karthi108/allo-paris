# Allô Paris dev runner: tests, then server on http://127.0.0.1:8000
Set-Location $PSScriptRoot
. .\.venv\Scripts\Activate.ps1
pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "Tests failed, server not started." -ForegroundColor Red; exit 1 }
uvicorn app.api.main:app --port 8000 --proxy-headers --reload --reload-dir app
