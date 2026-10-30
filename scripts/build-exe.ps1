# Build the Windows desktop app (run from repo root in PowerShell).
# Produces a windowed exe (no console) with the Mtrini logo, then smoke-tests it.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Windows PowerShell 5.1 turns any stderr line from a native tool (pip warnings, PyInstaller INFO logs)
# into a terminating error under "Stop". Run tools with "Continue" and fail on the real exit code.
function Invoke-Tool([scriptblock]$Command) {
  $ErrorActionPreference = "Continue"
  & $Command 2>&1 | ForEach-Object { "$_" }
  if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code ${LASTEXITCODE}: $Command" }
}

Write-Host "== 1/4 logo =="
Invoke-Tool { pip install --quiet pillow }
Invoke-Tool { python scripts\make-logo.py }

Write-Host "== 2/4 frontend =="
Invoke-Tool { npm run build --prefix frontend }

Write-Host "== 3/4 exe =="
Invoke-Tool { pip install --quiet pyinstaller pywebview }
Invoke-Tool { pyinstaller --noconfirm --clean --name MtriniWorkspace --noconsole `
  --icon "assets\logo.ico" --version-file "scripts\version-info.txt" `
  --add-data "frontend\dist;frontend\dist" --add-data "assets\logo.ico;assets" `
  --collect-submodules mtrini `
  --exclude-module torch --exclude-module torchvision --exclude-module torchao `
  --exclude-module transformers --exclude-module tensorflow --exclude-module datasets `
  --exclude-module bitsandbytes --exclude-module triton --exclude-module pandas `
  --exclude-module pyarrow --exclude-module lxml --exclude-module pytest `
  --exclude-module matplotlib `
  backend\desktop.py }

Write-Host "== 4/4 smoke test =="
$healthy = $false
$p = Start-Process -FilePath ".\dist\MtriniWorkspace\MtriniWorkspace.exe" -PassThru
try {
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 4
    try {
      $h = Invoke-WebRequest -Uri "http://localhost:8787/api/health" -TimeoutSec 5
      if ($h.StatusCode -eq 200) { Write-Host "OK: $($h.Content)"; $healthy = $true; break }
    } catch {}
  }
} finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
if (-not $healthy) { throw "Smoke test failed: the app never answered on http://localhost:8787/api/health" }

Write-Host "Done. App: dist\MtriniWorkspace\MtriniWorkspace.exe"
Write-Host "Setup: iscc scripts\setup.iss  -> installer\MtriniWorkspace-Setup-0.8.2.exe"
