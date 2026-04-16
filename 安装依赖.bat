@echo off
setlocal
cd /d "%~dp0"

REM Keep this file ASCII-only to avoid cmd encoding issues.
echo Installing required packages...
echo.

where python >nul 2>nul
if %errorlevel%==0 (
    python -m pip install -r requirements.txt
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -m pip install -r requirements.txt
    ) else (
        echo Python was not found in PATH.
        echo Please install Python 3.8+ and enable "Add Python to PATH".
        pause
        exit /b 1
    )
)

if errorlevel 1 (
    echo.
    echo Install failed. Please check network and pip configuration.
    pause
    exit /b 1
)

echo.
echo Done. You can now run "启动医疗系统.bat" or "启动医疗系统.pyw".
pause
