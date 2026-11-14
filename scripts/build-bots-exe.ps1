# Build the Mtrini Bots desktop app for Windows (run from repo root in PowerShell).
# Produces a windowed exe (no console) with the camel icon, then smoke-tests it.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Windows PowerShell 5.1 turns any stderr line from a native tool into a terminating error under "Stop".
# Run tools with "Continue" and fail on the real exit code.
function Invoke-Tool([scriptblock]$Command) {
  $ErrorActionPreference = "Continue"
  & $Command 2>&1 | ForEach-Object { "$_" }
  if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code ${LASTEXITCODE}: $Command" }
}

Write-Host "== 1/4 icon =="
Invoke-Tool { pip install --quiet pillow }
Invoke-Tool { python scripts\make-bots-icon.py }

Write-Host "== 2/4 screens =="
Invoke-Tool { npm run build --prefix frontend }

Write-Host "== 3/4 exe =="
Invoke-Tool { pip install --quiet pyinstaller pywebview }
Invoke-Tool { pyinstaller --noconfirm --clean --name MtriniBots --noconsole `
  --icon "assets\bots.ico" `
  --add-data "frontend\dist;frontend\dist" --add-data "assets\bots.ico;assets" `
  --paths backend --hidden-import desktop `
  --collect-submodules mtrini `
  --exclude-module torch --exclude-module torchvision --exclude-module torchao `
  --exclude-module transformers --exclude-module tensorflow --exclude-module datasets `
  --exclude-module bitsandbytes --exclude-module triton --exclude-module pandas `
  --exclude-module pyarrow --exclude-module lxml --exclude-module pytest `
  --exclude-module matplotlib --exclude-module zstandard `
  backend\bots_desktop.py }

Write-Host "== 4/4 smoke test =="
if (Get-NetTCPConnection -LocalPort 8789 -State Listen -ErrorAction SilentlyContinue) {
  throw "Port 8789 is in use (is Mtrini Bots running?). Close it so the smoke test checks the new build."
}
$version = (Select-String -Path backend\mtrini\bots\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$healthy = $false
# --background: the server with no window, which is also what runs at sign-in.
$p = Start-Process -FilePath ".\dist\MtriniBots\MtriniBots.exe" -ArgumentList "--background" -PassThru
try {
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 4
    try {
      $h = Invoke-WebRequest -Uri "http://localhost:8789/api/health" -TimeoutSec 5
      if ($h.StatusCode -eq 200 -and $h.Content -like "*`"$version`"*") {
        $page = Invoke-WebRequest -Uri "http://localhost:8789/" -TimeoutSec 5
        if ($page.Content -notlike "*Mtrini Bots*") { throw "The app answered but did not serve the Mtrini Bots screen." }
        Write-Host "OK: $($h.Content)"; $healthy = $true; break
      }
    } catch {}
  }
} finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
if (-not $healthy) { throw "Smoke test failed: the app never answered on http://localhost:8789/api/health" }

Write-Host "Done. App: dist\MtriniBots\MtriniBots.exe"
Write-Host "Setup: iscc scripts\setup-bots.iss  -> installer\MtriniBots-Setup-$version.exe"
