#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath, [Parameter(Mandatory)][switch]$Run)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
if (-not $Run) { throw 'Explicit Run required' }
$c = Read-HostConfig $ConfigPath
$lock = $null
# Guard failures exit successfully to suppress Scheduler's runtime-crash retry.
# A durable refusal artifact requires operator review; it is not a ready signal.
try {
    $lock = Enter-DeploymentLock $c
    $p = Read-ActiveRelease $c
    Wait-PrivateInterface $c
    $null = & (Join-Path $PSScriptRoot 'Test-ProductionPreflight.ps1') -ConfigPath $ConfigPath -ReleasePath $p.releasePath -ManifestSha256 $p.manifestSha256 -Mode Deployment
    $null = Assert-Database $c
    Assert-SourceHead $p.releasePath $c.expectedRevision
    $python = Join-Path $p.releasePath 'backend\.venv\Scripts\python.exe'
    if ($c.pythonPath -ne $python) { throw 'Use final immutable release venv' }
    $env:DATABASE_URL = 'sqlite:///' + $c.database.Replace('\','/')
    $env:SOURCE_ASSET_ROOT = $c.sourceRoot; $env:OUTPUT_ROOT = $c.outputRoot
    $env:PLAYWRIGHT_BROWSERS_PATH = $c.chromium.cacheRoot
    $env:PYTHONDONTWRITEBYTECODE = '1'
} catch {
    if (Test-Path -LiteralPath $c.logsRoot) { Write-Json (Join-Path (New-EvidenceDirectory $c 'backend-refused') 'refused.json') @{refused=$true;operatorReviewRequired=$true} }
    if ($lock) { Exit-DeploymentLock $lock }
    exit 0
}
try {
    Invoke-OwnedProcess $c 'backend' $python @('-B','-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--workers','1','--lifespan','on') (Join-Path $p.releasePath 'backend')
} finally { Exit-DeploymentLock $lock }
