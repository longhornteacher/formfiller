[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$Snapshot,
    [string]$TaskName = 'FormFiller Daily 3PM',
    [switch]$AllowUnconfigured,
    [string]$PowerShellPath
)
$ErrorActionPreference = 'Stop'
$snapshotFull = (Resolve-Path -LiteralPath $Snapshot).Path
$python = Join-Path $snapshotFull '.venv\Scripts\python.exe'
$launcher = Join-Path $snapshotFull 'Run-FormFillerOperation.ps1'
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'Installed runtime is missing.' }
# Validate the complete reviewed snapshot and confirm that it supports scheduled
# dispatch. This checks the designated runtime owner without rebinding it.
$validation = @'
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
try:
    from formfiller.deployment import validate_snapshot
    from formfiller.workspace import resolve_workspace
    from formfiller.ownership import verify_runtime_owner
    from formfiller.runner import _parse_args
    validate_snapshot(sys.argv[1])
    _parse_args(['--scheduled'])
    workspace = resolve_workspace(sys.argv[1])
    from pathlib import Path
    if workspace.installed_app is None:
        import json, os
        app = Path(os.environ['LOCALAPPDATA']) / 'FormFiller'
        installation = json.loads((app / 'installation.json').read_text(encoding='utf-8'))
        if (sys.argv[2] != 'allow_unconfigured' or (app / 'paths.json').exists()
                or Path(installation['installed_app']).resolve() != Path(sys.argv[1]).resolve()):
            raise ValueError('designated_snapshot_required')
    else:
        if workspace.installed_app.resolve() != Path(sys.argv[1]).resolve():
            raise ValueError('designated_snapshot_required')
        verify_runtime_owner(workspace.config_dir.parent, workspace.state_dir.parent)
except BaseException as exc:
    print('error code=' + getattr(exc, 'code', 'schedule_install_invalid'))
    sys.exit(2)
'@
$setupMode = if ($AllowUnconfigured) { 'allow_unconfigured' } else { 'configured' }
& $python -c $validation $snapshotFull $setupMode
if ($LASTEXITCODE -ne 0) { throw 'Schedule prerequisites failed.' }
# One planner task runs each morning (and at sign-in, idempotently). It picks
# each template's random time in the configured submit window, deletes yesterday's plan
# and leftover tasks, and registers one run-once task per slot. All launches use
# pythonw.exe, so no console window appears. The old minute-by-minute task is
# removed. TaskName is retained only for the -WhatIf message.
if ($PSCmdlet.ShouldProcess($TaskName, 'Install the daily planner and remove the every-minute task')) {
    Push-Location -LiteralPath $snapshotFull
    try { & $python -B -m formfiller.taskplan install-planner } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'Planner registration failed.' }
    Write-Output 'status=schedule_installed planner=daily window=configured'
}
