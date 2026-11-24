@echo off
setlocal
cd /d "%~dp0"
rem Use the managed environment first, then the Windows Python launcher.
if exist ".venv\Scripts\python.exe" goto local_python
py -3 -c "import sys; sys.exit(not ((3,10) <= sys.version_info[:2] <= (3,14)))" >nul 2>nul
if not errorlevel 1 goto py_launcher
python -c "import sys; sys.exit(not ((3,10) <= sys.version_info[:2] <= (3,14)))" >nul 2>nul
if not errorlevel 1 goto path_python
echo Install 64-bit Python 3.10 to 3.14 from python.org. Python 3.12 is recommended.
echo Enable "Add Python to PATH", then try again.
pause
exit /b 1
:local_python
".venv\Scripts\python.exe" bootstrap.py %*
goto result
:py_launcher
py -3 bootstrap.py %*
goto result
:path_python
python bootstrap.py %*
:result
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup or startup failed. See the message above and logs in this folder.
pause
exit /b 1
