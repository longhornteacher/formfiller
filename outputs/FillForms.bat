@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Setup is required. Run Setup.bat first.
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -m formfiller.runner %*
set "FORMFILLER_EXIT=%ERRORLEVEL%"
echo.
echo Runner exit code: %FORMFILLER_EXIT%
pause
exit /b %FORMFILLER_EXIT%
