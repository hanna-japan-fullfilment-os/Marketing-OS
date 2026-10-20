#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath, [Parameter(Mandatory)][string]$ReleasePath,
      [Parameter(Mandatory)][string]$ManifestSha256, [Parameter(Mandatory)][string]$AuthorizationId,
      [Parameter(Mandatory)][switch]$Install, [Parameter(Mandatory)][PSCredential]$Credential)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
if (-not $Install -or -not $AuthorizationId) { throw 'Explicit task installation required' }
$c = Read-HostConfig $ConfigPath
$null = & (Join-Path $PSScriptRoot 'Test-ProductionPreflight.ps1') -ConfigPath $ConfigPath -ReleasePath $ReleasePath -ManifestSha256 $ManifestSha256 -Mode Deployment
if ($Credential.UserName -ne $c.runtimeAccount) { throw 'Task credential account mismatch' }
$evidence = New-EvidenceDirectory $c 'task-install'
foreach ($kind in @('Backend','Frontend','Backup')) {
    $name = 'MarketingOS-' + $kind
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { throw 'Existing task: separate replacement authorization required' }
}
foreach ($kind in @('Backend','Frontend','Backup')) {
    $name = 'MarketingOS-' + $kind
    $xml = [IO.File]::ReadAllText((Join-Path $ReleasePath "deployment\windows\tasks\$name.xml.template"))
    $values = @{ACCOUNT=$c.runtimeAccount;POWERSHELL=$c.powershellPath;CONFIG=$ConfigPath;TOOLS=(Join-Path $ReleasePath 'scripts\production');RELEASE=$ReleasePath;MANIFEST_SHA=$ManifestSha256}
    foreach ($entry in $values.GetEnumerator()) { $xml = $xml.Replace('__' + $entry.Key + '__',[Security.SecurityElement]::Escape($entry.Value)) }
    if ($xml -match '__[A-Z_]+__') { throw 'Unresolved task template' }
    $null = [xml]$xml
    [IO.File]::WriteAllText((Join-Path $evidence "$name.xml"),$xml,[Text.UTF8Encoding]::new($false))
    # Password is passed in-memory to Windows only; never serialized or logged.
    $plain = $Credential.GetNetworkCredential().Password
    try { $null = Register-ScheduledTask -TaskName $name -Xml $xml -User $c.runtimeAccount -Password $plain -ErrorAction Stop }
    finally { $plain = $null }
}
