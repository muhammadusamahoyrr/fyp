# Attorney.AI -- bring the whole demo up on this laptop.
#
# ORDER MATTERS AND IS THE WHOLE POINT OF THIS SCRIPT.
#
# The backend reads FRONTEND_URL once, at import (config.py: settings =
# Settings()), and that value is baked into every invitation email at send
# time. ngrok's free tier hands out a NEW url on every start. So the tunnel has
# to be up, and its url written to .env, BEFORE the backend starts -- otherwise
# every emailed link points at the previous tunnel, or at localhost, and dies in
# the recipient's inbox with no error anywhere.
#
#   frontend :3000 -> ngrok -> read url -> write .env -> backend :8000
#
# ASCII ONLY, deliberately. Windows PowerShell 5.1 reads a BOM-less file as
# ANSI, which mangles any non-ASCII character -- and a mangled em dash inside a
# string becomes a stray quote and a parse error pages away from the real cause.
#
# PowerShell 5.1 compatible: no &&, no ternary, no ?? operators.

$ErrorActionPreference = 'Stop'

$Root     = Split-Path -Parent $PSScriptRoot
$Backend  = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$EnvFile  = Join-Path $Backend '.env'
$Port     = 3000

function Say([string]$m, [string]$c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Step([string]$m) { Write-Host ''; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok([string]$m)   { Write-Host "    OK  $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "    !!  $m" -ForegroundColor Yellow }
function Die([string]$m)  { Write-Host "    XX  $m" -ForegroundColor Red; exit 1 }

function Test-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $pr = New-Object Security.Principal.WindowsPrincipal($id)
  return $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ALL owners, not the first. Two processes can hold one port at once when they
# bind different addresses: Next binds '::' (dual-stack) while
# EonVPNRoutingService binds '127.0.0.1', and both are listed. Which one a
# client reaches then depends on name resolution -- 'localhost' tries ::1 and
# gets Next, '127.0.0.1' gets the VPN and an empty reply. Looking at only the
# first listener reports whichever happened to be enumerated first and hides
# the conflict entirely.
function Get-PortOwners([int]$p) {
  $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  if (-not $conns) { return @() }
  $procs = @()
  foreach ($c in $conns) {
    $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if ($proc) {
      $procs += [pscustomobject]@{
        Process = $proc; Name = $proc.ProcessName
        Id = $proc.Id; Address = $c.LocalAddress
      }
    }
  }
  return $procs
}

function Get-PortOwner([int]$p) {
  $all = Get-PortOwners $p
  if ($all.Count -eq 0) { return $null }
  return $all[0].Process
}

function Wait-Http([string]$url, [int]$seconds, [string]$label) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 | Out-Null
      return $true
    } catch {
      # Any HTTP response at all means it is listening; only a connection
      # failure means "not up yet". A 401 or 404 is a healthy server.
      if ($_.Exception.Response) { return $true }
    }
    Start-Sleep -Seconds 2
  }
  Warn "$label did not answer within $seconds s"
  return $false
}

Say ''
Say '  Attorney.AI demo launcher' Cyan
Say '  -------------------------' Cyan

# -- 1. Preflight -----------------------------------------------------------
Step 'Checking prerequisites'

if (-not (Test-Path $EnvFile)) { Die 'backend\.env not found' }

# .NET read here too, for the reason spelled out at the write below: reading
# this file as ANSI is how it got double-encoded in the first place.
$envText = [System.IO.File]::ReadAllText($EnvFile)
foreach ($k in @('SMTP_USER', 'SMTP_PASSWORD')) {
  $m = [regex]::Match($envText, "(?m)^$k=(.*)$")
  if (-not $m.Success -or -not $m.Groups[1].Value.Trim()) {
    # Never echoed, only tested for emptiness.
    Warn "$k is empty -- invitations will NOT be emailed (the app will say so)"
  } else {
    Ok "$k is set"
  }
}

$uvicorn = Join-Path $Backend 'venv\Scripts\uvicorn.exe'
if (-not (Test-Path $uvicorn)) { Die "venv uvicorn not found at $uvicorn" }
Ok 'backend venv present'

$ngrokCfg = Join-Path $env:LOCALAPPDATA 'ngrok\ngrok.yml'
if (-not (Test-Path $ngrokCfg)) {
  Die 'ngrok has no authtoken. Run:  npx ngrok config add-authtoken <token>'
}
Ok 'ngrok authenticated'

# -- 2. Free port 3000 ------------------------------------------------------
# EonVPNRoutingService binds 127.0.0.1:3000 and is StartType=Automatic, so it
# reclaims the port on every boot. When it wins, ngrok forwards to IT, and the
# symptom is a 307 redirect loop that looks nothing like a port conflict.
Step "Freeing port $Port"

$owners = Get-PortOwners $Port
foreach ($o in $owners) { Say "    -- $($o.Address) : $($o.Name) (PID $($o.Id))" }

# Handled FIRST and independently of anything else on the port, because the VPN
# and the dev server coexist. Leaving the VPN bound to 127.0.0.1 leaves the demo
# working over 'localhost' and broken over '127.0.0.1', which is the kind of
# half-working that wastes an hour later.
$vpn = @($owners | Where-Object { $_.Name -like 'EonVPN*' })
if ($vpn.Count -gt 0) {
  if (Test-Admin) {
    Stop-Service EonVPNGatewayService, EonVPNRoutingService -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    if (@(Get-PortOwners $Port | Where-Object { $_.Name -like 'EonVPN*' }).Count -gt 0) {
      Die "EonVPN still holds $Port"
    }
    Ok 'EonVPN services stopped'
    Warn 'they are StartType=Automatic and will return after a reboot'
    Warn 'to stop that:  Set-Service EonVPNRoutingService -StartupType Manual'
  } else {
    Warn "EonVPN is bound to 127.0.0.1:$Port -- the demo will work over 'localhost' but not '127.0.0.1'"
    Warn 'Re-run as Administrator to have this handled, or:'
    Warn '  Stop-Service EonVPNGatewayService, EonVPNRoutingService'
  }
}

$others = @($owners | Where-Object { $_.Name -notlike 'EonVPN*' })
if ($others.Count -eq 0) {
  Ok "port $Port is free for the dev server"
} elseif (@($others | Where-Object { $_.Name -eq 'node' }).Count -gt 0) {
  Ok 'a dev server is already on 3000 -- leaving it alone'
} else {
  Die "$Port is held by $($others[0].Name) (PID $($others[0].Id)). Free it and re-run."
}

# -- 3. Frontend ------------------------------------------------------------
Step 'Starting the frontend (:3000)'

$devRunning = @(Get-PortOwners $Port | Where-Object { $_.Name -eq 'node' }).Count -gt 0
if (-not $devRunning) {
  $feCmd = "Set-Location '$Frontend'; Write-Host 'FRONTEND :3000' -ForegroundColor Cyan; npx --no-install next dev -p $Port"
  Start-Process powershell -ArgumentList @('-NoExit', '-Command', $feCmd) | Out-Null
}
if (Wait-Http "http://localhost:$Port/sign" 180 'frontend') { Ok 'frontend answering' }

# -- 4. Tunnel --------------------------------------------------------------
# ONE tunnel, not two: next.config.js rewrites /api/v1/* to the backend
# server-side, so the page and the API share an origin. A second tunnel for
# :8000 would also mean CORS and a second url to keep in sync.
Step 'Starting the ngrok tunnel'

$tunnelUrl = $null
try {
  $t = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 3
  $existing = $t.tunnels | Where-Object { $_.proto -eq 'https' } | Select-Object -First 1
  if ($existing) {
    $tunnelUrl = $existing.public_url
    Ok "reusing the running tunnel: $tunnelUrl"
  }
} catch { }

if (-not $tunnelUrl) {
  $ngCmd = "Write-Host 'NGROK -> localhost:$Port' -ForegroundColor Cyan; npx --yes ngrok@latest http $Port"
  Start-Process powershell -ArgumentList @('-NoExit', '-Command', $ngCmd) | Out-Null

  $deadline = (Get-Date).AddSeconds(60)
  while (((Get-Date) -lt $deadline) -and (-not $tunnelUrl)) {
    Start-Sleep -Seconds 2
    try {
      $t = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 3
      $https = $t.tunnels | Where-Object { $_.proto -eq 'https' } | Select-Object -First 1
      if ($https) { $tunnelUrl = $https.public_url }
    } catch { }
  }
  if (-not $tunnelUrl) { Die 'ngrok did not report a tunnel within 60s' }
  Ok "tunnel up: $tunnelUrl"
}

# -- 5. Point invitation emails at the tunnel -------------------------------
Step 'Writing FRONTEND_URL into backend\.env'

# ONLY WRITE IF THE VALUE ACTUALLY CHANGED. Rewriting unconditionally leaves a
# litter of identical backups, each one a full copy of every secret in .env.
#
# READ AND WRITE VIA .NET, NOT Get-Content/Set-Content. PowerShell 5.1 reads a
# BOM-less file as ANSI (cp1252) and `Set-Content -Encoding UTF8` writes a BOM,
# so the pair silently DOUBLE-ENCODES the file: an em dash in a comment became
# the bytes c3 a2 e2 82 ac e2 80 9d, and 0x9d is undefined in cp1252. Starlette's
# Config -- reached from slowapi's Limiter at import time -- reads .env with the
# locale codec and no encoding argument, so the whole backend died at startup
# with a UnicodeDecodeError pointing at a config file nobody had touched by hand.
#
# UTF8Encoding($false) means "UTF-8, no BOM". ReadAllText detects the encoding
# properly. Together they leave bytes the script did not intend to change alone.
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$envText = [System.IO.File]::ReadAllText($EnvFile)
$current = $null
$m = [regex]::Match($envText, '(?m)^FRONTEND_URL=(.*)$')
if ($m.Success) { $current = $m.Groups[1].Value.Trim() }

if ($current -eq $tunnelUrl) {
  Ok 'FRONTEND_URL already correct, left untouched'
} else {
  $stamp  = [int][double]::Parse((Get-Date -UFormat %s))
  $backup = "$EnvFile.bak.$stamp"
  Copy-Item $EnvFile $backup
  if ($m.Success) {
    $envText = [regex]::Replace($envText, '(?m)^FRONTEND_URL=.*$', "FRONTEND_URL=$tunnelUrl")
  } else {
    $envText = $envText.TrimEnd("`r", "`n") + "`nFRONTEND_URL=$tunnelUrl`n"
  }
  [System.IO.File]::WriteAllText($EnvFile, $envText, $Utf8NoBom)
  Ok "FRONTEND_URL=$tunnelUrl"
  Ok "backup: $(Split-Path -Leaf $backup)"
}


# -- 6. Backend, LAST -------------------------------------------------------
# After the .env write, never before: a running process cannot see the change.
# watchfiles ignores dotfiles, so --reload does NOT pick up .env either.
Step 'Starting the backend (:8000)'

# ALWAYS RESTART A BACKEND WE RECOGNISE, rather than trying to work out whether
# the running one is stale. There is no way to read FRONTEND_URL out of a live
# process, and every proxy for it (file mtimes, process start times) is wrong in
# some ordinary case -- an unrelated .env edit, a re-run that changes nothing.
# Guessing wrong here is silent: the demo works for you and every emailed link
# is dead. A restart costs ~40s and is always right.
$existingApi = Get-PortOwner 8000
if ($existingApi) {
  if (@('python', 'pythonw', 'uvicorn') -contains $existingApi.ProcessName) {
    Warn "restarting the backend (PID $($existingApi.Id)) so it picks up FRONTEND_URL"
    Stop-Process -Id $existingApi.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
  } else {
    Warn ":8000 is held by '$($existingApi.ProcessName)' (PID $($existingApi.Id)) -- not touching it"
    Warn 'if that is not the API, emailed links may point at the previous tunnel'
  }
}

if (-not (Get-PortOwner 8000)) {
  $beCmd = "Set-Location '$Backend'; Write-Host 'BACKEND :8000' -ForegroundColor Cyan; venv\Scripts\uvicorn.exe app.main:app --reload --port 8000"
  Start-Process powershell -ArgumentList @('-NoExit', '-Command', $beCmd) | Out-Null
  if (Wait-Http 'http://127.0.0.1:8000/api/v1/agreements' 240 'backend') { Ok 'backend answering' }
}

# -- 7. Prove the chain, do not assume it -----------------------------------
Step 'Verifying end to end'

$hdr = @{ 'ngrok-skip-browser-warning' = '1' }

$pageOk = $false
try {
  $r = Invoke-WebRequest -Uri "$tunnelUrl/sign" -UseBasicParsing -TimeoutSec 30 -Headers $hdr
  if ($r.StatusCode -eq 200) { $pageOk = $true }
} catch { }
if ($pageOk) { Ok 'signing page loads through the tunnel' }
else { Warn 'signing page did NOT load through the tunnel' }

$apiOk = $false
try {
  Invoke-WebRequest -Uri "$tunnelUrl/api/v1/agreements/invitation/view" -Method POST `
    -UseBasicParsing -TimeoutSec 30 -ContentType 'application/json' `
    -Headers $hdr -Body '{"token":"short"}' | Out-Null
} catch {
  # 422 is the expected answer: the request reached FastAPI and was validated.
  if ($_.Exception.Response -and ([int]$_.Exception.Response.StatusCode -eq 422)) { $apiOk = $true }
}
if ($apiOk) { Ok 'API reachable through the same origin' }
else { Warn 'API did NOT answer through the tunnel' }

Say ''
Say '  ---------------------------------------------' Cyan
Say "   DEMO URL   $tunnelUrl" Green
Say '  ---------------------------------------------' Cyan
Say ''
Say '   Remember:' Yellow
Say '   - replace the [UNREVIEWED SAMPLE] text before sending, or the server refuses it'
Say '   - invitation links expire after 7 days'
Say '   - restarting ngrok changes the URL and kills links already emailed'
Say ''
