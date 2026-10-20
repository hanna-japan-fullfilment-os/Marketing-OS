#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath, [Parameter(Mandatory)][string]$ReleasePath,
      [Parameter(Mandatory)][string]$ManifestSha256, [Parameter(Mandatory)][string]$AuthorizationId,
      [Parameter(Mandatory)][switch]$Activate)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
if (-not $Activate -or -not $AuthorizationId) { throw 'Explicit activation authorization required' }
$c = Read-HostConfig $ConfigPath; $lock = Enter-DeploymentLock $c
try {
    # STOP is an operator-owned prerequisite: never blindly terminate another app.
    Assert-Offline $c
    $null = Read-Release $c $ReleasePath $ManifestSha256
    $null = & (Join-Path $PSScriptRoot 'Test-ProductionPreflight.ps1') -ConfigPath $ConfigPath -ReleasePath $ReleasePath -ManifestSha256 $ManifestSha256 -Mode Deployment
    $null = Assert-Database $c
    $evidence = New-EvidenceDirectory $c 'activation'
    Write-Json (Join-Path $evidence 'authorization.json') @{authorizationId=$AuthorizationId;releasePath=$ReleasePath;manifestSha256=$ManifestSha256}
    $backup = & (Join-Path $PSScriptRoot 'Invoke-DatabaseBackup.ps1') -ConfigPath $ConfigPath -ReleasePath $ReleasePath -ManifestSha256 $ManifestSha256 -Execute | ConvertFrom-Json -AsHashtable
    if ($backup.verified -ne $true -or $backup.independentVerified -ne $true) { throw 'Verified pre-release backup required' }
    Write-Json (Join-Path $evidence 'pre-release-backup.json') $backup
    Set-AtomicPointer $c.pointerPath @{schemaVersion=1;releasePath=$ReleasePath;manifestSha256=$ManifestSha256;commit=$c.expectedCommit}
} finally { Exit-DeploymentLock $lock }
try {
    Start-ScheduledTask -TaskName 'MarketingOS-Backend' -ErrorAction Stop
    Wait-Ready { Get-Health 'http://127.0.0.1:8000/api/health' } 180
    Start-ScheduledTask -TaskName 'MarketingOS-Frontend' -ErrorAction Stop
    Wait-Ready { Get-Health ($c.frontendOrigin + '/backend/api/health') } 180
    & (Join-Path $PSScriptRoot 'Test-ProductionAcceptance.ps1') -ConfigPath $ConfigPath -Execute
} catch {
    Write-Json (Join-Path $evidence 'FAILED-OPERATOR-REVIEW.json') @{failed=$true;automaticRollback=$false;automaticRestore=$false}
    throw 'Activation acceptance failed; operator must stop processes and review evidence'
}
