# Windows PowerShell 5.1 entrypoint; dependencies use verified per-user setup.
[CmdletBinding()]
param(
    [string]$AppDataRoot = $env:LOCALAPPDATA,
    [string]$DesktopDirectory,
    [string]$PythonPath,
    [switch]$NoLaunch,
    [switch]$NoPrerequisiteInstall,
    [switch]$Update
)
$ErrorActionPreference = 'Stop'
$entryRoot = [IO.Path]::GetDirectoryName($MyInvocation.MyCommand.Path)
try {
    $architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -ne 'AMD64') { throw 'windows_x64_required' }
    if (-not $AppDataRoot -or -not [IO.Path]::IsPathRooted($AppDataRoot)) { throw 'local_runtime_location_unavailable' }
    . (Join-Path $entryRoot 'tools\Bootstrap-WebUI.ps1') -RepositoryRoot $entryRoot -AppDataRoot $AppDataRoot
    $dependencyRoot = Join-Path $AppDataRoot 'FormFiller\Dependencies'
    $shell = Resolve-FormFillerPowerShell $dependencyRoot -NoInstall:$NoPrerequisiteInstall
    if ($PythonPath) {
        if (-not (Test-FormFillerPython $PythonPath)) { throw 'python_311_required' }
        $python = $PythonPath
    } else { $python = Resolve-FormFillerPython $dependencyRoot -NoInstall:$NoPrerequisiteInstall }
    Install-FormFillerEdge -NoInstall:$NoPrerequisiteInstall
    $arguments = @('-NoProfile', '-File', (Join-Path $entryRoot 'tools\Install-FormFiller.ps1'),
                   '-RepositoryRoot', $entryRoot, '-AppDataRoot', $AppDataRoot, '-PythonPath', $python, '-PowerShellPath', $shell)
    if ($DesktopDirectory) { $arguments += @('-DesktopDirectory', $DesktopDirectory) }
    if ($NoLaunch) { $arguments += '-NoLaunch' }
    if ($Update) { $arguments += '-Update' }
    & $shell @arguments
    exit $LASTEXITCODE
} catch {
    $code = [string]$_.Exception.Message
    if ($code -notmatch '^[a-z0-9_]+$') { $code = 'install_failed' }
    Write-Output "status=blocked code=$code"
    Write-Output 'Setup needs PowerShell 7, Python 3.11+ with tkinter, and Microsoft Edge. If your organization blocks installation, ask IT to allow the missing prerequisite, then run Install.ps1 again.'
    exit 2
}
