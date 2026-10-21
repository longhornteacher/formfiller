[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$Snapshot,
    [string]$TaskName = 'FormFiller Daily 3PM',
    [switch]$AllowUnconfigured
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
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and $existing.State -eq 'Running') { throw 'Wait until the existing task has finished.' }
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
# Start every day; only the approved calendar can establish a school day.
# On a device in another zone, dispatch checks all day and the installed
# launcher exits quietly outside the Central window. Never change the OS zone.
$centralDevice = (Get-TimeZone).Id -eq 'Central Standard Time'
$startHour = if ($centralDevice) { 12 } else { 0 }
$durationMinutes = if ($centralDevice) { 210 } else { 1440 }
$start = Get-Date -Hour $startHour -Minute 0 -Second 0
$trigger = New-ScheduledTaskTrigger -Daily -At $start
# A local wall-clock boundary follows daylight-saving transitions.
$trigger.StartBoundary = $start.ToString("yyyy-MM-dd'T'HH:mm:ss")
$repeat = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Minutes $durationMinutes)
$trigger.Repetition = $repeat.Repetition
$shell = (Get-Command pwsh -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute $shell -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -Scheduled -AppDataRoot "{1}"' -f $launcher, $env:LOCALAPPDATA) -WorkingDirectory $snapshotFull
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
if ($PSCmdlet.ShouldProcess($TaskName, 'Replace fixed batch time with noon–3:30 PM background dispatch')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'FormFiller: randomized per-template school-day schedule, 12:00–15:30 Central; no automatic retries.' -Force | Out-Null
    Write-Output 'status=schedule_installed window=12:00-15:30 timezone=America/Chicago'
}
