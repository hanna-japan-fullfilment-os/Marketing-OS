#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath, [Parameter(Mandatory)][string]$Repository,
      [Parameter(Mandatory)][string]$ApprovedCommit, [Parameter(Mandatory)][switch]$Stage,
      [Parameter(Mandatory)][switch]$BuildFrontend)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Common.psm1') -Force
if (-not $Stage -or -not $BuildFrontend) { throw 'Explicit staging and build required' }
$c = Read-HostConfig $ConfigPath
if ($ApprovedCommit -ne $c.expectedCommit) { throw 'Unapproved commit' }
Assert-GitIdentity $c $Repository -Clean
$runtime = Read-Json $c.runtimeManifestPath
if (-not $runtime.artifactsApproved -or (Get-Sha256 $c.runtimeManifestPath) -ne $c.runtimeManifestSha256 -or $c.gates.VERIFIED_RUNTIME_ARTIFACTS.approved -ne $true -or (Get-Sha256 $c.gates.VERIFIED_RUNTIME_ARTIFACTS.evidencePath) -ne $c.gates.VERIFIED_RUNTIME_ARTIFACTS.sha256) { throw 'Approve prepared runtime artifacts first; no automatic installs' }
$target = Join-Path $c.releasesRoot $ApprovedCommit
$null = Assert-AbsolutePath $target -MustExist
# Provision dependencies separately under the FINAL release path; never copy a
# venv or install anything here. Existing source/manifest means immutable refusal.
if (Test-Path -LiteralPath (Join-Path $target 'release.json')) { throw 'Immutable release already exists' }
$preparedPython = Join-Path $target 'backend\.venv\Scripts\python.exe'
$null = Assert-AbsolutePath $preparedPython -MustExist
if ($c.pythonPath -ne $preparedPython) { throw 'Configure final immutable release Python path' }
$packages = Invoke-Native $preparedPython @('-B','-c','import importlib.metadata as m,json; print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions()}))') $target | ConvertFrom-Json -AsHashtable
if ($packages.Count -ne $runtime.packages.Count) { throw 'Prepared dependency set differs from frozen runtime' }
foreach ($entry in $runtime.packages.GetEnumerator()) { if ($packages[$entry.Key] -ne $entry.Value) { throw 'Prepared dependency version differs from frozen runtime' } }
foreach ($identity in $c.runtimeFiles) { if ((Get-Sha256 $identity.path) -ne $identity.sha256) { throw 'Prepared runtime hash mismatch' } }
foreach ($required in @($preparedPython,$c.nodePath,$c.npmCliPath,$c.chromium.path)) { if ($required -notin @($c.runtimeFiles | ForEach-Object { $_.path })) { throw 'Prepared runtime approval incomplete' } }
if ((Invoke-Native $preparedPython @('-B','-c','import sys; print(".".join(map(str,sys.version_info[:3])))') $target) -ne $runtime.python.version) { throw 'Prepared Python version mismatch' }
if ($c.runtimeFiles.Count -lt 4 -or (Invoke-Native $c.nodePath @('--version') $target) -ne $runtime.node.version -or (Invoke-Native $c.nodePath @($c.npmCliPath,'--version') $target) -ne $runtime.npm.version) { throw 'Prepared build runtime mismatch' }
$null = Assert-AbsolutePath (Join-Path $target 'frontend\node_modules') -MustExist
foreach ($item in Get-ChildItem -LiteralPath $target -File -Recurse -Force) {
    $relative = [IO.Path]::GetRelativePath($target,$item.FullName).Replace('\','/')
    if ($relative -notmatch '^(backend/\.venv/|frontend/node_modules/)') { throw 'Staging directory contains unapproved content' }
}
$git = (Get-Command git.exe).Source
$files = (Invoke-Native $git @('ls-tree','-r','--name-only',$ApprovedCommit) $Repository) -split "`n"
$allowed = @($files | Where-Object { $_ -match '^(backend/(app/|alembic/|alembic\.ini$|requirements\.txt$)|frontend/(src/|public/|package(-lock)?\.json$|tsconfig[^/]*\.json$|vite\.config\.ts$|index\.html$)|scripts/production/|deployment/windows/)' })
foreach ($file in $allowed) {
    if ($file -match '(?i)(^|/)(\.env[^/]*|data|logs?|backups?|node_modules|\.venv)(/|$)' -or $file -match '(?i)\.(db|sqlite3?|png|jpe?g|webp|gif|mp4|pem|key|pfx)$' -or $file.Contains('..')) { throw 'Sensitive/binary release content refused' }
    $mode = Invoke-Native $git @('ls-tree',$ApprovedCommit,'--',$file) $Repository
    if (-not $mode.StartsWith('100644 ') -and -not $mode.StartsWith('100755 ')) { throw 'Non-regular Git content refused' }
    $destination = Join-Path $target $file
    $null = Assert-AbsolutePath $destination
    if (Test-Path -LiteralPath $destination) { throw 'Staged file already exists' }
    $null = [IO.Directory]::CreateDirectory((Split-Path -Parent $destination))
    # Preserve exact committed bytes, including BOM/newlines. Decode only for
    # validation; never round-trip source through OS newline conversion.
    $bytes = Invoke-Native $git @('show',"${ApprovedCommit}:$file") $Repository -BinaryOutput
    $content = [Text.UTF8Encoding]::new($false,$true).GetString($bytes)
    if ($content -match '(?i)(sk-proj-[A-Za-z0-9_-]{12,}|-----BEGIN .*PRIVATE KEY-----)') { throw 'Credential-like content refused' }
    [IO.File]::WriteAllBytes($destination,$bytes)
}
$oldBase = $env:VITE_API_BASE_URL
try {
    $env:VITE_API_BASE_URL = '/backend'
    $null = Invoke-Native $c.nodePath @($c.npmCliPath,'run','build') (Join-Path $target 'frontend') 600
} finally { $env:VITE_API_BASE_URL = $oldBase }
$null = Assert-AbsolutePath (Join-Path $target 'frontend\dist\index.html') -MustExist
Assert-SourceHead $target $c.expectedRevision
$artifacts = @{}
foreach ($file in Get-ChildItem -LiteralPath $target -File -Recurse -Force) { $artifacts[[IO.Path]::GetRelativePath($target,$file.FullName).Replace('\','/')] = Get-Sha256 $file.FullName }
Write-Json (Join-Path $target 'release.json') @{schemaVersion=1;commit=$ApprovedCommit;tree=$c.expectedTree;revision=$c.expectedRevision;apiBase='/backend';createdUtc=[DateTime]::UtcNow.ToString('o');artifacts=$artifacts}
@{releasePath=$target;manifestSha256=(Get-Sha256 (Join-Path $target 'release.json'));activation=$false} | ConvertTo-Json
