@echo off
setlocal
cd /d "%~dp0"
echo FormFiller environment check. This installs nothing and changes no settings.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -File "%~dp0Check-FormFillerEnvironment.ps1" 2> "%~dp0Check-startup-error.txt"
set "CHECK_EXIT=%ERRORLEVEL%"
if not "%CHECK_EXIT%"=="0" (
    echo.
    echo The check script could not run ^(exit code %CHECK_EXIT%^). That is useful information.
    echo Details were saved to Check-startup-error.txt in this folder.
    echo Please send that file.
) else (
    del "%~dp0Check-startup-error.txt" >nul 2>&1
)
echo.
pause
exit /b %CHECK_EXIT%
