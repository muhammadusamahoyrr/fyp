# compile.ps1 - full LaTeX build, reports the page count.
# Usage:  powershell -File paper\compile.ps1
#
# Four passes are needed: pdflatex (aux), bibtex (bbl), pdflatex (numbers),
# pdflatex (settle refs/floats). The page count is what gates the length pass,
# so it is printed last and nothing else is printed loudly.

$ErrorActionPreference = "Continue"
$bin = "$env:LOCALAPPDATA\Programs\MiKTeX\miktex\bin\x64"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$log = @()
& "$bin\pdflatex.exe" -interaction=nonstopmode main.tex > $null 2>&1
& "$bin\bibtex.exe" main > "bibtex.out" 2>&1
& "$bin\pdflatex.exe" -interaction=nonstopmode main.tex > $null 2>&1
& "$bin\pdflatex.exe" -interaction=nonstopmode main.tex > $null 2>&1

$logText = Get-Content main.log -Raw

# Real errors only - MiKTeX's "check for updates" nag is not one.
$errors = Select-String -Path main.log -Pattern "^!" | ForEach-Object { $_.Line }
$undef  = Select-String -Path main.log -Pattern "(Citation|Reference) .* undefined" |
          ForEach-Object { $_.Line }
$overfull = (Select-String -Path main.log -Pattern "Overfull \\hbox").Count

if ($errors) { "ERRORS:"; $errors | Select-Object -First 10 }
if ($undef)  { "UNDEFINED:"; $undef  | Select-Object -First 10 }

$pages = if ($logText -match "Output written on main\.pdf \((\d+) pages") { $Matches[1] } else { "?" }
"overfull hboxes : $overfull"
"PAGES           : $pages"
