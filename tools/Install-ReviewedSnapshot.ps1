[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,
    [string]$SourceBundle = (Join-Path $PSScriptRoot 'artifacts\formfiller-clean-source'),
    [string]$PythonPath,
    [string]$SourceRoot = (Join-Path $PSScriptRoot '..'),
    [switch]$InstallDependencies
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$sourceRootFull = (Resolve-Path -LiteralPath $SourceRoot).Path
$destinationFull = [System.IO.Path]::GetFullPath($Destination)
if ($destinationFull.Equals($repoRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $destinationFull.StartsWith($repoRoot.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Install destination must be outside the editable source checkout.'
}
$bundleFull = (Resolve-Path -LiteralPath $SourceBundle).Path
if (Test-Path -LiteralPath $destinationFull) {
    if ((Get-ChildItem -LiteralPath $destinationFull -Force | Measure-Object).Count -gt 0) {
        throw 'Install destination must be a new or empty directory. Use a new directory for each reviewed snapshot.'
    }
}
$expectedFiles = @(
    'formfiller\__init__.py',
    'formfiller\browser.py',
    'formfiller\calendar.py',
    'formfiller\calendar_xlsx.py',
    'formfiller\default_calendar.py',
    'formfiller\deployment.py',
    'formfiller\migrate.py',
    'formfiller\monitor.py',
    'formfiller\ownership.py',
    'formfiller\run_and_check.py',
    'formfiller\runner.py',
    'formfiller\scheduling.py',
    'formfiller\schema_changes.py',
    'formfiller\taskplan.py',
    'formfiller\state.py',
    'formfiller\store.py',
    'formfiller\workspace.py',
    'formfiller\skyward.py',
    'formfiller\web.py',
    'requirements.txt'
)
$assetRoot = Join-Path $bundleFull 'formfiller\web_static'
if (Test-Path -LiteralPath $assetRoot -PathType Container) {
    if (((Get-Item -LiteralPath $assetRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Refusing a linked web asset root.' }
    $assetExtensions = @('.html', '.js', '.css', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.woff', '.woff2')
    foreach ($asset in Get-ChildItem -LiteralPath $assetRoot -Force -Recurse) {
        if (($asset.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Refusing a linked web asset.' }
        if ($asset.PSIsContainer) { continue }
        if ($assetExtensions -notcontains $asset.Extension.ToLowerInvariant()) { throw "Unsupported web asset type: $($asset.Extension)" }
        $relativeAsset = [System.IO.Path]::GetRelativePath($bundleFull, $asset.FullName)
        $expectedFiles += $relativeAsset
    }
}
foreach ($relative in $expectedFiles) {
    $bundleFile = Join-Path $bundleFull $relative
    if (-not (Test-Path -LiteralPath $bundleFile -PathType Leaf)) {
        throw "Clean source bundle is incomplete: $relative"
    }
    if (((Get-Item -LiteralPath $bundleFile -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Refusing a linked bundle file: $relative" }
}

New-Item -ItemType Directory -Path $destinationFull -Force | Out-Null
foreach ($relative in $expectedFiles) {
    $target = Join-Path $destinationFull $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $bundleFull $relative) -Destination $target -Force
}
$manifestFiles = @{}
foreach ($relative in ($expectedFiles | Where-Object { $_.StartsWith('formfiller\', [System.StringComparison]::OrdinalIgnoreCase) })) {
    $path = Join-Path $destinationFull $relative
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    $manifestFiles[$relative.Replace('\', '/')] = $hash.ToLowerInvariant()
}
$manifest = [ordered]@{ version = 1; source_root = $sourceRootFull; files = $manifestFiles }
$manifestPath = Join-Path $destinationFull 'install-manifest.json'
$manifestJson = $manifest | ConvertTo-Json -Depth 5
$utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
[System.IO.File]::WriteAllText($manifestPath, $manifestJson, $utf8NoBom)

if ($PythonPath) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'PythonPath must identify an existing Python executable.' }
    $pythonExe = (Resolve-Path -LiteralPath $PythonPath).Path
    $pythonPrefix = @()
} else {
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $pythonExe = $pythonCommand.Source
        $pythonPrefix = @('-3')
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCommand) { throw 'Python launcher (py) or -PythonPath is required to create the installed runtime.' }
        $pythonExe = $pythonCommand.Source
        $pythonPrefix = @()
    }
}
Write-Output 'Creating the Python runtime. This can take a minute...'
& $pythonExe @pythonPrefix -m venv (Join-Path $destinationFull '.venv')
if ($LASTEXITCODE -ne 0) { throw 'Could not create the installed virtual environment.' }
if ($InstallDependencies) {
    Write-Output 'Installing application dependencies...'
    & (Join-Path $destinationFull '.venv\Scripts\python.exe') -m pip install -r (Join-Path $destinationFull 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install runtime dependencies into the installed snapshot.' }
}
$launcher = @'
[CmdletBinding()]
param(
    [string]$Workspace,
    [string]$Runtime,
    [int]$Port = 0,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$WebArgs
)
$ErrorActionPreference = 'Stop'
$installRoot = $PSScriptRoot
$installPath = (Resolve-Path -LiteralPath $installRoot).Path.TrimEnd('\')
$manifestPath = Join-Path $installRoot 'install-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Installed snapshot manifest is missing.' }
try { $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json } catch { throw 'Installed snapshot manifest is invalid.' }
if ($manifest.version -ne 1 -or -not $manifest.source_root -or -not $manifest.files) { throw 'Installed snapshot manifest is invalid.' }
$sourceRoot = [System.IO.Path]::GetFullPath([string]$manifest.source_root).TrimEnd('\')
if ($installPath.Equals($sourceRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $installPath.StartsWith($sourceRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Private mode cannot run from the editable source checkout.'
}
$listed = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($property in $manifest.files.PSObject.Properties) { [void]$listed.Add([string]$property.Name) }
$expected = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$packageRoot = Join-Path $installRoot 'formfiller'
foreach ($entry in Get-ChildItem -LiteralPath $packageRoot -Force -Recurse) {
    if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Installed snapshot contains a linked file.' }
    if ($entry.PSIsContainer) { continue }
    $relative = [System.IO.Path]::GetRelativePath($installRoot, $entry.FullName).Replace('\', '/')
    if ($entry.Extension.ToLowerInvariant() -in @('.py', '.pyc', '.pyd', '.dll', '.so', '.exe', '.bat', '.cmd', '.ps1') -or
        $relative.StartsWith('formfiller/web_static/', [System.StringComparison]::OrdinalIgnoreCase)) {
        [void]$expected.Add($relative)
    }
}
if ($expected.Count -ne $listed.Count) { throw 'Installed snapshot inventory changed.' }
foreach ($relative in $expected) {
    if (-not $listed.Contains($relative)) { throw 'Installed snapshot inventory changed.' }
    $property = $manifest.files.PSObject.Properties | Where-Object { $_.Name -eq $relative } | Select-Object -First 1
    if (-not $property) { throw 'Installed snapshot inventory changed.' }
    $expectedHash = [string]$property.Value
    $actualHash = (Get-FileHash -LiteralPath (Join-Path $installRoot $relative.Replace('/', '\')) -Algorithm SHA256).Hash
    if ($actualHash -ne $expectedHash) { throw 'Installed snapshot hash check failed.' }
}
$python = Join-Path $installRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Installed virtual environment is missing. Reinstall the snapshot.' }
Set-Location -LiteralPath $installRoot
$launchArgs = @('--private')
if ($Workspace) { $launchArgs += @('--workspace', $Workspace) }
if ($Runtime) { $launchArgs += @('--runtime', $Runtime) }
if ($Port -gt 0) { $launchArgs += @('--port', [string]$Port) }
if ($WebArgs) { $launchArgs += $WebArgs }
$env:PYTHONDONTWRITEBYTECODE = '1'
& $python -m formfiller.web @launchArgs
exit $LASTEXITCODE
'@
$launcher | Set-Content -LiteralPath (Join-Path $destinationFull 'Run-FormFillerPrivate.ps1') -Encoding UTF8
$operationLauncher = @'
[CmdletBinding()]
param([switch]$CheckOnly, [switch]$Scheduled, [string]$AppDataRoot)
$ErrorActionPreference = 'Stop'
if ($AppDataRoot) {
    if (-not [IO.Path]::IsPathFullyQualified($AppDataRoot)) { throw 'local_runtime_location_invalid' }
    $env:LOCALAPPDATA = $AppDataRoot
}
if ($Scheduled) {
    # First installation is dormant until a human chooses the private workspace.
    # The explicit locator is authoritative, including packaged-app redirection.
    Remove-Item Env:FORM_FILLER_WORKSPACE, Env:FORM_FILLER_RUNTIME, Env:FORM_FILLER_INSTALLED_APP -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'FormFiller\paths.json'))) { exit 0 }
}
$installRoot = $PSScriptRoot
$installPath = (Resolve-Path -LiteralPath $installRoot).Path.TrimEnd('\')
$manifestPath = Join-Path $installRoot 'install-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Installed snapshot manifest is missing.' }
try { $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json } catch { throw 'Installed snapshot manifest is invalid.' }
if ($manifest.version -ne 1 -or -not $manifest.source_root -or -not $manifest.files) { throw 'Installed snapshot manifest is invalid.' }
$sourceRoot = [System.IO.Path]::GetFullPath([string]$manifest.source_root).TrimEnd('\')
if ($installPath.Equals($sourceRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $installPath.StartsWith($sourceRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Private mode cannot run from the editable source checkout.'
}
$listed = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($property in $manifest.files.PSObject.Properties) { [void]$listed.Add([string]$property.Name) }
$expected = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$packageRoot = Join-Path $installRoot 'formfiller'
foreach ($entry in Get-ChildItem -LiteralPath $packageRoot -Force -Recurse) {
    if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Installed snapshot contains a linked file.' }
    if ($entry.PSIsContainer) { continue }
    $relative = [System.IO.Path]::GetRelativePath($installRoot, $entry.FullName).Replace('\', '/')
    if ($entry.Extension.ToLowerInvariant() -in @('.py', '.pyc', '.pyd', '.dll', '.so', '.exe', '.bat', '.cmd', '.ps1') -or
        $relative.StartsWith('formfiller/web_static/', [System.StringComparison]::OrdinalIgnoreCase)) {
        [void]$expected.Add($relative)
    }
}
if ($expected.Count -ne $listed.Count) { throw 'Installed snapshot inventory changed.' }
foreach ($relative in $expected) {
    if (-not $listed.Contains($relative)) { throw 'Installed snapshot inventory changed.' }
    $property = $manifest.files.PSObject.Properties | Where-Object { $_.Name -eq $relative } | Select-Object -First 1
    if (-not $property) { throw 'Installed snapshot inventory changed.' }
    $expectedHash = [string]$property.Value
    $actualHash = (Get-FileHash -LiteralPath (Join-Path $installRoot $relative.Replace('/', '\')) -Algorithm SHA256).Hash
    if ($actualHash -ne $expectedHash) { throw 'Installed snapshot hash check failed.' }
}
$python = Join-Path $installRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Installed virtual environment is missing.' }
Set-Location -LiteralPath $installRoot
$operationArgs = @()
if ($CheckOnly) { $operationArgs += '--check-only' }
if ($Scheduled) {
    # This also supports a scheduler device whose OS uses another time zone.
    & $python -c "import sys; from datetime import datetime; from zoneinfo import ZoneInfo; n=datetime.now(ZoneInfo('America/Chicago')); sys.exit(0 if 720 <= n.hour*60+n.minute < 930 else 3)"
    if ($LASTEXITCODE -eq 3) { exit 0 }
    if ($LASTEXITCODE -ne 0) { exit 2 }
    $operationArgs += '--scheduled'
}
$env:PYTHONDONTWRITEBYTECODE = '1'
& $python -m formfiller.run_and_check @operationArgs
exit $LASTEXITCODE
'@
$operationLauncher | Set-Content -LiteralPath (Join-Path $destinationFull 'Run-FormFillerOperation.ps1') -Encoding UTF8
Write-Output "Installed application snapshot: $destinationFull"
Write-Output "Install manifest: $(Join-Path $destinationFull 'install-manifest.json')"
Write-Output 'The installed launcher starts private mode; without path options, the first-run workspace flow can choose the private folder.'
Write-Output 'Private configuration and persistent state must remain in the designated private userworkspace.'
