#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath, [Parameter(Mandatory)][switch]$Execute,
      [Parameter(Mandatory)][string]$ReleasePath, [Parameter(Mandatory)][string]$ManifestSha256,
      [string]$SourceRevision, [string]$SourceContractPath, [string]$SourceContractSha256,
      [switch]$ApplyRetention)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
if (-not $Execute) { throw 'Explicit backup execution required' }
$c = Read-HostConfig $ConfigPath
$null = Read-Release $c $ReleasePath $ManifestSha256
$null = Assert-AbsolutePath $c.backupRoot -MustExist
$null = Assert-AbsolutePath $c.independentBackupRoot -MustExist
$gate = $c.gates.INDEPENDENT_BACKUP
if ($gate.approved -ne $true -or (Get-Sha256 $gate.evidencePath) -ne $gate.sha256) { throw 'Independent backup evidence required' }
$a = Get-Partition -DriveLetter ([IO.Path]::GetPathRoot($c.database).Substring(0,1)) -ErrorAction Stop
$b = Get-Partition -DriveLetter ([IO.Path]::GetPathRoot($c.independentBackupRoot).Substring(0,1)) -ErrorAction Stop
if ($a.DiskNumber -eq $b.DiskNumber) { throw 'Same disk is not independent protection' }
if ($SourceRevision) {
    if (-not $SourceContractPath -or (Get-Sha256 $SourceContractPath) -ne $SourceContractSha256) { throw 'Source contract approval required' }
    $contract = $SourceContractPath; $revision = $SourceRevision
} else { $contract = $c.runtimeManifestPath; $revision = $c.expectedRevision }
$evidence = New-EvidenceDirectory $c 'backup'
$destination = Join-Path $c.backupRoot ('marketing-os-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [guid]::NewGuid().ToString('N') + '.db')
$result = Invoke-Native $c.pythonPath @('-B',(Join-Path $PSScriptRoot 'sqlite_guard.py'),'backup','--database',$c.database,'--revision',$revision,'--contract',$contract,'--destination',$destination) $PSScriptRoot 600 | ConvertFrom-Json -AsHashtable
Write-Json (Join-Path $evidence 'local-backup.json') $result
$independent = Join-Path $c.independentBackupRoot ([IO.Path]::GetFileName($destination))
$null = Assert-AbsolutePath $independent
if (Test-Path -LiteralPath $independent) { throw 'Independent backup collision' }
[IO.File]::Copy($destination,$independent,$false)
if ((Get-Sha256 $independent) -ne $result.sha256) { throw 'Independent copy hash mismatch' }
$null = Invoke-Native $c.pythonPath @('-B',(Join-Path $PSScriptRoot 'sqlite_guard.py'),'inspect','--database',$independent,'--revision',$revision,'--contract',$contract) $PSScriptRoot 600
$result.independentPath = $independent; $result.independentVerified = $true
Write-Json "$destination.json" $result
Write-Json "$independent.json" $result
Write-Json (Join-Path $evidence 'verified.json') $result
# Retention applies only to this tool's verified manifests and copies. Unknown
# files and the V3.45 backup outside these roots are never deletion candidates.
$manifests = @()
foreach ($file in Get-ChildItem -LiteralPath $c.backupRoot -Filter 'marketing-os-*.db.json' -File) {
    $m = Read-Json $file.FullName
    if ($m.verified -ne $true -or $m.independentVerified -ne $true) { throw 'Unverified retention input' }
    $manifests += $m
}
$inputFile = Join-Path $evidence 'retention-input.json'; Write-Json $inputFile @($manifests)
$candidates = @(Invoke-Native $c.pythonPath @('-B',(Join-Path $PSScriptRoot 'sqlite_guard.py'),'retention','--manifests',$inputFile) $PSScriptRoot | ConvertFrom-Json)
Write-Json (Join-Path $evidence 'retention-plan.json') @($candidates)
if ($ApplyRetention) {
    foreach ($candidate in $candidates) {
        $m = Read-Json "$candidate.json"
        foreach ($pair in @(@($candidate,$c.backupRoot), @($m.independentPath,$c.independentBackupRoot))) {
            $p = Assert-AbsolutePath $pair[0] -MustExist
            if ((Split-Path -Parent $p) -ne $pair[1] -or [IO.Path]::GetFileName($p) -notmatch '^marketing-os-[0-9TZ]+-[a-f0-9]{32}\.db$' -or (Get-Sha256 $p) -ne $m.sha256) { throw 'Unsafe retention target' }
        }
        # Record deletion intent first. An interrupted deletion requires review.
        Write-Json (Join-Path $evidence ([IO.Path]::GetFileName($candidate) + '.deletion.json')) $m
        foreach ($p in @($candidate,$m.independentPath)) { Remove-Item -LiteralPath $p; Remove-Item -LiteralPath "$p.json" }
    }
}
$result | ConvertTo-Json -Depth 20
