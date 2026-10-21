# Installed next to installation.json; this launcher never depends on the clone.
[CmdletBinding()]
param([switch]$Foreground)
$ErrorActionPreference = 'Stop'
try {
    $appRoot = $PSScriptRoot
    $locator = Join-Path $appRoot 'paths.json'
    if (Test-Path -LiteralPath $locator) {
        $mapping = Get-Content -LiteralPath $locator -Raw | ConvertFrom-Json
        if (@($mapping.PSObject.Properties.Name | Where-Object { $_ -notin @('workspace', 'runtime', 'installed_app') }).Count -or
            @($mapping.PSObject.Properties).Count -ne 3) { throw 'workspace_locator_invalid' }
        foreach ($key in @('workspace', 'runtime', 'installed_app')) {
            if (-not ($mapping.$key -is [string]) -or -not [IO.Path]::IsPathFullyQualified($mapping.$key)) { throw 'workspace_locator_invalid' }
        }
        $installed = $mapping.installed_app
        $env:FORM_FILLER_WORKSPACE = $mapping.workspace
        $env:FORM_FILLER_RUNTIME = $mapping.runtime
        $env:FORM_FILLER_INSTALLED_APP = $installed
    } else {
        $installation = Get-Content -LiteralPath (Join-Path $appRoot 'installation.json') -Raw | ConvertFrom-Json
        if ($installation.version -ne 1 -or -not ($installation.installed_app -is [string]) -or
            -not [IO.Path]::IsPathFullyQualified($installation.installed_app)) { throw 'installation_invalid' }
        $installed = $installation.installed_app
        # Do not inherit another project's workspace from the installing agent.
        Remove-Item Env:FORM_FILLER_WORKSPACE, Env:FORM_FILLER_RUNTIME, Env:FORM_FILLER_INSTALLED_APP -ErrorAction SilentlyContinue
    }
    # Make the native desktop and packaged-agent launches use the same locator.
    $env:LOCALAPPDATA = Split-Path -Parent $appRoot
    $launcher = Join-Path $installed 'Run-FormFillerPrivate.ps1'
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'installed_webui_missing' }
    if ($Foreground) {
        & $launcher -WebArgs @('--open')
        exit $LASTEXITCODE
    }
    $shell = (Get-Process -Id $PID).Path
    Start-Process -FilePath $shell -ArgumentList @('-NoProfile', '-WindowStyle', 'Hidden', '-File', ('"' + $launcher + '"'), '-WebArgs', '--open') -WorkingDirectory $installed -WindowStyle Hidden | Out-Null
    exit 0
} catch {
    # Fixed text only: paths, answers, and credentials never enter notifications.
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show('FormFiller could not start. Run its installer again to check the installed application.', 'FormFiller')
    exit 2
}
