# Runs the backend test suite (including the source-asset immutability safety test).
# Run from the repo root: .\scripts\test.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
& ".\.venv\Scripts\python.exe" -m pytest tests/ -v
Pop-Location
