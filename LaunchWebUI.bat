@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Bootstrap-WebUI.ps1"
set "FORMFILLER_UI_EXIT=%ERRORLEVEL%"
if not "%FORMFILLER_UI_EXIT%"=="0" pause
exit /b %FORMFILLER_UI_EXIT%
