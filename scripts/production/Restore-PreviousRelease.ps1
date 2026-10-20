#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath, [Parameter(Mandatory)][string]$PreviousPointerPath,
      [Parameter(Mandatory)][string]$PreviousPointerSha256, [Parameter(Mandatory)][string]$AuthorizationId,
      [Parameter(Mandatory)][switch]$Rollback)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
if (-not $Rollback -or -not $AuthorizationId) { throw 'Explicit code rollback authorization required' }
$c = Read-HostConfig $ConfigPath
if ((Get-Sha256 $PreviousPointerPath) -ne $PreviousPointerSha256) { throw 'Previous pointer approval mismatch' }
$p = Read-Json $PreviousPointerPath
# Config must explicitly approve the previous commit/tree and compatible revision.
# This refuses an incompatible code rollback rather than restoring any database.
$null = Read-Release $c $p.releasePath $p.manifestSha256
$null = Assert-Database $c
& (Join-Path $PSScriptRoot 'Set-ActiveRelease.ps1') -ConfigPath $ConfigPath -ReleasePath $p.releasePath -ManifestSha256 $p.manifestSha256 -AuthorizationId $AuthorizationId -Activate
