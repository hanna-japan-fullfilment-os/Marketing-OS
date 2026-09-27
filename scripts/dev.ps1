# Starts the backend (FastAPI) and frontend (Vite) dev servers together.
# Run from the repo root: .\scripts\dev.ps1
#
# By default both servers only accept connections from this PC (127.0.0.1 /
# localhost) — nothing changes from before. Pass -Remote to instead bind both
# to 0.0.0.0 (every network interface on this PC), so the app is reachable from
# another device on the same network or over a private VPN like Tailscale —
# see the README's "Access it from your phone or another device" section for
# the full walkthrough (setting VITE_API_BASE_URL / CORS_ORIGINS, Windows
# Firewall, etc. — binding the servers is only one piece of that).
#
#   .\scripts\dev.ps1          # local-only, same as always
#   .\scripts\dev.ps1 -Remote  # reachable from other devices too

param(
    [switch]$Remote
)

$root = Split-Path -Parent $PSScriptRoot
$bindHost = if ($Remote) { "0.0.0.0" } else { "127.0.0.1" }
$frontendExtraArgs = if ($Remote) { "-- --host 0.0.0.0" } else { "" }

$backend = Start-Process -PassThru -NoNewWindow powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$root\backend'; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --host $bindHost --port 8000"
)

$frontend = Start-Process -PassThru -NoNewWindow powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$root\frontend'; npm run dev $frontendExtraArgs"
)

Write-Host "Backend:  http://${bindHost}:8000  (docs at /docs)" -ForegroundColor Green
Write-Host "Frontend: http://${bindHost}:5173" -ForegroundColor Green

if ($Remote) {
    Write-Host ""
    Write-Host "Remote access is ON — both servers are listening on every network" -ForegroundColor Yellow
    Write-Host "interface on this PC, not just localhost. Make sure frontend\.env's" -ForegroundColor Yellow
    Write-Host "VITE_API_BASE_URL and backend\.env's CORS_ORIGINS are set to this PC's" -ForegroundColor Yellow
    Write-Host "Tailscale (or LAN) address before relying on this from another device —" -ForegroundColor Yellow
    Write-Host "see the README." -ForegroundColor Yellow
    $tailscaleIp = & tailscale ip -4 2>$null
    if ($LASTEXITCODE -eq 0 -and $tailscaleIp) {
        Write-Host "Detected Tailscale IP: $tailscaleIp" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Press Ctrl+C in this window to stop both, or close them individually." -ForegroundColor Yellow

Wait-Process -Id $backend.Id, $frontend.Id
