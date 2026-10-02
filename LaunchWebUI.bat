@echo off
setlocal
cd /d "%~dp0"
where pwsh.exe >nul 2>nul
if errorlevel 1 (
  echo FormFiller requires PowerShell 7. Install it, then launch this file again.
  pause
  exit /b 2
)
pwsh.exe -NoProfile -File "%~dp0tools\Launch-WebUI.ps1"
set "FORMFILLER_UI_EXIT=%ERRORLEVEL%"
if not "%FORMFILLER_UI_EXIT%"=="0" pause
exit /b %FORMFILLER_UI_EXIT%
