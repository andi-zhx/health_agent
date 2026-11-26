@echo off
call "%~dp0start.bat" --install-only
if errorlevel 1 exit /b 1
pause
