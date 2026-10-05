# Attorney.AI -- OFFLINE Document Analyzer demo (simulated AI, synthetic documents).
#
#   .\demo\analyzer-demo.ps1 start          # replica set + backend :8765 + frontend :3765
#   .\demo\analyzer-demo.ps1 status
#   .\demo\analyzer-demo.ps1 stop           # stops only what start started
#   .\demo\analyzer-demo.ps1 reset          # lists the demo databases it would drop
#   .\demo\analyzer-demo.ps1 reset --yes
#   .\demo\analyzer-demo.ps1 start --backend-port 8766 --frontend-port 3766
#
# A thin wrapper around backend\scripts\analyzer_demo.py (see DEMO_RUNBOOK.md).
# Unlike start-demo.ps1 it never edits .env or .env.local, starts no tunnel and
# calls no external AI service. ASCII only (Windows PowerShell 5.1).

$ErrorActionPreference = 'Stop'
$Root    = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Python  = Join-Path $Backend 'venv\Scripts\python.exe'

if (-not (Test-Path $Python)) {
  Write-Host "Backend virtual environment not found at $Python" -ForegroundColor Red
  Write-Host "Create it first (see backend\README) and run this again." -ForegroundColor Red
  exit 1
}
if ($args.Count -eq 0) {
  Write-Host 'Usage: .\demo\analyzer-demo.ps1 start|status|stop|reset|fixtures [options]'
  exit 1
}

Push-Location $Backend
try {
  & $Python (Join-Path $Backend 'scripts\analyzer_demo.py') @args
  $code = $LASTEXITCODE
} finally {
  Pop-Location
}
exit $code
