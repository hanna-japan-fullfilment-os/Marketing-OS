#requires -Version 7.4
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script:Utf8 = [System.Text.UTF8Encoding]::new($false, $true)

function Assert-AbsolutePath([string]$Path, [switch]$MustExist) {
    if (-not $Path -or -not [IO.Path]::IsPathFullyQualified($Path) -or $Path.StartsWith('\\')) { throw 'Local absolute path required' }
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -ne $Path.TrimEnd('\') -and $full.TrimEnd('\') -ne $Path.TrimEnd('\')) { throw 'Canonical absolute path required' }
    $item = $full
    while ($item) {
        if (Test-Path -LiteralPath $item) {
            if ((Get-Item -LiteralPath $item -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse paths are forbidden' }
        }
        $parent = [IO.Path]::GetDirectoryName($item)
        if ($parent -eq $item) { break }; $item = $parent
    }
    if ($MustExist -and -not (Test-Path -LiteralPath $full)) { throw 'Required path absent' }
    return $full
}
function Get-Sha256([string]$Path) { (Get-FileHash -LiteralPath (Assert-AbsolutePath $Path -MustExist) -Algorithm SHA256).Hash }
function Read-Json([string]$Path) { [IO.File]::ReadAllText((Assert-AbsolutePath $Path -MustExist), $script:Utf8) | ConvertFrom-Json -AsHashtable }
function Write-Json([string]$Path, $Value) {
    $null = Assert-AbsolutePath $Path
    [IO.File]::WriteAllText($Path, (ConvertTo-Json -InputObject $Value -Depth 40) + "`n", $script:Utf8)
}
function Invoke-Native([string]$File, [string[]]$Arguments, [string]$WorkingDirectory, [ValidateRange(1,900)][int]$TimeoutSeconds = 120, [switch]$Raw, [string]$EvidenceDirectory, [switch]$BinaryOutput) {
    $null = Assert-AbsolutePath $File -MustExist
    $si = [Diagnostics.ProcessStartInfo]::new($File)
    $si.UseShellExecute = $false; $si.RedirectStandardOutput = $true; $si.RedirectStandardError = $true
    $si.StandardOutputEncoding = $script:Utf8; $si.StandardErrorEncoding = $script:Utf8
    if ($WorkingDirectory) { $si.WorkingDirectory = Assert-AbsolutePath $WorkingDirectory -MustExist }
    foreach ($arg in $Arguments) { $si.ArgumentList.Add($arg) }
    $p = [Diagnostics.Process]::new(); $p.StartInfo = $si
    try {
        if (-not $p.Start()) { throw 'Native launch failed' }
        $buffer = $null
        if ($BinaryOutput) { $buffer = [IO.MemoryStream]::new(); $stdout = $p.StandardOutput.BaseStream.CopyToAsync($buffer) }
        else { $stdout = $p.StandardOutput.ReadToEndAsync() }
        $stderr = $p.StandardError.ReadToEndAsync()
        $timedOut = -not $p.WaitForExit($TimeoutSeconds * 1000)
        if ($timedOut) { $p.Kill($true); $p.WaitForExit() }
        if ($BinaryOutput) { $null = $stdout.GetAwaiter().GetResult(); $bytes = $buffer.ToArray(); $buffer.Dispose(); $result = '' }
        else { $result = $stdout.GetAwaiter().GetResult() }
        $errorText = $stderr.GetAwaiter().GetResult()
        if ($EvidenceDirectory) {
            $null = Assert-AbsolutePath $EvidenceDirectory -MustExist
            if ($BinaryOutput) { [IO.File]::WriteAllBytes((Join-Path $EvidenceDirectory 'native-stdout.bin'),$bytes) }
            else { [IO.File]::WriteAllText((Join-Path $EvidenceDirectory 'native-stdout.log'),$result,$script:Utf8) }
            [IO.File]::WriteAllText((Join-Path $EvidenceDirectory 'native-stderr.log'),$errorText,$script:Utf8)
            Write-Json (Join-Path $EvidenceDirectory 'native-exit.json') @{exitCode=$p.ExitCode;timedOut=$timedOut}
        }
        if ($timedOut) { throw 'Native command timed out' }
        if ($p.ExitCode -ne 0) { throw "Native command failed (exit $($p.ExitCode)); output withheld" }
        if ($BinaryOutput) { Write-Output -NoEnumerate $bytes; return }
        if ($Raw) { return $result }
        return $result.Trim()
    } finally { $p.Dispose() }
}
function Read-HostConfig([string]$Path) {
    $c = Read-Json $Path
    foreach ($key in @('database','releasesRoot','pointerPath','logsRoot','backupRoot','sourceRoot','outputRoot','pythonPath','powershellPath','runtimeManifestPath')) { $null = Assert-AbsolutePath $c[$key] }
    if ($c.schemaVersion -ne 1 -or $c.backendHost -ne '127.0.0.1' -or $c.backendPort -ne 8000 -or $c.expectedRevision -ne 'e3f4a5c1d001') { throw 'Unsupported host contract' }
    if ($c.expectedCommit -notmatch '^[0-9a-f]{40}$' -or $c.expectedTree -notmatch '^[0-9a-f]{40}$') { throw 'Approved Git identity required' }
    if ($c.database -ne 'C:\My Apps\marketing-os\marketing-os_4\backend\data\app.db' -and $c.environment -ne 'isolated-test') { throw 'Unapproved canonical target' }
    foreach ($k in @('pointerPath','logsRoot','backupRoot')) { if ($c[$k] -eq $c.database) { throw 'Path collision' } }
    foreach ($k in @('database','sourceRoot','outputRoot','logsRoot','backupRoot','pointerPath')) {
        if ($c[$k].StartsWith($c.releasesRoot.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Persistent state must be outside immutable releases' }
    }
    return $c
}
function Enter-DeploymentLock($Config) {
    $name = 'Global\MarketingOS-' + [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($script:Utf8.GetBytes($Config.database.ToLowerInvariant())))
    $m = [Threading.Mutex]::new($false, $name)
    if (-not $m.WaitOne(0)) { $m.Dispose(); throw 'Deployment operation already active' }
    return $m
}
function Exit-DeploymentLock($Mutex) { $Mutex.ReleaseMutex(); $Mutex.Dispose() }
function Assert-GitIdentity($Config, [string]$Repository, [switch]$Clean) {
    $git = (Get-Command git.exe -ErrorAction Stop).Source
    if ((Invoke-Native $git @('rev-parse','HEAD') $Repository) -ne $Config.expectedCommit -or (Invoke-Native $git @('rev-parse','HEAD^{tree}') $Repository) -ne $Config.expectedTree) { throw 'Git identity mismatch' }
    if ($Clean -and (Invoke-Native $git @('--no-optional-locks','status','--porcelain=v1','--untracked-files=all') $Repository)) { throw 'Source must be clean' }
}
function Read-Release($Config, [string]$ReleasePath, [string]$ManifestSha256) {
    $root = Assert-AbsolutePath $ReleasePath -MustExist
    if ($root -ne (Join-Path $Config.releasesRoot $Config.expectedCommit)) { throw 'Release path identity mismatch' }
    $manifestPath = Join-Path $root 'release.json'
    if ($ManifestSha256 -notmatch '^[A-Fa-f0-9]{64}$' -or (Get-Sha256 $manifestPath) -ne $ManifestSha256) { throw 'Manifest approval mismatch' }
    $m = Read-Json $manifestPath
    if ($m.schemaVersion -ne 1 -or $m.commit -ne $Config.expectedCommit -or $m.tree -ne $Config.expectedTree -or $m.revision -ne $Config.expectedRevision -or $m.apiBase -ne '/backend' -or $m.artifacts.Count -eq 0) { throw 'Release contract mismatch' }
    foreach ($entry in $m.artifacts.GetEnumerator()) {
        if ([IO.Path]::IsPathRooted($entry.Key) -or $entry.Key -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe artifact path' }
        $p = Assert-AbsolutePath (Join-Path $root $entry.Key) -MustExist
        if (-not $p.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or (Get-Sha256 $p) -ne $entry.Value) { throw 'Release artifact mismatch' }
    }
    $actual = @(Get-ChildItem -LiteralPath $root -File -Recurse -Force | Where-Object { $_.FullName -ne $manifestPath } | ForEach-Object { [IO.Path]::GetRelativePath($root, $_.FullName).Replace('\','/') })
    if (@(Compare-Object @($m.artifacts.Keys | Sort-Object) @($actual | Sort-Object)).Count) { throw 'Unmanifested release content' }
    return $m
}
function Read-ActiveRelease($Config) {
    $p = Read-Json $Config.pointerPath
    if ($p.schemaVersion -ne 1 -or $p.commit -ne $Config.expectedCommit) { throw 'Active pointer identity mismatch' }
    $null = Read-Release $Config $p.releasePath $p.manifestSha256
    return $p
}
function Set-AtomicPointer([string]$Path, $Pointer) {
    $null = Assert-AbsolutePath $Path
    $parent = Split-Path -Parent $Path; $null = Assert-AbsolutePath $parent -MustExist
    $temp = Join-Path $parent ('.pointer-' + [guid]::NewGuid().ToString('N'))
    Write-Json $temp $Pointer
    # Flush content before an atomic same-volume namespace change. Retain old
    # pointer as explicit rollback evidence; never remove a previous backup.
    $stream = [IO.File]::Open($temp, 'Open', 'ReadWrite', 'None')
    try { $stream.Flush($true) } finally { $stream.Dispose() }
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temp, $Path, "$Path.previous.$([guid]::NewGuid().ToString('N'))", $false) }
    else { [IO.File]::Move($temp, $Path) }
}
function Assert-Database($Config, [string]$Revision = $Config.expectedRevision) {
    $null = Assert-AbsolutePath $Config.database -MustExist
    $text = Invoke-Native $Config.pythonPath @('-B', (Join-Path $PSScriptRoot 'sqlite_guard.py'), 'inspect', '--database', $Config.database, '--revision', $Revision, '--contract', $Config.runtimeManifestPath) $PSScriptRoot
    return ($text | ConvertFrom-Json -AsHashtable)
}
function Assert-SourceHead([string]$ReleasePath, [string]$Revision) {
    $heads = @{}; $parents = @()
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $ReleasePath 'backend\alembic\versions') -Filter '*.py') {
        $text = [IO.File]::ReadAllText($file.FullName, $script:Utf8)
        $r = [regex]::Match($text, '(?m)^revision(?:\s*:\s*str)?\s*=\s*["'']([a-z0-9]+)["'']')
        $d = [regex]::Match($text, '(?ms)^down_revision[^=]*=\s*["'']([a-z0-9]+)["'']')
        if (-not $r.Success -or $heads.ContainsKey($r.Groups[1].Value)) { throw 'Unparseable or duplicate migration identity' }
        $heads[$r.Groups[1].Value] = $true
        if ($d.Success) { $parents += $d.Groups[1].Value }
    }
    $remaining = @($heads.Keys | Where-Object { $_ -notin $parents })
    if ($remaining.Count -ne 1 -or $remaining[0] -ne $Revision) { throw 'Release Alembic head mismatch' }
}
function Wait-Ready([scriptblock]$Probe, [ValidateRange(1,300)][int]$Seconds = 180) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    do { if (& $Probe) { return }; Start-Sleep -Milliseconds 500 } while ($timer.Elapsed.TotalSeconds -lt $Seconds)
    throw 'Bounded readiness timeout'
}
function Wait-PrivateInterface($Config) {
    foreach ($gate in $Config.gates.Values) { if ($gate.approved -ne $true) { throw 'Resolve deployment gates before boot startup' } }
    $ip = [Net.IPAddress]::Parse($Config.tailscale.ipv4)
    if ($ip.AddressFamily -ne 'InterNetwork' -or $ip.GetAddressBytes()[0] -ne 100 -or $ip.GetAddressBytes()[1] -lt 64 -or $ip.GetAddressBytes()[1] -gt 127) { throw 'Approved tailnet IPv4 required' }
    Wait-Ready {
        $addresses = @([Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | Where-Object OperationalStatus -EQ 'Up' | ForEach-Object { $_.GetIPProperties().UnicastAddresses.Address.ToString() })
        return $Config.tailscale.ipv4 -in $addresses
    } 180
}
function Get-Health([string]$Uri) {
    try { $r = Invoke-WebRequest -Uri $Uri -TimeoutSec 3 -MaximumRedirection 0 -NoProxy; return ($r.StatusCode -eq 200 -and ($r.Content | ConvertFrom-Json).status -eq 'ok') } catch { return $false }
}
function New-EvidenceDirectory($Config, [string]$Operation) {
    $root = Assert-AbsolutePath $Config.logsRoot -MustExist
    $path = Join-Path $root ($Operation + '-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $path
    return $path
}
function Assert-Offline($Config) {
    foreach ($name in @('MarketingOS-Backend','MarketingOS-Frontend')) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
        if ($task.State -eq 'Running') { throw 'Quiesce and stop production tasks first' }
    }
    if (@(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object LocalPort -EQ $Config.backendPort).Count) { throw 'Backend listener still active' }
}
function Assert-NoFailureLatch($Config) {
    if (-not (Test-Path -LiteralPath $Config.logsRoot)) { throw 'Evidence root absent' }
    foreach ($dir in Get-ChildItem -LiteralPath $Config.logsRoot -Directory -Filter 'migration-*') {
        if ((Test-Path -LiteralPath (Join-Path $dir.FullName 'attempt-started.json')) -and -not (Test-Path -LiteralPath (Join-Path $dir.FullName 'verified.json'))) { throw 'Unresolved migration attempt: keep offline' }
    }
}
function Invoke-OwnedProcess($Config, [string]$Name, [string]$Executable, [string[]]$Arguments, [string]$Directory) {
    $evidence = New-EvidenceDirectory $Config $Name
    $si = [Diagnostics.ProcessStartInfo]::new((Assert-AbsolutePath $Executable -MustExist))
    $si.WorkingDirectory = Assert-AbsolutePath $Directory -MustExist; $si.UseShellExecute = $false
    $si.RedirectStandardOutput = $true; $si.RedirectStandardError = $true
    foreach ($arg in $Arguments) { $si.ArgumentList.Add($arg) }
    $p = [Diagnostics.Process]::new(); $p.StartInfo = $si
    $out = [IO.File]::Create((Join-Path $evidence 'stdout.log')); $err = [IO.File]::Create((Join-Path $evidence 'stderr.log'))
    $started = $false
    $stopRequested = $false; $forcedTermination = $false
    try {
        if (-not $p.Start()) { throw 'Runtime failed to start' }
        $started = $true
        Write-Json (Join-Path $evidence 'process.json') @{launcherPid=$PID;childPid=$p.Id;startUtc=$p.StartTime.ToUniversalTime().ToString('o');executable=$Executable;release=$Directory}
        $a = $p.StandardOutput.BaseStream.CopyToAsync($out); $b = $p.StandardError.BaseStream.CopyToAsync($err)
        # Stop requests are per-run files; no PID-only kill of an unrelated process.
        while (-not $p.WaitForExit(500)) {
            if (Test-Path -LiteralPath (Join-Path $evidence 'stop.request')) {
                $stopRequested = $true
                # Console children may not expose a window. Give graceful close a
                # bounded opportunity, then terminate only this owned process tree.
                $null = $p.CloseMainWindow()
                if (-not $p.WaitForExit(15000)) { $forcedTermination = $true; $p.Kill($true); $p.WaitForExit() }
            }
        }
        $null = $a.GetAwaiter().GetResult(); $null = $b.GetAwaiter().GetResult()
        Write-Json (Join-Path $evidence 'exit.json') @{exitCode=$p.ExitCode;stopRequested=$stopRequested;forcedTermination=$forcedTermination;utc=[DateTime]::UtcNow.ToString('o')}
        if ($p.ExitCode -ne 0 -and -not $stopRequested) { throw 'Runtime crash' }
    } finally { if ($started -and -not $p.HasExited) { $p.Kill($true); $p.WaitForExit() }; $out.Dispose(); $err.Dispose(); $p.Dispose() }
}
Export-ModuleMember -Function *
