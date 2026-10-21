#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$AppDataRoot = $env:LOCALAPPDATA,
    [string]$DesktopDirectory = [Environment]::GetFolderPath('DesktopDirectory'),
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [string]$PowerShellPath,
    [switch]$NoLaunch,
    [switch]$Update
)
$ErrorActionPreference = 'Stop'
$updateLock = $null
$updateLockPath = $null
$locatorChanged = $false
$installationChanged = $false
$locatorOriginal = $null
$installationOriginal = $null
function Assert-InstalledSnapshot([string]$Snapshot) {
    $interpreter = Join-Path $Snapshot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $interpreter -PathType Leaf)) { throw 'installed_python_missing' }
    $probe = @'
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
try:
    from formfiller.deployment import validate_snapshot
    validate_snapshot(sys.argv[1])
except Exception:
    print('status=blocked code=installed_snapshot_invalid')
    sys.exit(2)
'@
    & $interpreter -c $probe $Snapshot
    if ($LASTEXITCODE -ne 0) { throw 'installed_snapshot_invalid' }
}
try {
    $repoRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
    if (-not [IO.Path]::IsPathFullyQualified($AppDataRoot) -or
        -not [IO.Path]::IsPathFullyQualified($DesktopDirectory)) { throw 'install_location_invalid' }
    $appRoot = Join-Path $AppDataRoot 'FormFiller'
    $locator = Join-Path $appRoot 'paths.json'
    $installationPath = Join-Path $appRoot 'installation.json'
    $shell = if ($PowerShellPath) { $PowerShellPath } else { (Get-Process -Id $PID).Path }
    $shortcutPath = Join-Path $DesktopDirectory 'Launch FormFiller.lnk'
    $shortcutShell = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $shortcutPath) {
        $priorShortcut = $shortcutShell.CreateShortcut($shortcutPath)
        if ($priorShortcut.Description -ne 'FormFiller local WebUI') { throw 'desktop_shortcut_exists' }
    }
    New-Item -ItemType Directory -Path $appRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $DesktopDirectory -Force | Out-Null
    # Recover a packaged-agent installation before considering a fresh install.
    if (-not (Test-Path -LiteralPath $locator)) {
        $packages = Join-Path $AppDataRoot 'Packages'
        $candidates = @()
        if (Test-Path -LiteralPath $packages -PathType Container) {
            foreach ($package in Get-ChildItem -LiteralPath $packages -Directory -Filter 'OpenAI.Codex_*') {
                $candidate = Join-Path $package.FullName 'LocalCache\Local\FormFiller\paths.json'
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidates += $candidate }
            }
        }
        if ($candidates.Count -gt 1) { throw 'workspace_locator_ambiguous' }
        if ($candidates.Count -eq 1) {
            # The same strict locator validation below applies to recovered data.
            [IO.File]::Copy($candidates[0], $locator, $false)
        }
    }
    $mapping = $null
    $existingRoot = $null
    if (Test-Path -LiteralPath $locator) {
        $mapping = Get-Content -LiteralPath $locator -Raw | ConvertFrom-Json
        if (@($mapping.PSObject.Properties).Count -ne 3 -or
            @($mapping.PSObject.Properties.Name | Where-Object { $_ -notin @('workspace', 'runtime', 'installed_app') }).Count) { throw 'workspace_locator_invalid' }
        foreach ($key in @('workspace', 'runtime', 'installed_app')) {
            if (-not ($mapping.$key -is [string]) -or -not [IO.Path]::IsPathFullyQualified($mapping.$key)) { throw 'workspace_locator_invalid' }
        }
        $installedRoot = $mapping.installed_app
        $existingRoot = $installedRoot
    } elseif (Test-Path -LiteralPath $installationPath) {
        $installation = Get-Content -LiteralPath $installationPath -Raw | ConvertFrom-Json
        if ($installation.version -ne 1 -or -not ($installation.installed_app -is [string]) -or
            -not [IO.Path]::IsPathFullyQualified($installation.installed_app)) { throw 'installation_invalid' }
        $installedRoot = $installation.installed_app
        $existingRoot = $installedRoot
    } else {
        Write-Output 'Preparing FormFiller application files...'
        $installedRoot = Join-Path $appRoot ('App\snapshot-' + [Guid]::NewGuid().ToString('N').Substring(0, 12))
        $artifacts = Join-Path $repoRoot 'tools\artifacts'
        & (Join-Path $repoRoot 'tools\Build-CleanSource.ps1') -RepositoryRoot $repoRoot -OutputRoot $artifacts | Out-Null
        & (Join-Path $repoRoot 'tools\Install-ReviewedSnapshot.ps1') -Destination $installedRoot -SourceRoot $repoRoot -SourceBundle (Join-Path $artifacts 'formfiller-clean-source') -PythonPath $PythonPath -InstallDependencies
    }
    if ($Update -and $existingRoot) {
        # An explicit update never repairs a modified snapshot by replacing it.
        Assert-InstalledSnapshot $existingRoot
        $installedRoot = Join-Path $appRoot ('App\snapshot-' + [Guid]::NewGuid().ToString('N').Substring(0, 12))
        $artifacts = Join-Path $repoRoot 'tools\artifacts'
        & (Join-Path $repoRoot 'tools\Build-CleanSource.ps1') -RepositoryRoot $repoRoot -OutputRoot $artifacts | Out-Null
        & (Join-Path $repoRoot 'tools\Install-ReviewedSnapshot.ps1') -Destination $installedRoot -SourceRoot $repoRoot -SourceBundle (Join-Path $artifacts 'formfiller-clean-source') -PythonPath $PythonPath -InstallDependencies
    }
    # Verify a fresh or reused snapshot before changing launchers or shortcuts.
    Assert-InstalledSnapshot $installedRoot
    if (Test-Path -LiteralPath $installationPath) { $installationOriginal = [IO.File]::ReadAllBytes($installationPath) }
    if ($Update -and $mapping) {
        $locatorOriginal = [IO.File]::ReadAllBytes($locator)
        $stateRoot = Join-Path $mapping.runtime 'state'
        New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
        $updateLockPath = Join-Path $stateRoot '.runner.lock'
        # Never remove or reuse an existing lock. Hold this new lock until the
        # snapshot locator and task have both switched to the verified build.
        $updateLock = [IO.File]::Open($updateLockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $mapping.installed_app = $installedRoot
        $locatorTemp = Join-Path $appRoot ('.paths-' + [Guid]::NewGuid().ToString('N') + '.tmp')
        try {
            [IO.File]::WriteAllText($locatorTemp, ($mapping | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
            [IO.File]::Move($locatorTemp, $locator, $true)
            $locatorChanged = $true
        } finally { if (Test-Path -LiteralPath $locatorTemp) { Remove-Item -LiteralPath $locatorTemp } }
    }
    $temporary = Join-Path $appRoot ('.installation-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllText($temporary, (@{version=1; installed_app=$installedRoot} | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
        [IO.File]::Move($temporary, $installationPath, $true)
        $installationChanged = $true
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
    $openScript = Join-Path $appRoot 'Open-FormFiller.ps1'
    Copy-Item -LiteralPath (Join-Path $repoRoot 'tools\Open-FormFiller.ps1') -Destination $openScript -Force
    $iconPath = Join-Path $appRoot 'FormFiller.ico'
    & (Join-Path $repoRoot 'tools\Build-LauncherIcon.ps1') -SourceSvg (Join-Path $repoRoot 'outputs\formfiller\web_static\formfiller.svg') -DestinationIco $iconPath
    $savedLocal = $env:LOCALAPPDATA
    $savedWorkspace = $env:FORM_FILLER_WORKSPACE
    $savedRuntime = $env:FORM_FILLER_RUNTIME
    $savedInstalled = $env:FORM_FILLER_INSTALLED_APP
    try {
        $env:LOCALAPPDATA = $AppDataRoot
        Remove-Item Env:FORM_FILLER_WORKSPACE, Env:FORM_FILLER_RUNTIME, Env:FORM_FILLER_INSTALLED_APP -ErrorAction SilentlyContinue
        & (Join-Path $repoRoot 'tools\Install-SchoolDaySchedule.ps1') -Snapshot $installedRoot -AllowUnconfigured -PowerShellPath $shell
    } finally {
        $env:LOCALAPPDATA = $savedLocal
        $env:FORM_FILLER_WORKSPACE = $savedWorkspace
        $env:FORM_FILLER_RUNTIME = $savedRuntime
        $env:FORM_FILLER_INSTALLED_APP = $savedInstalled
    }
    $shortcut = $shortcutShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $shell
    $shortcut.Arguments = '-NoProfile -WindowStyle Hidden -File "' + $openScript + '"'
    $shortcut.WorkingDirectory = $appRoot
    $shortcut.Description = 'FormFiller local WebUI'
    $shortcut.IconLocation = $iconPath + ',0'
    $shortcut.WindowStyle = 7
    $shortcut.Save()
    # Replace only the old shortcut created by this installation.
    $legacyPath = Join-Path $DesktopDirectory 'FormFiller.lnk'
    if (Test-Path -LiteralPath $legacyPath -PathType Leaf) {
        $legacy = $shortcutShell.CreateShortcut($legacyPath)
        if ($legacy.Description -eq 'FormFiller local WebUI' -and $legacy.WorkingDirectory -eq $appRoot -and
            $legacy.Arguments.Contains('"' + $openScript + '"')) {
            Remove-Item -LiteralPath $legacyPath
        }
    }
    Write-Output 'status=installed desktop_shortcut=Launch_FormFiller background_schedule=ready'
    Write-Output 'Double-click Launch FormFiller on your desktop. Choose a private workspace, add your forms, and complete the Readiness checks before submitting.'
    if (-not $NoLaunch) {
        Start-Process -FilePath $shell -ArgumentList @('-NoProfile', '-WindowStyle', 'Hidden', '-File', ('"' + $openScript + '"')) -WorkingDirectory $appRoot -WindowStyle Hidden | Out-Null
    }
    exit 0
} catch {
    if ($locatorChanged) { [IO.File]::WriteAllBytes($locator, $locatorOriginal) }
    if ($installationChanged) {
        if ($installationOriginal) { [IO.File]::WriteAllBytes($installationPath, $installationOriginal) }
        else { Remove-Item -LiteralPath $installationPath }
    }
    $code = [string]$_.Exception.Message
    if ($code -notmatch '^[a-z0-9_]+$') { $code = 'install_failed' }
    Write-Output "status=blocked code=$code"
    exit 2
} finally {
    if ($updateLock) {
        $updateLock.Dispose()
        Remove-Item -LiteralPath $updateLockPath
    }
}
