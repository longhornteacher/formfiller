@echo off
call "%~dp0FillForms.bat" --login
exit /b %ERRORLEVEL%
