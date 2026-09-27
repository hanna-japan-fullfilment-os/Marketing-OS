# One-time setup for the Marketing Operating System (Windows PowerShell).
# Run from the repo root: .\scripts\setup.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "== Backend: Python virtual environment ==" -ForegroundColor Cyan
Push-Location "$root\backend"
if (-not (Test-Path ".venv")) {
    py -3 -m venv .venv
}
& ".\.venv\Scripts\pip.exe" install --upgrade pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt

Write-Host "Installing Playwright's Chromium (used by the creative pipeline to render campaign images)..." -ForegroundColor Cyan
& ".\.venv\Scripts\playwright.exe" install chromium

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created backend\.env — edit it to set OPENAI_API_KEY, SOURCE_ASSET_ROOT, OUTPUT_ROOT." -ForegroundColor Yellow
}

Write-Host "Applying database migrations..." -ForegroundColor Cyan
& ".\.venv\Scripts\alembic.exe" upgrade head
Pop-Location

Write-Host "== Frontend: npm install ==" -ForegroundColor Cyan
Push-Location "$root\frontend"
npm install
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}
Pop-Location

Write-Host ""
Write-Host "Setup complete. Next steps:" -ForegroundColor Green
Write-Host "  1. Edit backend\.env — set OPENAI_API_KEY, SOURCE_ASSET_ROOT, OUTPUT_ROOT."
Write-Host "  2. Run .\scripts\dev.ps1 to start both servers."
