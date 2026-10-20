#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath, [Parameter(Mandatory)][switch]$Run)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
if (-not $Run) { throw 'Explicit Run required' }
$c = Read-HostConfig $ConfigPath
try {
    $p = Read-ActiveRelease $c
    Wait-PrivateInterface $c
    $null = & (Join-Path $PSScriptRoot 'Test-ProductionPreflight.ps1') -ConfigPath $ConfigPath -ReleasePath $p.releasePath -ManifestSha256 $p.manifestSha256 -Mode Deployment
    Wait-Ready { Get-Health 'http://127.0.0.1:8000/api/health' } 180
    $evidence = New-EvidenceDirectory $c 'caddy-config'
    $template = [IO.File]::ReadAllText((Join-Path $p.releasePath 'deployment\windows\Caddyfile.template'))
    if ($c.tailscale.ipv4 -notmatch '^100\.[0-9.]+$') { throw 'Private binding required' }
    $dist = Join-Path $p.releasePath 'frontend\dist'
    if ($dist.Contains('"') -or $dist.Contains("`n") -or $dist.Contains('`')) { throw 'Unsafe Caddy path' }
    $content = $template.Replace('__TAILSCALE_IPV4__',$c.tailscale.ipv4).Replace('__FRONTEND_DIST__',$dist.Replace('\','/'))
    $config = Join-Path $evidence 'Caddyfile'
    [IO.File]::WriteAllText($config,$content,[Text.UTF8Encoding]::new($false))
    $null = Invoke-Native $c.caddy.path @('validate','--config',$config,'--adapter','caddyfile') $evidence
} catch {
    if (Test-Path -LiteralPath $c.logsRoot) { Write-Json (Join-Path (New-EvidenceDirectory $c 'frontend-refused') 'refused.json') @{refused=$true;operatorReviewRequired=$true} }
    exit 0
}
Invoke-OwnedProcess $c 'frontend' $c.caddy.path @('run','--config',$config,'--adapter','caddyfile') $p.releasePath
