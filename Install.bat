@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0Install.ps1"
set "FORMFILLER_INSTALL_EXIT=%ERRORLEVEL%"
if not "%FORMFILLER_INSTALL_EXIT%"=="0" pause
exit /b %FORMFILLER_INSTALL_EXIT%
