#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath, [string]$ReleasePath, [string]$ManifestSha256,
      [ValidateSet('Implementation','Deployment')][string]$Mode = 'Implementation')
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
$c = Read-HostConfig $ConfigPath
$failed = [Collections.Generic.List[string]]::new()
foreach ($gate in @('INDEPENDENT_BACKUP','APPROVED_CADDY','TAILSCALE_IDENTITY_ACL','UNATTENDED_TASK_RIGHTS','FILESYSTEM_ACCESS','ONEDRIVE_AVAILABILITY','VERIFIED_RUNTIME_ARTIFACTS','PRODUCTION_ACCEPTANCE')) {
    try {
        $g = $c.gates[$gate]
        if ($g.approved -ne $true -or -not $g.evidencePath -or (Get-Sha256 $g.evidencePath) -ne $g.sha256) { throw 'Unresolved gate' }
    } catch { $failed.Add($gate) }
}
try {
    if (-not $ReleasePath -or -not $ManifestSha256) { throw 'Approved release required' }
    $null = Read-Release $c $ReleasePath $ManifestSha256
    Assert-SourceHead $ReleasePath $c.expectedRevision
} catch { $failed.Add('APPROVED_RELEASE') }
try {
    if ([Security.Principal.WindowsIdentity]::GetCurrent().Name -ne $c.runtimeAccount) { throw 'Runtime account mismatch' }
    if ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Runtime must not be elevated' }
    $null = Get-ScheduledTask -ErrorAction Stop
    if ((Get-TimeZone).Id -ne 'Tokyo Standard Time') { throw '02:00 JST task requires Tokyo host timezone' }
} catch { $failed.Add('RUNTIME_ACCOUNT_AND_TASKS') }
try {
    Assert-ProductionAssetRoots $c -MustExist
    foreach ($path in @($c.logsRoot,$c.backupRoot,$c.releasesRoot)) { $null = Assert-AbsolutePath $path -MustExist }
    $null = Assert-Database $c
    Assert-NoFailureLatch $c
} catch { $failed.Add('PATHS_DATABASE_SCHEMA') }
try {
    $primary = Get-Partition -DriveLetter ([IO.Path]::GetPathRoot($c.database).Substring(0,1)) -ErrorAction Stop
    $other = Get-Partition -DriveLetter ([IO.Path]::GetPathRoot($c.independentBackupRoot).Substring(0,1)) -ErrorAction Stop
    if ($primary.DiskNumber -eq $other.DiskNumber) { throw 'Backups share primary disk' }
    $disk = Get-Disk -Number $other.DiskNumber -ErrorAction Stop
    if ($disk.IsOffline -or $disk.IsReadOnly -or $disk.BusType -eq 'Unknown') { throw 'Unproven backup storage' }
    $null = Assert-AbsolutePath $c.independentBackupRoot -MustExist
} catch { $failed.Add('INDEPENDENT_BACKUP_DISK') }
try {
    if (-not $c.caddy.approved -or (Get-Sha256 $c.caddy.path) -ne $c.caddy.sha256) { throw 'Caddy identity unresolved' }
    if ((Invoke-Native $c.caddy.path @('version') $PSScriptRoot) -ne $c.caddy.version) { throw 'Caddy version mismatch' }
} catch { $failed.Add('CADDY_IDENTITY') }
try {
    $ip = [Net.IPAddress]::Parse($c.tailscale.ipv4)
    if ($ip.AddressFamily -ne 'InterNetwork' -or $ip.GetAddressBytes()[0] -ne 100 -or $ip.GetAddressBytes()[1] -lt 64 -or $ip.GetAddressBytes()[1] -gt 127) { throw 'Tailnet IPv4 required' }
    if (-not $c.tailscale.hostname -or -not $c.tailscale.aclApproved -or $c.frontendOrigin -ne "http://$($c.tailscale.hostname):8080") { throw 'Unverified private origin' }
    $j = Invoke-Native $c.tailscale.cliPath @('status','--json') $PSScriptRoot | ConvertFrom-Json -AsHashtable
    if ($j.BackendState -ne 'Running' -or $c.tailscale.ipv4 -notin $j.TailscaleIPs -or $j.Self.DNSName.TrimEnd('.') -ne $c.tailscale.hostname.TrimEnd('.')) { throw 'Tailnet identity mismatch' }
    $addresses = @([Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | Where-Object OperationalStatus -EQ 'Up' | ForEach-Object { $_.GetIPProperties().UnicastAddresses.Address.ToString() })
    if ($c.tailscale.ipv4 -notin $addresses) { throw 'Private interface absent' }
} catch { $failed.Add('TAILSCALE_IDENTITY') }
try {
    $runtime = Read-Json $c.runtimeManifestPath
    if ($runtime.artifactsApproved -ne $true -or (Get-Sha256 $c.runtimeManifestPath) -ne $c.runtimeManifestSha256) { throw 'Runtime artifacts not approved' }
    if ($runtime.pathContract.sourceRoot -ne $c.sourceRoot -or $runtime.pathContract.outputRoot -ne $c.outputRoot) { throw 'Effective asset roots must be preserved' }
    foreach ($identity in $c.runtimeFiles) { if ((Get-Sha256 $identity.path) -ne $identity.sha256) { throw 'Runtime hash mismatch' } }
    if ($c.runtimeFiles.Count -lt 4 -or (Get-Sha256 $c.chromium.path) -ne $c.chromium.sha256 -or (Get-Item -LiteralPath $c.chromium.path).VersionInfo.ProductVersion -ne $c.chromium.version) { throw 'Incomplete runtime identity' }
    $v = Invoke-Native $c.pythonPath @('-B','-c','import sys; print(".".join(map(str,sys.version_info[:3])))') $PSScriptRoot
    if ($v -ne $runtime.python.version) { throw 'Python mismatch' }
    $packages = Invoke-Native $c.pythonPath @('-B','-c','import importlib.metadata as m,json; print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions()}))') $PSScriptRoot | ConvertFrom-Json -AsHashtable
    if ($packages.Count -ne $runtime.packages.Count) { throw 'Frozen dependency set mismatch' }
    foreach ($entry in $runtime.packages.GetEnumerator()) { if ($packages[$entry.Key] -ne $entry.Value) { throw 'Frozen dependency version mismatch' } }
    foreach ($required in @($c.pythonPath,$c.nodePath,$c.npmCliPath,$c.chromium.path)) { if ($required -notin @($c.runtimeFiles | ForEach-Object { $_.path })) { throw 'Missing runtime artifact approval' } }
    if ((Invoke-Native $c.nodePath @('--version') $PSScriptRoot) -ne $runtime.node.version -or (Invoke-Native $c.nodePath @($c.npmCliPath,'--version') $PSScriptRoot) -ne $runtime.npm.version) { throw 'Node/npm mismatch' }
    if ((Get-Sha256 $c.chromium.headlessShellPath) -ne $c.chromium.headlessShellSha256) { throw 'Matching headless shell approval missing' }
} catch { $failed.Add('FROZEN_RUNTIME_IDENTITY') }
$result = @{IMPLEMENTATION_READY=$true; DEPLOYMENT_READY=($failed.Count -eq 0); unresolvedGates=@($failed | Sort-Object -Unique)}
$result | ConvertTo-Json -Depth 8
if ($Mode -eq 'Deployment' -and $failed.Count) { throw 'Deployment preflight refused unresolved gates' }
