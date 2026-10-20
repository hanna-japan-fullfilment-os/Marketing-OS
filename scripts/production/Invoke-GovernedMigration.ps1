#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath, [Parameter(Mandatory)][string]$ReleasePath,
      [Parameter(Mandatory)][string]$ManifestSha256, [Parameter(Mandatory)][string]$FromRevision,
      [Parameter(Mandatory)][string]$AuthorizedTarget, [Parameter(Mandatory)][string]$ExpectedDatabaseSha256,
      [Parameter(Mandatory)][string]$SourceContractPath, [Parameter(Mandatory)][string]$SourceContractSha256,
      [Parameter(Mandatory)][string]$AuthorizationId, [Parameter(Mandatory)][switch]$Execute)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
if (-not $Execute -or -not $AuthorizationId -or $FromRevision -eq $AuthorizedTarget) { throw 'Explicit non-noop migration authorization required' }
$c = Read-HostConfig $ConfigPath
if ($AuthorizedTarget -ne $c.expectedRevision) { throw 'Target is not approved release revision' }
$lock = Enter-DeploymentLock $c
$evidence = $null
try {
    Assert-Offline $c
    Assert-NoFailureLatch $c
    foreach ($dir in Get-ChildItem -LiteralPath $c.logsRoot -Directory -Filter 'migration-*') {
        $prior = Join-Path $dir.FullName 'authorization.json'
        if ((Test-Path -LiteralPath $prior) -and (Read-Json $prior).authorizationId -eq $AuthorizationId) { throw 'Authorization already consumed; no migration retry' }
    }
    $null = Read-Release $c $ReleasePath $ManifestSha256
    Assert-SourceHead $ReleasePath $AuthorizedTarget
    if ((Get-Sha256 $c.database) -ne $ExpectedDatabaseSha256 -or (Get-Sha256 $SourceContractPath) -ne $SourceContractSha256) { throw 'Migration source lock mismatch' }
    $evidence = New-EvidenceDirectory $c 'migration'
    Write-Json (Join-Path $evidence 'authorization.json') @{authorizationId=$AuthorizationId;from=$FromRevision;target=$AuthorizedTarget;sourceSha256=$ExpectedDatabaseSha256;manifestSha256=$ManifestSha256}
    $backup = & (Join-Path $PSScriptRoot 'Invoke-DatabaseBackup.ps1') -ConfigPath $ConfigPath -Execute -ReleasePath $ReleasePath -ManifestSha256 $ManifestSha256 -SourceRevision $FromRevision -SourceContractPath $SourceContractPath -SourceContractSha256 $SourceContractSha256 | ConvertFrom-Json -AsHashtable
    if (-not $backup.verified -or -not $backup.independentVerified -or (Get-Sha256 $c.database) -ne $ExpectedDatabaseSha256) { throw 'Backup/source verification failed' }
    $env:DATABASE_URL = 'sqlite:///' + $c.database.Replace('\','/')
    $env:PYTHONDONTWRITEBYTECODE = '1'
    Write-Json (Join-Path $evidence 'attempt-started.json') @{attempt=1;utc=[DateTime]::UtcNow.ToString('o')}
    # Exactly one native invocation. Never stamp, retry, downgrade or restore.
    $output = Invoke-Native $c.pythonPath @('-B','-m','alembic','-c',(Join-Path $ReleasePath 'backend\alembic.ini'),'upgrade',$AuthorizedTarget) (Join-Path $ReleasePath 'backend') 600 -EvidenceDirectory $evidence
    [IO.File]::WriteAllText((Join-Path $evidence 'alembic-stdout.log'),$output,[Text.UTF8Encoding]::new($false))
    $post = Assert-Database $c
    $null = Invoke-Native $c.pythonPath @('-B',(Join-Path $PSScriptRoot 'sqlite_guard.py'),'compare','--database',$c.database,'--reference',$backup.backup) $PSScriptRoot 600
    Write-Json (Join-Path $evidence 'verified.json') @{revision=$post.revision;quick_check=$post.quick_check;sha256=(Get-Sha256 $c.database);backup=$backup.backup;applicationOffline=$true}
} catch {
    if ($evidence) { Write-Json (Join-Path $evidence 'FAILED-KEEP-OFFLINE.json') @{failed=$true;automaticRetry=$false;automaticRestore=$false;separateRestoreAuthorizationRequired=$true} }
    throw 'Migration stopped; preserve evidence and keep application offline. No automatic retry or restore.'
} finally { Exit-DeploymentLock $lock }
