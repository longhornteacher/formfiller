# Compatible with Windows PowerShell 5.1; no preinstalled Python, pwsh or winget
# is needed for the Python and PowerShell runtimes.
[CmdletBinding()]
param([string]$RepositoryRoot,
      [string]$AppDataRoot = $env:LOCALAPPDATA)

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 can evaluate parameter defaults before $PSScriptRoot
# is populated for -File. Resolve our location only after parameter binding.
$bootstrapScriptRoot = [IO.Path]::GetDirectoryName($MyInvocation.MyCommand.Path)
if (-not $RepositoryRoot) { $RepositoryRoot = Join-Path $bootstrapScriptRoot '..' }

function Receive-VerifiedDependency($Url, $Destination, $Hash) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
    $stream = [IO.File]::OpenRead($Destination)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $actualHash = [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $algorithm.Dispose() }
    if ($actualHash -ne $Hash) {
        throw 'dependency_download_invalid'
    }
}

function Test-FormFillerPython([string]$Executable) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
    if ($Executable -like '*\Microsoft\WindowsApps\*') { return $false }
    # Require pip, venv and tkinter too: the workspace picker needs tkinter.
    & $Executable -c 'import sys, pip, venv, tkinter; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,15) else 1)' *> $null
    return ($LASTEXITCODE -eq 0)
}

function Resolve-FormFillerPython([string]$DependencyRoot) {
    $pythonRoot = Join-Path $DependencyRoot 'Python313'
    $python = Join-Path $pythonRoot 'python.exe'
    if (Test-FormFillerPython $python) { return $python }
    foreach ($name in @('python.exe', 'python3.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and (Test-FormFillerPython $command.Source)) { return $command.Source }
    }
    # py is optional; ask it for the real executable so PATH refresh is unnecessary.
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $candidate = & $py.Source -3 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-FormFillerPython ([string]$candidate))) { return [string]$candidate }
    }
    New-Item -ItemType Directory -Path $DependencyRoot -Force | Out-Null
    $installer = Join-Path $DependencyRoot 'python-3.13.16-amd64.exe'
    Write-Host 'Downloading Python for FormFiller...'
    Receive-VerifiedDependency 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.exe' $installer 'fb4f9f5d438b2396da0086dc70b935c530cb578e37adc6d354f7ad2037fee83b'
    Write-Host 'Installing Python for this Windows account...'
    $process = Start-Process -FilePath $installer -ArgumentList @('/quiet', 'InstallAllUsers=0',
        ('TargetDir="' + $pythonRoot + '"'), 'PrependPath=0', 'Include_launcher=0',
        'Include_test=0', 'Include_pip=1', 'Include_tcltk=1') -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -notin @(0, 3010) -or -not (Test-FormFillerPython $python)) { throw 'python_install_failed' }
    return $python
}

function Resolve-FormFillerPowerShell([string]$DependencyRoot) {
    $command = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($command) {
        & $command.Source -NoProfile -Command 'if ($PSVersionTable.PSVersion.Major -ge 7) { exit 0 }; exit 1' *> $null
        if ($LASTEXITCODE -eq 0) { return $command.Source }
    }
    $destination = Join-Path $DependencyRoot 'PowerShell-7.6.6'
    $executable = Join-Path $destination 'pwsh.exe'
    if (-not (Test-Path -LiteralPath $destination)) {
        New-Item -ItemType Directory -Path $DependencyRoot -Force | Out-Null
        $archive = Join-Path $DependencyRoot 'PowerShell-7.6.6-win-x64.zip'
        Write-Host 'Downloading PowerShell for FormFiller...'
        Receive-VerifiedDependency 'https://github.com/PowerShell/PowerShell/releases/download/v7.6.6/PowerShell-7.6.6-win-x64.zip' $archive '02fe458be20493fbdf43f61ea20610b811ee6c738ab1676c61b9cfcd1a33c860'
        $staging = Join-Path $DependencyRoot ('powershell-staging-' + [Guid]::NewGuid().ToString('N'))
        Write-Host 'Preparing PowerShell for this Windows account...'
        Expand-Archive -LiteralPath $archive -DestinationPath $staging
        Move-Item -LiteralPath $staging -Destination $destination
    }
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw 'powershell_install_failed' }
    $signature = Get-AuthenticodeSignature -LiteralPath $executable
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation(?:,|$)') {
        throw 'dependency_signature_invalid'
    }
    & $executable -NoProfile -Command 'exit 0' *> $null
    if ($LASTEXITCODE -ne 0) { throw 'powershell_install_failed' }
    return $executable
}

function Test-FormFillerEdge {
    foreach ($root in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:LOCALAPPDATA)) {
        if ($root -and (Test-Path -LiteralPath (Join-Path $root 'Microsoft\Edge\Application\msedge.exe'))) { return $true }
    }
    return $false
}

function Install-FormFillerEdge {
    if (Test-FormFillerEdge) { return }
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) { throw 'edge_install_requires_it' }
    Write-Host 'Installing Microsoft Edge. Windows may request administrator approval...'
    & $winget.Source install --id Microsoft.Edge --exact --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0 -or -not (Test-FormFillerEdge)) { throw 'edge_install_requires_it' }
}

# Dot-sourcing exposes helpers for the PS7 launcher and isolated tests.
if ($MyInvocation.InvocationName -ne '.') {
    try {
        $architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
        if ($architecture -ne 'AMD64') { throw 'windows_x64_required' }
        if (-not $AppDataRoot -or -not [IO.Path]::IsPathRooted($AppDataRoot)) { throw 'local_runtime_location_unavailable' }
        $dependencyRoot = Join-Path $AppDataRoot 'FormFiller\Dependencies'
        $shell = Resolve-FormFillerPowerShell $dependencyRoot
        Install-FormFillerEdge
        & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $bootstrapScriptRoot 'Launch-WebUI.ps1') -RepositoryRoot $RepositoryRoot -AppDataRoot $AppDataRoot
        exit $LASTEXITCODE
    } catch {
        # Never echo exception text, which can contain private paths.
        Write-Host 'FormFiller setup could not finish. Check internet access. If your school blocks downloads or software installation, ask IT to allow FormFiller setup.'
        Write-Host 'Required downloads: python.org, GitHub PowerShell releases, and the Python package index. Microsoft Edge must be available.'
        exit 2
    }
}
