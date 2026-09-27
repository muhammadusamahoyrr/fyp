# Attorney.AI -- shut the demo down cleanly.
#
# Stops only what start-demo.ps1 starts: the dev server, the backend and the
# tunnel. It does NOT restart EonVPN -- that service is yours, it is
# StartType=Automatic, and it returns on its own at next boot. To bring it back
# now:  Start-Service EonVPNGatewayService, EonVPNRoutingService
#
# ASCII only, for the reason given at the top of start-demo.ps1.

$ErrorActionPreference = 'Continue'

function Say([string]$m, [string]$c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Ok([string]$m) { Write-Host "    OK  $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "    !!  $m" -ForegroundColor Yellow }

$Safe = @('node', 'python', 'pythonw', 'uvicorn', 'ngrok')

function Stop-Port([int]$p, [string]$label) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
       Select-Object -First 1
  if (-not $c) { Ok "$label -- nothing on $p"; return }

  $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
  if (-not $proc) { Ok "$label -- stale entry on $p"; return }

  # A safety rail, not politeness: :3000 in particular can be held by a VPN
  # routing service, and a blind Stop-Process on whatever owns the port would
  # take down something that has nothing to do with this demo.
  if ($Safe -notcontains $proc.ProcessName) {
    Warn "$label on $p is '$($proc.ProcessName)' (PID $($proc.Id)) -- NOT stopping it"
    return
  }
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  Ok "$label stopped (PID $($proc.Id))"
}

Say ''
Say '  Stopping the Attorney.AI demo' Cyan

Stop-Port 3000 'frontend'
Stop-Port 8000 'backend'

# The tunnel has no fixed port of its own; its agent API on 4040 identifies it.
$c = Get-NetTCPConnection -LocalPort 4040 -State Listen -ErrorAction SilentlyContinue |
     Select-Object -First 1
if ($c) {
  $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
  if ($proc) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Ok "ngrok stopped (PID $($proc.Id))"
  }
} else {
  Ok 'ngrok -- not running'
}

Say ''
Say '  Done. Any link already emailed is now dead, because the tunnel is gone.' Yellow
Say ''
