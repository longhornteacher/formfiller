@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" exit /b 2
".venv\Scripts\python.exe" -m formfiller.runner --live
exit /b %ERRORLEVEL%
