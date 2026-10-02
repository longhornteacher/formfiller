@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or newer from python.org, including the Python launcher.
  pause
  exit /b 2
)
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Run SignIn.bat, then follow README.md before enabling live use.
pause
exit /b 0
:failed
echo Setup failed. Check your network and district software policy.
pause
exit /b 2
