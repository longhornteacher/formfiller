[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$AppDataRoot = $env:LOCALAPPDATA
)

$ErrorActionPreference = 'Stop'
function Read-WorkspaceMapping([string]$LocatorPath) {
    if (((Get-Item -LiteralPath $LocatorPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'workspace_locator_invalid'
    }
    $value = Get-Content -LiteralPath $LocatorPath -Raw | ConvertFrom-Json
    $keys = @($value.PSObject.Properties.Name)
    if ($keys.Count -ne 3 -or @($keys | Where-Object { $_ -notin @('workspace', 'runtime', 'installed_app') }).Count -ne 0) {
        throw 'workspace_locator_invalid'
    }
    foreach ($key in @('workspace', 'runtime', 'installed_app')) {
        if (-not ($value.$key -is [string]) -or -not [IO.Path]::IsPathFullyQualified($value.$key)) {
            throw 'workspace_locator_invalid'
        }
    }
    return $value
}

try {
    $repoRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
    if (-not $AppDataRoot -or -not [IO.Path]::IsPathFullyQualified($AppDataRoot)) {
        throw 'local_runtime_location_unavailable'
    }
    $appRoot = Join-Path $AppDataRoot 'FormFiller'
    $locator = Join-Path $appRoot 'paths.json'
    $mapping = $null
    if (Test-Path -LiteralPath $locator) {
        $mapping = Read-WorkspaceMapping $locator
    } else {
        # Windows can redirect writes made by the packaged Codex desktop app.
        # Recover only its existing locator, never copy private files or rebind
        # a runtime owner. The native desktop launcher can use these same paths.
        $packagesRoot = Join-Path $AppDataRoot 'Packages'
        $candidates = @()
        if (Test-Path -LiteralPath $packagesRoot -PathType Container) {
            foreach ($package in Get-ChildItem -LiteralPath $packagesRoot -Directory -Filter 'OpenAI.Codex_*') {
                $candidate = Join-Path $package.FullName 'LocalCache\Local\FormFiller\paths.json'
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidates += $candidate }
            }
        }
        if ($candidates.Count -gt 1) { throw 'workspace_locator_ambiguous' }
        if ($candidates.Count -eq 1) {
            $mapping = Read-WorkspaceMapping $candidates[0]
            if (-not (Test-Path -LiteralPath (Join-Path $mapping.installed_app 'Run-FormFillerPrivate.ps1') -PathType Leaf)) {
                throw 'installed_webui_missing'
            }
            New-Item -ItemType Directory -Path $appRoot -Force | Out-Null
            $temporary = Join-Path $appRoot ('.paths-' + [Guid]::NewGuid().ToString('N') + '.tmp')
            try {
                [IO.File]::WriteAllText($temporary, ($mapping | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
                # Do not overwrite a locator created by another launch/setup.
                [IO.File]::Move($temporary, $locator)
            } finally {
                if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
            }
            Write-Output 'Found the existing FormFiller installation.'
        }
    }
    if ($null -ne $mapping) {
        $installedRoot = $mapping.installed_app
        $env:FORM_FILLER_WORKSPACE = $mapping.workspace
        $env:FORM_FILLER_RUNTIME = $mapping.runtime
        $env:FORM_FILLER_INSTALLED_APP = $mapping.installed_app
    } else {
        Write-Output 'Setting up the FormFiller WebUI for first use...'
        $installedRoot = Join-Path $appRoot ('App\snapshot-ui-' + [Guid]::NewGuid().ToString('N').Substring(0, 12))
        $artifacts = Join-Path $repoRoot 'tools\artifacts'
        Write-Output 'Preparing application files...'
        & (Join-Path $repoRoot 'tools\Build-CleanSource.ps1') -RepositoryRoot $repoRoot -OutputRoot $artifacts | Out-Null
        $installArgs = @{
            Destination = $installedRoot; SourceRoot = $repoRoot
            SourceBundle = (Join-Path $artifacts 'formfiller-clean-source'); InstallDependencies = $true
        }
        $existingPython = Join-Path $repoRoot 'outputs\.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $existingPython -PathType Leaf) { $installArgs.PythonPath = $existingPython }
        & (Join-Path $repoRoot 'tools\Install-ReviewedSnapshot.ps1') `
            @installArgs
    }
    $launcher = Join-Path $installedRoot 'Run-FormFillerPrivate.ps1'
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        throw 'installed_webui_missing'
    }
    Write-Output 'Opening FormFiller in your browser. Keep this window open while using it.'
    # The installed launcher verifies its complete inventory and hashes before
    # private data can be loaded. Opening the UI never requests a submission.
    & $launcher --open
    if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }
    exit 0
} catch {
    # Exception text may contain a private path. Show only fixed instructions.
    Write-Output 'The WebUI could not start. Check that Python 3.11+ and PowerShell 7 are installed and the installed FormFiller snapshot is intact.'
    exit 2
}
