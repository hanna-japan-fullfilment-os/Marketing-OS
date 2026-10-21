#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath, [Parameter(Mandatory)][switch]$Execute)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
if (-not $Execute) { throw 'Explicit acceptance execution required' }
$c = Read-HostConfig $ConfigPath; $p = Read-ActiveRelease $c
$null = & (Join-Path $PSScriptRoot 'Test-ProductionPreflight.ps1') -ConfigPath $ConfigPath -ReleasePath $p.releasePath -ManifestSha256 $p.manifestSha256 -Mode Deployment
$db = Assert-Database $c
Assert-ProductionAssetRoots $c -MustExist
foreach ($root in @($c.sourceRoot,$c.outputRoot)) { $null = Get-ChildItem -LiteralPath $root -ErrorAction Stop | Select-Object -First 1 }
if (-not (Get-Health 'http://127.0.0.1:8000/api/health') -or -not (Get-Health ($c.frontendOrigin + '/backend/api/health'))) { throw 'Health failed' }
if ($c.verifiedFactsProductId -notmatch '^[a-f0-9]{32}$' -or $c.acceptanceStaticPath -notmatch '^/assets/[a-zA-Z0-9._/-]+\.(js|css)$' -or $c.acceptanceStaticPath.Contains('..')) { throw 'Safe acceptance targets required' }
foreach ($path in @('/backend/api/products/' + $c.verifiedFactsProductId + '/verified-facts','/',$c.acceptanceStaticPath,'/brands')) {
    $response = Invoke-WebRequest -Uri ($c.frontendOrigin + $path) -TimeoutSec 10 -MaximumRedirection 0 -NoProxy
    if ($response.StatusCode -ne 200) { throw 'Acceptance GET failed' }
    if ($path -eq '/brands' -and $response.Content -notmatch '<!doctype html>') { throw 'SPA fallback failed' }
    if ($path -eq '/' -or $path -eq '/brands' -or $path -eq $c.acceptanceStaticPath) {
        $relative = if ($path -eq '/' -or $path -eq '/brands') { 'index.html' } else { $path.TrimStart('/') }
        $expectedFile = Join-Path $p.releasePath ('frontend\dist\' + $relative)
        $bodyHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($response.RawContentStream.ToArray()))
        if ($bodyHash -ne (Get-Sha256 $expectedFile)) { throw 'HTTP content differs from approved release artifact' }
    } else {
        $null = $response.Content | ConvertFrom-Json -ErrorAction Stop
    }
}
# Health alone proves neither ASGI lifespan nor provider non-use. Require hashed
# evidence from a separately governed observer for THIS immutable release.
if ((Get-Sha256 $c.startupEvidencePath) -ne $c.startupEvidenceSha256) { throw 'Startup observation evidence required' }
$observed = Read-Json $c.startupEvidencePath
if ($observed.commit -ne $c.expectedCommit -or $observed.manifestSha256 -ne $p.manifestSha256 -or $observed.asgiStartupComplete -ne $true -or $observed.providerCalls -ne 0) { throw 'Startup/provider observation not proven' }
$evidence = New-EvidenceDirectory $c 'acceptance'
Write-Json (Join-Path $evidence 'PASS.json') @{passed=$true;commit=$c.expectedCommit;revision=$db.revision;quick_check=$db.quick_check;startupEvidenceSha256=$c.startupEvidenceSha256;providerWorkflowsExercised=$false}
