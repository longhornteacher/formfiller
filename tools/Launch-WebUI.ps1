[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$AppDataRoot = $env:LOCALAPPDATA
)

$ErrorActionPreference = 'Stop'
try {
    $repoRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
    if (-not $AppDataRoot -or -not [IO.Path]::IsPathFullyQualified($AppDataRoot)) {
        throw 'local_runtime_location_unavailable'
    }
    $appRoot = Join-Path $AppDataRoot 'FormFiller'
    $locator = Join-Path $appRoot 'paths.json'
    if (Test-Path -LiteralPath $locator) {
        $mapping = Get-Content -LiteralPath $locator -Raw | ConvertFrom-Json
        if (-not ($mapping.installed_app -is [string]) -or
            -not [IO.Path]::IsPathFullyQualified($mapping.installed_app)) {
            throw 'workspace_locator_invalid'
        }
        $installedRoot = $mapping.installed_app
    } else {
        Write-Output 'Setting up the FormFiller WebUI for first use...'
        $installedRoot = Join-Path $appRoot ('App\snapshot-ui-' + [Guid]::NewGuid().ToString('N').Substring(0, 12))
        $artifacts = Join-Path $repoRoot 'tools\artifacts'
        & (Join-Path $repoRoot 'tools\Build-CleanSource.ps1') -RepositoryRoot $repoRoot -OutputRoot $artifacts
        & (Join-Path $repoRoot 'tools\Install-ReviewedSnapshot.ps1') `
            -Destination $installedRoot -SourceRoot $repoRoot `
            -SourceBundle (Join-Path $artifacts 'formfiller-clean-source') -InstallDependencies
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
