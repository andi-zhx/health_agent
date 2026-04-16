@echo off
setlocal
cd /d "%~dp0"

REM Keep this file ASCII-only to avoid cmd encoding issues.
REM Prefer python, fallback to py launcher.
where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0launch.py"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py "%~dp0launch.py"
    ) else (
        echo Python was not found in PATH.
        echo Please install Python 3.8+ and enable "Add Python to PATH".
        echo Then run "安装依赖.bat" and start again.
        pause
        exit /b 1
    )
)

if errorlevel 1 (
    echo.
    echo Startup failed. Check error_log.txt in this folder.
    if exist "%~dp0error_log.txt" type "%~dp0error_log.txt"
    echo.
    pause
)
