# Windows PowerShell 5.1 bootstrap. The application itself uses PowerShell 7.
[CmdletBinding()]
param(
    [string]$AppDataRoot = $env:LOCALAPPDATA,
    [string]$DesktopDirectory,
    [string]$PythonPath,
    [switch]$NoLaunch,
    [switch]$NoPrerequisiteInstall
)
$ErrorActionPreference = 'Stop'

function Find-PowerShell7 {
    foreach ($candidate in @((Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe'),
                              (Join-Path $env:LOCALAPPDATA 'Microsoft\PowerShell\7\pwsh.exe'))) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    $command = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch '\\(\.codex|\.cache|codex-runtimes|plugins)\\') { return $command.Source }
}
function Find-Python {
    if ($PythonPath) { $candidates = @($PythonPath) } else {
        $candidates = @()
        foreach ($name in @('py', 'python')) {
            $command = Get-Command $name -ErrorAction SilentlyContinue
            if ($command -and $command.Source -notlike '*\WindowsApps\*') { $candidates += $command.Source }
        }
        $pythonRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
        if (Test-Path -LiteralPath $pythonRoot) {
            $candidates += @(Get-ChildItem -LiteralPath $pythonRoot -Directory | ForEach-Object { Join-Path $_.FullName 'python.exe' })
        }
    }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $prefix = @()
        if ([IO.Path]::GetFileName($candidate) -eq 'py.exe') { $prefix = @('-3') }
        try {
            $resolved = & $candidate @prefix -c "import sys; print(getattr(sys, '_base_executable', sys.executable) if sys.version_info >= (3, 11) else '')" 2>$null
        } catch { continue }
        if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath ([string]$resolved) -PathType Leaf)) { return [string]$resolved }
    }
}
function Install-Prerequisite([string]$Id) {
    if ($NoPrerequisiteInstall) { throw 'prerequisite_install_disabled' }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { throw 'winget_required' }
    Write-Output "Installing prerequisite: $Id"
    # Run the official package manager visibly if it needs OS consent. Never
    # change execution policy or attempt to bypass a managed-device restriction.
    & $winget.Source install --exact --id $Id --source winget --accept-source-agreements --accept-package-agreements --silent --disable-interactivity | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'prerequisite_install_failed' }
}
try {
    if (-not $AppDataRoot) { throw 'local_runtime_location_unavailable' }
    $shell = Find-PowerShell7
    if (-not $shell) { Install-Prerequisite 'Microsoft.PowerShell'; $shell = Find-PowerShell7 }
    if (-not $shell) { throw 'powershell_7_required' }
    $python = Find-Python
    if (-not $python) {
        if ($PythonPath) { throw 'python_311_required' }
        Install-Prerequisite 'Python.Python.3.13'
        $python = Find-Python
    }
    if (-not $python) { throw 'python_311_required' }
    $edgePaths = @((Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
                   (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
                   (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe'))
    if (-not @($edgePaths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }).Count) {
        Install-Prerequisite 'Microsoft.Edge'
        if (-not @($edgePaths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }).Count) { throw 'edge_required' }
    }
    $arguments = @('-NoProfile', '-File', (Join-Path $PSScriptRoot 'tools\Install-FormFiller.ps1'),
                   '-RepositoryRoot', $PSScriptRoot, '-AppDataRoot', $AppDataRoot, '-PythonPath', $python)
    if ($DesktopDirectory) { $arguments += @('-DesktopDirectory', $DesktopDirectory) }
    if ($NoLaunch) { $arguments += '-NoLaunch' }
    & $shell @arguments
    exit $LASTEXITCODE
} catch {
    $code = [string]$_.Exception.Message
    if ($code -notmatch '^[a-z0-9_]+$') { $code = 'install_failed' }
    Write-Output "status=blocked code=$code"
    Write-Output 'Setup needs PowerShell 7, Python 3.11+, and Microsoft Edge. If software installation is blocked by your organization, ask IT to install the missing prerequisite, then run Install.ps1 again.'
    exit 2
}
