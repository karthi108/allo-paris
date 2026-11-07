# Allô Paris: lint + test, then commit everything and push. Usage: .\ship.ps1 "message"
param([Parameter(Mandatory = $true)][string]$Message)
Set-Location $PSScriptRoot
. .\.venv\Scripts\Activate.ps1
ruff check . ; if ($LASTEXITCODE -ne 0) { exit 1 }
ruff format --check . ; if ($LASTEXITCODE -ne 0) { exit 1 }
mypy app ; if ($LASTEXITCODE -ne 0) { exit 1 }
pytest -q ; if ($LASTEXITCODE -ne 0) { exit 1 }
git add -A
git status --short
git commit -m $Message
git push
