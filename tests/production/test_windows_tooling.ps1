#requires -Version 7.4
[CmdletBinding()]
param([string]$TemporaryRoot = [IO.Path]::GetTempPath())
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Import-Module (Join-Path $root 'scripts\production\Common.psm1') -Force
$script:checks = 0
function Check([bool]$Condition, [string]$Name) { if (-not $Condition) { throw "FAILED: $Name" }; $script:checks++ }
function Refuses([scriptblock]$Action, [string]$Name) { $refused=$false; try { $null = & $Action } catch { $refused=$true }; Check $refused $Name }
$TemporaryRoot = Assert-AbsolutePath $TemporaryRoot -MustExist
$temp = Join-Path $TemporaryRoot ('marketing-os-tooling-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -Path $temp -ItemType Directory
try {
    foreach ($f in Get-ChildItem (Join-Path $root 'scripts\production') -File | Where-Object Extension -In '.ps1','.psm1') {
        $tokens=$null; $errors=$null
        $ast = [Management.Automation.Language.Parser]::ParseFile($f.FullName,[ref]$tokens,[ref]$errors)
        Check ($errors.Count -eq 0) ('parse ' + $f.Name)
        Check ([IO.File]::ReadAllText($f.FullName).Contains("`$ErrorActionPreference = 'Stop'")) ('stop policy ' + $f.Name)
        if ($f.Extension -eq '.ps1') {
            Check (@($ast.ParamBlock.Parameters | Where-Object { $_.Name.VariablePath.UserPath -eq 'ConfigPath' -and $_.Extent.Text -match 'Mandatory' }).Count -eq 1) ('explicit config ' + $f.Name)
        }
    }
    Refuses { Assert-AbsolutePath 'relative' } 'relative path'
    Refuses { Assert-AbsolutePath '\\server\share' } 'UNC SQLite path'
    Refuses { Assert-AbsolutePath (Join-Path $temp '..\escape') } 'traversal path'
    Refuses { Assert-AbsolutePath (Join-Path $temp 'absent') -MustExist } 'absent path'
    $assetConfig = Read-Json (Join-Path $root 'deployment\windows\host-config.example.json')
    Assert-ProductionAssetRoots $assetConfig -MustExist
    Check $true 'actual approved OneDrive pair metadata only'
    Check ((Assert-ProductionAssetRoot $assetConfig Source $assetConfig.sourceRoot.ToLowerInvariant() -MustExist) -eq $assetConfig.sourceRoot.ToLowerInvariant()) 'case insensitive approved root identity'
    foreach ($role in @('Source','Output')) {
        $key = if ($role -eq 'Source') { 'sourceRoot' } else { 'outputRoot' }
        Check ((Assert-ProductionAssetRoot $assetConfig $role $assetConfig[$key] -MustExist) -eq $assetConfig[$key]) "actual $role root"
        Refuses { Assert-AbsolutePath $assetConfig[$key] -MustExist } "generic guard still refuses $role cloud path"
    }
    foreach ($bad in @('', 'relative','\\server\share','\\?\C:\Users\wesle','C:\','C:\Users\wesle\..\wesle','C:\bad*','C:\bad:stream','C:\bad|path','C:\bad.','C:\NUL','C:\Users\wesle\OneDriveFake\input','C:\Users\other\OneDrive\Desktop\Marketing Pictures Input',($assetConfig.sourceRoot+'\child'))) {
        Refuses { Assert-ProductionAssetRoot $assetConfig Source $bad } "unsafe asset syntax/identity $bad"
    }
    Refuses { Assert-ProductionAssetRoot $assetConfig Source $assetConfig.outputRoot } 'wrong role substitution'
    $swap = $assetConfig.Clone(); $swap.sourceRoot=$assetConfig.outputRoot; $swap.outputRoot=$assetConfig.sourceRoot
    Refuses { Assert-ProductionAssetRoots $swap } 'swapped production roots'
    $local = $assetConfig.Clone(); $local.environment='isolated-test'
    foreach ($key in @('sourceRoot','outputRoot','releasesRoot','pointerPath','logsRoot','backupRoot','pythonPath','powershellPath','runtimeManifestPath')) { $local[$key]=Join-Path $temp $key }
    $local.database=Join-Path $temp 'data\db.sqlite'
    $null=New-Item -ItemType Directory -Path $local.sourceRoot,$local.outputRoot
    Assert-ProductionAssetRoots $local -MustExist; Check $true 'ordinary isolated asset directories'
    Refuses { Assert-ProductionAssetRoot $local Source (Join-Path $temp 'missing') -MustExist } 'missing required asset'
    foreach ($pair in @(@($local.sourceRoot,$local.sourceRoot),@($local.sourceRoot,(Join-Path $local.sourceRoot 'child')),@((Join-Path $local.outputRoot 'child'),$local.outputRoot))) {
        $bad=$local.Clone();$bad.sourceRoot=$pair[0];$bad.outputRoot=$pair[1]
        Refuses { Assert-ProductionAssetRoots $bad } 'source output equality or ancestry'
    }
    foreach ($key in @('releasesRoot','pointerPath','logsRoot','backupRoot','database','independentBackupRoot','nodePath','npmCliPath')) {
        $bad=$local.Clone();$bad[$key]=$local.sourceRoot
        Refuses { Assert-ProductionAssetRoots $bad } "protected collision $key"
    }
    $bad=$local.Clone();$bad.database=Join-Path $local.sourceRoot 'app.db'
    Refuses { Assert-ProductionAssetRoots $bad } 'protected database directory collision'
    foreach ($key in @('caddy','chromium')) {
        $bad=$local.Clone();$bad[$key]=@{path=$local.sourceRoot}
        Refuses { Assert-ProductionAssetRoots $bad } "protected $key artifact collision"
    }
    # Replace only the module metadata seam in memory; no links/reparse objects are created.
    $module=Get-Module Common
    $originalMetadata = & $module { (Get-Item Function:Get-AssetPathMetadata).ScriptBlock }
    try {
        foreach ($tag in @(0x9000e01au,0x9000601au,0x9000701au)) {
            & $module { param($t) $script:assetTestTag=$t; function script:Get-AssetPathMetadata($Path) { @{Directory=$true;Reparse=($Path -like '*\OneDrive*');LinkType=$null;Tag=$script:assetTestTag} } } $tag
            Assert-ProductionAssetRoots $assetConfig -MustExist; Check $true "approved cloud tag $tag scoped to pair"
        }
        foreach ($tag in @(0xA000000Cu,0xA0000003u,0xA000001Du,0x9000101Au,0x00000001u)) {
            & $module { param($t) $script:assetTestTag=$t }
            Refuses { Assert-ProductionAssetRoots $assetConfig -MustExist } "unknown or redirecting tag $tag"
        }
        & $module { function script:Get-AssetPathMetadata($Path) { @{Directory=$true;Reparse=$true;LinkType='SymbolicLink';Tag=0x9000e01au} } }
        Refuses { Assert-ProductionAssetRoots $assetConfig } 'link type denied even with cloud tag'
        & $module { function script:Get-AssetPathMetadata($Path) { @{Directory=$true;Reparse=$true;LinkType=$null;Tag=$null} } }
        Refuses { Assert-ProductionAssetRoots $assetConfig } 'missing reparse tag refused'
        & $module { function script:Get-AssetPathMetadata($Path) { @{Directory=$true;Reparse=$true;LinkType=$null;Tag=0x9000e01au} } }
        Refuses { Assert-ProductionAssetRoots $assetConfig } 'cloud tag outside approved ancestor chain refused'
        & $module { function script:Get-AssetPathMetadata($Path) { @{Directory=$false;Reparse=$false;LinkType=$null;Tag=$null} } }
        Refuses { Assert-ProductionAssetRoots $assetConfig } 'file used as asset directory refused'
        & $module { function script:Get-AssetPathMetadata($Path) { throw 'fixture metadata read failure' } }
        Refuses { Assert-ProductionAssetRoots $assetConfig } 'metadata failure closed'
    } finally { & $module { param($body) Set-Item Function:script:Get-AssetPathMetadata $body } $originalMetadata }
    $jsonArray = Join-Path $temp 'array.json'
    Write-Json $jsonArray @(@{verified=$true})
    Check ([IO.File]::ReadAllText($jsonArray).TrimStart().StartsWith('[')) 'single manifest array preserved'
    Write-Json $jsonArray @()
    Check ([IO.File]::ReadAllText($jsonArray).Trim() -eq '[]') 'empty JSON array preserved'
    $pointer = Join-Path $temp 'current'
    Set-AtomicPointer $pointer @{schemaVersion=1;commit='first'}
    Check ((Read-Json $pointer).commit -eq 'first') 'initial pointer'
    Set-AtomicPointer $pointer @{schemaVersion=1;commit='second'}
    Check ((Read-Json $pointer).commit -eq 'second') 'atomic pointer replacement'
    $previous = @(Get-ChildItem -LiteralPath $temp -Filter 'current.previous.*')
    Check ($previous.Count -eq 1) 'pointer evidence retained'
    Check ((Read-Json $previous[0].FullName).commit -eq 'first') 'previous pointer intact'
    Set-AtomicPointer $pointer (Read-Json $previous[0].FullName)
    Check ((Read-Json $pointer).commit -eq 'first') 'isolated rollback'

    $commit = 'a' * 40; $tree = 'b' * 40
    $release = Join-Path $temp $commit; $null = New-Item $release -ItemType Directory
    $file = Join-Path $release 'payload.txt'; [IO.File]::WriteAllText($file,'approved')
    $manifest = Join-Path $release 'release.json'
    Write-Json $manifest @{schemaVersion=1;commit=$commit;tree=$tree;revision='e3f4a5c1d001';apiBase='/backend';createdUtc='2026-10-20T00:00:00Z';artifacts=@{'payload.txt'=(Get-Sha256 $file)}}
    $cfg = @{releasesRoot=$temp;expectedCommit=$commit;expectedTree=$tree;expectedRevision='e3f4a5c1d001'}
    $hash = Get-Sha256 $manifest
    $null = Read-Release $cfg $release $hash; Check $true 'verified release'
    Refuses { Read-Release $cfg $release ('0' * 64) } 'unapproved manifest'
    [IO.File]::WriteAllText($file,'changed')
    Refuses { Read-Release $cfg $release $hash } 'changed artifact'
    [IO.File]::WriteAllText($file,'approved')
    [IO.File]::WriteAllText((Join-Path $release 'extra.txt'),'extra')
    Refuses { Read-Release $cfg $release $hash } 'unmanifested artifact'
    Remove-Item -LiteralPath (Join-Path $release 'extra.txt')
    $m = Read-Json $manifest; $m.artifacts=@{'../escape.txt'=('0'*64)}; Write-Json $manifest $m
    Refuses { Read-Release $cfg $release (Get-Sha256 $manifest) } 'manifest traversal'
    $versions = Join-Path $release 'backend\alembic\versions'; $null = New-Item $versions -ItemType Directory -Force
    [IO.File]::WriteAllText((Join-Path $versions 'one.py'),"revision: str = 'one'`ndown_revision = None`n")
    [IO.File]::WriteAllText((Join-Path $versions 'two.py'),"revision: str = 'two'`ndown_revision = 'one'`n")
    Assert-SourceHead $release 'two'; Check $true 'sole migration head'
    Refuses { Assert-SourceHead $release 'one' } 'wrong migration head'
    [IO.File]::WriteAllText((Join-Path $versions 'fork.py'),"revision = 'fork'`ndown_revision = 'one'`n")
    Refuses { Assert-SourceHead $release 'two' } 'multiple migration heads'

    foreach ($kind in @('Backend','Frontend','Backup')) {
        $text = [IO.File]::ReadAllText((Join-Path $root "deployment\windows\tasks\MarketingOS-$kind.xml.template"))
        foreach ($token in @('ACCOUNT','POWERSHELL','CONFIG','TOOLS','RELEASE','MANIFEST_SHA')) { $text=$text.Replace("__${token}__",[Security.SecurityElement]::Escape('fixture & value')) }
        $xml = [xml]$text
        Check ($xml.Task.Principals.Principal.RunLevel -eq 'LeastPrivilege') "$kind least privilege"
        Check ($xml.Task.Settings.MultipleInstancesPolicy -eq 'IgnoreNew') "$kind singleton"
        if ($kind -ne 'Backup') {
            Check ($xml.Task.Settings.RestartOnFailure.Interval -eq 'PT1M' -and $xml.Task.Settings.RestartOnFailure.Count -eq '3') "$kind bounded restart"
            Check ($null -ne $xml.Task.Triggers.BootTrigger) "$kind boot"
        } else {
            Check ($null -eq $xml.Task.Settings.RestartOnFailure) 'backup no retry'
            Check ($xml.Task.Triggers.CalendarTrigger.StartBoundary.EndsWith('T02:00:00')) 'backup 02:00'
        }
    }
    $caddy = [IO.File]::ReadAllText((Join-Path $root 'deployment\windows\Caddyfile.template'))
    Check ($caddy.Contains('handle_path /backend/*')) 'proxy prefix stripping'
    Check ($caddy.Contains('bind 127.0.0.1 __TAILSCALE_IPV4__')) 'private binds'
    Check ($caddy.Contains('try_files {path} /index.html')) 'SPA fallback'
    $example = Read-Json (Join-Path $root 'deployment\windows\host-config.example.json')
    Check (@($example.gates.Values | Where-Object approved -EQ $true).Count -eq 0) 'unresolved deployment gates preserved'
    Check ($null -eq $example.tailscale.hostname -and $null -eq $example.independentBackupRoot) 'unknown resources not invented'
    $python = Join-Path $root 'backend\.venv\Scripts\python.exe'
    $output = Invoke-Native $python @('-B','-c','import sys; sys.stderr.write("ordinary stderr"); print("success")') $temp
    Check ($output -eq 'success') 'native stderr does not cause false failure'
    $raw = Invoke-Native $python @('-B','-c','import sys; sys.stdout.buffer.write(bytes([239,187,191,65,13,10,66,10]))') $temp -BinaryOutput
    Check ([Convert]::ToHexString($raw) -eq 'EFBBBF410D0A420A') 'Git blob byte transport preserves BOM and newlines'
    Refuses { Invoke-Native $python @('-B','-c','raise SystemExit(7)') $temp -EvidenceDirectory $temp } 'native exit code checked'
    Check ((Read-Json (Join-Path $temp 'native-exit.json')).exitCode -eq 7) 'native failure evidence retained'
    $timerNative=[Diagnostics.Stopwatch]::StartNew()
    Refuses { Invoke-Native $python @('-B','-c','import time; print("before timeout",flush=True); time.sleep(20)') $temp 1 -EvidenceDirectory $temp } 'native timeout'
    Check ($timerNative.Elapsed.TotalSeconds -lt 8) 'native timeout bounded'
    Check ((Read-Json (Join-Path $temp 'native-exit.json')).timedOut -eq $true) 'timeout evidence retained'
    Invoke-OwnedProcess @{logsRoot=$temp} 'sim-normal' $python @('-B','-c','print("fixture")') $temp
    $normal = @(Get-ChildItem -LiteralPath $temp -Directory -Filter 'sim-normal-*')[0].FullName
    Check ((Read-Json (Join-Path $normal 'exit.json')).exitCode -eq 0) 'owned normal process evidence'
    Check ((Read-Json (Join-Path $normal 'process.json')).childPid -ne $PID) 'launcher and owned child identities distinguished'
    Refuses { Invoke-OwnedProcess @{logsRoot=$temp} 'sim-crash' $python @('-B','-c','raise SystemExit(2)') $temp } 'runtime crash propagates for bounded Scheduler restart'
    Invoke-OwnedProcess @{logsRoot=$temp} 'sim-stop' $python @('-B','-c','import pathlib,time; p=next(pathlib.Path.cwd().glob("sim-stop-*")); (p/"stop.request").write_text("fixture"); time.sleep(30)') $temp
    $stopped = @(Get-ChildItem -LiteralPath $temp -Directory -Filter 'sim-stop-*')[0].FullName
    $stoppedEvidence = Read-Json (Join-Path $stopped 'exit.json')
    Check ($stoppedEvidence.stopRequested -eq $true) 'intentional stop suppresses crash restart'
    $isolated = Read-Json (Join-Path $root 'deployment\windows\host-config.example.json')
    $isolated.environment = 'isolated-test'
    foreach ($key in @('database','pointerPath','logsRoot','backupRoot','sourceRoot','outputRoot','pythonPath','powershellPath','runtimeManifestPath')) { $isolated[$key] = Join-Path $temp $key }
    # Keep assets outside the protected DB directory under the new role contract.
    $isolated.database=Join-Path $temp 'database\app.db'
    $isolated.releasesRoot=$temp
    # Persistent fixture paths must not be inside its fake immutable release root.
    $isolated.releasesRoot=Join-Path $temp 'releases'
    $fixtureConfig = Join-Path $temp 'host.json'; Write-Json $fixtureConfig $isolated
    $report = & (Join-Path $root 'scripts\production\Test-ProductionPreflight.ps1') -ConfigPath $fixtureConfig -Mode Implementation | ConvertFrom-Json
    Check ($report.IMPLEMENTATION_READY -eq $true -and $report.DEPLOYMENT_READY -eq $false) 'readiness distinction'
    Check ('INDEPENDENT_BACKUP' -in $report.unresolvedGates -and 'PRODUCTION_ACCEPTANCE' -in $report.unresolvedGates) 'deployment blockers preserved'
    Refuses { & (Join-Path $root 'scripts\production\Test-ProductionPreflight.ps1') -ConfigPath $fixtureConfig -Mode Deployment } 'deployment refusal'
    $cloudFixture=$isolated.Clone();$cloudFixture.sourceRoot=$assetConfig.sourceRoot;$cloudFixture.outputRoot=$assetConfig.outputRoot
    $cloudConfig=Join-Path $temp 'cloud-host.json';Write-Json $cloudConfig $cloudFixture
    $cloudReport=& (Join-Path $root 'scripts\production\Test-ProductionPreflight.ps1') -ConfigPath $cloudConfig -Mode Implementation | ConvertFrom-Json
    Check ($cloudReport.IMPLEMENTATION_READY -and -not $cloudReport.DEPLOYMENT_READY) 'actual cloud pair through isolated preflight'
    foreach ($gate in $assetConfig.gates.Keys) { Check ($gate -in $cloudReport.unresolvedGates) "cloud preflight preserves $gate" }
    Refuses { & (Join-Path $root 'scripts\production\Test-ProductionPreflight.ps1') -ConfigPath $cloudConfig -Mode Deployment } 'cloud preflight deployment refusal'
    Refuses { Wait-PrivateInterface $isolated } 'unresolved private gate refuses before wait'
    foreach ($entry in @(@('Start-Backend.ps1','Run'),@('Start-Frontend.ps1','Run'),@('Invoke-DatabaseBackup.ps1','Execute'),@('Set-ActiveRelease.ps1','Activate'),@('Restore-PreviousRelease.ps1','Rollback'),@('Test-ProductionAcceptance.ps1','Execute'))) {
        $parameters=@{ConfigPath=$fixtureConfig;$entry[1]=$false}
        switch ($entry[0]) {
            'Invoke-DatabaseBackup.ps1' { $parameters.ReleasePath=$release; $parameters.ManifestSha256=$hash }
            'Set-ActiveRelease.ps1' { $parameters.ReleasePath=$release; $parameters.ManifestSha256=$hash; $parameters.AuthorizationId='fixture' }
            'Restore-PreviousRelease.ps1' { $parameters.PreviousPointerPath=$pointer; $parameters.PreviousPointerSha256=(Get-Sha256 $pointer); $parameters.AuthorizationId='fixture' }
        }
        Refuses { & (Join-Path $root ('scripts\production\'+$entry[0])) @parameters } ('explicit invocation ' + $entry[0])
    }
    Refuses { & (Join-Path $root 'scripts\production\Invoke-GovernedMigration.ps1') -ConfigPath $fixtureConfig -ReleasePath $release -ManifestSha256 $hash -FromRevision e3f4a5c1d001 -AuthorizedTarget e3f4a5c1d001 -ExpectedDatabaseSha256 $hash -SourceContractPath $manifest -SourceContractSha256 $hash -AuthorizationId fixture -Execute } 'no-op migration refuses before any write'
    $latchRoot = Join-Path $temp 'latches'; $null=New-Item $latchRoot -ItemType Directory
    $attempt = Join-Path $latchRoot 'migration-fixture'; $null=New-Item $attempt -ItemType Directory
    Write-Json (Join-Path $attempt 'attempt-started.json') @{attempt=1}
    Refuses { Assert-NoFailureLatch @{logsRoot=$latchRoot} } 'partial migration blocks startup'
    Write-Json (Join-Path $attempt 'verified.json') @{verified=$true}
    Assert-NoFailureLatch @{logsRoot=$latchRoot}; Check $true 'verified attempt clears operational refusal'
    $timer=[Diagnostics.Stopwatch]::StartNew()
    Refuses { Wait-Ready { $false } 1 } 'bounded readiness'
    Check ($timer.Elapsed.TotalSeconds -lt 5) 'readiness bounded wall time'
    Write-Output "WINDOWS_TOOLING_TESTS=PASS CHECKS=$script:checks"
} finally {
    # Only the freshly created, resolved fixture root may be removed recursively.
    $safe=[IO.Path]::GetFullPath($temp)
    if ((Split-Path -Parent $safe) -ne $TemporaryRoot.TrimEnd('\') -or [IO.Path]::GetFileName($safe) -notmatch '^marketing-os-tooling-[a-f0-9]{32}$') { throw 'Unsafe fixture cleanup' }
    Remove-Item -LiteralPath $safe -Recurse -Force
}
