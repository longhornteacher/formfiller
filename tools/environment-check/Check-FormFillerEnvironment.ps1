# FormFiller environment check v2. Windows PowerShell 5.1 compatible.
# Reports what this computer allows. It installs nothing, changes no settings,
# and reads no private data. Temporary files and one never-run scheduled task
# are created and removed. Names of the user, computer and domain are scrubbed.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$started = Get-Date
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$stamp = $started.ToString('yyyyMMdd-HHmmss')
$logPath = Join-Path $here "FormFiller-Check-$stamp.log"
try { [IO.File]::WriteAllText($logPath, '') } catch { $logPath = Join-Path $env:TEMP "FormFiller-Check-$stamp.log" }
$work = Join-Path $env:TEMP ("FormFillerCheck-" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$results = New-Object System.Collections.ArrayList

# Scrub identifying names before anything is written.
$scrub = @()
foreach ($pair in @(@($env:USERPROFILE, '%USERPROFILE%'), @($env:USERNAME, '<user>'),
        @($env:COMPUTERNAME, '<computer>'), @($env:USERDOMAIN, '<domain>'), @($env:USERDNSDOMAIN, '<dnsdomain>'))) {
    if ($pair[0] -and $pair[0].Length -ge 2) { $scrub += ,@([regex]::Escape($pair[0]), $pair[1]) }
}
function Clean([string]$text) {
    if ($null -eq $text) { return '' }
    foreach ($pair in $scrub) { $text = [regex]::Replace($text, $pair[0], $pair[1], 'IgnoreCase') }
    return $text
}
function Out-Line([string]$text) {
    $line = Clean $text
    Write-Host $line
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}
function Section([string]$title) { Out-Line ''; Out-Line ('=== ' + $title + ' ===') }
function Record([string]$name, [string]$status, [string]$detail) {
    [void]$results.Add([pscustomobject]@{Name = $name; Status = $status; Detail = (Clean $detail)})
    Out-Line ('[{0}] {1}: {2}' -f $status, $name, $detail)
}
function Short($e) { return ($e.Exception.GetType().Name + ': ' + ($e.Exception.Message -replace '\s+', ' ')) }

# Run a program with a timeout; returns exit code, output and whether it timed out.
function Invoke-Probe([string]$File, [string[]]$ArgList, [int]$TimeoutSec = 30) {
    $o = Join-Path $work ([Guid]::NewGuid().ToString('N') + '.out')
    $r = Join-Path $work ([Guid]::NewGuid().ToString('N') + '.err')
    $result = [pscustomobject]@{Started = $false; TimedOut = $false; ExitCode = $null; Out = ''; Err = ''; Failure = ''}
    try {
        $params = @{FilePath = $File; PassThru = $true; WindowStyle = 'Hidden'; RedirectStandardOutput = $o; RedirectStandardError = $r; ErrorAction = 'Stop'}
        if ($ArgList -and $ArgList.Count) { $params.ArgumentList = $ArgList }
        $p = Start-Process @params
        $result.Started = $true
        # Touching Handle caches it; otherwise ExitCode can read back as null.
        $null = $p.Handle
        if (-not $p.WaitForExit($TimeoutSec * 1000)) {
            $result.TimedOut = $true
            try { & taskkill.exe /T /F /PID $p.Id *> $null } catch {}
        } else { $result.ExitCode = $p.ExitCode }
    } catch { $result.Failure = Short $_ }
    if (Test-Path -LiteralPath $o) { $result.Out = (Get-Content -LiteralPath $o -Raw -ErrorAction SilentlyContinue) }
    if (Test-Path -LiteralPath $r) { $result.Err = (Get-Content -LiteralPath $r -Raw -ErrorAction SilentlyContinue) }
    if ($null -eq $result.Out) { $result.Out = '' }
    if ($null -eq $result.Err) { $result.Err = '' }
    return $result
}

New-Item -ItemType Directory -Path $work -Force | Out-Null

Out-Line 'FormFiller environment check v2'
Out-Line ('Started: ' + $started.ToString('s'))
Out-Line ('Log file: ' + $logPath)

# ---------------------------------------------------------------- system
Section 'System'
try {
    $os = Get-CimInstance Win32_OperatingSystem
    Record 'Windows' 'INFO' ('{0} build {1} {2}' -f $os.Caption, $os.BuildNumber, $os.OSArchitecture)
    if ($os.OSArchitecture -notmatch '64') { Record 'Windows x64' 'FAIL' 'FormFiller requires 64-bit Windows' }
} catch { Record 'Windows' 'WARN' (Short $_) }
Record 'PowerShell' 'INFO' ('{0} {1}' -f $PSVersionTable.PSEdition, $PSVersionTable.PSVersion)
$mode = $ExecutionContext.SessionState.LanguageMode
Record 'PowerShell language mode' $(if ($mode -eq 'FullLanguage') { 'PASS' } else { 'FAIL' }) ([string]$mode + ' (ConstrainedLanguage blocks most scripting)')
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Record 'Running as administrator' 'INFO' ([string]$isAdmin + ' (FormFiller needs standard-user rights only)')
try {
    $cs = Get-CimInstance Win32_ComputerSystem
    Record 'Domain joined' 'INFO' ([string]$cs.PartOfDomain)
} catch { Record 'Domain joined' 'WARN' (Short $_) }
try {
    $ds = & dsregcmd.exe /status 2>$null | Select-String -Pattern '^\s*(AzureAdJoined|EnterpriseJoined|DomainJoined)\s*:'
    Record 'Join state (dsregcmd)' 'INFO' (($ds | ForEach-Object { $_.Line.Trim() }) -join '; ')
} catch { Record 'Join state (dsregcmd)' 'WARN' (Short $_) }
try {
    $enroll = @(Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Enrollments' -ErrorAction Stop | Where-Object { (Get-ItemProperty $_.PSPath).ProviderID }).Count
    Record 'Device management enrollments' 'INFO' "$enroll"
} catch { Record 'Device management enrollments' 'INFO' 'unreadable' }
try {
    $av = Get-CimInstance -Namespace 'root/SecurityCenter2' -ClassName AntiVirusProduct -ErrorAction Stop
    Record 'Antivirus products' 'INFO' (($av | ForEach-Object { $_.displayName }) -join '; ')
} catch { Record 'Antivirus products' 'INFO' 'unreadable' }
try {
    $free = (Get-PSDrive -Name ($env:SystemDrive.TrimEnd(':'))).Free
    Record 'Free disk space' $(if ($free -gt 2GB) { 'PASS' } else { 'WARN' }) ('{0:N1} GB on system drive' -f ($free / 1GB))
} catch { Record 'Free disk space' 'WARN' (Short $_) }

# ------------------------------------------------- script and code policy
Section 'Script and application control policy'
try {
    $lines = Get-ExecutionPolicy -List | ForEach-Object { '{0}={1}' -f $_.Scope, $_.ExecutionPolicy }
    Record 'Execution policy' 'INFO' ($lines -join '; ')
    $effective = Get-ExecutionPolicy
    Record 'Effective execution policy' $(if ($effective -in @('AllSigned')) { 'FAIL' } elseif ($effective -in @('Restricted')) { 'FAIL' } else { 'PASS' }) ([string]$effective + ' (unsigned scripts need RemoteSigned or looser; policy is never bypassed)')
} catch { Record 'Execution policy' 'WARN' (Short $_) }
try {
    $zone = Get-Content -LiteralPath ($MyInvocation.MyCommand.Path) -Stream Zone.Identifier -ErrorAction Stop
    Record 'Check script marked as downloaded (MOTW)' 'WARN' (($zone -join ' ') -replace '\s+', ' ')
} catch { Record 'Check script marked as downloaded (MOTW)' 'PASS' 'no Zone.Identifier mark' }
try {
    $dg = Get-CimInstance -Namespace 'root\Microsoft\Windows\DeviceGuard' -ClassName Win32_DeviceGuard -ErrorAction Stop
    Record 'Code integrity (WDAC) enforcement' 'INFO' ('kernel={0} user={1} (0 off, 1 audit, 2 enforced)' -f $dg.CodeIntegrityPolicyEnforcementStatus, $dg.UsermodeCodeIntegrityPolicyEnforcementStatus)
} catch { Record 'Code integrity (WDAC) enforcement' 'INFO' 'unreadable' }
try {
    $srp = Test-Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\SrpV2'
    $svc = Get-Service -Name AppIDSvc -ErrorAction SilentlyContinue
    Record 'AppLocker policy keys' 'INFO' ('SrpV2 present={0}; AppIDSvc={1}' -f $srp, $(if ($svc) { $svc.Status } else { 'absent' }))
    $pol = Get-AppLockerPolicy -Effective -ErrorAction Stop
    $count = @($pol.RuleCollections | ForEach-Object { $_ }).Count
    Record 'AppLocker effective rules' 'INFO' "$count rules"
} catch { Record 'AppLocker effective rules' 'INFO' 'unreadable or none' }

# Behavior tests are more reliable than reading policy. Build one tiny unsigned
# program (it only returns 0) to learn whether unsigned executables may run.
$unsignedExe = Join-Path $work 'unsigned-source.exe'
try {
    Add-Type -TypeDefinition 'public static class FormFillerProbe { public static int Main() { return 0; } }' -OutputAssembly $unsignedExe -OutputType ConsoleApplication -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $unsignedExe)) { throw 'not created' }
} catch { $unsignedExe = $null; Record 'Build a tiny unsigned test program' 'WARN' ('skipped: ' + (Short $_)) }
$probeDir = Join-Path $env:LOCALAPPDATA ('FormFillerCheck-' + [Guid]::NewGuid().ToString('N').Substring(0, 6))
try {
    New-Item -ItemType Directory -Path $probeDir -Force -ErrorAction Stop | Out-Null
    Record 'Write to LOCALAPPDATA' 'PASS' 'writable'
    $isRedirected = ($env:LOCALAPPDATA -like '\\*') -or ($env:LOCALAPPDATA -like '*OneDrive*')
    Record 'LOCALAPPDATA is network or OneDrive redirected' $(if ($isRedirected) { 'WARN' } else { 'PASS' }) ([string]$isRedirected)
    if ($unsignedExe) {
        $exeCopy = Join-Path $probeDir 'unsigned-probe.exe'
        Copy-Item -LiteralPath $unsignedExe -Destination $exeCopy -ErrorAction Stop
        $r = Invoke-Probe $exeCopy @() 15
        if ($r.Started -and $r.ExitCode -eq 0) { Record 'Run an UNSIGNED program from LOCALAPPDATA' 'PASS' 'allowed' }
        else { Record 'Run an UNSIGNED program from LOCALAPPDATA' 'FAIL' ('blocked or failed: ' + $r.Failure + ' ' + $r.Err.Trim()) }
    }
    $ps1 = Join-Path $probeDir 'probe.ps1'
    Set-Content -LiteralPath $ps1 -Value 'exit 0' -Encoding ASCII
    $r = Invoke-Probe (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') @('-NoProfile', '-File', $ps1) 30
    if ($r.Started -and $r.ExitCode -eq 0) { Record 'Run a .ps1 file from LOCALAPPDATA' 'PASS' 'allowed' }
    else { Record 'Run a .ps1 file from LOCALAPPDATA' 'FAIL' ('blocked or failed: ' + $r.Failure + ' ' + ($r.Err -replace '\s+', ' ')) }
    $bat = Join-Path $probeDir 'probe.bat'
    Set-Content -LiteralPath $bat -Value '@exit /b 0' -Encoding ASCII
    $r = Invoke-Probe (Join-Path $env:SystemRoot 'System32\cmd.exe') @('/c', "`"$bat`"") 15
    if ($r.Started -and $r.ExitCode -eq 0) { Record 'Run a .bat file from LOCALAPPDATA' 'PASS' 'allowed' }
    else { Record 'Run a .bat file from LOCALAPPDATA' 'FAIL' ('blocked or failed: ' + $r.Failure) }
    # Files from a downloaded zip carry a "from the internet" mark (zone 3).
    $marked = @{}
    foreach ($kind in @('ps1', 'bat', 'py')) {
        $file = Join-Path $probeDir ('marked.' + $kind)
        Set-Content -LiteralPath $file -Value $(if ($kind -eq 'ps1') { 'exit 0' } elseif ($kind -eq 'bat') { '@exit /b 0' } else { 'raise SystemExit(0)' }) -Encoding ASCII
        Set-Content -LiteralPath $file -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3" -ErrorAction Stop
        $marked[$kind] = $file
    }
    $r = Invoke-Probe (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') @('-NoProfile', '-File', $marked['ps1']) 30
    $psOk = ($r.Started -and $r.ExitCode -eq 0)
    Record 'Run a DOWNLOAD-MARKED .ps1 (what a zip from the internet gives)' $(if ($psOk) { 'PASS' } else { 'FAIL' }) ($(if ($psOk) { 'allowed' } else { 'blocked: ' + $r.Failure + ' ' + ($r.Err -replace '\s+', ' ') }))
    $r = Invoke-Probe (Join-Path $env:SystemRoot 'System32\cmd.exe') @('/c', "`"$($marked['bat'])`"") 15
    Record 'Run a DOWNLOAD-MARKED .bat' $(if ($r.Started -and $r.ExitCode -eq 0) { 'PASS' } else { 'FAIL' }) ($(if ($r.Started) { 'exit ' + $r.ExitCode } else { 'blocked: ' + $r.Failure }))
    $script:markedPy = $marked['py']
} catch { Record 'LOCALAPPDATA program tests' 'FAIL' (Short $_) }

try {
    if ($unsignedExe) {
        $tempExe = Join-Path $work 'unsigned-probe.exe'
        Copy-Item -LiteralPath $unsignedExe -Destination $tempExe -ErrorAction Stop
        $r = Invoke-Probe $tempExe @() 15
        Record 'Run an UNSIGNED program from TEMP' $(if ($r.Started -and $r.ExitCode -eq 0) { 'PASS' } else { 'FAIL' }) ($(if ($r.Started) { 'allowed' } else { 'blocked: ' + $r.Failure }))
    }
} catch { Record 'Run an UNSIGNED program from TEMP' 'FAIL' (Short $_) }

# ----------------------------------------------------------------- Python
Section 'Python'
$candidates = New-Object System.Collections.ArrayList
function Add-Candidate([string]$p, [string]$source) {
    if (-not $p) { return }
    $p = $p.Trim().Trim('"')
    if ($p -notlike '*.exe') { $p = Join-Path $p 'python.exe' }
    if ((Test-Path -LiteralPath $p -PathType Leaf) -and -not ($candidates | Where-Object { $_.Path -ieq $p })) {
        [void]$candidates.Add([pscustomobject]@{Path = $p; Source = $source})
    }
}
try { foreach ($c in @(Get-Command python.exe, python3.exe -All -ErrorAction SilentlyContinue)) { Add-Candidate $c.Source 'PATH' } } catch {}
try {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        Record 'py launcher' 'INFO' 'present'
        $list = & $py.Source -0p 2>$null
        foreach ($line in @($list)) { if ($line -match '([A-Za-z]:\\[^\r\n]*python[w]?\.exe)') { Add-Candidate $Matches[1] 'py launcher' } }
    } else { Record 'py launcher' 'INFO' 'absent' }
} catch {}
foreach ($hive in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore', 'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
    try {
        foreach ($v in @(Get-ChildItem $hive -ErrorAction Stop)) {
            $ip = Get-ItemProperty (Join-Path $v.PSPath 'InstallPath') -ErrorAction SilentlyContinue
            if ($ip) { Add-Candidate ($(if ($ip.ExecutablePath) { $ip.ExecutablePath } else { $ip.'(default)' })) 'registry' }
        }
    } catch {}
}
foreach ($pattern in @("$env:LOCALAPPDATA\Programs\Python\Python*\python.exe", "$env:ProgramFiles\Python*\python.exe", "$env:SystemDrive\Python*\python.exe", "$env:LOCALAPPDATA\FormFiller\Dependencies\Python*\python.exe")) {
    foreach ($f in @(Get-ChildItem $pattern -ErrorAction SilentlyContinue)) { Add-Candidate $f.FullName 'known folder' }
}
$pycheck = Join-Path $work 'pycheck.py'
Set-Content -LiteralPath $pycheck -Encoding ASCII -Value @'
import sys
print("version", sys.version.split()[0], "bits", 64 if sys.maxsize > 2**32 else 32)
for name in ("pip", "venv", "ensurepip", "tkinter", "ssl", "sqlite3", "zoneinfo"):
    try:
        __import__(name)
        print(name, "ok")
    except Exception as exc:
        print(name, "MISSING", type(exc).__name__)
'@
$goodPython = $null
if ($candidates.Count -eq 0) { Record 'Python installations' 'WARN' 'none found (FormFiller would need to install one)' }
$checked = 0
foreach ($cand in $candidates) {
    if ($checked -ge 5) { break }
    $label = 'Python at ' + $cand.Path + ' (' + $cand.Source + ')'
    if ($cand.Path -like '*\Microsoft\WindowsApps\*') { Record $label 'INFO' 'Microsoft Store alias, not a real interpreter; skipped'; continue }
    $checked++
    $r = Invoke-Probe $cand.Path @('-I', $pycheck) 30
    if (-not $r.Started) { Record $label 'FAIL' ('cannot start: ' + $r.Failure); continue }
    if ($r.TimedOut) { Record $label 'FAIL' 'timed out'; continue }
    $text = ($r.Out -replace '\s+', ' ').Trim()
    $ok = ($text -match 'tkinter ok') -and ($text -match 'pip ok') -and ($text -match 'venv ok') -and ($text -match 'ssl ok') -and ($r.ExitCode -eq 0)
    $versionOk = ($text -match 'version 3\.(1[1-4])\.')
    Record $label $(if ($ok -and $versionOk) { 'PASS' } else { 'WARN' }) $text
    if ($ok -and $versionOk -and -not $goodPython) { $goodPython = $cand.Path }
}
if ($goodPython) {
    $venv = Join-Path $work 'venvtest'
    $r = Invoke-Probe $goodPython @('-m', 'venv', $venv) 180
    if ($r.Started -and $r.ExitCode -eq 0 -and (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
        Record 'Create a virtual environment' 'PASS' 'created'
        $r2 = Invoke-Probe (Join-Path $venv 'Scripts\python.exe') @('-c', 'print(1)') 30
        Record 'Run python.exe from a new virtual environment' $(if ($r2.Started -and $r2.ExitCode -eq 0) { 'PASS' } else { 'FAIL' }) ($(if ($r2.Started) { 'allowed' } else { 'blocked: ' + $r2.Failure }))
        $r3 = Invoke-Probe (Join-Path $venv 'Scripts\python.exe') @('-m', 'pip', '--version') 60
        Record 'pip in virtual environment' $(if ($r3.ExitCode -eq 0) { 'PASS' } else { 'WARN' }) (($r3.Out + $r3.Err) -replace '\s+', ' ').Trim()
        $r4 = Invoke-Probe (Join-Path $venv 'Scripts\python.exe') @('-m', 'pip', 'config', 'list') 60
        $cfg = (($r4.Out + $r4.Err) -replace '\s+', ' ').Trim()
        Record 'pip configuration' 'INFO' $(if ($cfg) { $cfg } else { 'defaults' })
    } else { Record 'Create a virtual environment' 'FAIL' ('exit=' + $r.ExitCode + ' ' + $r.Failure + ' ' + ($r.Err -replace '\s+', ' ')) }
} else { Record 'Virtual environment test' 'INFO' 'skipped: no suitable Python' }
if ($goodPython -and $script:markedPy) {
    $r = Invoke-Probe $goodPython @('-I', $script:markedPy) 30
    Record 'Run a DOWNLOAD-MARKED .py with Python' $(if ($r.Started -and $r.ExitCode -eq 0) { 'PASS' } else { 'FAIL' }) ($(if ($r.Started) { 'exit ' + $r.ExitCode } else { 'blocked: ' + $r.Failure }))
}

# The decisive test: install the pinned FormFiller dependencies into the
# temporary virtual environment and start Edge through Playwright.
Section 'FormFiller dependencies (temporary install, removed afterwards)'
$venvPython = if ($venv) { Join-Path $venv 'Scripts\python.exe' } else { $null }
if ($goodPython -and $venvPython -and (Test-Path -LiteralPath $venvPython)) {
    $r = Invoke-Probe $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir', '--only-binary=:all:', 'playwright==1.63.0', 'openpyxl==3.1.5', 'tzdata==2026.4') 900
    $tail = ((($r.Out + ' ' + $r.Err) -replace '\s+', ' ').Trim())
    if ($tail.Length -gt 700) { $tail = $tail.Substring($tail.Length - 700) }
    if ($r.Started -and $r.ExitCode -eq 0) {
        Record 'pip install playwright, openpyxl, tzdata' 'PASS' 'installed from the package index'
        $depCheck = Join-Path $work 'depcheck.py'
        Set-Content -LiteralPath $depCheck -Encoding ASCII -Value @'
import importlib
for name in ("playwright", "greenlet", "pyee", "openpyxl", "tzdata"):
    try:
        importlib.import_module(name)
        print(name, "ok")
    except Exception as exc:
        print(name, "FAILED", type(exc).__name__, str(exc)[:120])
from zoneinfo import ZoneInfo
ZoneInfo("America/Chicago")
print("zoneinfo America/Chicago ok")
'@
        $r2 = Invoke-Probe $venvPython @($depCheck) 60
        $t2 = (($r2.Out + ' ' + $r2.Err) -replace '\s+', ' ').Trim()
        Record 'Import compiled and bundled packages' $(if ($r2.ExitCode -eq 0 -and $t2 -notmatch 'FAILED') { 'PASS' } else { 'FAIL' }) $t2
        $r3 = Invoke-Probe $venvPython @('-m', 'playwright', '--version') 60
        Record 'Run the Playwright driver (bundled node.exe)' $(if ($r3.ExitCode -eq 0) { 'PASS' } else { 'FAIL' }) ((($r3.Out + ' ' + $r3.Err + ' ' + $r3.Failure) -replace '\s+', ' ').Trim())
        $pwEdge = Join-Path $work 'pwedge.py'
        Set-Content -LiteralPath $pwEdge -Encoding ASCII -Value @'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page()
    page.goto("about:blank")
    print("edge ok", browser.version)
    browser.close()
'@
        $r4 = Invoke-Probe $venvPython @($pwEdge) 120
        Record 'Playwright drives installed Edge' $(if ($r4.ExitCode -eq 0 -and $r4.Out -match 'edge ok') { 'PASS' } else { 'FAIL' }) ((($r4.Out + ' ' + $r4.Err + ' ' + $r4.Failure) -replace '\s+', ' ').Trim())
    } else {
        Record 'pip install playwright, openpyxl, tzdata' 'FAIL' ('exit=' + $r.ExitCode + ' timedout=' + $r.TimedOut + ' ' + $r.Failure + ' ...' + $tail)
    }
} else { Record 'FormFiller dependency install' 'INFO' 'skipped: no suitable Python and virtual environment' }

# --------------------------------------------------- PowerShell 7, tools
Section 'Other tools'
$pwsh = Get-Command pwsh.exe -ErrorAction SilentlyContinue
if (-not $pwsh) { foreach ($p in @("$env:ProgramFiles\PowerShell\7\pwsh.exe", "$env:LOCALAPPDATA\FormFiller\Dependencies\PowerShell\pwsh.exe")) { if (Test-Path $p) { $pwsh = [pscustomobject]@{Source = $p} } } }
if ($pwsh) { $r = Invoke-Probe $pwsh.Source @('-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()') 30; Record 'PowerShell 7' 'PASS' ('present; ' + ($r.Out -replace '\s+', ' ').Trim() + ' ' + $r.Failure) }
else { Record 'PowerShell 7' 'INFO' 'not installed (FormFiller currently expects it)' }
$winget = Get-Command winget.exe -ErrorAction SilentlyContinue
if ($winget) { $r = Invoke-Probe $winget.Source @('--version') 30; Record 'winget' 'INFO' ('present ' + ($r.Out -replace '\s+', ' ').Trim() + ' ' + $r.Failure) }
else { Record 'winget' 'INFO' 'absent' }
$git = Get-Command git.exe -ErrorAction SilentlyContinue
Record 'git' 'INFO' $(if ($git) { 'present' } else { 'absent' })

# ------------------------------------------------------------------- Edge
Section 'Microsoft Edge'
$edge = $null
foreach ($p in @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")) { if ($p -and (Test-Path $p)) { $edge = $p; break } }
if (-not $edge) { Record 'Edge installed' 'FAIL' 'msedge.exe not found in standard locations' }
else {
    Record 'Edge installed' 'PASS' ((Get-Item $edge).VersionInfo.ProductVersion)
    try {
        $names = @(Get-Item 'HKLM:\SOFTWARE\Policies\Microsoft\Edge' -ErrorAction Stop | ForEach-Object { $_.Property })
        Record 'Edge policy names set by organization' 'INFO' ($(if ($names.Count) { $names -join ', ' } else { 'none' }))
    } catch { Record 'Edge policy names set by organization' 'INFO' 'none or unreadable' }
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
        $listener.Start(); $port = $listener.LocalEndpoint.Port; $listener.Stop()
        $profile = Join-Path $work 'edge-profile'
        $proc = Start-Process -FilePath $edge -PassThru -ArgumentList @('--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', "--user-data-dir=`"$profile`"", "--remote-debugging-port=$port", 'about:blank') -ErrorAction Stop
        $ok = $false; $detail = 'no DevTools endpoint within 25 seconds'
        for ($i = 0; $i -lt 25 -and -not $ok; $i++) {
            Start-Sleep -Seconds 1
            try {
                $req = [Net.HttpWebRequest]::Create("http://127.0.0.1:$port/json/version")
                $req.Proxy = $null; $req.Timeout = 2000
                $resp = $req.GetResponse(); $resp.Close(); $ok = $true; $detail = 'headless Edge started and its automation endpoint answered'
            } catch {}
        }
        try { & taskkill.exe /T /F /PID $proc.Id *> $null } catch {}
        Record 'Edge headless launch with automation endpoint' $(if ($ok) { 'PASS' } else { 'FAIL' }) $detail
    } catch { Record 'Edge headless launch with automation endpoint' 'FAIL' (Short $_) }
}

# ---------------------------------------------------------------- network
Section 'Network'
try {
    $proxy = [Net.WebRequest]::GetSystemWebProxy().GetProxy([Uri]'https://www.python.org')
    Record 'System proxy for https' 'INFO' ($(if ($proxy.Host -eq 'www.python.org') { 'direct' } else { 'via proxy ' + $proxy.Host }))
} catch { Record 'System proxy for https' 'INFO' (Short $_) }
function Test-Url([string]$label, [string]$url) {
    try {
        $req = [Net.HttpWebRequest]::Create($url)
        $req.Method = 'HEAD'; $req.Timeout = 12000; $req.AllowAutoRedirect = $true
        $req.UserAgent = 'FormFillerEnvironmentCheck'
        if ($req.Proxy) { $req.Proxy.Credentials = [Net.CredentialCache]::DefaultCredentials }
        $code = $null
        try { $resp = $req.GetResponse(); $code = [int]$resp.StatusCode; $resp.Close() }
        catch [Net.WebException] { if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode } else { throw } }
        $issuer = ''
        try { if ($req.ServicePoint.Certificate) { $issuer = ' certificate issuer: ' + (($req.ServicePoint.Certificate.Issuer -split ',')[0]) } } catch {}
        Record $label 'PASS' ("HTTP $code" + $issuer)
    } catch { Record $label 'FAIL' (Short $_) }
}
Test-Url 'python.org' 'https://www.python.org/'
Test-Url 'Python installer download' 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.exe'
Test-Url 'PyPI index' 'https://pypi.org/simple/playwright/'
Test-Url 'PyPI file host' 'https://files.pythonhosted.org/'
Test-Url 'GitHub' 'https://github.com/'
Test-Url 'GitHub release downloads (PowerShell 7)' 'https://github.com/PowerShell/PowerShell/releases'
Test-Url 'Microsoft sign-in' 'https://login.microsoftonline.com/'
Test-Url 'Microsoft Forms' 'https://forms.office.com/'
# Download the pinned Python installer, but never run it.
try {
    $installer = Join-Path $work 'python-installer.exe'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.exe' -OutFile $installer -TimeoutSec 240 -ErrorAction Stop
    $hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    $hashOk = ($hash -eq 'fb4f9f5d438b2396da0086dc70b935c530cb578e37adc6d354f7ad2037fee83b')
    $sig = Get-AuthenticodeSignature -LiteralPath $installer
    $signer = if ($sig.SignerCertificate) { (($sig.SignerCertificate.Subject -split ',')[0]) } else { 'none' }
    Record 'Python installer downloaded (not run)' $(if ($hashOk -and $sig.Status -eq 'Valid') { 'PASS' } else { 'FAIL' }) ('pinned hash match=' + $hashOk + '; signature=' + $sig.Status + '; signer=' + $signer)
    Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
} catch { Record 'Python installer downloaded (not run)' 'FAIL' (Short $_) }
try {
    $listener = New-Object System.Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
    $listener.Start(); $port = $listener.LocalEndpoint.Port
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect('127.0.0.1', $port); $client.Close(); $listener.Stop()
    Record 'Local web server on 127.0.0.1' 'PASS' 'loopback listen and connect worked'
} catch { Record 'Local web server on 127.0.0.1' 'FAIL' (Short $_) }

# --------------------------------------------- scheduling and shortcuts
Section 'Scheduling and shortcuts'
$taskName = 'FormFillerEnvCheck-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
try {
    $action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32\cmd.exe') -Argument '/c exit 0'
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddYears(1)
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -ErrorAction Stop | Out-Null
    Record 'Create a scheduled task as this user' 'PASS' 'created (never run) and removed'
} catch { Record 'Create a scheduled task as this user' 'FAIL' (Short $_) }
finally { try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {} }
try {
    $desktop = [Environment]::GetFolderPath('DesktopDirectory')
    $redirected = ($desktop -like '\\*') -or ($desktop -like '*OneDrive*')
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $desktop ('FormFillerEnvCheck-' + [Guid]::NewGuid().ToString('N').Substring(0, 6) + '.lnk')))
    $lnk.TargetPath = (Join-Path $env:SystemRoot 'System32\cmd.exe')
    $lnk.Save()
    Remove-Item -LiteralPath $lnk.FullName -Force
    Record 'Create a Desktop shortcut' 'PASS' ('created and removed; Desktop redirected to network/OneDrive=' + $redirected)
} catch { Record 'Create a Desktop shortcut' 'FAIL' (Short $_) }

# ---------------------------------------------------------------- summary
Section 'Summary'
foreach ($status in @('FAIL', 'WARN')) {
    $items = @($results | Where-Object { $_.Status -eq $status })
    Out-Line ('{0} items: {1}' -f $status, $items.Count)
    foreach ($i in $items) { Out-Line ('  - ' + $i.Name) }
}
Out-Line ('PASS items: ' + @($results | Where-Object { $_.Status -eq 'PASS' }).Count)
Out-Line ('Finished: ' + (Get-Date).ToString('s'))
try { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue } catch {}
try { if (Test-Path -LiteralPath $probeDir) { Remove-Item -LiteralPath $probeDir -Recurse -Force -ErrorAction SilentlyContinue } } catch {}
Out-Line ''
Out-Line 'Check complete. Send the .log file; it contains no user, computer or domain names.'
